"""Self-learning corrections of Solar Forecast Plus.

Shortly after sunset the actual PV yield of the day is compared with the raw
forecast of all entries. From that the learner derives

* a weighted efficiency factor (every day counts, clear days the most),
* a factor per month (seasonal, blended with the overall factor),
* a time-of-day profile (10 bins from sunrise to sunset), and
* accuracy statistics of the day-ahead forecast, including a comparison
  weather model.

During the day it also measures the deviation so far and corrects the rest
of today's forecast (intraday correction).

The pure calculations live in module level functions so they can be tested
without Home Assistant.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_sunset,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LEARN_ACTUAL_ENTITY,
    CONF_LEARN_AUTO_APPLY,
    CONF_LEARN_CLOUD_ENTITY,
    CONF_LEARN_CLOUD_THRESHOLD,
    CONF_LEARN_COMPARE_MODEL,
    CONF_LEARN_ENABLED,
    CONF_LEARN_INTRADAY,
    CONF_LEARN_MIN_DAYS,
    CONF_LEARN_OFFSET,
    CONF_LEARN_SMOOTHING,
    DOMAIN,
    LEARN_DEFAULTS,
    LEARN_HISTORY_DAYS,
    LEARN_MAX_RATIO,
    LEARN_MIN_FORECAST_KWH,
    LEARN_SEASON_PRIOR,
    LOGGER,
    PROFILE_MIN_SHARE,
    PROFILE_MIN_WEIGHT,
    PROFILE_RANGE,
    PROFILE_SEASON_PRIOR,
    SIGNAL_LEARNING_UPDATED,
)
from .corrections import (
    PROFILE_BINS,
    Intraday,
    bin_energy,
    energy_until,
    forecast_bins,
    intraday_from,
)

SEASONS = ("winter", "uebergang", "sommer")
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.learning"
INTRADAY_INTERVAL = timedelta(minutes=5)
ACCURACY_DAYS = 30

_ENERGY_TO_KWH = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}


@dataclass
class LearningState:
    """Persisted learning state."""

    factor: float | None = None
    clear_days: int = 0
    weight_total: float = 0.0
    last_date: str | None = None
    last_ratio: float | None = None
    last_clear: bool | None = None
    last_cloud: float | None = None
    last_cloud_source: str | None = None
    last_weight: float | None = None
    last_actual_kwh: float | None = None
    last_forecast_kwh: float | None = None
    last_clear_date: str | None = None
    last_skip_reason: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    monthly: dict[str, dict[str, float]] = field(default_factory=dict)
    profile: list[dict[str, float]] = field(
        default_factory=lambda: [{"r": 1.0, "w": 0.0} for _ in range(PROFILE_BINS)]
    )
    profile_days: float = 0.0
    profile_seasons: dict[str, list[dict[str, float]]] = field(default_factory=dict)
    accuracy: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LearningState:
        state = cls()
        if not data:
            return state
        for key in cls.__dataclass_fields__:
            if key in data and data[key] is not None:
                setattr(state, key, data[key])
        if not isinstance(state.history, list):
            state.history = []
        if not isinstance(state.monthly, dict):
            state.monthly = {}
        if not isinstance(state.profile, list) or len(state.profile) != PROFILE_BINS:
            state.profile = [{"r": 1.0, "w": 0.0} for _ in range(PROFILE_BINS)]
        if not isinstance(state.profile_seasons, dict):
            state.profile_seasons = {}
        state.profile_seasons = {
            k: v
            for k, v in state.profile_seasons.items()
            if k in SEASONS and isinstance(v, list) and len(v) == PROFILE_BINS
        }
        if not isinstance(state.accuracy, list):
            state.accuracy = []
        # Migration from 0.3: clear days count as full-weight days.
        if not data.get("weight_total") and state.clear_days:
            state.weight_total = float(state.clear_days)
        return state

    def as_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


@dataclass
class DayResult:
    """Outcome of one daily evaluation."""

    evaluated: bool
    reason: str | None = None
    ratio: float | None = None
    clear: bool = False
    weight: float = 0.0
    total: float | None = None


# --- pure calculations -------------------------------------------------------


def day_weight(cloud: float | None, threshold: float) -> float:
    """Weight of a day for learning: 1 up to the threshold, then falling."""
    if cloud is None:
        return 0.0
    if cloud <= threshold:
        return 1.0
    span = max(100.0 - threshold, 1.0)
    return round(max(0.0, 1.0 - (cloud - threshold) / span) ** 2, 3)


def _ema(old: float | None, new: float, alpha: float) -> float:
    if old is None:
        return new
    return old + alpha * (new - old)


def evaluate_day(
    state: LearningState,
    *,
    day: date,
    actual_kwh: float | None,
    forecast_kwh: float | None,
    cloud: float | None,
    cloud_threshold: float,
    smoothing: float,
    current_efficiency: float,
) -> DayResult:
    """Update ``state`` with the result of one day (pure function).

    ``forecast_kwh`` is the raw forecast (computed with
    ``current_efficiency``).
    """
    if actual_kwh is None:
        return _skip(state, day, "actual_unavailable")
    if forecast_kwh is None or forecast_kwh < LEARN_MIN_FORECAST_KWH:
        return _skip(state, day, "forecast_too_small")

    ratio = round(min(actual_kwh / forecast_kwh, LEARN_MAX_RATIO), 3)
    clear = cloud is not None and cloud < cloud_threshold
    weight = day_weight(cloud, cloud_threshold)
    total = round(ratio * current_efficiency, 4)

    state.last_date = day.isoformat()
    state.last_ratio = ratio
    state.last_clear = clear
    state.last_cloud = cloud
    state.last_weight = weight
    state.last_actual_kwh = round(actual_kwh, 3)
    state.last_forecast_kwh = round(forecast_kwh, 3)
    state.last_skip_reason = None

    # A first value needs a reasonably clear day; afterwards every day counts
    # with its weight.
    if weight > 0 and (state.factor is not None or weight >= 0.5):
        first = state.factor is None
        state.factor = round(
            total if first else _ema(state.factor, total, smoothing * weight), 4
        )
        state.weight_total = round(state.weight_total + weight, 3)
        month = str(day.month)
        entry = state.monthly.get(month)
        if entry is None:
            entry = {"f": total, "w": 0.0}
        else:
            entry["f"] = round(_ema(entry["f"], total, smoothing * weight), 4)
        entry["w"] = round(entry["w"] + weight, 3)
        state.monthly[month] = entry
    if clear:
        state.clear_days += 1
        state.last_clear_date = day.isoformat()

    state.history = [h for h in state.history if h.get("d") != day.isoformat()]
    state.history.append(
        {"d": day.isoformat(), "v": ratio, "k": clear, "w": weight}
    )
    state.history = state.history[-LEARN_HISTORY_DAYS:]

    return DayResult(
        evaluated=True, ratio=ratio, clear=clear, weight=weight, total=total
    )


def _skip(state: LearningState, day: date, reason: str) -> DayResult:
    state.last_skip_reason = f"{day.isoformat()}: {reason}"
    return DayResult(evaluated=False, reason=reason)


def seasonal_factor(state: LearningState, day: date) -> float | None:
    """Overall factor blended with the factor of the month of ``day``."""
    if state.factor is None:
        return None
    entry = state.monthly.get(str(day.month))
    if not entry or entry.get("w", 0) <= 0:
        return state.factor
    w = float(entry["w"])
    return round(
        (w * float(entry["f"]) + LEARN_SEASON_PRIOR * state.factor)
        / (w + LEARN_SEASON_PRIOR),
        4,
    )


def season_of(day: date) -> str:
    """Season by sun height: winter (Nov-Feb), transition, summer (May-Aug)."""
    if day.month in (11, 12, 1, 2):
        return "winter"
    if day.month in (5, 6, 7, 8):
        return "sommer"
    return "uebergang"


def _empty_profile() -> list[dict[str, float]]:
    return [{"r": 1.0, "w": 0.0} for _ in range(PROFILE_BINS)]


def _learn_bins(
    entries: list[dict[str, float]], rel: dict[int, float], weight: float, smoothing: float
) -> None:
    for i, value in rel.items():
        entry = entries[i]
        entry["r"] = round(
            value if entry["w"] <= 0 else _ema(entry["r"], value, smoothing * weight), 4
        )
        entry["w"] = round(entry["w"] + weight, 3)


def update_profile(
    state: LearningState,
    *,
    actual_bins: list[float],
    forecast_bins_kwh: list[float],
    weight: float,
    smoothing: float,
    day: date | None = None,
) -> bool:
    """Learn the relative deviation per daylight bin (pure function).

    The overall profile and, if ``day`` is given, the profile of its season
    are updated.
    """
    actual_total = sum(actual_bins)
    forecast_total = sum(forecast_bins_kwh)
    if weight <= 0 or actual_total <= 0 or forecast_total < LEARN_MIN_FORECAST_KWH:
        return False
    day_ratio = actual_total / forecast_total
    rel = {
        i: min(max((a / f) / day_ratio, 0.2), 2.0)
        for i, (a, f) in enumerate(zip(actual_bins, forecast_bins_kwh))
        if f >= PROFILE_MIN_SHARE * forecast_total
    }
    if not rel:
        return False
    _learn_bins(state.profile, rel, weight, smoothing)
    state.profile_days = round(state.profile_days + weight, 3)
    if day is not None:
        season = state.profile_seasons.setdefault(season_of(day), _empty_profile())
        _learn_bins(season, rel, weight, smoothing)
    return True


def profile_values(state: LearningState, day: date | None = None) -> list[float] | None:
    """Applicable profile (bins without enough data stay neutral).

    With ``day`` the profile of its season is blended in: the overall value
    counts like PROFILE_SEASON_PRIOR days, so the seasonal profile takes over
    the more days of that season have been learned.
    """
    low, high = PROFILE_RANGE
    season = state.profile_seasons.get(season_of(day)) if day is not None else None
    values = []
    for i, e in enumerate(state.profile):
        if e["w"] < PROFILE_MIN_WEIGHT:
            values.append(1.0)
            continue
        r = e["r"]
        if season is not None and season[i]["w"] > 0:
            ws = season[i]["w"]
            r = (ws * season[i]["r"] + PROFILE_SEASON_PRIOR * r) / (ws + PROFILE_SEASON_PRIOR)
        values.append(round(min(max(r, low), high), 4))
    if all(v == 1.0 for v in values):
        return None
    return values


def record_accuracy(state: LearningState, day: date, actual_kwh: float) -> bool:
    """Close the pending day-ahead forecast of ``day`` with the actual yield."""
    pending = state.pending
    if not pending or pending.get("d") != day.isoformat():
        return False
    item = {"d": day.isoformat(), "a": round(actual_kwh, 3)}
    for key in ("raw", "cor", "alt"):
        if pending.get(key) is not None:
            item[key] = round(float(pending[key]), 3)
    if pending.get("model"):
        item["m"] = pending["model"]
    state.accuracy = [x for x in state.accuracy if x.get("d") != item["d"]]
    state.accuracy.append(item)
    state.accuracy = state.accuracy[-ACCURACY_DAYS:]
    state.pending = None
    return True


def accuracy_summary(state: LearningState) -> dict[str, Any]:
    """Weighted absolute percentage error and bias per forecast variant."""
    result: dict[str, Any] = {"days": len(state.accuracy)}
    for key in ("cor", "raw", "alt"):
        items = [x for x in state.accuracy if x.get(key) is not None and x["a"] > 0]
        actual = sum(x["a"] for x in items)
        if not items or actual <= 0:
            result[key] = None
            continue
        abs_err = sum(abs(x[key] - x["a"]) for x in items)
        bias = sum(x[key] - x["a"] for x in items)
        result[key] = {
            "error": round(100 * abs_err / actual, 1),
            "bias": round(100 * bias / actual, 1),
            "days": len(items),
        }
    return result


def energy_state_to_kwh(value: str, unit: str | None) -> float | None:
    """Convert an energy sensor state to kWh."""
    if value in (None, STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    factor = _ENERGY_TO_KWH.get((unit or "kwh").lower(), 1.0)
    return number * factor


def numeric_state(value: str | None) -> float | None:
    """Return a float for a numeric state or None."""
    if value in (None, STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --- Home Assistant glue -----------------------------------------------------


class PvLearner:
    """Domain-wide learner shared by all config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.state = LearningState()
        self.entry: ConfigEntry | None = None
        self.intraday: Intraday | None = None
        self._unsubs: list[CALLBACK_TYPE] = []

    # -- lifecycle -----------------------------------------------------------

    async def async_load(self) -> None:
        self.state = LearningState.from_dict(await self._store.async_load())

    def _save(self) -> None:
        self._store.async_delay_save(self.state.as_dict, 5)

    @callback
    def async_attach(self, entry: ConfigEntry) -> None:
        """Use ``entry``'s learning settings (the entry with learning enabled)."""
        self.async_detach()
        self.entry = entry
        offset = timedelta(minutes=int(self.option(CONF_LEARN_OFFSET)))
        self._unsubs.append(
            async_track_sunset(self.hass, self._async_sunset, offset=offset)
        )
        if self.intraday_enabled:
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self._async_intraday_tick, INTRADAY_INTERVAL
                )
            )
        LOGGER.debug("PV learning attached to %s (sunset %+s)", entry.title, offset)

    @callback
    def async_detach(self, entry: ConfigEntry | None = None) -> None:
        if entry is not None and self.entry is not None and entry.entry_id != self.entry.entry_id:
            return
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        self.entry = None
        self.intraday = None

    # -- options -------------------------------------------------------------

    def option(self, key: str) -> Any:
        if self.entry is None:
            return LEARN_DEFAULTS[key]
        value = self.entry.options.get(key)
        return LEARN_DEFAULTS[key] if value is None else value

    @property
    def enabled(self) -> bool:
        return self.entry is not None and bool(self.option(CONF_LEARN_ENABLED))

    @property
    def intraday_enabled(self) -> bool:
        return (
            self.enabled
            and bool(self.option(CONF_LEARN_INTRADAY))
            and bool(self.option(CONF_LEARN_ACTUAL_ENTITY))
        )

    @property
    def auto_apply(self) -> bool:
        return self.enabled and bool(self.option(CONF_LEARN_AUTO_APPLY))

    @property
    def min_days(self) -> int:
        return int(self.option(CONF_LEARN_MIN_DAYS))

    @property
    def compare_model(self) -> str | None:
        model = self.option(CONF_LEARN_COMPARE_MODEL)
        return str(model).strip() or None if model else None

    @property
    def learning_complete(self) -> bool:
        return (
            self.state.factor is not None
            and self.state.weight_total >= self.min_days
        )

    @property
    def applied_factor(self) -> float | None:
        """Overall learned factor if it is applied (for display)."""
        if self.auto_apply and self.learning_complete:
            return float(self.state.factor)
        return None

    def applied_factor_for(self, day: date) -> float | None:
        """Seasonal learned factor of ``day`` if it is applied."""
        if self.auto_apply and self.learning_complete:
            return seasonal_factor(self.state, day)
        return None

    def applied_profile(self) -> list[float] | None:
        """Profile applied today (for display and change detection)."""
        return self.applied_profile_for(dt_util.now().date())

    def applied_profile_for(self, day: date) -> list[float] | None:
        if self.auto_apply:
            return profile_values(self.state, day)
        return None

    # -- helpers -------------------------------------------------------------

    def _coordinators(self) -> list[Any]:
        domain_data = self.hass.data.get(DOMAIN, {})
        return [
            value
            for key, value in domain_data.items()
            if key != "learner" and getattr(value, "raw", None) is not None
        ]

    def current_efficiency(self) -> float:
        """DC-weighted efficiency currently in effect (today)."""
        applied = self.applied_factor_for(dt_util.now().date())
        return applied if applied is not None else self.configured_efficiency()

    def configured_efficiency(self) -> float:
        coordinators = self._coordinators()
        total_kwp = sum(c.dc_kwp_total for c in coordinators)
        if not total_kwp:
            return 1.0
        acc = 0.0
        for c in coordinators:
            effs = c.configured_efficiency
            kwps = list(c.forecast.dc_kwp)
            acc += sum(e * k for e, k in zip(effs, kwps))
        return acc / total_kwp

    def _actual_kwh(self) -> float | None:
        state = self.hass.states.get(self.option(CONF_LEARN_ACTUAL_ENTITY) or "")
        if state is None:
            return None
        return energy_state_to_kwh(
            state.state, state.attributes.get("unit_of_measurement")
        )

    def _cloud(self, day: date) -> tuple[float | None, str | None]:
        entity = self.option(CONF_LEARN_CLOUD_ENTITY)
        if entity:
            cloud_state = self.hass.states.get(entity)
            value = numeric_state(cloud_state.state if cloud_state else None)
            if value is not None:
                return value, "sensor"
        for c in self._coordinators():
            value = c.raw.daylight_cloud_cover(day)
            if value is not None:
                return value, "open-meteo"
        return None, None

    async def _async_actual_bins(
        self, day: date, daylight: tuple[datetime, datetime]
    ) -> list[float] | None:
        """Actual energy per daylight bin from the recorder history."""
        entity_id = self.option(CONF_LEARN_ACTUAL_ENTITY)
        if not entity_id or "recorder" not in self.hass.config.components:
            return None
        try:
            from homeassistant.components.recorder import get_instance, history

            start = dt_util.start_of_local_day(day)
            end = start + timedelta(days=1)
            states = await get_instance(self.hass).async_add_executor_job(
                history.state_changes_during_period,
                self.hass,
                start,
                end,
                entity_id,
            )
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("No history for the profile: %s", err)
            return None
        samples: list[tuple[datetime, float]] = []
        for st in states.get(entity_id, []):
            value = energy_state_to_kwh(
                st.state, st.attributes.get("unit_of_measurement")
            )
            if value is not None:
                samples.append((st.last_changed, value))
        if len(samples) < 4:
            return None
        return bin_energy(samples, daylight)

    # -- intraday ------------------------------------------------------------

    async def _async_intraday_tick(self, _now: datetime | None = None) -> None:
        self.async_update_intraday()

    @callback
    def async_update_intraday(self, now: datetime | None = None) -> None:
        """Recompute the intraday correction and republish all forecasts."""
        coordinators = self._coordinators()
        previous = self.intraday
        if not self.intraday_enabled or not coordinators:
            self.intraday = None
        else:
            now = now or dt_util.now()
            so_far = sum(energy_until(c.base, now) for c in coordinators) / 1000
            day = sum(c.base.day_production(now.date()) for c in coordinators) / 1000
            self.intraday = intraday_from(
                now=now,
                actual_kwh=self._actual_kwh(),
                forecast_so_far_kwh=so_far,
                forecast_day_kwh=day,
            )
        if self.intraday is None and previous is None:
            return
        for c in coordinators:
            c.async_publish()
        async_dispatcher_send(self.hass, SIGNAL_LEARNING_UPDATED)

    # -- evaluation ----------------------------------------------------------

    async def _async_sunset(self) -> None:
        await self.async_evaluate()

    async def async_evaluate(self, day: date | None = None) -> DayResult:
        """Compare today's actual yield with the forecast and learn."""
        if not self.enabled:
            return DayResult(evaluated=False, reason="disabled")

        day = day or dt_util.now().date()
        coordinators = self._coordinators()
        forecast_wh = sum(c.raw.day_production(day) for c in coordinators)
        forecast_kwh = forecast_wh / 1000 if coordinators else None
        actual_kwh = self._actual_kwh()
        cloud, source = self._cloud(day)

        previous = (self.applied_factor_for(day), self.applied_profile())
        result = evaluate_day(
            self.state,
            day=day,
            actual_kwh=actual_kwh,
            forecast_kwh=forecast_kwh,
            cloud=cloud,
            cloud_threshold=float(self.option(CONF_LEARN_CLOUD_THRESHOLD)),
            smoothing=float(self.option(CONF_LEARN_SMOOTHING)),
            current_efficiency=self.configured_efficiency(),
        )
        if result.evaluated:
            self.state.last_cloud_source = source

        # time-of-day profile
        if result.evaluated and coordinators:
            daylight = coordinators[0].raw.daylight.get(day)
            if daylight is not None:
                actual_bins = await self._async_actual_bins(day, daylight)
                if actual_bins is not None:
                    update_profile(
                        self.state,
                        actual_bins=actual_bins,
                        forecast_bins_kwh=forecast_bins(
                            [c.raw for c in coordinators], day
                        ),
                        weight=result.weight,
                        smoothing=float(self.option(CONF_LEARN_SMOOTHING)),
                        day=day,
                    )

        # accuracy of yesterday's day-ahead forecast, then a new day-ahead
        if actual_kwh is not None:
            record_accuracy(self.state, day, actual_kwh)
        await self._async_store_day_ahead(day + timedelta(days=1), coordinators)

        LOGGER.info(
            "PV learning %s: actual=%s kWh forecast=%s kWh cloud=%s (%s) -> %s",
            day,
            actual_kwh,
            forecast_kwh,
            cloud,
            source,
            result,
        )
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_LEARNING_UPDATED)

        if (self.applied_factor_for(day), self.applied_profile()) != previous:
            await self.async_refresh_forecasts()
        return result

    async def _async_store_day_ahead(
        self, target: date, coordinators: list[Any]
    ) -> None:
        if not coordinators:
            return
        raw = sum(c.raw.day_production(target) for c in coordinators) / 1000
        cor = sum(c.base.day_production(target) for c in coordinators) / 1000
        alt = None
        model = self.compare_model
        if model:
            results = await asyncio.gather(
                *(c.async_fetch_compare(model, target) for c in coordinators),
                return_exceptions=True,
            )
            if all(isinstance(r, (int, float)) for r in results):
                alt = sum(results) / 1000
            else:
                LOGGER.debug("Comparison model %s unavailable: %s", model, results)
        self.state.pending = {
            "d": target.isoformat(),
            "raw": round(raw, 3),
            "cor": round(cor, 3),
            "alt": round(alt, 3) if alt is not None else None,
            "model": model,
        }

    async def async_refresh_forecasts(self) -> None:
        for coordinator in self._coordinators():
            coordinator.async_publish()
        self.async_update_intraday()

    # -- manual control ------------------------------------------------------

    async def async_set(
        self,
        *,
        factor: float | None = None,
        clear_days: int | None = None,
        history: list[dict[str, Any]] | None = None,
        last_clear_date: str | None = None,
        reset: bool = False,
    ) -> None:
        if reset:
            self.state = LearningState()
        if factor is not None:
            # A manually set factor replaces the seasonal values as well.
            self.state.factor = round(float(factor), 4)
            self.state.monthly = {}
        if clear_days is not None:
            self.state.clear_days = int(clear_days)
            self.state.weight_total = max(self.state.weight_total, float(clear_days))
        if history is not None:
            cleaned = []
            for item in history:
                try:
                    clear = bool(item.get("k", False))
                    cleaned.append(
                        {
                            "d": str(item["d"]),
                            "v": float(item["v"]),
                            "k": clear,
                            "w": float(item.get("w", 1.0 if clear else 0.0)),
                        }
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            self.state.history = cleaned[-LEARN_HISTORY_DAYS:]
            if cleaned:
                last = cleaned[-1]
                self.state.last_date = last["d"]
                self.state.last_ratio = last["v"]
                self.state.last_clear = last["k"]
        if last_clear_date is not None:
            self.state.last_clear_date = str(last_clear_date)
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_LEARNING_UPDATED)
        await self.async_refresh_forecasts()

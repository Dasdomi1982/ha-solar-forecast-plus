"""Self-learning efficiency factor (Open-Meteo Solar Forecast Plus).

Once a day, shortly after sunset, the actual PV yield of the day is compared
with the forecast of all configured entries. On clear days (cloud cover below a
threshold) the ratio is turned into an efficiency factor and smoothed with an
exponential moving average. After a minimum number of clear days the learned
factor can optionally replace the configured efficiency factor of every entry.

The pure calculation lives in :func:`evaluate_day` so it can be tested without
Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_sunset
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LEARN_ACTUAL_ENTITY,
    CONF_LEARN_AUTO_APPLY,
    CONF_LEARN_CLOUD_ENTITY,
    CONF_LEARN_CLOUD_THRESHOLD,
    CONF_LEARN_ENABLED,
    CONF_LEARN_MIN_DAYS,
    CONF_LEARN_OFFSET,
    CONF_LEARN_SMOOTHING,
    DOMAIN,
    LEARN_DEFAULTS,
    LEARN_HISTORY_DAYS,
    LEARN_MAX_RATIO,
    LEARN_MIN_FORECAST_KWH,
    LOGGER,
    SIGNAL_LEARNING_UPDATED,
)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.learning"

_ENERGY_TO_KWH = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}


@dataclass
class LearningState:
    """Persisted learning state."""

    factor: float | None = None
    clear_days: int = 0
    last_date: str | None = None
    last_ratio: float | None = None
    last_clear: bool | None = None
    last_cloud: float | None = None
    last_actual_kwh: float | None = None
    last_forecast_kwh: float | None = None
    last_clear_date: str | None = None
    last_skip_reason: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LearningState:
        state = cls()
        if not data:
            return state
        for key in cls.__dataclass_fields__:
            if key in data:
                setattr(state, key, data[key])
        if not isinstance(state.history, list):
            state.history = []
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
    total: float | None = None


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
    """Update ``state`` with the result of one day (pure function)."""
    if actual_kwh is None:
        return _skip(state, day, "actual_unavailable")
    if forecast_kwh is None or forecast_kwh < LEARN_MIN_FORECAST_KWH:
        return _skip(state, day, "forecast_too_small")

    ratio = round(min(actual_kwh / forecast_kwh, LEARN_MAX_RATIO), 3)
    clear = cloud is not None and cloud < cloud_threshold
    total = round(ratio * current_efficiency, 4)

    state.last_date = day.isoformat()
    state.last_ratio = ratio
    state.last_clear = clear
    state.last_cloud = cloud
    state.last_actual_kwh = round(actual_kwh, 3)
    state.last_forecast_kwh = round(forecast_kwh, 3)
    state.last_skip_reason = None

    if clear:
        if state.factor is None:
            state.factor = round(total, 4)
        else:
            state.factor = round(
                (1 - smoothing) * state.factor + smoothing * total, 4
            )
        state.clear_days += 1
        state.last_clear_date = day.isoformat()

    state.history = [h for h in state.history if h.get("d") != day.isoformat()]
    state.history.append({"d": day.isoformat(), "v": ratio, "k": clear})
    state.history = state.history[-LEARN_HISTORY_DAYS:]

    return DayResult(evaluated=True, ratio=ratio, clear=clear, total=total)


def _skip(state: LearningState, day: date, reason: str) -> DayResult:
    state.last_skip_reason = f"{day.isoformat()}: {reason}"
    return DayResult(evaluated=False, reason=reason)


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


class PvLearner:
    """Domain-wide learner shared by all config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.state = LearningState()
        self.entry: ConfigEntry | None = None
        self._unsub_sunset: CALLBACK_TYPE | None = None

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
        self._unsub_sunset = async_track_sunset(
            self.hass, self._async_sunset, offset=offset
        )
        LOGGER.debug("PV learning attached to %s (sunset %+s)", entry.title, offset)

    @callback
    def async_detach(self, entry: ConfigEntry | None = None) -> None:
        if entry is not None and self.entry is not None and entry.entry_id != self.entry.entry_id:
            return
        if self._unsub_sunset is not None:
            self._unsub_sunset()
            self._unsub_sunset = None
        self.entry = None

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
    def min_days(self) -> int:
        return int(self.option(CONF_LEARN_MIN_DAYS))

    @property
    def learning_complete(self) -> bool:
        return self.state.factor is not None and self.state.clear_days >= self.min_days

    @property
    def applied_factor(self) -> float | None:
        """Factor that replaces the configured efficiency, if any."""
        if (
            self.enabled
            and bool(self.option(CONF_LEARN_AUTO_APPLY))
            and self.learning_complete
        ):
            return float(self.state.factor)
        return None

    # -- evaluation ----------------------------------------------------------

    def _coordinators(self) -> list[Any]:
        domain_data = self.hass.data.get(DOMAIN, {})
        return [
            value
            for key, value in domain_data.items()
            if key != "learner" and getattr(value, "data", None) is not None
        ]

    def current_efficiency(self) -> float:
        """DC-weighted efficiency currently used across all entries."""
        coordinators = self._coordinators()
        total_kwp = sum(c.dc_kwp_total for c in coordinators)
        if not total_kwp:
            return 1.0
        return (
            sum(c.effective_efficiency * c.dc_kwp_total for c in coordinators)
            / total_kwp
        )

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

    async def _async_sunset(self) -> None:
        await self.async_evaluate()

    async def async_evaluate(self, day: date | None = None) -> DayResult:
        """Compare today's actual yield with the forecast and learn."""
        if not self.enabled:
            return DayResult(evaluated=False, reason="disabled")

        day = day or dt_util.now().date()
        coordinators = self._coordinators()
        forecast_wh = sum(c.data.day_production(day) for c in coordinators)
        forecast_kwh = forecast_wh / 1000 if coordinators else None

        actual_kwh = None
        actual_state = self.hass.states.get(self.option(CONF_LEARN_ACTUAL_ENTITY) or "")
        if actual_state is not None:
            actual_kwh = energy_state_to_kwh(
                actual_state.state,
                actual_state.attributes.get("unit_of_measurement"),
            )

        cloud = None
        cloud_entity = self.option(CONF_LEARN_CLOUD_ENTITY)
        if cloud_entity:
            cloud_state = self.hass.states.get(cloud_entity)
            cloud = numeric_state(cloud_state.state if cloud_state else None)

        previous_applied = self.applied_factor
        result = evaluate_day(
            self.state,
            day=day,
            actual_kwh=actual_kwh,
            forecast_kwh=forecast_kwh,
            cloud=cloud,
            cloud_threshold=float(self.option(CONF_LEARN_CLOUD_THRESHOLD)),
            smoothing=float(self.option(CONF_LEARN_SMOOTHING)),
            current_efficiency=self.current_efficiency(),
        )
        LOGGER.info(
            "PV learning %s: actual=%s kWh forecast=%s kWh cloud=%s -> %s",
            day,
            actual_kwh,
            forecast_kwh,
            cloud,
            result,
        )
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_LEARNING_UPDATED)

        if self.applied_factor != previous_applied:
            await self.async_refresh_forecasts()
        return result

    async def async_refresh_forecasts(self) -> None:
        for coordinator in self._coordinators():
            coordinator._apply_learned_efficiency()  # noqa: SLF001
            await coordinator.async_request_refresh()

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
        previous_applied = self.applied_factor
        if reset:
            self.state = LearningState()
        if factor is not None:
            self.state.factor = round(float(factor), 4)
        if clear_days is not None:
            self.state.clear_days = int(clear_days)
        if history is not None:
            cleaned = []
            for item in history:
                try:
                    cleaned.append(
                        {"d": str(item["d"]), "v": float(item["v"]), "k": bool(item.get("k", False))}
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
        if self.applied_factor != previous_applied:
            await self.async_refresh_forecasts()

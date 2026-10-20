"""Plus: correction of the raw forecast (pure functions, no Home Assistant).

The library always computes the *raw* forecast with the configured efficiency
factor. Solar Forecast Plus derives the published forecast from it by
multiplying every 15-minute slot with

    day factor (learned / configured, per season)
  × time-of-day profile (learned, normalised so the daily total is unchanged)
  × intraday correction (today only, from the actual yield so far)

Keeping the raw forecast untouched avoids feedback loops in the learning.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from .forecast_lib.models import Estimate

PROFILE_BINS = 10
SLOT = timedelta(minutes=15)

# Intraday correction
INTRADAY_MIN_FORECAST_KWH = 0.3  # forecast so far needed before correcting
INTRADAY_FULL_SHARE = 0.25  # share of the day's forecast for full confidence
INTRADAY_TAU_HOURS = 3.0  # how fast the correction fades into the future
INTRADAY_RATIO_RANGE = (0.3, 2.0)


@dataclass(frozen=True)
class Intraday:
    """Measured deviation of today so far."""

    now: datetime
    ratio: float  # actual so far / forecast so far (unclamped)
    weight: float  # 0..1 confidence

    @property
    def future_ratio(self) -> float:
        low, high = INTRADAY_RATIO_RANGE
        return min(max(self.ratio, low), high)

    def multiplier(self, slot_start: datetime) -> float:
        if slot_start.date() != self.now.date():
            return 1.0
        if slot_start + SLOT <= self.now:
            # past slots of today: scale so they sum up to the actual yield
            return max(self.ratio, 0.0)
        hours_ahead = max((slot_start - self.now).total_seconds() / 3600, 0.0)
        fade = math.exp(-hours_ahead / INTRADAY_TAU_HOURS)
        return 1.0 + (self.future_ratio - 1.0) * self.weight * fade


def daylight_bin(
    slot_start: datetime, daylight: dict[date, tuple[datetime, datetime]]
) -> int | None:
    """Return the profile bin (0..9 from sunrise to sunset) of a slot."""
    sun = daylight.get(slot_start.date())
    if sun is None:
        return None
    rise, sset = sun
    span = (sset - rise).total_seconds()
    if span <= 0:
        return None
    middle = slot_start + SLOT / 2
    pos = (middle - rise).total_seconds() / span
    return min(max(int(pos * PROFILE_BINS), 0), PROFILE_BINS - 1)


def intraday_from(
    *,
    now: datetime,
    actual_kwh: float | None,
    forecast_so_far_kwh: float,
    forecast_day_kwh: float,
) -> Intraday | None:
    """Build the intraday correction or None if not (yet) meaningful."""
    if actual_kwh is None or forecast_so_far_kwh < INTRADAY_MIN_FORECAST_KWH:
        return None
    ratio = min(actual_kwh / forecast_so_far_kwh, 3.0)
    share = forecast_so_far_kwh / forecast_day_kwh if forecast_day_kwh > 0 else 1.0
    weight = min(share / INTRADAY_FULL_SHARE, 1.0)
    return Intraday(now=now, ratio=round(ratio, 4), weight=round(weight, 3))


def energy_until(estimate: Estimate, until: datetime) -> float:
    """Forecast energy (Wh) of the day of ``until`` before ``until``."""
    total = 0.0
    for start, wh in estimate.wh_period_15m.items():
        if start.date() != until.date() or start >= until:
            continue
        end = start + SLOT
        if end <= until:
            total += wh
        else:
            total += wh * (until - start) / SLOT
    return total


def apply_corrections(
    raw: Estimate,
    *,
    day_factor: Callable[[date], float] | None = None,
    profile: list[float] | None = None,
    intraday: Intraday | None = None,
) -> Estimate:
    """Return a corrected copy of ``raw``."""
    if day_factor is None and profile is None and intraday is None:
        return raw

    profile_norm: dict[date, float] = {}
    if profile is not None:
        # Normalise per day so the profile only shifts energy within the day.
        weighted: dict[date, float] = {}
        plain: dict[date, float] = {}
        for start, wh in raw.wh_period_15m.items():
            b = daylight_bin(start, raw.daylight)
            p = profile[b] if b is not None else 1.0
            weighted[start.date()] = weighted.get(start.date(), 0.0) + wh * p
            plain[start.date()] = plain.get(start.date(), 0.0) + wh
        for day, value in weighted.items():
            profile_norm[day] = plain[day] / value if value > 0 else 1.0

    cache: dict[datetime, float] = {}

    def multiplier(start: datetime) -> float:
        if start in cache:
            return cache[start]
        m = 1.0
        if day_factor is not None:
            m *= day_factor(start.date())
        if profile is not None:
            b = daylight_bin(start, raw.daylight)
            if b is not None:
                m *= profile[b] * profile_norm.get(start.date(), 1.0)
        if intraday is not None:
            m *= intraday.multiplier(start)
        cache[start] = m
        return m

    wh_15m = {t: wh * multiplier(t) for t, wh in raw.wh_period_15m.items()}
    watts = {t: round(w * multiplier(t)) for t, w in raw.watts.items()}

    raw_hour: dict[datetime, float] = {}
    new_hour: dict[datetime, float] = {}
    for t, wh in raw.wh_period_15m.items():
        hour = t.replace(minute=0, second=0, microsecond=0)
        raw_hour[hour] = raw_hour.get(hour, 0.0) + wh
        new_hour[hour] = new_hour.get(hour, 0.0) + wh_15m[t]

    wh_period: dict[datetime, float] = {}
    for hour, wh in raw.wh_period.items():
        base = raw_hour.get(hour, 0.0)
        scale = new_hour[hour] / base if base > 0 else multiplier(hour)
        wh_period[hour] = wh * scale

    wh_days: dict[date, float] = {}
    for hour, wh in wh_period.items():
        wh_days[hour.date()] = wh_days.get(hour.date(), 0.0) + wh
    for day in raw.wh_days:
        wh_days.setdefault(day, 0.0)

    return replace(
        raw,
        watts=watts,
        wh_period=wh_period,
        wh_days=wh_days,
        wh_period_15m=wh_15m,
    )


def bin_energy(
    samples: list[tuple[datetime, float]],
    daylight: tuple[datetime, datetime],
) -> list[float]:
    """Split a cumulative daily energy series (kWh) into the daylight bins.

    ``samples`` are (time, cumulative kWh) pairs of one day in ascending
    order. Drops (resets/glitches) are ignored. The cumulative value at each
    bin border is interpolated linearly.
    """
    rise, sset = daylight
    span = sset - rise
    borders = [rise + span * i / PROFILE_BINS for i in range(PROFILE_BINS + 1)]

    clean: list[tuple[datetime, float]] = []
    offset = 0.0
    last = None
    for t, v in samples:
        if last is not None and v < last - 0.05:
            offset += last  # reset during the day
        last = v
        clean.append((t, v + offset))
    if len(clean) < 2:
        return [0.0] * PROFILE_BINS

    def value_at(when: datetime) -> float:
        if when <= clean[0][0]:
            return clean[0][1]
        for (t0, v0), (t1, v1) in zip(clean, clean[1:]):
            if t0 <= when <= t1:
                if t1 == t0:
                    return v1
                return v0 + (v1 - v0) * (when - t0) / (t1 - t0)
        return clean[-1][1]

    cumulative = [value_at(b) for b in borders]
    return [max(cumulative[i + 1] - cumulative[i], 0.0) for i in range(PROFILE_BINS)]


def forecast_bins(estimates: list[Estimate], day: date) -> list[float]:
    """Raw forecast energy (kWh) per daylight bin of ``day`` (all entries)."""
    bins = [0.0] * PROFILE_BINS
    for est in estimates:
        for start, wh in est.wh_period_15m.items():
            if start.date() != day:
                continue
            b = daylight_bin(start, est.daylight)
            if b is not None:
                bins[b] += wh / 1000
    return bins

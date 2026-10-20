"""Tests of the 0.4 features: corrections, profile, accuracy, totals."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from homeassistant.core import HomeAssistant

from custom_components.solar_forecast_plus.const import DOMAIN
from custom_components.solar_forecast_plus.corrections import (
    PROFILE_BINS,
    Intraday,
    apply_corrections,
    bin_energy,
    daylight_bin,
    energy_until,
    intraday_from,
)
from custom_components.solar_forecast_plus.forecast_lib.models import Estimate
from custom_components.solar_forecast_plus.learner import (
    LearningState,
    accuracy_summary,
    day_weight,
    evaluate_day,
    profile_values,
    record_accuracy,
    seasonal_factor,
    update_profile,
)

from .test_plus import BASE_OPTIONS, LEARN_OPTIONS, _entry, _fake_response, _patch_api

TZ = timezone.utc
DAY = date(2026, 6, 1)


def _estimate() -> Estimate:
    """Bell curve 06:00-18:00 on DAY and DAY+1, 15-minute slots."""
    wh15, watts = {}, {}
    for d in (0, 1):
        start = datetime(2026, 6, 1, tzinfo=TZ) + timedelta(days=d)
        for i in range(96):
            t = start + timedelta(minutes=15 * i)
            h = t.hour + t.minute / 60
            w = max(0.0, 4000 * (1 - ((h + 0.125 - 12) / 6) ** 2))
            watts[t] = round(w)
            wh15[t] = w / 4
    wh_period: dict[datetime, float] = {}
    for t, wh in wh15.items():
        hour = t.replace(minute=0)
        wh_period[hour] = wh_period.get(hour, 0.0) + wh
    wh_days: dict[date, float] = {}
    for t, wh in wh_period.items():
        wh_days[t.date()] = wh_days.get(t.date(), 0.0) + wh
    daylight = {
        DAY + timedelta(days=d): (
            datetime(2026, 6, 1, 6, tzinfo=TZ) + timedelta(days=d),
            datetime(2026, 6, 1, 18, tzinfo=TZ) + timedelta(days=d),
        )
        for d in (0, 1)
    }
    cloud = {
        datetime(2026, 6, 1, h, tzinfo=TZ): (20.0 if 6 <= h < 18 else 100.0)
        for h in range(24)
    }
    return Estimate(
        watts=watts,
        wh_period=wh_period,
        wh_days=wh_days,
        api_timezone=TZ,
        wh_period_15m=wh15,
        cloud_cover=cloud,
        daylight=daylight,
    )


# --- corrections ---------------------------------------------------------------


def test_day_factor_scales_everything():
    raw = _estimate()
    cor = apply_corrections(raw, day_factor=lambda d: 1.1)
    assert cor.wh_days[DAY] == pytest.approx(raw.wh_days[DAY] * 1.1)
    t = datetime(2026, 6, 1, 12, tzinfo=TZ)
    assert cor.watts[t] == round(raw.watts[t] * 1.1)
    assert raw.wh_days[DAY] == pytest.approx(sum(raw.wh_period_15m[x] for x in raw.wh_period_15m if x.date() == DAY))


def test_profile_keeps_daily_total_but_shifts_energy():
    raw = _estimate()
    profile = [0.6, 0.8] + [1.0] * 6 + [1.2, 1.2]
    cor = apply_corrections(raw, profile=profile)
    assert cor.wh_days[DAY] == pytest.approx(raw.wh_days[DAY], rel=1e-6)
    morning = datetime(2026, 6, 1, 6, 30, tzinfo=TZ)
    evening = datetime(2026, 6, 1, 17, 0, tzinfo=TZ)
    assert cor.wh_period_15m[morning] < raw.wh_period_15m[morning]
    assert cor.wh_period_15m[evening] > raw.wh_period_15m[evening]


def test_intraday_matches_actual_and_fades():
    raw = _estimate()
    now = datetime(2026, 6, 1, 12, tzinfo=TZ)
    so_far = energy_until(raw, now) / 1000
    day = raw.wh_days[DAY] / 1000
    intraday = intraday_from(now=now, actual_kwh=so_far * 0.8, forecast_so_far_kwh=so_far, forecast_day_kwh=day)
    assert intraday.ratio == pytest.approx(0.8) and intraday.weight == 1.0
    cor = apply_corrections(raw, intraday=intraday)
    # past part of today equals the actual yield
    assert energy_until(cor, now) / 1000 == pytest.approx(so_far * 0.8, rel=1e-3)
    # the near future is corrected more than the far future, tomorrow not at all
    near = datetime(2026, 6, 1, 12, 15, tzinfo=TZ)
    far = datetime(2026, 6, 1, 17, 0, tzinfo=TZ)
    assert cor.wh_period_15m[near] / raw.wh_period_15m[near] < cor.wh_period_15m[far] / raw.wh_period_15m[far] < 1
    tomorrow = datetime(2026, 6, 2, 12, tzinfo=TZ)
    assert cor.wh_period_15m[tomorrow] == raw.wh_period_15m[tomorrow]


def test_intraday_waits_for_enough_energy():
    now = datetime(2026, 6, 1, 6, 30, tzinfo=TZ)
    assert intraday_from(now=now, actual_kwh=0.05, forecast_so_far_kwh=0.1, forecast_day_kwh=30) is None
    early = intraday_from(now=now, actual_kwh=2, forecast_so_far_kwh=1, forecast_day_kwh=40)
    assert early.weight == pytest.approx(0.1)
    assert Intraday(now=now, ratio=5, weight=1).future_ratio == 2.0


def test_daylight_bins_and_bin_energy():
    raw = _estimate()
    assert daylight_bin(datetime(2026, 6, 1, 6, 0, tzinfo=TZ), raw.daylight) == 0
    assert daylight_bin(datetime(2026, 6, 1, 17, 45, tzinfo=TZ), raw.daylight) == 9
    assert daylight_bin(datetime(2026, 6, 3, 12, tzinfo=TZ), raw.daylight) is None
    rise, sset = raw.daylight[DAY]
    # 1 kWh per hour linearly, with a reset glitch at 12:00
    samples = [(rise + timedelta(hours=h), float(h)) for h in range(0, 7)]
    samples += [(rise + timedelta(hours=6, minutes=1), 0.0)]
    samples += [(rise + timedelta(hours=h), float(h - 6)) for h in range(7, 13)]
    bins = bin_energy(samples, (rise, sset))
    assert len(bins) == PROFILE_BINS
    assert sum(bins) == pytest.approx(12, abs=0.05)
    assert bins[0] == pytest.approx(1.2, abs=0.05)


# --- learning --------------------------------------------------------------------


def test_day_weight():
    assert day_weight(10, 30) == 1.0
    assert day_weight(30, 30) == 1.0
    assert 0.4 < day_weight(50, 30) < 0.6
    assert day_weight(95, 30) < 0.01
    assert day_weight(None, 30) == 0.0


def test_cloudy_days_learn_a_little_and_seasons_blend():
    state = LearningState()
    kw = dict(cloud_threshold=30, smoothing=0.2, current_efficiency=0.8)
    evaluate_day(state, day=date(2026, 10, 1), actual_kwh=40, forecast_kwh=40, cloud=10, **kw)
    assert state.factor == 0.8
    evaluate_day(state, day=date(2026, 10, 2), actual_kwh=60, forecast_kwh=40, cloud=65, **kw)
    assert 0.8 < state.factor < 0.8 + 0.2 * 0.4  # less than a full clear day
    assert 1 < state.weight_total < 2
    assert state.clear_days == 1
    # A different month gets its own factor, blended with the overall one
    for d in range(1, 6):
        evaluate_day(state, day=date(2027, 1, d), actual_kwh=30, forecast_kwh=40, cloud=0, **kw)
    jan = seasonal_factor(state, date(2027, 1, 10))
    october = seasonal_factor(state, date(2026, 10, 20))
    assert jan < october
    assert state.monthly["1"]["f"] < jan  # pulled towards the overall factor


def test_profile_learning():
    state = LearningState()
    forecast = [2, 3, 5, 6, 7, 7, 6, 5, 3, 2]
    actual = [1.0, 2.4, 5, 6, 7, 7, 6, 5, 3.6, 2.4]  # shaded morning, good evening
    for _ in range(6):
        update_profile(state, actual_bins=actual, forecast_bins_kwh=forecast, weight=1.0, smoothing=0.2)
    values = profile_values(state)
    assert values is not None
    assert values[0] < 0.6 and values[1] < 0.9
    assert values[8] > 1.1
    assert state.profile_days == 6
    # not enough data -> neutral
    assert profile_values(LearningState()) is None


def test_accuracy_records():
    state = LearningState()
    state.pending = {"d": "2026-10-20", "raw": 20.0, "cor": 18.0, "alt": 24.0, "model": "best_match"}
    assert not record_accuracy(state, date(2026, 10, 19), 17.0)
    assert record_accuracy(state, date(2026, 10, 20), 17.0)
    state.pending = {"d": "2026-10-21", "raw": 10.0, "cor": 9.0, "alt": 8.0}
    record_accuracy(state, date(2026, 10, 21), 10.0)
    summary = accuracy_summary(state)
    assert summary["days"] == 2
    assert summary["cor"]["error"] == pytest.approx(100 * (1 + 1) / 27, abs=0.1)
    assert summary["raw"]["bias"] == pytest.approx(100 * 3 / 27, abs=0.1)
    assert summary["alt"]["error"] == pytest.approx(100 * (7 + 2) / 27, abs=0.1)


def test_estimate_daylight_cloud():
    raw = _estimate()
    assert raw.daylight_cloud_cover(DAY) == 20.0
    assert raw.daylight_cloud_cover(date(2026, 7, 1)) is None


def test_state_migration_from_03():
    state = LearningState.from_dict({"factor": 0.83, "clear_days": 3, "history": []})
    assert state.weight_total == 3.0
    assert len(state.profile) == PROFILE_BINS


# --- Home Assistant --------------------------------------------------------------


async def test_totals_accuracy_and_open_meteo_cloud(hass: HomeAssistant):
    options = {**BASE_OPTIONS, **LEARN_OPTIONS, "learn_cloud_entity": None}
    entry = _entry(options)
    entry.add_to_hass(hass)
    response = _fake_response(days=8)
    times = response["minutely_15"]["time"][::4]
    response["hourly"] = {"time": times, "cloud_cover": [5.0] * len(times)}
    with _patch_api(response):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        learner = hass.data[DOMAIN]["learner"]
        today = coordinator.data.now().date()

        total = hass.states.get("sensor.solar_forecast_plus_gesamt_heute")
        assert total is not None
        assert float(total.state) == pytest.approx(coordinator.data.energy_production_today / 1000, abs=0.01)
        assert hass.states.get("sensor.solar_forecast_plus_gesamt_morgen") is not None
        assert hass.states.get("sensor.solar_forecast_plus_gesamt_leistung") is not None

        forecast_kwh = coordinator.raw.day_production(today) / 1000
        hass.states.async_set("sensor.pv_daily", str(forecast_kwh), {"unit_of_measurement": "kWh"})
        await learner.async_evaluate(today)
        # cloud cover came from Open-Meteo, the day was clear
        assert learner.state.last_cloud == 5.0
        assert learner.state.last_cloud_source == "open-meteo"
        assert learner.state.clear_days == 1
        # day-ahead forecast and comparison model were stored for tomorrow
        pending = learner.state.pending
        assert pending["d"] == (today + timedelta(days=1)).isoformat()
        assert pending["alt"] == pytest.approx(pending["raw"], rel=1e-6)

        # tomorrow evening the pending forecast is closed
        tomorrow = today + timedelta(days=1)
        hass.states.async_set("sensor.pv_daily", str(pending["raw"]), {"unit_of_measurement": "kWh"})
        await learner.async_evaluate(tomorrow)
        await hass.async_block_till_done()
        acc = hass.states.get("sensor.solar_forecast_plus_treffsicherheit")
        assert acc.attributes["tage"] == 1
        assert acc.attributes["abweichung_ohne_lernen"] == 0.0


async def test_intraday_changes_remaining_today(hass: HomeAssistant):
    entry = _entry({**BASE_OPTIONS, **LEARN_OPTIONS, "learn_auto_apply": False})
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    learner = hass.data[DOMAIN]["learner"]
    est = coordinator.raw
    today = est.now().date()
    noon = datetime.combine(today, datetime.min.time(), est.api_timezone) + timedelta(hours=12)
    so_far = energy_until(est, noon) / 1000
    hass.states.async_set("sensor.pv_daily", str(so_far * 0.5), {"unit_of_measurement": "kWh"})
    learner.async_update_intraday(now=noon)
    assert learner.intraday is not None
    assert learner.intraday.ratio == pytest.approx(0.5, abs=0.01)
    assert coordinator.data.day_production(today) < est.day_production(today)
    # the raw forecast used for learning is untouched
    assert coordinator.raw is est

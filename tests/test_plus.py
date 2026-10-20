"""End-to-end tests of the Plus features inside a real Home Assistant core."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_forecast_plus.const import DOMAIN
from custom_components.solar_forecast_plus.learner import (
    LearningState,
    energy_state_to_kwh,
    evaluate_day,
)

from datetime import datetime, timedelta, timezone

from .test_robustness import _fake_response as _raw_response


def _fake_response(days: int = 8, **nulls) -> dict:
    """Fake API data covering yesterday .. today+6 (real dates)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return _raw_response(days=days, start=today - timedelta(days=1), **nulls)

BASE_OPTIONS = {
    "api_key": None,
    "base_url": "https://api.open-meteo.com",
    "model": "icon_seamless",
    "inverter_power": 15000,
    "max_snowcover_depth_cm": 5,
    "latitude": 50.75,
    "longitude": 7.85,
    "declination": 40,
    "azimuth": 250,
    "modules_power": 11160,
    "array_inverter_power": 0,
    "efficiency_factor": 0.83,
    "tracking": "none",
    "damping_morning": 0,
    "damping_evening": 0,
    "use_horizon": False,
    "partial_shading": False,
    "horizon_filepath": "/config/www/horizont.txt",
}

LEARN_OPTIONS = {
    "learn_enabled": True,
    "learn_actual_entity": "sensor.pv_daily",
    "learn_cloud_entity": "sensor.cloud_mean",
    "learn_cloud_threshold": 30,
    "learn_smoothing": 0.2,
    "learn_min_days": 2,
    "learn_auto_apply": True,
    "learn_sunset_offset": 30,
}


def _entry(options: dict) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Westseite",
        data={"latitude": 50.75, "longitude": 7.85},
        options=options,
    )


def _patch_api(response: dict | Exception):
    async def fake_request(self, uri, *, params=None):
        if isinstance(response, Exception):
            raise response
        return response

    return patch(
        "custom_components.solar_forecast_plus.forecast_lib."
        "open_meteo_solar_forecast.OpenMeteoSolarForecast._request",
        fake_request,
    )


# --- pure learning logic -----------------------------------------------------


def test_evaluate_day_learns_only_on_clear_days():
    state = LearningState()
    cloudy = evaluate_day(
        state, day=date(2026, 10, 19), actual_kwh=34.2, forecast_kwh=31.9,
        cloud=70, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    )
    assert cloudy.evaluated and not cloudy.clear
    assert state.factor is None and state.clear_days == 0
    assert state.history[-1]["v"] == 1.072 and state.history[-1]["k"] is False
    assert 0 < state.history[-1]["w"] < 0.5  # cloudy days count only a little

    clear = evaluate_day(
        state, day=date(2026, 10, 20), actual_kwh=40.0, forecast_kwh=40.0,
        cloud=10, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    )
    assert clear.clear
    assert state.factor == 0.83  # first clear day is taken directly
    evaluate_day(
        state, day=date(2026, 10, 21), actual_kwh=44.0, forecast_kwh=40.0,
        cloud=5, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    )
    assert state.clear_days == 2
    assert state.factor == pytest.approx(0.8 * 0.83 + 0.2 * 0.913, abs=1e-4)
    assert state.last_clear_date == "2026-10-21"


def test_evaluate_day_skips_bad_input():
    state = LearningState()
    assert not evaluate_day(
        state, day=date(2026, 10, 19), actual_kwh=None, forecast_kwh=30,
        cloud=10, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    ).evaluated
    assert not evaluate_day(
        state, day=date(2026, 10, 19), actual_kwh=5, forecast_kwh=0.2,
        cloud=10, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    ).evaluated
    huge = evaluate_day(
        state, day=date(2026, 10, 19), actual_kwh=500, forecast_kwh=10,
        cloud=10, cloud_threshold=30, smoothing=0.2, current_efficiency=0.83,
    )
    assert huge.ratio == 3.0  # capped


def test_energy_units():
    assert energy_state_to_kwh("34.19", "kWh") == pytest.approx(34.19)
    assert energy_state_to_kwh("34190", "Wh") == pytest.approx(34.19)
    assert energy_state_to_kwh("unavailable", "kWh") is None


# --- Home Assistant integration ------------------------------------------------


async def test_setup_with_null_snow_depth(hass: HomeAssistant):
    """The real-world bug from 2026-10-19 must not break the setup any more."""
    entry = _entry(BASE_OPTIONS)
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8, snow_depth=[10, 11, 500])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get("sensor.westseite_energy_production_today")
    assert state is not None


async def test_retained_forecast_survives_options_change(hass: HomeAssistant):
    entry = _entry(BASE_OPTIONS)
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator._store._async_handle_write_data()  # flush delayed save

    # Options change + API outage right afterwards: entry must still load.
    with _patch_api(RuntimeError("API down")):
        hass.config_entries.async_update_entry(
            entry, options={**BASE_OPTIONS, "model": "best_match"}
        )
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_learning_end_to_end(hass: HomeAssistant):
    entry = _entry({**BASE_OPTIONS, **LEARN_OPTIONS})
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        learner = hass.data[DOMAIN]["learner"]
        today = coordinator.data.now().date()
        forecast_kwh = coordinator.data.day_production(today) / 1000
        assert forecast_kwh > 1

        # Cloudy day: evaluated, not learned
        hass.states.async_set("sensor.pv_daily", str(forecast_kwh), {"unit_of_measurement": "kWh"})
        hass.states.async_set("sensor.cloud_mean", "70")
        await hass.services.async_call(DOMAIN, "learning_evaluate", blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.solar_forecast_plus_ertrag_zu_prognose").state == "1.0"
        assert hass.states.get("sensor.solar_forecast_plus_klare_tage").state == "0"
        assert learner.applied_factor is None

        # Two clear days with 10 % more yield than forecast
        hass.states.async_set("sensor.cloud_mean", "10")
        hass.states.async_set("sensor.pv_daily", str(forecast_kwh * 1.1), {"unit_of_measurement": "kWh"})
        await learner.async_evaluate(today)
        assert learner.applied_factor is None  # 1 of 2 days
        await learner.async_evaluate(today)
        await hass.async_block_till_done()

        assert learner.state.clear_days == 2
        assert learner.applied_factor == pytest.approx(0.913, abs=0.002)
        factor_state = hass.states.get("sensor.solar_forecast_plus_pv_faktor")
        assert factor_state.attributes["eingelernt"] is True
        assert factor_state.attributes["angewendet"] is True
        # The forecast now uses the learned factor
        assert coordinator.effective_efficiency == pytest.approx(learner.applied_factor)

        # Manual correction via service
        await hass.services.async_call(
            DOMAIN, "learning_set", {"factor": 0.85, "clear_days": 3}, blocking=True
        )
        await hass.async_block_till_done()
        assert hass.states.get("sensor.solar_forecast_plus_pv_faktor").state == "0.85"
        assert coordinator.effective_efficiency == pytest.approx(0.85)


async def test_options_flow_learning_step(hass: HomeAssistant):
    entry = _entry(BASE_OPTIONS)
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "api_key": "",
                "base_url": "https://api.open-meteo.com",
                "model": "icon_seamless",
                "inverter_power": 15000,
                "max_snowcover_depth_cm": 5,
            },
        )
        assert result["step_id"] == "array"
        array = {k: BASE_OPTIONS[k] for k in (
            "latitude", "longitude", "declination", "azimuth", "modules_power",
            "array_inverter_power", "tracking", "efficiency_factor",
            "damping_morning", "damping_evening", "use_horizon", "partial_shading",
            "horizon_filepath",
        )}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**array, "add_another": False}
        )
        assert result["step_id"] == "learning"

        # enabling without sensors is rejected
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"learn_enabled": True}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]["learn_actual_entity"] == "learn_actual_required"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "learn_enabled": True,
                "learn_actual_entity": "sensor.pv_daily",
                "learn_cloud_entity": "sensor.cloud_mean",
                "learn_cloud_threshold": 30,
                "learn_smoothing": 0.2,
                "learn_min_days": 10,
                "learn_auto_apply": False,
                "learn_sunset_offset": 30,
            },
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    assert entry.options["learn_enabled"] is True
    assert entry.options["azimuth"] == 250
    assert entry.options["max_snowcover_depth_cm"] == 5
    assert hass.states.get("sensor.solar_forecast_plus_pv_faktor") is not None


async def test_diagnostics_include_plus_data(hass: HomeAssistant):
    from custom_components.solar_forecast_plus.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    entry = _entry({**BASE_OPTIONS, **LEARN_OPTIONS})
    entry.add_to_hass(hass)
    with _patch_api(_fake_response(days=8, snow_depth=[5, 6])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["plus"]["snow_gaps_last_fetch"] == 2
    assert diag["plus"]["learning"]["clear_days"] == 0

"""Robustness of the forecast calculation against gaps in the API response.

Run with:  python -m pytest tests/test_robustness.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "custom_components/open_meteo_solar_forecast/forecast_lib"

# Import the vendored library as a stand-alone package (no Home Assistant needed).
spec = importlib.util.spec_from_file_location(
    "forecast_lib", LIB / "__init__.py", submodule_search_locations=[str(LIB)]
)
forecast_lib = importlib.util.module_from_spec(spec)
sys.modules["forecast_lib"] = forecast_lib
spec.loader.exec_module(forecast_lib)
OpenMeteoSolarForecast = forecast_lib.OpenMeteoSolarForecast


def _fake_response(days: int = 2, start: datetime | None = None, **nulls) -> dict:
    """Build a minimal Open-Meteo-like response with a sunny bell curve."""
    start = start or datetime(2026, 6, 1, tzinfo=timezone.utc)
    times = [start + timedelta(minutes=15 * i) for i in range(days * 96)]
    gti = []
    for t in times:
        hour = t.hour + t.minute / 60
        gti.append(max(0.0, 800 * (1 - ((hour - 12) / 7) ** 2)))
    m15 = {
        "time": [int(t.timestamp()) for t in times],
        "temperature_2m": [20.0] * len(times),
        "global_tilted_irradiance": list(gti),
        "global_tilted_irradiance_instant": list(gti),
        "diffuse_radiation": [g * 0.3 for g in gti],
        "diffuse_radiation_instant": [g * 0.3 for g in gti],
        "direct_radiation": [g * 0.7 for g in gti],
        "direct_radiation_instant": [g * 0.7 for g in gti],
        "snow_depth": [0.0] * len(times),
    }
    for key, indices in nulls.items():
        if indices == "missing":
            del m15[key]
            continue
        for i in indices:
            m15[key][i] = None
    day_starts = [start + timedelta(days=d) for d in range(days)]
    return {
        "utc_offset_seconds": 0,
        "minutely_15": m15,
        "daily": {
            "time": [int(d.timestamp()) for d in day_starts],
            "sunrise": [int((d + timedelta(hours=5)).timestamp()) for d in day_starts],
            "sunset": [int((d + timedelta(hours=19)).timestamp()) for d in day_starts],
        },
    }


def _run(response: dict, **kwargs) -> tuple[float, OpenMeteoSolarForecast]:
    forecast = OpenMeteoSolarForecast(
        latitude=50.75,
        longitude=7.85,
        azimuth=0,
        declination=40,
        dc_kwp=10,
        **kwargs,
    )

    async def fake_request(uri, *, params=None):
        return response

    forecast._request = fake_request  # type: ignore[method-assign]
    estimate = asyncio.run(forecast.estimate())
    return sum(estimate.wh_days.values()), forecast


def test_baseline_produces_energy():
    total, forecast = _run(_fake_response(), max_snowcover_depth_cm=5)
    assert total > 10_000
    assert forecast.last_data_gaps == 0
    assert forecast.last_snow_gaps == 0


def test_null_snow_depth_does_not_crash():
    """The original bug: None * 100 -> TypeError."""
    baseline, _ = _run(_fake_response(), max_snowcover_depth_cm=5)
    total, forecast = _run(
        _fake_response(snow_depth=[40, 41, 42, 120]), max_snowcover_depth_cm=5
    )
    assert total == baseline  # missing snow counts as "no snow"
    assert forecast.last_snow_gaps == 4


def test_missing_snow_variable_does_not_crash():
    total, forecast = _run(
        _fake_response(snow_depth="missing"), max_snowcover_depth_cm=5
    )
    assert total > 10_000
    assert forecast.last_snow_gaps > 0


def test_snow_still_reduces_output():
    response = _fake_response()
    response["minutely_15"]["snow_depth"] = [0.10] * len(
        response["minutely_15"]["time"]
    )  # 10 cm > 5 cm threshold -> zero output
    total, _ = _run(response, max_snowcover_depth_cm=5)
    assert total == 0


def test_null_diffuse_with_horizon_and_partial_shading():
    # Horizon at 30° everywhere, so the morning/evening sun is shaded.
    horizon = ((0.0, 30.0), (360.0, 30.0))
    total, forecast = _run(
        _fake_response(
            diffuse_radiation=range(20, 80),
            direct_radiation_instant=range(30, 60),
        ),
        use_horizon=True,
        partial_shading=True,
        horizon_map=horizon,
    )
    assert total > 0
    assert forecast.last_data_gaps > 0


def test_null_gti_slot_is_skipped():
    baseline, _ = _run(_fake_response())
    total, forecast = _run(_fake_response(global_tilted_irradiance=[48]))
    assert 0 < total < baseline
    assert forecast.last_data_gaps == 1


def test_null_sunrise_does_not_crash():
    response = _fake_response()
    response["daily"]["sunrise"][1] = None
    total, _ = _run(response, damping_morning=0.5)
    assert total > 0

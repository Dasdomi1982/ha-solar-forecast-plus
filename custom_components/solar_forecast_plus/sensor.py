# Modified in 2026 by Dasdomi1982 for Solar Forecast Plus (changes marked "Plus:"; see NOTICE and CHANGELOG.md).
"""Support for the Open-Meteo Solar Forecast sensor service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

from .forecast_lib.models import Estimate

from .const import (
    ATTR_WATTS,
    ATTR_WH_PERIOD,
    ATTR_WH_PERIOD_15M,
    CONF_LEARN_ENABLED,
    DOMAIN,
    SIGNAL_FORECAST_UPDATED,
    SIGNAL_LEARNING_UPDATED,
)
from .learner import accuracy_summary, profile_values, season_of, seasonal_factor
from .coordinator import OpenMeteoSolarForecastDataUpdateCoordinator


@dataclass(frozen=True)
class OpenMeteoSolarForecastSensorEntityDescription(SensorEntityDescription):
    """Describes a Solar Forecast Sensor."""

    state: Callable[[Estimate], Any] | None = None


SENSORS: tuple[OpenMeteoSolarForecastSensorEntityDescription, ...] = (
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_today",
        translation_key="energy_production_today",
        state=lambda estimate: estimate.energy_production_today,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_today_remaining",
        translation_key="energy_production_today_remaining",
        state=lambda estimate: estimate.energy_production_today_remaining,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_tomorrow",
        translation_key="energy_production_tomorrow",
        state=lambda estimate: estimate.energy_production_tomorrow,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d2",
        translation_key="energy_production_d2",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=2)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d3",
        translation_key="energy_production_d3",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=3)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d4",
        translation_key="energy_production_d4",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=4)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d5",
        translation_key="energy_production_d5",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=5)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d6",
        translation_key="energy_production_d6",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=6)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_production_d7",
        translation_key="energy_production_d7",
        state=lambda estimate: estimate.day_production(
            estimate.now().date() + timedelta(days=7)
        ),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_highest_peak_time_today",
        translation_key="power_highest_peak_time_today",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_highest_peak_time_tomorrow",
        translation_key="power_highest_peak_time_tomorrow",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_now",
        translation_key="power_production_now",
        device_class=SensorDeviceClass.POWER,
        state=lambda estimate: estimate.power_production_now,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_next_15minutes",
        translation_key="power_production_next_15minutes",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(minutes=15)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_next_30minutes",
        translation_key="power_production_next_30minutes",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(minutes=30)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_next_hour",
        translation_key="power_production_next_hour",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=1)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_next_12hours",
        translation_key="power_production_next_12hours",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=12)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="power_production_next_24hours",
        translation_key="power_production_next_24hours",
        state=lambda estimate: estimate.power_production_at_time(
            estimate.now() + timedelta(hours=24)
        ),
        device_class=SensorDeviceClass.POWER,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_current_hour",
        translation_key="energy_current_hour",
        state=lambda estimate: estimate.energy_current_hour,
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
    OpenMeteoSolarForecastSensorEntityDescription(
        key="energy_next_hour",
        translation_key="energy_next_hour",
        state=lambda estimate: estimate.sum_energy_production(1),
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        suggested_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Defer sensor setup to the shared sensor module."""
    coordinator: OpenMeteoSolarForecastDataUpdateCoordinator = hass.data[DOMAIN][
        entry.entry_id
    ]

    async_add_entities(
        OpenMeteoSolarForecastSensorEntity(
            entry_id=entry.entry_id,
            coordinator=coordinator,
            entity_description=entity_description,
        )
        for entity_description in SENSORS
    )

    # Plus: learning sensors live on the entry that has learning enabled.
    if entry.options.get(CONF_LEARN_ENABLED):
        async_add_entities(
            LearningSensorEntity(entry_id=entry.entry_id, kind=kind)
            for kind in ("learned_factor", "yield_ratio", "clear_days", "accuracy")
        )
        async_add_entities(
            TotalSensorEntity(entry_id=entry.entry_id, kind=kind)
            for kind in TotalSensorEntity._ENTITY_SUFFIX
        )


class OpenMeteoSolarForecastSensorEntity(
    CoordinatorEntity[OpenMeteoSolarForecastDataUpdateCoordinator], SensorEntity
):
    """Defines a Open-Meteo sensor."""

    entity_description: OpenMeteoSolarForecastSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        *,
        entry_id: str,
        coordinator: OpenMeteoSolarForecastDataUpdateCoordinator,
        entity_description: OpenMeteoSolarForecastSensorEntityDescription,
    ) -> None:
        """Initialize Open-Meteo Solar sensor."""
        super().__init__(coordinator=coordinator)
        self.entity_description = entity_description
        service_slug = slugify(coordinator.config_entry.title) or coordinator.config_entry.entry_id
        self.entity_id = f"{SENSOR_DOMAIN}.{service_slug}_{entity_description.key}"
        self._attr_unique_id = f"{entry_id}_{entity_description.key}"

        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry_id)},
            manufacturer="Open-Meteo",
            name="Solar Forecast Plus",
            configuration_url="https://open-meteo.com",
        )

    async def _update_callback(self, now: datetime) -> None:
        """Update the entity without fetching data from server.

        This is required for the power_production_* sensors to update
        as they take data in 15-minute intervals and the update interval
        is 30 minutes."""
        if not self.enabled:
            return

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()

        # Update the state of the sensor every minute without
        # fetching new data from the server.
        self.async_on_remove(
            async_track_utc_time_change(
                self.hass,
                self._update_callback,
                second=0,
            )
        )

    @property
    def native_value(self) -> datetime | StateType:
        """Return the state of the sensor."""
        if self.entity_description.state is None:
            state: StateType | datetime = getattr(
                self.coordinator.data, self.entity_description.key
            )
        else:
            state = self.entity_description.state(self.coordinator.data)

        return state

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes."""
        if self.entity_description.key.startswith(
            "energy_production_d"
        ) or self.entity_description.key in (
            "energy_production_today",
            "energy_production_tomorrow",
        ):
            target_date = self.coordinator.data.now().date()
            if self.entity_description.key == "energy_production_tomorrow":
                target_date += timedelta(days=1)
            elif self.entity_description.key.startswith("energy_production_d"):
                target_date += timedelta(
                    days=int(self.entity_description.key[len("energy_production_d") :])
                )
            elif self.entity_description.key == "energy_production_today":
                pass  # target_date is already set to today
            else:
                raise ValueError(
                    f"Unexpected key {self.entity_description.key} for extra_state_attributes"
                )

            return {
                ATTR_WATTS: {
                    watt_datetime.isoformat(): watt_value
                    for watt_datetime, watt_value in self.coordinator.data.watts.items()
                    if watt_datetime.date() == target_date
                },
                ATTR_WH_PERIOD: {
                    wh_datetime.isoformat(): wh_value
                    for wh_datetime, wh_value in self.coordinator.data.wh_period.items()
                    if wh_datetime.date() == target_date
                },
                ATTR_WH_PERIOD_15M: {
                    wh_datetime.isoformat(): wh_value
                    for wh_datetime, wh_value in self.coordinator.data.wh_period_15m.items()
                    if wh_datetime.date() == target_date
                },
            }

        return None



def _plus_device(entry_id: str) -> DeviceInfo:
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, entry_id)},
        manufacturer="Open-Meteo",
        name="Solar Forecast Plus",
        configuration_url="https://open-meteo.com",
    )


class LearningSensorEntity(SensorEntity):
    """Plus: sensors of the self-learning corrections."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    _ENTITY_SUFFIX = {
        "learned_factor": "pv_faktor",
        "yield_ratio": "ertrag_zu_prognose",
        "clear_days": "klare_tage",
        "accuracy": "treffsicherheit",
    }

    _ICONS = {
        "learned_factor": "mdi:solar-panel",
        "yield_ratio": "mdi:solar-power-variant",
        "clear_days": "mdi:weather-sunny",
        "accuracy": "mdi:bullseye-arrow",
    }

    def __init__(self, *, entry_id: str, kind: str) -> None:
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry_id}_{kind}"
        self.entity_id = f"{SENSOR_DOMAIN}.solar_forecast_plus_{self._ENTITY_SUFFIX[kind]}"
        self._attr_icon = self._ICONS[kind]
        if kind in ("learned_factor", "yield_ratio"):
            self._attr_suggested_display_precision = 2
        if kind == "accuracy":
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_suggested_display_precision = 1
        self._attr_device_info = _plus_device(entry_id)

    @property
    def _learner(self):
        return self.hass.data[DOMAIN]["learner"]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_LEARNING_UPDATED, self.async_write_ha_state
            )
        )

    @property
    def native_value(self) -> StateType:
        state = self._learner.state
        if self._kind == "learned_factor":
            return state.factor
        if self._kind == "yield_ratio":
            return state.last_ratio
        if self._kind == "accuracy":
            cor = accuracy_summary(state).get("cor")
            return cor["error"] if cor else None
        return state.clear_days

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        learner = self._learner
        state = learner.state
        today = dt_util.now().date()
        if self._kind == "learned_factor":
            profile = profile_values(state, today)
            return {
                "letzter_klarer_tag": state.last_clear_date,
                "klare_tage": state.clear_days,
                "gewichtete_tage": state.weight_total,
                "min_tage": learner.min_days,
                "eingelernt": learner.learning_complete,
                "angewendet": learner.applied_factor is not None,
                "faktor_saison": seasonal_factor(state, today),
                "faktor_je_monat": {
                    m: v["f"] for m, v in sorted(state.monthly.items(), key=lambda x: int(x[0]))
                },
                "tagesprofil": [round(e["r"], 3) for e in state.profile],
                "tagesprofil_tage": state.profile_days,
                "jahreszeit": season_of(today),
                "tagesprofil_jahreszeit": {
                    name: [round(e["r"], 3) for e in entries]
                    for name, entries in state.profile_seasons.items()
                },
                "tagesprofil_jahreszeit_tage": {
                    name: round(max(e["w"] for e in entries), 2)
                    for name, entries in state.profile_seasons.items()
                },
                "tagesprofil_aktiv": learner.applied_profile() is not None,
                "daempfung_morgens": _damping(profile, morning=True),
                "daempfung_abends": _damping(profile, morning=False),
                "wirkungsgrad_konfiguriert": round(learner.configured_efficiency(), 4),
                "wirkungsgrad_aktiv": round(learner.current_efficiency(), 4),
            }
        if self._kind == "yield_ratio":
            intraday = learner.intraday
            return {
                "datum": state.last_date,
                "klar": state.last_clear,
                "bewoelkung": state.last_cloud,
                "bewoelkung_quelle": state.last_cloud_source,
                "gewicht": state.last_weight,
                "ist_kwh": state.last_actual_kwh,
                "prognose_kwh": state.last_forecast_kwh,
                "uebersprungen": state.last_skip_reason,
                "heute_verhaeltnis": intraday.ratio if intraday else None,
                "heute_vertrauen": intraday.weight if intraday else None,
                "verlauf": state.history[-14:],
            }
        if self._kind == "accuracy":
            summary = accuracy_summary(state)
            cor, raw, alt = summary.get("cor"), summary.get("raw"), summary.get("alt")
            model = learner.compare_model
            better = None
            if cor and alt:
                better = "plus" if cor["error"] <= alt["error"] else model
            return {
                "tage": summary["days"],
                "abweichung_plus": cor["error"] if cor else None,
                "verzerrung_plus": cor["bias"] if cor else None,
                "abweichung_ohne_lernen": raw["error"] if raw else None,
                "vergleichsmodell": model,
                "abweichung_vergleichsmodell": alt["error"] if alt else None,
                "verzerrung_vergleichsmodell": alt["bias"] if alt else None,
                "besser": better,
                "offen": state.pending,
                "verlauf": state.accuracy[-14:],
            }
        return {"min_tage": learner.min_days, "gewichtete_tage": state.weight_total}


def _damping(profile: list[float] | None, *, morning: bool) -> float | None:
    if profile is None:
        return None
    values = profile[:2] if morning else profile[-2:]
    return round(max(0.0, 1.0 - sum(values) / len(values)), 2)


class TotalSensorEntity(SensorEntity):
    """Plus: sum of all entries (whole plant)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    _ENTITY_SUFFIX = {
        "total_today": "gesamt_heute",
        "total_today_remaining": "gesamt_heute_rest",
        "total_tomorrow": "gesamt_morgen",
        "total_power_now": "gesamt_leistung",
    }

    def __init__(self, *, entry_id: str, kind: str) -> None:
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry_id}_{kind}"
        self.entity_id = f"{SENSOR_DOMAIN}.solar_forecast_plus_{self._ENTITY_SUFFIX[kind]}"
        if kind == "total_power_now":
            self._attr_device_class = SensorDeviceClass.POWER
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 0
        else:
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
            self._attr_suggested_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
            self._attr_suggested_display_precision = 1
        self._attr_device_info = _plus_device(entry_id)

    def _coordinators(self) -> list[OpenMeteoSolarForecastDataUpdateCoordinator]:
        return [
            value
            for key, value in self.hass.data.get(DOMAIN, {}).items()
            if key != "learner" and getattr(value, "data", None) is not None
        ]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FORECAST_UPDATED, self.async_write_ha_state
            )
        )
        self.async_on_remove(
            async_track_utc_time_change(self.hass, self._async_tick, second=0)
        )

    @callback
    def _async_tick(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return bool(self._coordinators())

    def _value(self, estimate: Estimate) -> float:
        if self._kind == "total_today":
            return estimate.energy_production_today
        if self._kind == "total_today_remaining":
            return estimate.energy_production_today_remaining
        if self._kind == "total_tomorrow":
            return estimate.energy_production_tomorrow
        return estimate.power_production_now

    @property
    def native_value(self) -> StateType:
        coordinators = self._coordinators()
        if not coordinators:
            return None
        return round(sum(self._value(c.data) for c in coordinators), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        coordinators = self._coordinators()
        if self._kind == "total_power_now":
            return {
                "teile_w": {
                    c.config_entry.title: round(self._value(c.data)) for c in coordinators
                }
            }
        attrs: dict[str, Any] = {
            "teile_kwh": {
                c.config_entry.title: round(self._value(c.data) / 1000, 2)
                for c in coordinators
            },
            "ohne_korrektur_kwh": round(
                sum(self._value(c.raw) for c in coordinators if c.raw is not None)
                / 1000,
                2,
            ),
        }
        if self._kind in ("total_today", "total_tomorrow"):
            target = dt_util.now().date()
            if self._kind == "total_tomorrow":
                target += timedelta(days=1)
            hours: dict[str, float] = {}
            for c in coordinators:
                for t, wh in c.data.wh_period.items():
                    if t.date() == target:
                        key = t.isoformat()
                        hours[key] = round(hours.get(key, 0.0) + wh, 1)
            attrs[ATTR_WH_PERIOD] = dict(sorted(hours.items()))
            raw_cloud = next((c.raw for c in coordinators if c.raw is not None), None)
            if raw_cloud is not None:
                attrs["bewoelkung"] = raw_cloud.daylight_cloud_cover(target)
        return attrs

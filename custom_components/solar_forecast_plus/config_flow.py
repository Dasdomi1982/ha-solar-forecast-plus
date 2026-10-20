# Modified in 2026 by Dasdomi1982 for Solar Forecast Plus (changes marked "Plus:"; see NOTICE and CHANGELOG.md).
"""Config flow for Open-Meteo Solar Forecast integration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY, CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_ARRAY_INVERTER_POWER,
    CONF_AZIMUTH,
    CONF_BASE_URL,
    CONF_DAMPING_EVENING,
    CONF_DAMPING_MORNING,
    CONF_DECLINATION,
    CONF_EFFICIENCY_FACTOR,
    CONF_INVERTER_POWER,
    CONF_MODEL,
    CONF_USE_HORIZON,
    CONF_PARTIAL_SHADING,
    CONF_HORIZON_FILEPATH,
    CONF_MAX_SNOWCOVER_DEPTH_CM,
    CONF_MODULES_POWER,
    CONF_TRACKING,
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
    LEARN_KEYS,
    TRACKING_OPTIONS,
)

try:
    from homeassistant.config_entries import ConfigFlowResult  # >=2024.4.0b0
except ImportError:
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

CONF_ADD_ANOTHER = "add_another"

DEFAULT_HORIZON_FILEPATH = (
    "/config/custom_components/solar_forecast_plus/horizon.txt"
)

# Fields that can differ per PV array. Stored as a scalar for a single array
# and as equal-length lists for multi-array setups (the format the
# coordinator already understands).
PER_ARRAY_KEYS = (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_DECLINATION,
    CONF_AZIMUTH,
    CONF_MODULES_POWER,
    CONF_ARRAY_INVERTER_POWER,
    CONF_EFFICIENCY_FACTOR,
    CONF_TRACKING,
    CONF_DAMPING_MORNING,
    CONF_DAMPING_EVENING,
    CONF_USE_HORIZON,
    CONF_PARTIAL_SHADING,
    CONF_HORIZON_FILEPATH,
)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _array_defaults(latitude: float, longitude: float) -> dict[str, Any]:
    return {
        CONF_LATITUDE: latitude,
        CONF_LONGITUDE: longitude,
        CONF_DECLINATION: 25,
        CONF_AZIMUTH: 180,
        CONF_MODULES_POWER: None,
        CONF_ARRAY_INVERTER_POWER: 0,
        CONF_EFFICIENCY_FACTOR: 1.0,
        CONF_TRACKING: "none",
        CONF_DAMPING_MORNING: 0.0,
        CONF_DAMPING_EVENING: 0.0,
        CONF_USE_HORIZON: False,
        CONF_PARTIAL_SHADING: False,
        CONF_HORIZON_FILEPATH: DEFAULT_HORIZON_FILEPATH,
    }


def _array_schema(defaults: dict[str, Any], add_another_default: bool) -> vol.Schema:
    def _field(key: str) -> vol.Marker:
        default = defaults.get(key)
        if default is None:
            return vol.Required(key)
        return vol.Required(key, default=default)

    return vol.Schema(
        {
            _field(CONF_LATITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-90, max=90, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            _field(CONF_LONGITUDE): NumberSelector(
                NumberSelectorConfig(
                    min=-180, max=180, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            _field(CONF_DECLINATION): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=90,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°",
                )
            ),
            _field(CONF_AZIMUTH): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=360,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="°",
                )
            ),
            _field(CONF_MODULES_POWER): vol.All(
                NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="Wp",
                    )
                ),
                vol.Coerce(int),
            ),
            _field(CONF_ARRAY_INVERTER_POWER): vol.All(
                NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="W",
                    )
                ),
                vol.Coerce(int),
            ),
            _field(CONF_TRACKING): SelectSelector(
                SelectSelectorConfig(
                    options=list(TRACKING_OPTIONS),
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="tracking",
                )
            ),
            _field(CONF_EFFICIENCY_FACTOR): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=1, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            _field(CONF_DAMPING_MORNING): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=1, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            _field(CONF_DAMPING_EVENING): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=1, step="any", mode=NumberSelectorMode.BOX
                )
            ),
            _field(CONF_USE_HORIZON): BooleanSelector(),
            _field(CONF_PARTIAL_SHADING): BooleanSelector(),
            vol.Optional(
                CONF_HORIZON_FILEPATH,
                default=defaults.get(CONF_HORIZON_FILEPATH, DEFAULT_HORIZON_FILEPATH),
            ): str,
            vol.Optional(CONF_ADD_ANOTHER, default=add_another_default): BooleanSelector(),
        }
    )


def _normalize_array_input(user_input: dict[str, Any]) -> dict[str, Any]:
    array = {key: user_input.get(key) for key in PER_ARRAY_KEYS}
    filepath = str(array[CONF_HORIZON_FILEPATH] or "").strip()
    array[CONF_HORIZON_FILEPATH] = filepath or DEFAULT_HORIZON_FILEPATH
    return array


def _collapse_arrays(arrays: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse per-array dicts into scalar (one array) or list options."""
    if len(arrays) == 1:
        return dict(arrays[0])
    return {key: [array[key] for array in arrays] for key in PER_ARRAY_KEYS}


def _expand_arrays(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Expand stored scalar-or-list options into one dict per array."""

    def _stored(key: str, default: Any) -> Any:
        return entry.options.get(key, entry.data.get(key, default))

    defaults = _array_defaults(0.0, 0.0)
    raw = {key: _stored(key, defaults[key]) for key in PER_ARRAY_KEYS}
    count = max(
        (len(value) for value in raw.values() if _is_sequence(value)), default=1
    )

    arrays = []
    for index in range(count):
        array = {}
        for key, value in raw.items():
            if _is_sequence(value):
                array[key] = value[index] if index < len(value) else value[0]
            else:
                array[key] = value
        arrays.append(array)
    return arrays


def _scalar(value: Any) -> Any:
    """Reduce a possibly-list legacy value to its first item."""
    if _is_sequence(value):
        return value[0] if value else None
    return value


def _learning_schema(current: dict[str, Any]) -> vol.Schema:
    """Plus: settings of the self-learning efficiency factor."""

    def _default(key: str) -> Any:
        value = current.get(key)
        return LEARN_DEFAULTS[key] if value is None else value

    def _entity(key: str) -> vol.Marker:
        value = current.get(key)
        if value:
            return vol.Optional(key, description={"suggested_value": value})
        return vol.Optional(key)

    return vol.Schema(
        {
            vol.Required(
                CONF_LEARN_ENABLED, default=_default(CONF_LEARN_ENABLED)
            ): BooleanSelector(),
            _entity(CONF_LEARN_ACTUAL_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="energy")
            ),
            _entity(CONF_LEARN_CLOUD_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_LEARN_CLOUD_THRESHOLD, default=_default(CONF_LEARN_CLOUD_THRESHOLD)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=100, step=1, mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Required(
                CONF_LEARN_SMOOTHING, default=_default(CONF_LEARN_SMOOTHING)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.05, max=1, step=0.05, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_LEARN_MIN_DAYS, default=_default(CONF_LEARN_MIN_DAYS)
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Coerce(int),
            ),
            vol.Required(
                CONF_LEARN_AUTO_APPLY, default=_default(CONF_LEARN_AUTO_APPLY)
            ): BooleanSelector(),
            vol.Required(
                CONF_LEARN_OFFSET, default=_default(CONF_LEARN_OFFSET)
            ): vol.All(
                NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=240, step=5, mode=NumberSelectorMode.BOX,
                        unit_of_measurement="min",
                    )
                ),
                vol.Coerce(int),
            ),
        }
    )


def _validate_learning(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if user_input.get(CONF_LEARN_ENABLED):
        if not user_input.get(CONF_LEARN_ACTUAL_ENTITY):
            errors[CONF_LEARN_ACTUAL_ENTITY] = "learn_actual_required"
        if not user_input.get(CONF_LEARN_CLOUD_ENTITY):
            errors[CONF_LEARN_CLOUD_ENTITY] = "learn_cloud_required"
    return errors


def _learning_options(user_input: dict[str, Any]) -> dict[str, Any]:
    return {key: user_input.get(key, LEARN_DEFAULTS[key]) for key in LEARN_KEYS}


class OpenMeteoSolarForecastFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Open-Meteo Solar Forecast."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._common: dict[str, Any] = {}
        self._arrays: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OpenMeteoSolarForecastOptionFlowHandler:
        """Get the options flow for this handler."""
        return OpenMeteoSolarForecastOptionFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the common settings."""
        if user_input is not None:
            self._common = user_input
            self._arrays = []
            return await self.async_step_array()

        return self.async_show_form(
            step_id="user",
            last_step=False,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self.hass.config.location_name
                    ): str,
                    vol.Optional(CONF_API_KEY, default=""): str,
                    vol.Required(
                        CONF_BASE_URL, default="https://api.open-meteo.com"
                    ): str,
                    vol.Optional(CONF_MODEL, default="best_match"): str,
                    vol.Required(CONF_INVERTER_POWER, default=0): vol.All(
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="W",
                            )
                        ),
                        vol.Coerce(int),
                    ),
                    vol.Required(CONF_MAX_SNOWCOVER_DEPTH_CM, default=0.0): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            step="any",
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="cm",
                        )
                    ),
                }
            ),
        )

    async def async_step_array(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the settings of one PV array."""
        if user_input is not None:
            add_another = user_input.get(CONF_ADD_ANOTHER, False)
            self._arrays.append(_normalize_array_input(user_input))
            if add_another:
                return await self.async_step_array()

            return await self.async_step_learning()

        defaults = _array_defaults(
            self.hass.config.latitude, self.hass.config.longitude
        )
        if self._arrays:
            defaults = dict(self._arrays[-1])
        return self.async_show_form(
            step_id="array",
            data_schema=_array_schema(defaults, add_another_default=False),
            description_placeholders={"array_number": str(len(self._arrays) + 1)},
        )


    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Plus: self-learning efficiency factor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_learning(user_input)
            if not errors:
                per_array = _collapse_arrays(self._arrays)
                return self.async_create_entry(
                    title=self._common[CONF_NAME],
                    data={
                        CONF_LATITUDE: per_array[CONF_LATITUDE],
                        CONF_LONGITUDE: per_array[CONF_LONGITUDE],
                    },
                    options={
                        CONF_API_KEY: self._common[CONF_API_KEY],
                        CONF_BASE_URL: self._common[CONF_BASE_URL],
                        CONF_MODEL: self._common[CONF_MODEL],
                        CONF_INVERTER_POWER: self._common[CONF_INVERTER_POWER],
                        CONF_MAX_SNOWCOVER_DEPTH_CM: self._common[
                            CONF_MAX_SNOWCOVER_DEPTH_CM
                        ],
                        **{key: per_array[key] for key in PER_ARRAY_KEYS},
                        **_learning_options(user_input),
                    },
                )

        return self.async_show_form(
            step_id="learning",
            data_schema=_learning_schema(user_input or {}),
            errors=errors,
        )


class OpenMeteoSolarForecastOptionFlowHandler(OptionsFlow):
    """Handle options."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._common: dict[str, Any] = {}
        self._arrays: list[dict[str, Any]] = []
        self._stored_arrays: list[dict[str, Any]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the common settings."""
        if user_input is not None:
            self._common = user_input
            self._arrays = []
            self._stored_arrays = _expand_arrays(self.config_entry)
            return await self.async_step_array()

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            last_step=False,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_API_KEY,
                        description={
                            "suggested_value": options.get(CONF_API_KEY, "")
                        },
                    ): str,
                    vol.Required(
                        CONF_BASE_URL, default=options[CONF_BASE_URL]
                    ): str,
                    vol.Optional(
                        CONF_MODEL, default=options.get(CONF_MODEL, "best_match")
                    ): str,
                    vol.Required(
                        CONF_INVERTER_POWER,
                        default=options.get(CONF_INVERTER_POWER, 0),
                    ): vol.All(
                        NumberSelector(
                            NumberSelectorConfig(
                                min=0,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="W",
                            )
                        ),
                        vol.Coerce(int),
                    ),
                    vol.Required(
                        CONF_MAX_SNOWCOVER_DEPTH_CM,
                        default=_scalar(
                            options.get(CONF_MAX_SNOWCOVER_DEPTH_CM, 0.0)
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            step="any",
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="cm",
                        )
                    ),
                }
            ),
        )

    async def async_step_array(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the settings of one PV array."""
        if user_input is not None:
            add_another = user_input.get(CONF_ADD_ANOTHER, False)
            self._arrays.append(_normalize_array_input(user_input))
            if add_another:
                return await self.async_step_array()

            return await self.async_step_learning()

        index = len(self._arrays)
        if index < len(self._stored_arrays):
            defaults = self._stored_arrays[index]
        else:
            defaults = dict(self._arrays[-1])
        # Default to walking through all previously configured arrays;
        # unchecking the box early drops the remaining arrays.
        add_another_default = index + 1 < len(self._stored_arrays)
        return self.async_show_form(
            step_id="array",
            data_schema=_array_schema(defaults, add_another_default),
            description_placeholders={"array_number": str(index + 1)},
        )

    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Plus: self-learning efficiency factor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_learning(user_input)
            if not errors:
                per_array = _collapse_arrays(self._arrays)
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_API_KEY: self._common.get(CONF_API_KEY),
                        CONF_BASE_URL: self._common[CONF_BASE_URL],
                        CONF_MODEL: self._common[CONF_MODEL],
                        CONF_INVERTER_POWER: self._common[CONF_INVERTER_POWER],
                        CONF_MAX_SNOWCOVER_DEPTH_CM: self._common[
                            CONF_MAX_SNOWCOVER_DEPTH_CM
                        ],
                        **{key: per_array[key] for key in PER_ARRAY_KEYS},
                        **_learning_options(user_input),
                    },
                )

        current = user_input or {
            key: self.config_entry.options.get(key) for key in LEARN_KEYS
        }
        return self.async_show_form(
            step_id="learning",
            data_schema=_learning_schema(current),
            errors=errors,
        )

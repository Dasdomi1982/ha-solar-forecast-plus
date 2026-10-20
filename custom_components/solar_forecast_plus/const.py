# Modified in 2026 by Dasdomi1982 for Solar Forecast Plus (changes marked "Plus:"; see NOTICE and CHANGELOG.md).
"""Constants for the Open-Meteo Solar Forecast integration."""

from __future__ import annotations

import logging

DOMAIN = "solar_forecast_plus"
LOGGER = logging.getLogger(__package__)

CONF_BASE_URL = "base_url"
CONF_DECLINATION = "declination"
CONF_AZIMUTH = "azimuth"
CONF_MODULES_POWER = "modules_power"
CONF_DAMPING_MORNING = "damping_morning"
CONF_DAMPING_EVENING = "damping_evening"
CONF_INVERTER_POWER = "inverter_power"
CONF_ARRAY_INVERTER_POWER = "array_inverter_power"
CONF_EFFICIENCY_FACTOR = "efficiency_factor"
CONF_TRACKING = "tracking"

TRACKING_OPTIONS = ("none", "azimuth", "tilt", "dual")
CONF_USE_HORIZON = "use_horizon"
CONF_PARTIAL_SHADING = "partial_shading"
CONF_HORIZON_FILEPATH = "horizon_filepath"
CONF_MAX_SNOWCOVER_DEPTH_CM = "max_snowcover_depth_cm"
CONF_MODEL = "model"

ATTR_WATTS = "watts"
ATTR_WH_PERIOD = "wh_period"
ATTR_WH_PERIOD_15M = "wh_period_15m"

# --- Plus: self-learning efficiency factor -----------------------------------
CONF_LEARN_ENABLED = "learn_enabled"
CONF_LEARN_ACTUAL_ENTITY = "learn_actual_entity"
CONF_LEARN_CLOUD_ENTITY = "learn_cloud_entity"
CONF_LEARN_CLOUD_THRESHOLD = "learn_cloud_threshold"
CONF_LEARN_SMOOTHING = "learn_smoothing"
CONF_LEARN_MIN_DAYS = "learn_min_days"
CONF_LEARN_AUTO_APPLY = "learn_auto_apply"
CONF_LEARN_OFFSET = "learn_sunset_offset"

LEARN_KEYS = (
    CONF_LEARN_ENABLED,
    CONF_LEARN_ACTUAL_ENTITY,
    CONF_LEARN_CLOUD_ENTITY,
    CONF_LEARN_CLOUD_THRESHOLD,
    CONF_LEARN_SMOOTHING,
    CONF_LEARN_MIN_DAYS,
    CONF_LEARN_AUTO_APPLY,
    CONF_LEARN_OFFSET,
)

LEARN_DEFAULTS = {
    CONF_LEARN_ENABLED: False,
    CONF_LEARN_ACTUAL_ENTITY: None,
    CONF_LEARN_CLOUD_ENTITY: None,
    CONF_LEARN_CLOUD_THRESHOLD: 30.0,
    CONF_LEARN_SMOOTHING: 0.2,
    CONF_LEARN_MIN_DAYS: 10,
    CONF_LEARN_AUTO_APPLY: False,
    CONF_LEARN_OFFSET: 30,
}

# A daily ratio above this is treated as implausible (sensor glitch).
LEARN_MAX_RATIO = 3.0
# Below this forecast (kWh) a day is not evaluated (night/snow/error).
LEARN_MIN_FORECAST_KWH = 1.0
LEARN_HISTORY_DAYS = 30

SIGNAL_LEARNING_UPDATED = f"{DOMAIN}_learning_updated"

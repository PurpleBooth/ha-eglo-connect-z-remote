"""Constants for the EGLO connect.z Remote integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "eglo_remote"

# The integration consumes events published by the ZHA integration.
ZHA_DOMAIN = "zha"
ZHA_EVENT = "zha_event"

# Bus event the integration fires for every translated button action.
EVENT_REMOTE_ACTION = "eglo_remote_action"

MANUFACTURER = "AwoX"

# EGLO connect.z remotes this integration knows how to interpret. The
# ERCU_3groups_Zm is the "Fernbedienung 2.0" (EGLO 99099); ERCU_Zm is the
# older remote which uses the same command set.
SUPPORTED_MODELS = ("ERCU_3groups_Zm", "ERCU_Zm")

CONF_IEEE = "ieee"
CONF_MODEL = "model"
CONF_SUBTYPE = "subtype"

ATTR_DEVICE_IEEE = "device_ieee"
ATTR_ACTION_GROUP = "action_group"
ATTR_LEVEL = "level"
ATTR_COLOR_TEMPERATURE = "color_temperature"

PLATFORMS: list[Platform] = [Platform.EVENT]

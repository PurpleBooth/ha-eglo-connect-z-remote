"""Device triggers for EGLO connect.z remotes.

The triggers are offered on the integration's own device card (the event
entity's device), and fire from the ``eglo_remote_action`` bus event that
``RemoteController`` publishes for each translated button press.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.device_automation.exceptions import (
    InvalidDeviceAutomationConfig,
)
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DEVICE_IEEE,
    CONF_IEEE,
    CONF_SUBTYPE,
    DOMAIN,
    EVENT_REMOTE_ACTION,
)
from .translator import (
    ACTION_DEFINITIONS,
    GESTURE_LONG,
    GESTURE_SHORT,
    GESTURE_ZONE,
    ActionDefinition,
)

GESTURE_TRIGGER_TYPES = {
    GESTURE_SHORT: "button_short_press",
    GESTURE_LONG: "button_long_press",
    GESTURE_ZONE: "zone_selected",
}
TRIGGER_TYPE_GESTURES = {
    trigger_type: gesture for gesture, trigger_type in GESTURE_TRIGGER_TYPES.items()
}

# One trigger per (gesture, subtype) pair; each pair maps to exactly one
# action. Sorting keeps the order stable in the automation editor.
TRIGGER_DEFINITIONS: list[ActionDefinition] = sorted(
    {
        (definition.gesture, definition.subtype): definition
        for definition in ACTION_DEFINITIONS
    }.values(),
    key=lambda definition: (definition.gesture, definition.subtype),
)

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(GESTURE_TRIGGER_TYPES.values()),
        vol.Required(CONF_SUBTYPE): vol.In(
            {definition.subtype for definition in TRIGGER_DEFINITIONS}
        ),
    }
)


def _async_get_entry(hass: HomeAssistant, device: dr.DeviceEntry):
    """Return this integration's config entry owning the device, or raise."""
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise InvalidDeviceAutomationConfig(
            f"Device {device.id} is not owned by {DOMAIN}"
        )
    return entry


def _async_get_device(hass: HomeAssistant, config: ConfigType) -> dr.DeviceEntry:
    """Return the device a trigger is attached to, or raise."""
    device = dr.async_get(hass).async_get(config[CONF_DEVICE_ID])
    if device is None:
        raise InvalidDeviceAutomationConfig(
            f"Device {config[CONF_DEVICE_ID]} not found"
        )
    _async_get_entry(hass, device)
    return device


def _async_get_ieee(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """Return the IEEE address stored in the owning config entry."""
    entry = _async_get_entry(hass, device)
    return entry.data[CONF_IEEE]


async def async_validate_trigger_config(
    hass: HomeAssistant, config: ConfigType
) -> ConfigType:
    """Validate a device trigger config."""
    _async_get_device(hass, config)
    return TRIGGER_SCHEMA(config)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List the triggers this integration offers for a device."""
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: GESTURE_TRIGGER_TYPES[definition.gesture],
            CONF_SUBTYPE: definition.subtype,
            "metadata": {"secondary": False},
        }
        for definition in TRIGGER_DEFINITIONS
    ]


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, Any]:
    """The triggers have no additional fields."""
    return {}


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger to the eglo_remote_action bus event."""
    device = _async_get_device(hass, config)
    ieee = _async_get_ieee(hass, device)
    if ieee is None:
        raise InvalidDeviceAutomationConfig(
            f"Config entry for device {device.id} is missing the IEEE address"
        )

    definition = next(
        candidate
        for candidate in TRIGGER_DEFINITIONS
        if candidate.gesture == TRIGGER_TYPE_GESTURES[config[CONF_TYPE]]
        and candidate.subtype == config[CONF_SUBTYPE]
    )

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_REMOTE_ACTION,
            event_trigger.CONF_EVENT_DATA: {
                ATTR_DEVICE_IEEE: ieee,
                "action": definition.name,
            },
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )

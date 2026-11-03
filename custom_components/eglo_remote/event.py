"""Event entity exposing the remote's button actions."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_COLOR_TEMPERATURE,
    ATTR_DEVICE_IEEE,
    ATTR_LEVEL,
    ATTR_ZONE,
    CONF_IEEE,
    CONF_MODEL,
    DOMAIN,
    EVENT_REMOTE_ACTION,
    MANUFACTURER,
)
from .translator import ACTION_NAMES

PAYLOAD_KEYS = (ATTR_ZONE, ATTR_LEVEL, ATTR_COLOR_TEMPERATURE)


def _device_name(ieee: str) -> str:
    """Return a display name that distinguishes multiple remotes."""
    return f"EGLO connect.z Remote ({ieee.replace(':', '')[-4:]})"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the event entity for a config entry."""
    async_add_entities([RemoteActionEventEntity(entry)])


class RemoteActionEventEntity(EventEntity):
    """Forward the remote's button actions as event entity events."""

    _attr_has_entity_name = True
    _attr_translation_key = "action"
    _attr_event_types = sorted(ACTION_NAMES)
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity from the config entry."""
        self._entry = entry
        ieee = entry.data[CONF_IEEE]
        self._attr_unique_id = f"{ieee}_remote_action"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ieee)},
            name=_device_name(ieee),
            manufacturer=MANUFACTURER,
            model=entry.data.get(CONF_MODEL),
        )
        self._attr_device_class = None

    async def async_added_to_hass(self) -> None:
        """Listen for actions while added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_REMOTE_ACTION, self._handle_action)
        )

    @callback
    def _handle_action(self, event: Event) -> None:
        """Record a translated action."""
        data = event.data
        if data.get(ATTR_DEVICE_IEEE) != self._entry.data[CONF_IEEE]:
            return
        attributes = {
            key: value for key in PAYLOAD_KEYS if (value := data.get(key)) is not None
        }
        self._trigger_event(data["action"], attributes or None)
        self.async_write_ha_state()

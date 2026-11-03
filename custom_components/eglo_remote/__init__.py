"""The EGLO connect.z Remote integration.

Gives ZHA-paired EGLO connect.z remotes (model ERCU_3groups_Zm / ERCU_Zm)
button actions in the form of an event entity and device triggers, which the
ZHA integration alone does not offer for these models.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    ATTR_DEVICE_IEEE,
    CONF_IEEE,
    DOMAIN,
    EVENT_REMOTE_ACTION,
    PLATFORMS,
    ZHA_EVENT,
)
from .translator import TranslationState, translate_zha_event

_LOGGER = logging.getLogger(__name__)


class RemoteController:
    """Relay ZHA events for one remote as translated actions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Store hass and entry references."""
        self.hass = hass
        self.entry = entry
        self.state = TranslationState()
        self._unsub_event: Callable[[], None] | None = None

    @property
    def ieee(self) -> str:
        """Return the Zigbee IEEE address of the remote."""
        return self.entry.data[CONF_IEEE]

    async def async_setup(self) -> None:
        """Start listening for ZHA events of this remote."""
        self._unsub_event = self.hass.bus.async_listen(ZHA_EVENT, self._on_zha_event)

    @callback
    def _on_zha_event(self, event: Event) -> None:
        """Translate a zha_event from the remote and publish the action."""
        data = event.data
        if data.get("device_ieee") != self.ieee:
            return
        payload = translate_zha_event(data, self.state)
        if payload is None:
            return
        _LOGGER.debug(
            "Translated zha_event (cluster %s, command %s) to %s",
            data.get("cluster_id"),
            data.get("command"),
            payload,
        )
        self.hass.bus.async_fire(
            EVENT_REMOTE_ACTION, {ATTR_DEVICE_IEEE: self.ieee, **payload}
        )

    @callback
    def async_shutdown(self) -> None:
        """Stop listening for ZHA events."""
        if self._unsub_event is not None:
            self._unsub_event()
            self._unsub_event = None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up an EGLO remote from a config entry."""
    controller = RemoteController(hass, entry)
    await controller.async_setup()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        controller: RemoteController = hass.data[DOMAIN].pop(entry.entry_id)
        controller.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok

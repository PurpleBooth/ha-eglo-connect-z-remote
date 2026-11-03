"""EGLO connect.z Fernbedienung 2.0 — registers a ZHA quirk for the remote.

The integration itself has no entities or services: importing :mod:`quirk`
defines the quirk device class, whose ``__init_subclass__`` queues it into
zha-quirks' pending registry; draining it makes ZHA match the paired remote.
On a fresh Home Assistant start this runs before ZHA loads its devices, so
the remote comes up with device triggers right away.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

DOMAIN = "eglo_connect_z_remote"

_LOGGER = logging.getLogger(__name__)


def _register_quirk() -> None:
    """Import the quirk (queues it) and drain zha-quirks' pending registry."""
    import zhaquirks  # noqa: PLC0415  (deferred: pulls the zigpy stack)

    from .quirk import EgloConnectZRemote  # noqa: F401, PLC0415

    zhaquirks.setup()


async def _async_register_quirk(hass: HomeAssistant) -> None:
    """Register the quirk off the event loop and report the outcome."""
    await hass.async_add_executor_job(_register_quirk)

    zha_entries = hass.config_entries.async_entries("zha")
    if zha_entries and zha_entries[0].state.is_loaded:
        # ZHA's gateway already loaded the remote without the quirk.
        _LOGGER.info(
            "EGLO connect.z Remote quirk registered; restart Home Assistant "
            "(or run ZHA's 'Reload quirks' action) so the remote picks it up"
        )
    else:
        _LOGGER.info("EGLO connect.z Remote quirk registered with zha-quirks")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the quirk when Home Assistant starts."""
    await _async_register_quirk(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Keep the quirk registered for UI-created config entries."""
    await _async_register_quirk(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry) -> bool:
    """Nothing to unload: the quirk stays registered until restart."""
    return True

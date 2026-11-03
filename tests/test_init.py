"""Tests for setup, device linking, and the event translation pipeline."""

from custom_components.eglo_remote.const import (
    ATTR_DEVICE_IEEE,
    DOMAIN,
    EVENT_REMOTE_ACTION,
)
from tests.conftest import IEEE


def fire_zha_event(hass, cluster_id, command, args=None, params=None):
    hass.bus.async_fire(
        "zha_event",
        {
            "device_ieee": IEEE,
            "device_id": "8ec72ccc7640af5d8086bb435378485b",
            "endpoint_id": 1,
            "cluster_id": cluster_id,
            "command": command,
            "args": args if args is not None else [],
            "params": params if params is not None else {},
        },
    )


async def test_setup_creates_integration_device(hass, zha_device, loaded_entry):
    from homeassistant.helpers import device_registry as dr

    devices = dr.async_get(hass).async_get_devices(identifiers={(DOMAIN, IEEE)})
    assert len(devices) == 1
    device = devices[0]
    assert device.config_entry_id == loaded_entry.entry_id
    assert device.manufacturer == "AwoX"


async def test_zha_event_is_translated_to_bus_event(hass, zha_device, loaded_entry):
    events = []
    hass.bus.async_listen(
        EVENT_REMOTE_ACTION, lambda event: events.append(dict(event.data))
    )

    fire_zha_event(hass, 5, "recall", [0, 2], {"group_id": 0, "scene_id": 2})
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0]["action"] == "recall_2"
    assert events[0][ATTR_DEVICE_IEEE] == IEEE


async def test_spurious_on_is_suppressed(hass, zha_device, loaded_entry):
    events = []
    hass.bus.async_listen(
        EVENT_REMOTE_ACTION, lambda event: events.append(dict(event.data))
    )

    fire_zha_event(
        hass, 768, "enhanced_move_hue", [1, 3072], {"move_mode": 1, "rate": 3072}
    )
    fire_zha_event(hass, 6, "on")
    await hass.async_block_till_done()

    actions = [event["action"] for event in events]
    assert actions == ["refresh_colored"]


async def test_other_device_events_are_ignored(hass, zha_device, loaded_entry):
    events = []
    hass.bus.async_listen(
        EVENT_REMOTE_ACTION, lambda event: events.append(dict(event.data))
    )

    hass.bus.async_fire(
        "zha_event",
        {
            "device_ieee": "00:11:22:33:44:55:66:77",
            "endpoint_id": 1,
            "cluster_id": 6,
            "command": "on",
            "args": [],
            "params": {},
        },
    )
    await hass.async_block_till_done()
    assert events == []


async def test_unload_stops_translation(hass, zha_device, loaded_entry):
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    # The controller must no longer translate events.
    events = []
    hass.bus.async_listen(
        EVENT_REMOTE_ACTION, lambda event: events.append(dict(event.data))
    )
    fire_zha_event(hass, 6, "on")
    await hass.async_block_till_done()
    assert events == []


async def test_setup_without_registry_device(hass):
    """Setup succeeds even when the remote is not (yet) in the registry.

    The translation is keyed on the stable IEEE address, so a remote that
    re-joins later is picked up without touching the config entry.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=IEEE,
        data={"device_id": "00000000000000000000000000000000", "ieee": IEEE},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

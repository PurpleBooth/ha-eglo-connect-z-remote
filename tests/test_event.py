"""Tests for the event entity."""

from homeassistant.helpers import entity_registry as er

from custom_components.eglo_remote.const import EVENT_REMOTE_ACTION
from tests.conftest import IEEE


def get_entity_id(hass):
    return er.async_get(hass).async_get_entity_id(
        "event", "eglo_remote", f"{IEEE}_remote_action"
    )


async def test_event_entity_created(hass, zha_device, loaded_entry, own_device):
    entity_id = get_entity_id(hass)
    assert entity_id is not None

    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["event_types"]
    assert "on" in state.attributes["event_types"]
    assert "recall_2_long" in state.attributes["event_types"]

    # The entity must belong to the integration's own device card.
    entry = er.async_get(hass).async_get(entity_id)
    assert entry.device_id == own_device.id


async def test_event_entity_records_action(hass, zha_device, loaded_entry):
    entity_id = get_entity_id(hass)

    hass.bus.async_fire(
        EVENT_REMOTE_ACTION,
        {"device_ieee": IEEE, "action": "brightness_step_up"},
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state != "None"
    assert state.attributes["event_type"] == "brightness_step_up"


async def test_event_entity_records_attributes(hass, zha_device, loaded_entry):
    entity_id = get_entity_id(hass)

    hass.bus.async_fire(
        EVENT_REMOTE_ACTION,
        {
            "device_ieee": IEEE,
            "action": "color_temperature_move",
            "color_temperature": 454,
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "color_temperature_move"
    assert state.attributes["color_temperature"] == 454


async def test_event_entity_ignores_other_remotes(hass, zha_device, loaded_entry):
    entity_id = get_entity_id(hass)
    hass.bus.async_fire(
        EVENT_REMOTE_ACTION, {"device_ieee": "aa:aa:aa:aa:aa:aa:aa:aa", "action": "on"}
    )
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.state == "unknown"

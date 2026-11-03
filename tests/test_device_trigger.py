"""Tests for the device trigger platform."""

from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import callback

from custom_components.eglo_remote import device_trigger as eglo_dt
from custom_components.eglo_remote.const import (
    ATTR_DEVICE_IEEE,
    CONF_SUBTYPE,
    DOMAIN,
    EVENT_REMOTE_ACTION,
)


async def test_triggers_are_offered_on_the_remote_device(hass, own_device):
    """The acceptance check: the automation editor lists our triggers."""
    result = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, [own_device.id]
    )
    triggers = result[own_device.id]

    ours = [t for t in triggers if t.get(CONF_DOMAIN) == DOMAIN]
    assert len(ours) == len(eglo_dt.TRIGGER_DEFINITIONS)

    subtypes = {t[CONF_SUBTYPE] for t in ours}
    assert "turn_on" in subtypes
    assert "group_2" in subtypes

    for trigger in ours:
        assert trigger[CONF_PLATFORM] == "device"
        assert trigger[CONF_DEVICE_ID] == own_device.id
        assert trigger[CONF_TYPE] in (
            "button_short_press",
            "button_long_press",
            "zone_selected",
        )


async def test_attach_trigger_fires_on_matching_action(hass, own_device):
    fired = []

    @callback
    def action(payload, context=None):
        fired.append(payload)

    config = {
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_DEVICE_ID: own_device.id,
        CONF_TYPE: "button_short_press",
        CONF_SUBTYPE: "turn_on",
    }
    remove = await eglo_dt.async_attach_trigger(
        hass, config, action, {"variables": {}, "trigger_data": {}}
    )

    hass.bus.async_fire(
        EVENT_REMOTE_ACTION,
        {ATTR_DEVICE_IEEE: "a4:c1:38:19:fb:cd:41:6e", "action": "off"},
    )
    await hass.async_block_till_done()
    assert fired == []

    hass.bus.async_fire(
        EVENT_REMOTE_ACTION,
        {ATTR_DEVICE_IEEE: "a4:c1:38:19:fb:cd:41:6e", "action": "on"},
    )
    await hass.async_block_till_done()
    assert len(fired) == 1
    assert fired[0]["trigger"]["platform"] == "device"
    assert fired[0]["trigger"]["event"].data["action"] == "on"

    remove()


async def test_validate_rejects_unknown_device(hass, loaded_entry):
    from homeassistant.components.device_automation.exceptions import (
        InvalidDeviceAutomationConfig,
    )

    config = {
        CONF_PLATFORM: "device",
        CONF_DOMAIN: DOMAIN,
        CONF_DEVICE_ID: "does-not-exist",
        CONF_TYPE: "button_short_press",
        CONF_SUBTYPE: "turn_on",
    }
    try:
        await eglo_dt.async_validate_trigger_config(hass, config)
    except InvalidDeviceAutomationConfig:
        pass
    else:
        raise AssertionError("expected InvalidDeviceAutomationConfig")

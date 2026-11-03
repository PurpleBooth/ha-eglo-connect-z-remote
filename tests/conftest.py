"""Shared fixtures for the eglo_remote test suite."""

import pytest

from custom_components.eglo_remote.const import (
    DOMAIN,
    MANUFACTURER,
    SUPPORTED_MODELS,
    ZHA_DOMAIN,
)

IEEE = "a4:c1:38:19:fb:cd:41:6e"
MODEL = SUPPORTED_MODELS[0]  # ERCU_3groups_Zm


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def zha_device(hass):
    """Create the paired ZHA remote in the device registry."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    zha_entry = MockConfigEntry(domain=ZHA_DOMAIN, title="ZHA", data={})
    zha_entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=zha_entry.entry_id,
        identifiers={(ZHA_DOMAIN, IEEE)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=f"AwoX {MODEL}",
    )
    return device


@pytest.fixture
def own_device(hass, loaded_entry):
    """The device card the integration itself creates for the remote."""
    from homeassistant.helpers import device_registry as dr

    from custom_components.eglo_remote.const import DOMAIN

    device_registry = dr.async_get(hass)
    devices = device_registry.async_get_devices(identifiers={(DOMAIN, IEEE)})
    assert len(devices) == 1
    return devices[0]


@pytest.fixture
async def loaded_entry(hass, zha_device):
    """A fully set up eglo_remote config entry for the remote."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="EGLO connect.z Remote",
        unique_id=IEEE,
        data={
            "device_id": zha_device.id,
            "ieee": IEEE,
            "model": MODEL,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry

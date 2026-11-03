"""Tests for the config flow."""

from custom_components.eglo_remote.const import DOMAIN
from tests.conftest import IEEE, MODEL


async def test_user_flow_lists_supported_remote(hass, zha_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert zha_device.id in result["data_schema"].schema["device_id"].container


async def test_user_flow_creates_entry(hass, zha_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": zha_device.id}
    )
    await hass.async_block_till_done()

    assert result["type"] == "create_entry"
    assert result["data"] == {
        "device_id": zha_device.id,
        "ieee": IEEE,
        "model": MODEL,
    }
    assert result["result"].unique_id == IEEE


async def test_duplicate_device_aborts(hass, zha_device, loaded_entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device_id": zha_device.id}
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_no_supported_remote_aborts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "no_supported_remotes"

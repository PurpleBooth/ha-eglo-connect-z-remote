"""Config flow to add an EGLO connect.z remote that is paired with ZHA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_IEEE,
    CONF_MODEL,
    DOMAIN,
    MANUFACTURER,
    SUPPORTED_MODELS,
    ZHA_DOMAIN,
)


def discover_remotes(hass: HomeAssistant) -> dict[str, str]:
    """Return candidate ZHA devices this integration supports, by device id."""
    registry = dr.async_get(hass)
    found: dict[str, str] = {}
    for device in registry.devices.values():
        if device.disabled_by:
            continue
        for domain, _ieee in device.identifiers:
            if domain != ZHA_DOMAIN:
                continue
            if (
                device.manufacturer != MANUFACTURER
                or device.model not in SUPPORTED_MODELS
            ):
                continue
            name = device.name_by_user or device.name or device.model
            found[device.id] = f"{name} ({device.model})"
            break
    return found


class EgloRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for an EGLO connect.z remote."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the step to pick a remote."""
        errors: dict[str, str] = {}
        if user_input is not None:
            registry = dr.async_get(self.hass)
            device = registry.async_get(user_input[CONF_DEVICE_ID])
            if device is None:
                errors["base"] = "device_not_found"
            else:
                ieee = next(
                    address
                    for domain, address in device.identifiers
                    if domain == ZHA_DOMAIN
                )
                await self.async_set_unique_id(ieee)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=device.name or f"EGLO Remote ({device.model})",
                    data={
                        CONF_DEVICE_ID: device.id,
                        CONF_IEEE: ieee,
                        CONF_MODEL: device.model,
                    },
                )

        candidates = discover_remotes(self.hass)
        if not candidates:
            return self.async_abort(reason="no_supported_remotes")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_ID): vol.In(candidates)}),
            errors=errors,
        )

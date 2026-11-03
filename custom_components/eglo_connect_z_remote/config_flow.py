"""Config flow: a single no-input confirmation step."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


class EgloConnectZRemoteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a flow init — just create the entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create the entry; there is nothing to configure."""
        if user_input is not None:
            return self.async_create_entry(
                title="EGLO connect.z Fernbedienung 2.0", data={}
            )

        return self.async_show_form(step_id="user")

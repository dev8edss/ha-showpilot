"""Config flow for ShowPilot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ShowPilotAuthError, ShowPilotClient, ShowPilotConnectionError, ShowPilotError
from .const import CONF_TOKEN, DOMAIN

TOKEN_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _normalise(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


class ShowPilotConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _check(self, url: str, token: str | None) -> tuple[dict[str, str], str | None]:
        """Return (errors, show name)."""
        client = ShowPilotClient(async_get_clientsession(self.hass), url, token)
        try:
            health = await client.health()
            if not health.get("ok"):
                return {"base": "not_showpilot"}, None
            state = await client.state()
            if token:
                await client.plugin_health()
        except ShowPilotAuthError:
            return {CONF_TOKEN: "invalid_auth"}, None
        except ShowPilotConnectionError:
            return {"base": "cannot_connect"}, None
        except ShowPilotError:
            return {"base": "not_showpilot"}, None
        return {}, state.get("showName") or "ShowPilot"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = _normalise(user_input[CONF_URL])
            token = (user_input.get(CONF_TOKEN) or "").strip() or None
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_configured()
            errors, title = await self._check(url, token)
            if not errors:
                return self.async_create_entry(title=title, data={CONF_URL: url, CONF_TOKEN: token})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): str,
                        vol.Optional(CONF_TOKEN): TOKEN_SELECTOR,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = _normalise(user_input[CONF_URL])
            token = (user_input.get(CONF_TOKEN) or "").strip() or None
            await self.async_set_unique_id(url.lower())
            self._abort_if_unique_id_mismatch(reason="different_server")
            errors, _ = await self._check(url, token)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_URL: url, CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_URL): str,
                        vol.Optional(CONF_TOKEN): TOKEN_SELECTOR,
                    }
                ),
                {CONF_URL: entry.data[CONF_URL]},
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.get(CONF_TOKEN) or "").strip() or None
            errors, _ = await self._check(entry.data[CONF_URL], token)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: token})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Optional(CONF_TOKEN): TOKEN_SELECTOR}),
            description_placeholders={"url": entry.data[CONF_URL]},
            errors=errors,
        )

"""Config flow for the Towngas mini-program API."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import normalize_api_url
from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_AUTHORIZATION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL_VALIDATOR = vol.All(
    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
)
URL_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
TEXT_SELECTOR = TextSelector(TextSelectorConfig())


def validate_connection_options(
    user_input: dict[str, Any], errors: dict[str, str]
) -> dict[str, Any]:
    """Normalize and validate the current API configuration."""
    normalized = dict(user_input)
    normalized[CONF_API_URL] = normalize_api_url(
        str(normalized.get(CONF_API_URL, DEFAULT_API_URL))
    )
    normalized[CONF_ACCOUNT_ID] = str(
        normalized.get(CONF_ACCOUNT_ID, "")
    ).strip()
    normalized[CONF_AUTHORIZATION] = str(
        normalized.get(CONF_AUTHORIZATION, "")
    ).strip()

    parsed = urlsplit(normalized[CONF_API_URL])
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        errors[CONF_API_URL] = "invalid_url"
    if not normalized[CONF_ACCOUNT_ID].isdecimal() or int(
        normalized[CONF_ACCOUNT_ID] or 0
    ) <= 0:
        errors[CONF_ACCOUNT_ID] = "invalid_account_id"
    if not normalized[CONF_AUTHORIZATION]:
        errors[CONF_AUTHORIZATION] = "authorization_required"
    return normalized


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_API_URL, default=defaults.get(CONF_API_URL, DEFAULT_API_URL)
            ): URL_SELECTOR,
            vol.Required(
                CONF_ACCOUNT_ID, default=defaults.get(CONF_ACCOUNT_ID, "")
            ): TEXT_SELECTOR,
            vol.Required(
                CONF_AUTHORIZATION,
                default=defaults.get(CONF_AUTHORIZATION, ""),
            ): PASSWORD_SELECTOR,
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(
                    CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                ),
            ): UPDATE_INTERVAL_VALIDATOR,
        }
    )


class TowngasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Towngas account."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Create a current-API-only config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = validate_connection_options(user_input, errors)
            if not errors:
                await self.async_set_unique_id(
                    f"{DOMAIN}_{normalized[CONF_ACCOUNT_ID]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"港华燃气 {normalized[CONF_ACCOUNT_ID]}",
                    data=normalized,
                )
            user_input = normalized

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TowngasOptionsFlowHandler(config_entry)


class TowngasOptionsFlowHandler(config_entries.OptionsFlow):
    """Update API credentials and refresh interval."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show current API options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            normalized = validate_connection_options(user_input, errors)
            if not errors:
                return self.async_create_entry(title="", data=normalized)
            user_input = normalized

        defaults = dict(self._config_entry.data)
        defaults.update(self._config_entry.options)
        if user_input is not None:
            defaults.update(user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(defaults), errors=errors
        )

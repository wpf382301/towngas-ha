"""Config flow for the Towngas integration."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_FLARESOLVERR_URL,
    CONF_HOST,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=5, max=1440))
URL_VALIDATOR = vol.All(str, vol.Url())


def load_org_list() -> list[dict[str, Any]]:
    """Load the organization list from the bundled JSON file."""
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orglist.json")
    try:
        with open(file_path, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as err:
        _LOGGER.error("Failed to load organization list: %s", err)
        return []

    organizations = data.get("orgList", [])
    return organizations if isinstance(organizations, list) else []


class TowngasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Towngas config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        self.org_list: list[dict[str, Any]] = []
        self.selected_org: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select the Towngas organization."""
        errors: dict[str, str] = {}

        if not self.org_list:
            self.org_list = await self.hass.async_add_executor_job(load_org_list)
            if not self.org_list:
                return self.async_abort(reason="no_orgs")

        if user_input is not None:
            self.selected_org = next(
                (
                    organization
                    for organization in self.org_list
                    if organization.get("orgCode") == user_input["org_code"]
                ),
                None,
            )
            if self.selected_org is not None:
                return await self.async_step_account()
            errors["base"] = "invalid_org"

        organization_options = {
            organization["orgCode"]: (
                f"{organization.get('shortName', organization.get('orgName', '未知'))} "
                f"({organization.get('desc', '')})"
            )
            for organization in self.org_list
            if organization.get("orgCode")
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("org_code"): vol.In(organization_options)}
            ),
            errors=errors,
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure the account and fallback service."""
        if self.selected_org is None:
            return self.async_abort(reason="invalid_org")

        if user_input is not None:
            unique_id = f"{user_input[CONF_SUBS_CODE]}_{self.selected_org['orgCode']}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=(
                    f"Towngas {self.selected_org.get('shortName', '')} "
                    f"{user_input[CONF_SUBS_CODE]}"
                ),
                data={
                    CONF_SUBS_CODE: user_input[CONF_SUBS_CODE],
                    CONF_ORG_CODE: self.selected_org["orgCode"],
                    CONF_HOST: self.selected_org["host"],
                    CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL],
                    CONF_FLARESOLVERR_URL: user_input.get(
                        CONF_FLARESOLVERR_URL, DEFAULT_FLARESOLVERR_URL
                    ),
                },
            )

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SUBS_CODE): str,
                    vol.Optional(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): UPDATE_INTERVAL_VALIDATOR,
                    vol.Optional(
                        CONF_FLARESOLVERR_URL, default=DEFAULT_FLARESOLVERR_URL
                    ): URL_VALIDATOR,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return TowngasOptionsFlowHandler(config_entry)


class TowngasOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Towngas options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage update and FlareSolverr options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_UPDATE_INTERVAL,
                            self._config_entry.data.get(
                                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                            ),
                        ),
                    ): UPDATE_INTERVAL_VALIDATOR,
                    vol.Optional(
                        CONF_FLARESOLVERR_URL,
                        default=self._config_entry.options.get(
                            CONF_FLARESOLVERR_URL,
                            self._config_entry.data.get(
                                CONF_FLARESOLVERR_URL, DEFAULT_FLARESOLVERR_URL
                            ),
                        ),
                    ): URL_VALIDATOR,
                }
            ),
        )

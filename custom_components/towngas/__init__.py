"""The Towngas integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_FLARESOLVERR_URL,
    CONF_HOST,
    CONF_MINI_ACCOUNT_ID,
    CONF_MINI_API_TOKEN,
    CONF_MINI_API_URL,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
)
from .sensor import TowngasRecoverableError, TowngasCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
_LOGGER = logging.getLogger(__name__)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after user-visible options change, but not token rotation."""
    coordinator = entry.runtime_data
    if coordinator.matches_config_entry(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Towngas from a config entry."""
    config = entry.data
    options = entry.options
    coordinator = TowngasCoordinator(
        hass=hass,
        entry=entry,
        subs_code=config[CONF_SUBS_CODE],
        org_code=config[CONF_ORG_CODE],
        host=config[CONF_HOST],
        update_interval=options.get(
            CONF_UPDATE_INTERVAL,
            config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ),
        flaresolverr_url=options.get(
            CONF_FLARESOLVERR_URL,
            config.get(CONF_FLARESOLVERR_URL, DEFAULT_FLARESOLVERR_URL),
        ),
        mini_api_url=options.get(
            CONF_MINI_API_URL, config.get(CONF_MINI_API_URL, "")
        ),
        mini_api_token=options.get(
            CONF_MINI_API_TOKEN, config.get(CONF_MINI_API_TOKEN, "")
        ),
        mini_account_id=options.get(
            CONF_MINI_ACCOUNT_ID, config.get(CONF_MINI_ACCOUNT_ID, "")
        ),
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        if not isinstance(err.__cause__, TowngasRecoverableError):
            raise
        _LOGGER.warning(
            "Towngas credentials need attention; loading entities in unavailable "
            "state and waiting for updated options or a manual refresh: %s",
            err.__cause__,
        )
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Towngas config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

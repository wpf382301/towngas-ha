"""The Towngas integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FLARESOLVERR_URL,
    CONF_HOST,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
)
from .sensor import TowngasCoordinator

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


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
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Towngas config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

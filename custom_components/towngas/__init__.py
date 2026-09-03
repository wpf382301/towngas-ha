"""The Towngas integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .api import normalize_api_url
from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_AUTHORIZATION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_API_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LEGACY_CONF_MINI_ACCOUNT_ID,
    LEGACY_CONF_MINI_API_TOKEN,
    LEGACY_CONF_MINI_API_URL,
    LEGACY_CONF_ORG_CODE,
    LEGACY_CONF_SUBS_CODE,
    LEGACY_CONF_UPDATE_INTERVAL,
)
from .coordinator import TowngasCoordinator, TowngasRecoverableError
from .storage import TowngasStorage

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]
_LOGGER = logging.getLogger(__name__)


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrate v1 settings and preserve useful entity IDs."""
    if config_entry.version >= 2:
        return True

    data = config_entry.data
    options = config_entry.options

    def legacy_value(key: str, legacy_key: str, default: object = "") -> object:
        return options.get(
            key,
            options.get(legacy_key, data.get(key, data.get(legacy_key, default))),
        )

    account_id = str(
        legacy_value(CONF_ACCOUNT_ID, LEGACY_CONF_MINI_ACCOUNT_ID)
    ).strip()
    authorization = str(
        legacy_value(CONF_AUTHORIZATION, LEGACY_CONF_MINI_API_TOKEN)
    ).strip()
    if not account_id or not authorization:
        _LOGGER.error(
            "Cannot migrate Towngas entry without account_id and Authorization"
        )
        return False

    new_data = {
        CONF_API_URL: normalize_api_url(
            str(
                legacy_value(
                    CONF_API_URL, LEGACY_CONF_MINI_API_URL, DEFAULT_API_URL
                )
                or DEFAULT_API_URL
            )
        ),
        CONF_ACCOUNT_ID: account_id,
        CONF_AUTHORIZATION: authorization,
        CONF_UPDATE_INTERVAL: int(
            legacy_value(
                CONF_UPDATE_INTERVAL,
                LEGACY_CONF_UPDATE_INTERVAL,
                DEFAULT_UPDATE_INTERVAL,
            )
        ),
    }

    registry = er.async_get(hass)
    old_suffix = (
        f"{data.get(LEGACY_CONF_SUBS_CODE, '')}_"
        f"{data.get(LEGACY_CONF_ORG_CODE, '')}"
    )
    stable_prefix = f"{DOMAIN}_{config_entry.entry_id}"
    unique_id_updates = {
        f"towngas_balance_{old_suffix}": f"{stable_prefix}_balance",
        f"towngas_meter_reading_{old_suffix}": f"{stable_prefix}_meter_reading",
        f"towngas_refresh_{old_suffix}": f"{stable_prefix}_refresh",
    }
    obsolete_unique_ids = {
        f"towngas_latest_bill_month_{old_suffix}",
        f"towngas_latest_bill_usage_{old_suffix}",
        f"towngas_latest_bill_charge_{old_suffix}",
        f"towngas_latest_bill_unpaid_{old_suffix}",
    }
    for entity in er.async_entries_for_config_entry(
        registry, config_entry.entry_id
    ):
        if entity.unique_id in obsolete_unique_ids:
            registry.async_remove(entity.entity_id)
        elif entity.unique_id in unique_id_updates:
            registry.async_update_entity(
                entity.entity_id,
                new_unique_id=unique_id_updates[entity.unique_id],
            )

    hass.config_entries.async_update_entry(
        config_entry,
        data=new_data,
        options={},
        title=f"港华燃气 {account_id}",
        unique_id=f"{DOMAIN}_{account_id}",
        version=2,
    )
    _LOGGER.info("Migrated Towngas config entry to current API schema")
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when a user-visible option changed."""
    coordinator = entry.runtime_data
    if coordinator.matches_config_entry(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Towngas from a config entry."""
    storage = TowngasStorage(hass, entry.entry_id)
    await storage.async_load()
    coordinator = TowngasCoordinator(hass, entry, storage)
    entry.runtime_data = coordinator
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady as err:
        if not isinstance(err.__cause__, TowngasRecoverableError):
            raise
        _LOGGER.warning(
            "Towngas Authorization needs to be refreshed; entities are loaded "
            "unavailable so the manual synchronization button remains usable"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Towngas config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

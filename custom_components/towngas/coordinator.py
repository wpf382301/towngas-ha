"""Data coordinator for Towngas."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    TowngasApiClient,
    TowngasApiError,
    TowngasAuthenticationError,
    normalize_api_url,
)
from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_AUTHORIZATION,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .models import TowngasDataError, build_snapshot, parse_bills, parse_detail, parse_price
from .storage import TowngasStorage

_LOGGER = logging.getLogger(__name__)


class TowngasRecoverableError(UpdateFailed):
    """Raised when updating captured credentials can restore service."""


def config_value(entry: ConfigEntry, key: str, default: Any = "") -> Any:
    """Read an option override or its config-entry default."""
    return entry.options.get(key, entry.data.get(key, default))


class TowngasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Synchronize all current mini-program resources in one refresh."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        storage: TowngasStorage,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._storage = storage
        self.last_error: str | None = None
        self.last_updated: datetime | None = None
        self._api = TowngasApiClient(
            async_get_clientsession(hass),
            str(config_value(entry, CONF_API_URL)),
            str(config_value(entry, CONF_ACCOUNT_ID)),
            str(config_value(entry, CONF_AUTHORIZATION)),
            self._persist_session,
        )
        interval = int(
            config_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=interval),
        )

    def matches_config_entry(self, entry: ConfigEntry) -> bool:
        """Return whether entry updates are already active in this coordinator."""
        return (
            normalize_api_url(str(config_value(entry, CONF_API_URL)))
            == self._api.api_url
            and str(config_value(entry, CONF_ACCOUNT_ID)).strip()
            == self._api.account_id
            and str(config_value(entry, CONF_AUTHORIZATION)).strip()
            == self._api.authorization
            and int(config_value(entry, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
            == int(self.update_interval.total_seconds() / 60)
        )

    def _persist_session(self, authorization: str, account_id: str) -> None:
        """Persist rotated response credentials without logging their values."""
        data = dict(self._entry.data)
        options = dict(self._entry.options)
        target = options if options else data
        changed = False
        if target.get(CONF_AUTHORIZATION) != authorization:
            target[CONF_AUTHORIZATION] = authorization
            changed = True
        if target.get(CONF_ACCOUNT_ID) != account_id:
            target[CONF_ACCOUNT_ID] = account_id
            changed = True
        if changed:
            self._hass.config_entries.async_update_entry(
                self._entry, data=data, options=options
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch details, complete bill history pages and annual price tiers."""
        try:
            detail_payload = await self._api.async_get_detail()
            detail = parse_detail(detail_payload, self._api.account_id)
            raw_bills = await self._api.async_get_bills()
            bills = parse_bills(raw_bills, detail["customer_number"])
            price_payload = await self._api.async_get_price()
            tiers, annual_usage = parse_price(price_payload)
            stored_bills = await self._storage.async_merge(bills)
            snapshot = build_snapshot(
                detail,
                stored_bills,
                tiers,
                annual_usage,
                dt_util.now().strftime("%Y-%m"),
            )
        except TowngasAuthenticationError as err:
            self.last_error = str(err)
            raise TowngasRecoverableError(str(err)) from err
        except (TowngasApiError, TowngasDataError, aiohttp.ClientError) as err:
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err

        self.last_error = None
        self.last_updated = dt_util.utcnow()
        snapshot["data_updated_at"] = self.last_updated.isoformat()
        _LOGGER.debug(
            "Towngas data updated: %d retained bills", len(stored_bills)
        )
        return snapshot

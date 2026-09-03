"""Persistent sanitized bill history for Towngas."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY_PREFIX, STORAGE_VERSION


class TowngasStorage:
    """Merge bills by month without deleting older records."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}"
        )
        self._bills: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        """Load a previously saved history."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        bills = stored.get("bills")
        if not isinstance(bills, dict):
            return
        self._bills = {
            month: deepcopy(bill)
            for month, bill in bills.items()
            if isinstance(month, str) and isinstance(bill, dict)
        }

    @property
    def bills(self) -> list[dict[str, Any]]:
        """Return all bills ordered newest first."""
        return [
            deepcopy(self._bills[month])
            for month in sorted(self._bills, reverse=True)
        ]

    async def async_merge(self, bills: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add or update records while retaining months absent from this refresh."""
        merged = deepcopy(self._bills)
        for bill in bills:
            month = bill.get("month")
            if isinstance(month, str) and month:
                merged[month] = {**merged.get(month, {}), **deepcopy(bill)}
        if merged != self._bills:
            self._bills = merged
            await self._store.async_save({"bills": self._bills})
        return self.bills

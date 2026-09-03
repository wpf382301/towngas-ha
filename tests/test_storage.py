"""Tests for retained Towngas bill history."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from custom_components.towngas.storage import TowngasStorage


class FakeStore:
    initial: dict | None = None

    def __init__(self, *args: object) -> None:
        self.saved: dict | None = None

    async def async_load(self) -> dict | None:
        return self.initial

    async def async_save(self, data: dict) -> None:
        self.saved = data


class TowngasStorageTests(unittest.IsolatedAsyncioTestCase):
    """Ensure absent server records never delete saved bills."""

    @patch("custom_components.towngas.storage.Store", FakeStore)
    async def test_merge_updates_and_retains_history(self) -> None:
        FakeStore.initial = {
            "bills": {
                "2026-07": {"month": "2026-07", "usage": 16, "charge": 40},
                "2025-12": {"month": "2025-12", "usage": 10, "charge": 29.7},
            }
        }
        storage = TowngasStorage(object(), "entry")
        await storage.async_load()

        bills = await storage.async_merge(
            [{"month": "2026-07", "usage": 16, "charge": 47.52}]
        )

        self.assertEqual([item["month"] for item in bills], ["2026-07", "2025-12"])
        self.assertEqual(bills[0]["charge"], 47.52)


if __name__ == "__main__":
    unittest.main()

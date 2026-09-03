"""Tests for the Towngas full synchronization button."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.towngas.button import TowngasRefreshButton, refresh_error_message


class TowngasButtonTests(unittest.IsolatedAsyncioTestCase):
    """Verify refresh behavior and credential guidance."""

    async def test_press_refreshes_all_data(self) -> None:
        button = object.__new__(TowngasRefreshButton)
        button.coordinator = SimpleNamespace(
            async_request_refresh=AsyncMock(),
            last_update_success=True,
            last_error=None,
        )

        await button.async_press()

        button.coordinator.async_request_refresh.assert_awaited_once()

    async def test_press_reports_failure(self) -> None:
        button = object.__new__(TowngasRefreshButton)
        button.coordinator = SimpleNamespace(
            async_request_refresh=AsyncMock(),
            last_update_success=False,
            last_error="detail authentication failed (HTTP 401)",
        )

        with self.assertRaisesRegex(HomeAssistantError, "Authorization"):
            await button.async_press()

    def test_generic_error_keeps_diagnostic(self) -> None:
        self.assertIn("bill connection failed", refresh_error_message("bill connection failed"))


if __name__ == "__main__":
    unittest.main()

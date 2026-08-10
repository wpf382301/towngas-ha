"""Tests for the Towngas manual-refresh button."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.towngas.button import TowngasRefreshButton


def make_button(*, success: bool) -> TowngasRefreshButton:
    """Build a button without an entity platform for a pure unit test."""
    button = object.__new__(TowngasRefreshButton)
    button.coordinator = SimpleNamespace(
        async_request_refresh=AsyncMock(),
        last_update_success=success,
    )
    return button


class TowngasRefreshButtonTests(unittest.IsolatedAsyncioTestCase):
    """Verify immediate refresh behavior."""

    async def test_press_requests_refresh(self) -> None:
        button = make_button(success=True)

        await button.async_press()

        button.coordinator.async_request_refresh.assert_awaited_once()

    async def test_press_reports_failed_refresh(self) -> None:
        button = make_button(success=False)

        with self.assertRaises(HomeAssistantError):
            await button.async_press()

        button.coordinator.async_request_refresh.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

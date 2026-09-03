"""Tests for the Towngas manual-refresh button."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.towngas.button import (
    TowngasRefreshButton,
    refresh_error_message,
)


def make_button(
    *, success: bool, error: str | None = None
) -> TowngasRefreshButton:
    """Build a button without an entity platform for a pure unit test."""
    button = object.__new__(TowngasRefreshButton)
    button.coordinator = SimpleNamespace(
        async_request_refresh=AsyncMock(),
        last_update_success=success,
        last_error=error,
    )
    return button


class TowngasRefreshButtonTests(unittest.IsolatedAsyncioTestCase):
    """Verify immediate refresh behavior."""

    async def test_press_requests_refresh(self) -> None:
        button = make_button(success=True)

        await button.async_press()

        button.coordinator.async_request_refresh.assert_awaited_once()

    async def test_press_reports_failed_refresh(self) -> None:
        button = make_button(
            success=False,
            error="API error: 未绑定此户号 (resultCode=60151)",
        )

        with self.assertRaisesRegex(
            HomeAssistantError,
            "泰安泰山港华燃气有限公司.*重新绑定",
        ):
            await button.async_press()

        button.coordinator.async_request_refresh.assert_awaited_once()


class TowngasRefreshErrorMessageTests(unittest.TestCase):
    """Verify actionable refresh error messages."""

    def test_account_not_bound_message(self) -> None:
        message = refresh_error_message(
            "API error: 未绑定此户号 (resultCode=60151)"
        )
        self.assertIn("60151", message)
        self.assertIn("微信公众号", message)
        self.assertIn("重新绑定", message)

    def test_other_error_keeps_detail(self) -> None:
        self.assertEqual(
            refresh_error_message("HTTP error status 503"),
            "港华燃气余额更新失败：HTTP error status 503",
        )

    def test_missing_error_uses_fallback(self) -> None:
        self.assertIn("Home Assistant 日志", refresh_error_message(None))


if __name__ == "__main__":
    unittest.main()

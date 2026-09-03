"""Tests for the Towngas sensor coordinator."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.towngas.sensor import (
    TowngasAccountNotBound,
    TowngasCoordinator,
)


def make_coordinator() -> TowngasCoordinator:
    """Build a coordinator instance for pure unit tests."""
    coordinator = object.__new__(TowngasCoordinator)
    coordinator._subs_code = "123456"
    coordinator._org_code = "ORG01"
    coordinator._host = "https://example.invalid"
    coordinator._api_url = (
        "https://example.invalid/openapi/uv1/biz/checkRouters"
    )
    coordinator._flaresolverr_url = "http://127.0.0.1:8191/v1"
    coordinator._last_used_flaresolverr = False
    coordinator.last_error = None
    coordinator.last_updated = None
    return coordinator


class TowngasParserTests(unittest.TestCase):
    """Test response parsing and payload construction."""

    def test_parse_json(self) -> None:
        coordinator = make_coordinator()
        result = coordinator._parse_response(
            200,
            "application/json",
            '{"code": 0, "data": {"savingSum": 12.34}}',
        )
        self.assertEqual(result["savingSum"], 12.34)
        self.assertIsNotNone(coordinator.last_updated)

    def test_parse_html_pre(self) -> None:
        coordinator = make_coordinator()
        result = coordinator._parse_response(
            200,
            "text/html; charset=utf-8",
            '<html><pre>{&quot;data&quot;:{&quot;savingSum&quot;:8.5}}</pre></html>',
        )
        self.assertEqual(result["savingSum"], 8.5)

    def test_parse_jsonp(self) -> None:
        coordinator = make_coordinator()
        result = coordinator._parse_response(
            200,
            "application/javascript",
            'callback({"data":{"savingSum":1.25}})',
        )
        self.assertEqual(result["savingSum"], 1.25)

    def test_reject_missing_balance(self) -> None:
        coordinator = make_coordinator()
        with self.assertRaises(UpdateFailed):
            coordinator._parse_response(200, "application/json", '{"code":0}')

    def test_reject_account_not_bound_with_actionable_error(self) -> None:
        coordinator = make_coordinator()
        with self.assertRaisesRegex(
            TowngasAccountNotBound,
            r"未绑定此户号.*resultCode=60151",
        ):
            coordinator._parse_response(
                200,
                "application/json",
                '{"resultCode":"60151","resultMsg":"未绑定此户号"}',
            )

    def test_accept_string_zero_code(self) -> None:
        coordinator = make_coordinator()
        result = coordinator._parse_response(
            200,
            "application/json",
            '{"code":"0","data":{"savingSum":6.5}}',
        )
        self.assertEqual(result["savingSum"], 6.5)

    def test_flaresolverr_payload_is_sessionless(self) -> None:
        coordinator = make_coordinator()
        payload = coordinator._build_flaresolverr_payload()
        self.assertEqual(payload["cmd"], "request.get")
        self.assertNotIn("session", payload)
        self.assertTrue(payload["disableMedia"])
        self.assertIn("subsCode=123456", payload["url"])


class TowngasUpdateTests(unittest.IsolatedAsyncioTestCase):
    """Test direct/fallback update decisions."""

    async def test_direct_success_skips_flaresolverr(self) -> None:
        coordinator = make_coordinator()
        coordinator._direct_request = AsyncMock(
            return_value=(
                200,
                "application/json",
                '{"data":{"savingSum":20.5}}',
            )
        )
        coordinator._flaresolverr_request = AsyncMock()

        result = await coordinator._async_update_data()

        self.assertEqual(result["savingSum"], 20.5)
        coordinator._flaresolverr_request.assert_not_awaited()
        self.assertFalse(coordinator._last_used_flaresolverr)

    async def test_antibot_uses_temporary_fallback(self) -> None:
        coordinator = make_coordinator()
        coordinator._direct_request = AsyncMock(
            return_value=(200, "text/html", "<html>challenge</html>")
        )
        coordinator._flaresolverr_request = AsyncMock(
            return_value=(
                200,
                "application/json",
                '{"data":{"savingSum":30.75}}',
            )
        )

        result = await coordinator._async_update_data()

        self.assertEqual(result["savingSum"], 30.75)
        coordinator._flaresolverr_request.assert_awaited_once()
        self.assertTrue(coordinator._last_used_flaresolverr)

        # Every refresh retries the lightweight path instead of permanently
        # pinning the coordinator to a browser session.
        await coordinator._async_update_data()
        self.assertEqual(coordinator._direct_request.await_count, 2)

    async def test_account_not_bound_is_not_hidden_by_fallback_error(self) -> None:
        coordinator = make_coordinator()
        coordinator._direct_request = AsyncMock(
            return_value=(202, "text/html", "<html>challenge</html>")
        )
        coordinator._flaresolverr_request = AsyncMock(
            return_value=(
                200,
                "application/json",
                '{"resultCode":"60151","resultMsg":"未绑定此户号"}',
            )
        )

        with self.assertRaisesRegex(
            TowngasAccountNotBound,
            r"未绑定此户号.*resultCode=60151",
        ):
            await coordinator._async_update_data()

        self.assertIn("未绑定此户号", coordinator.last_error)


if __name__ == "__main__":
    unittest.main()

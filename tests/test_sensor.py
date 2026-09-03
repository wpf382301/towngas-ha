"""Tests for the Towngas sensor coordinator."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.towngas.sensor import (
    TowngasAccountNotBound,
    TowngasCoordinator,
    TowngasMiniApiAuthenticationError,
)


def make_coordinator() -> TowngasCoordinator:
    """Build a coordinator instance for pure unit tests."""
    coordinator = object.__new__(TowngasCoordinator)
    coordinator._subs_code = "123456"
    coordinator._org_code = "ORG01"
    coordinator._host = "https://example.invalid"
    coordinator._update_interval_minutes = 30
    coordinator._api_url = (
        "https://example.invalid/openapi/uv1/biz/checkRouters"
    )
    coordinator._flaresolverr_url = "http://127.0.0.1:8191/v1"
    coordinator._mini_api_url = ""
    coordinator._mini_api_token = ""
    coordinator._mini_account_id = ""
    coordinator._entry = SimpleNamespace(data={}, options={})
    coordinator._hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=Mock())
    )
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

    def test_parse_mini_program_account_response(self) -> None:
        coordinator = make_coordinator()
        result = coordinator._parse_mini_response(
            200,
            "application/json; charset=utf-8",
            """{
                "code": 0,
                "message": "ok",
                "data": {
                    "data": {"account": "123456"},
                    "last": {"currreading": "110", "recorddate": "2026-09-03"},
                    "tci": {"presaving": "173.3", "userid": "123456"}
                }
            }""",
        )

        self.assertEqual(result["savingSum"], 173.3)
        self.assertEqual(result["data_source"], "mini_program")
        self.assertEqual(result["meter_reading"], "110")
        self.assertEqual(result["meter_reading_date"], "2026-09-03")

    def test_reject_mini_program_account_mismatch(self) -> None:
        coordinator = make_coordinator()
        with self.assertRaisesRegex(UpdateFailed, "does not match"):
            coordinator._parse_mini_response(
                200,
                "application/json",
                '{"code":0,"data":{"data":{"account":"654321"},'
                '"tci":{"presaving":"1.0"}}}',
            )

    def test_mini_program_login_error_is_actionable(self) -> None:
        coordinator = make_coordinator()
        with self.assertRaisesRegex(
            TowngasMiniApiAuthenticationError, "登录身份不一致"
        ):
            coordinator._parse_mini_response(
                200,
                "application/json",
                '{"code":9999,"message":"登录身份不一致,请重新登录"}',
            )

    def test_persist_rotated_mini_program_token(self) -> None:
        coordinator = make_coordinator()
        coordinator._mini_api_token = "old-token"
        coordinator._mini_account_id = "100"
        coordinator._entry = SimpleNamespace(
            data={"mini_api_token": "old-token", "mini_account_id": "100"},
            options={},
        )

        coordinator._persist_mini_session("new-token", "101")

        call = coordinator._hass.config_entries.async_update_entry.call_args
        self.assertEqual(call.kwargs["data"]["mini_api_token"], "new-token")
        self.assertEqual(call.kwargs["data"]["mini_account_id"], "101")

    def test_rotated_credentials_match_updated_entry(self) -> None:
        coordinator = make_coordinator()
        coordinator._mini_api_url = "https://mini.example.invalid/account"
        coordinator._mini_api_token = "new-token"
        coordinator._mini_account_id = "101"
        entry = SimpleNamespace(
            data={
                "subsCode": "123456",
                "orgCode": "ORG01",
                "host": "https://example.invalid",
                "updatetime": 30,
                "flaresolverr_url": "http://127.0.0.1:8191/v1",
                "mini_api_url": "https://mini.example.invalid/account",
                "mini_api_token": "new-token",
                "mini_account_id": "101",
            },
            options={},
        )

        self.assertTrue(coordinator.matches_config_entry(entry))


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

    async def test_mini_program_success_skips_legacy_requests(self) -> None:
        coordinator = make_coordinator()
        coordinator._mini_api_url = "https://mini.example.invalid/account"
        coordinator._mini_api_token = "current-token"
        coordinator._mini_account_id = "100"
        coordinator._mini_program_request = AsyncMock(
            return_value=(
                200,
                "application/json",
                '{"code":0,"data":{"data":{"account":"123456"},'
                '"tci":{"presaving":"88.6"}}}',
                "current-token",
                "100",
            )
        )
        coordinator._direct_request = AsyncMock()
        coordinator._flaresolverr_request = AsyncMock()

        result = await coordinator._async_update_data()

        self.assertEqual(result["savingSum"], 88.6)
        coordinator._direct_request.assert_not_awaited()
        coordinator._flaresolverr_request.assert_not_awaited()

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

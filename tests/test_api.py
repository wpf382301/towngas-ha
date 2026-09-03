"""Tests for current Towngas API request behavior."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from custom_components.towngas.api import (
    TowngasApiClient,
    TowngasConnectionError,
    normalize_api_url,
)


class FakeResponse:
    def __init__(self, body: dict, headers: dict[str, str] | None = None) -> None:
        self.status = 200
        self._body = body
        self.headers = {"Content-Type": "application/json", **(headers or {})}

    async def json(self, content_type: object = None) -> dict:
        return self._body

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(self, responses: list[FakeResponse | BaseException]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class TowngasApiTests(unittest.IsolatedAsyncioTestCase):
    """Verify endpoint selection, pagination, rotation and retries."""

    def test_normalize_captured_url(self) -> None:
        self.assertEqual(
            normalize_api_url(
                "https://rqjf.jnyuxia.com/api/gas/detail?id=25076"
            ),
            "https://rqjf.jnyuxia.com",
        )

    async def test_rotated_token_is_used_by_next_request(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {"code": 0, "data": {"data": {}, "last": {}, "tci": {}}},
                    {"Authorization": "new-token", "accountid": "25076"},
                ),
                FakeResponse(
                    {"code": 0, "data": {"data": [], "total": 0}}
                ),
            ]
        )
        updates: list[tuple[str, str]] = []
        client = TowngasApiClient(
            session,
            "https://example.invalid",
            "25076",
            "old-token",
            lambda authorization, account_id: updates.append(
                (authorization, account_id)
            ),
        )

        await client.async_get_detail()
        await client.async_get_bills()

        self.assertEqual(updates, [("new-token", "25076")])
        self.assertEqual(session.calls[1]["headers"]["Authorization"], "new-token")

    async def test_bill_api_is_paginated(self) -> None:
        session = FakeSession(
            [
                FakeResponse({"code": 0, "data": {"data": [{"yrmonth": "1"}], "total": 2}}),
                FakeResponse({"code": 0, "data": {"data": [{"yrmonth": "2"}], "total": 2}}),
            ]
        )
        client = TowngasApiClient(
            session, "https://example.invalid", "25076", "token", lambda *_: None
        )

        records = await client.async_get_bills()

        self.assertEqual(len(records), 2)
        self.assertEqual(session.calls[0]["json"]["page"], 1)
        self.assertEqual(session.calls[1]["json"]["page"], 2)

    @patch("custom_components.towngas.api.asyncio.sleep", new_callable=AsyncMock)
    async def test_connection_failure_is_bounded(self, sleep: AsyncMock) -> None:
        session = FakeSession(
            [aiohttp.ClientConnectionError("down") for _ in range(3)]
        )
        client = TowngasApiClient(
            session, "https://example.invalid", "25076", "token", lambda *_: None
        )

        with self.assertRaises(TowngasConnectionError):
            await client.async_get_detail()

        self.assertEqual(len(session.calls), 3)
        self.assertEqual(sleep.await_count, 2)


if __name__ == "__main__":
    unittest.main()

"""Client for the current Towngas mini-program API."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

from .const import DEFAULT_API_URL

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
REQUEST_ATTEMPTS = 3
MAX_BILL_PAGES = 20
BILL_PAGE_SIZE = 12


class TowngasApiError(Exception):
    """Base exception for Towngas API failures."""


class TowngasAuthenticationError(TowngasApiError):
    """Raised when the captured Authorization is no longer valid."""


class TowngasConnectionError(TowngasApiError):
    """Raised after bounded connection retries are exhausted."""


def normalize_api_url(configured_url: str) -> str:
    """Return the service base URL from a base or captured endpoint URL."""
    value = (configured_url or DEFAULT_API_URL).strip()
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    marker = "/api/gas"
    if marker in path:
        path = path.split(marker, 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _as_account_id(value: str) -> int | str:
    return int(value) if value.isdecimal() else value


class TowngasApiClient:
    """Fetch account, bill and price data without retaining private payloads."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_url: str,
        account_id: str,
        authorization: str,
        session_updated: Callable[[str, str], None],
    ) -> None:
        self._session = session
        self.api_url = normalize_api_url(api_url)
        self.account_id = str(account_id).strip()
        self.authorization = authorization.strip()
        self._session_updated = session_updated

    def _endpoint(self, name: str) -> str:
        return f"{self.api_url}/api/gas/{name}"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "*/*",
            "Authorization": self.authorization,
            "accountid": self.account_id,
            "Content-Type": "application/json",
            "Referer": "https://servicewechat.com/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36 MicroMessenger/7.0"
            ),
            "xweb_xhr": "1",
        }

    def _rotate_session(
        self, authorization: str | None, account_id: str | None
    ) -> None:
        new_authorization = (authorization or "").strip()
        new_account_id = (account_id or "").strip()
        changed = False
        if new_authorization and new_authorization != self.authorization:
            self.authorization = new_authorization
            changed = True
        if new_account_id and new_account_id != self.account_id:
            self.account_id = new_account_id
            changed = True
        if changed:
            self._session_updated(self.authorization, self.account_id)

    @staticmethod
    def _unwrap_response(
        status: int, response: Any, endpoint: str
    ) -> dict[str, Any]:
        if status in (401, 403):
            raise TowngasAuthenticationError(
                f"{endpoint} authentication failed (HTTP {status})"
            )
        if status >= 400:
            raise TowngasApiError(f"{endpoint} failed (HTTP {status})")
        if not isinstance(response, dict):
            raise TowngasApiError(f"{endpoint} returned a non-object response")

        code = response.get("code", 0)
        if code not in (None, "", 0, "0"):
            message = str(response.get("message", response.get("msg", "未知错误")))
            error = f"{endpoint} failed: {message} (code={code})"
            if any(word in message for word in ("登录", "身份", "令牌", "授权")):
                raise TowngasAuthenticationError(error)
            raise TowngasApiError(error)

        payload = response.get("data")
        if not isinstance(payload, dict):
            raise TowngasApiError(f"{endpoint} response is missing data")
        return payload

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: BaseException | None = None
        for attempt in range(REQUEST_ATTEMPTS):
            try:
                async with self._session.request(
                    method,
                    self._endpoint(endpoint),
                    params=params,
                    json=json_body,
                    headers=self._headers(),
                    timeout=REQUEST_TIMEOUT,
                ) as response:
                    try:
                        body = await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise TowngasApiError(
                            f"{endpoint} returned invalid JSON"
                        ) from err
                    self._rotate_session(
                        response.headers.get("Authorization"),
                        response.headers.get("accountid"),
                    )
                    return self._unwrap_response(response.status, body, endpoint)
            except TowngasApiError:
                raise
            except (TimeoutError, asyncio.TimeoutError, aiohttp.ClientError) as err:
                last_error = err
                if attempt + 1 < REQUEST_ATTEMPTS:
                    await asyncio.sleep(2**attempt)

        raise TowngasConnectionError(
            f"{endpoint} connection failed after {REQUEST_ATTEMPTS} attempts"
        ) from last_error

    async def async_get_detail(self) -> dict[str, Any]:
        """Fetch account balance and the current meter reading."""
        return await self._request(
            "GET", "detail", params={"id": self.account_id}
        )

    async def async_get_bills(self) -> list[dict[str, Any]]:
        """Fetch all available bill pages, newest first."""
        records: list[dict[str, Any]] = []
        page = 1
        while page <= MAX_BILL_PAGES:
            payload = await self._request(
                "POST",
                "bill",
                json_body={
                    "id": _as_account_id(self.account_id),
                    "page": page,
                    "page_size": BILL_PAGE_SIZE,
                },
            )
            page_records = payload.get("data")
            if not isinstance(page_records, list):
                raise TowngasApiError("bill response is missing bill records")
            records.extend(item for item in page_records if isinstance(item, dict))

            try:
                total = int(payload.get("total", len(records)))
            except (TypeError, ValueError):
                total = len(records)
            if not page_records or len(records) >= total:
                break
            page += 1

        return records

    async def async_get_price(self) -> dict[str, Any]:
        """Fetch annual tier pricing and the server's cumulative usage."""
        return await self._request(
            "POST",
            "price",
            json_body={"id": _as_account_id(self.account_id)},
        )

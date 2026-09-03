"""Sensor platform for the Towngas integration."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import aiohttp

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FLARESOLVERR_URL,
    CONF_HOST,
    CONF_MINI_ACCOUNT_ID,
    CONF_MINI_API_TOKEN,
    CONF_MINI_API_URL,
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_MINI_API_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_DIRECT_TIMEOUT = aiohttp.ClientTimeout(total=20)
_FLARESOLVERR_TIMEOUT = aiohttp.ClientTimeout(total=70)
_MINI_API_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MINI_API_ATTEMPTS = 3


def _build_mini_api_urls(configured_url: str) -> tuple[str, str]:
    """Build the account-detail and bill URLs from a base or captured URL."""
    parsed = urlsplit((configured_url or DEFAULT_MINI_API_URL).strip())
    path = parsed.path.rstrip("/")
    if path.endswith("/detail"):
        detail_path = path
        bill_path = f"{path[:-len('/detail')]}/bill"
    elif path.endswith("/bill"):
        bill_path = path
        detail_path = f"{path[:-len('/bill')]}/detail"
    elif path.endswith("/api/gas"):
        detail_path = f"{path}/detail"
        bill_path = f"{path}/bill"
    else:
        detail_path = "/api/gas/detail"
        bill_path = "/api/gas/bill"

    def build(endpoint_path: str) -> str:
        return urlunsplit(
            (parsed.scheme, parsed.netloc, endpoint_path, "", "")
        )

    return build(detail_path), build(bill_path)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "{host}/",
    "X-Requested-With": "XMLHttpRequest",
}

MINI_PROGRAM_SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(
        key="meter_reading",
        name="Towngas Meter Reading",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement="m³",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:meter-gas",
    ),
    SensorEntityDescription(
        key="latest_bill_month",
        name="Towngas Latest Bill Month",
        icon="mdi:calendar-month",
    ),
    SensorEntityDescription(
        key="latest_bill_usage",
        name="Towngas Latest Bill Usage",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement="m³",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:fire",
    ),
    SensorEntityDescription(
        key="latest_bill_charge",
        name="Towngas Latest Bill Charge",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:receipt-text",
    ),
    SensorEntityDescription(
        key="latest_bill_unpaid",
        name="Towngas Latest Bill Unpaid",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:cash-clock",
    ),
)


class TowngasRecoverableError(UpdateFailed):
    """Raised when user action can restore Towngas updates."""


class TowngasAccountNotBound(TowngasRecoverableError):
    """Raised when Towngas no longer has the configured account bound."""


class TowngasMiniApiAuthenticationError(TowngasRecoverableError):
    """Raised when the mini-program credentials need to be refreshed."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Towngas sensors from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [TowngasSensor(coordinator, entry.data)]
    if coordinator.mini_program_enabled:
        entities.extend(
            TowngasMiniProgramSensor(coordinator, entry.data, description)
            for description in MINI_PROGRAM_SENSOR_DESCRIPTIONS
        )
    async_add_entities(entities)


class TowngasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch Towngas balance data with an on-demand browser fallback."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        subs_code: str,
        org_code: str,
        host: str,
        update_interval: int,
        flaresolverr_url: str,
        mini_api_url: str,
        mini_api_token: str,
        mini_account_id: str,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._subs_code = subs_code
        self._org_code = org_code
        self._host = host.rstrip("/")
        self._update_interval_minutes = update_interval
        self._flaresolverr_url = (flaresolverr_url or "").rstrip("/")
        self._api_url = f"{self._host}/openapi/uv1/biz/checkRouters"
        self._mini_api_url = (mini_api_url or "").strip()
        self._mini_detail_url, self._mini_bill_url = _build_mini_api_urls(
            self._mini_api_url
        )
        self._mini_api_token = (mini_api_token or "").strip()
        self._mini_account_id = str(mini_account_id or "").strip()
        self._http = async_get_clientsession(hass)
        self._last_used_flaresolverr = False
        self.last_error: str | None = None
        self.last_updated: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{subs_code}_{org_code}",
            update_interval=timedelta(minutes=update_interval),
        )

    @property
    def mini_program_enabled(self) -> bool:
        """Return whether mini-program credentials are configured."""
        return bool(self._mini_api_token or self._mini_account_id)

    def matches_config_entry(self, entry: ConfigEntry) -> bool:
        """Return whether a config-entry update is already active in memory."""
        config = entry.data
        options = entry.options

        def value(key: str, default: Any = "") -> Any:
            return options.get(key, config.get(key, default))

        return (
            str(config.get(CONF_SUBS_CODE, "")) == self._subs_code
            and str(config.get(CONF_ORG_CODE, "")) == self._org_code
            and str(config.get(CONF_HOST, "")).rstrip("/") == self._host
            and int(value(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
            == self._update_interval_minutes
            and str(
                value(CONF_FLARESOLVERR_URL, DEFAULT_FLARESOLVERR_URL)
            ).rstrip("/")
            == self._flaresolverr_url
            and str(value(CONF_MINI_API_URL)).strip() == self._mini_api_url
            and str(value(CONF_MINI_API_TOKEN)).strip() == self._mini_api_token
            and str(value(CONF_MINI_ACCOUNT_ID)).strip()
            == self._mini_account_id
        )

    def _request_params(self) -> dict[str, str]:
        return {
            "token": "0",
            "scene": "2003",
            "subsCode": self._subs_code,
            "orgCode": self._org_code,
        }

    async def _direct_request(self) -> tuple[int, str, str]:
        """Try the lightweight API request first."""
        headers = BROWSER_HEADERS.copy()
        headers["Referer"] = headers["Referer"].format(host=self._host)

        async with self._http.get(
            self._api_url,
            params=self._request_params(),
            headers=headers,
            ssl=False,
            timeout=_DIRECT_TIMEOUT,
        ) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                await response.text(),
            )

    async def _mini_program_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, str, str, str | None, str | None]:
        """Call the mini-program API with a bounded connection retry."""
        headers = {
            "Accept": "*/*",
            "Authorization": self._mini_api_token,
            "accountid": self._mini_account_id,
            "Content-Type": "application/json",
            "User-Agent": BROWSER_HEADERS["User-Agent"],
            "Referer": "https://servicewechat.com/",
            "xweb_xhr": "1",
        }
        for attempt in range(_MINI_API_ATTEMPTS):
            try:
                async with self._http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=_MINI_API_TIMEOUT,
                ) as response:
                    return (
                        response.status,
                        response.headers.get("Content-Type", ""),
                        await response.text(),
                        response.headers.get("Authorization"),
                        response.headers.get("accountid"),
                    )
            except (TimeoutError, aiohttp.ClientConnectionError):
                if attempt + 1 >= _MINI_API_ATTEMPTS:
                    raise
                await asyncio.sleep(2**attempt)

        raise RuntimeError("Mini-program request retry loop exhausted")

    async def _mini_program_detail_request(
        self,
    ) -> tuple[int, str, str, str | None, str | None]:
        """Fetch the account detail used for the current balance."""
        return await self._mini_program_request(
            "GET",
            self._mini_detail_url,
            params={"id": self._mini_account_id},
        )

    async def _mini_program_bill_request(
        self,
    ) -> tuple[int, str, str, str | None, str | None]:
        """Fetch up to twelve monthly bills for the configured account."""
        account_id: int | str = self._mini_account_id
        if self._mini_account_id.isdecimal():
            account_id = int(self._mini_account_id)
        return await self._mini_program_request(
            "POST",
            self._mini_bill_url,
            json_body={"id": account_id, "page": 1, "page_size": 12},
        )

    def _persist_mini_session(
        self, authorization: str | None, account_id: str | None
    ) -> None:
        """Persist rotated mini-program credentials without logging them."""
        new_token = (authorization or "").strip()
        new_account_id = (account_id or "").strip()
        token_changed = bool(new_token and new_token != self._mini_api_token)
        account_changed = bool(
            new_account_id and new_account_id != self._mini_account_id
        )
        if not token_changed and not account_changed:
            return

        data = dict(self._entry.data)
        options = dict(self._entry.options)

        if token_changed:
            self._mini_api_token = new_token
            target = options if CONF_MINI_API_TOKEN in options else data
            target[CONF_MINI_API_TOKEN] = new_token
        if account_changed:
            self._mini_account_id = new_account_id
            target = options if CONF_MINI_ACCOUNT_ID in options else data
            target[CONF_MINI_ACCOUNT_ID] = new_account_id

        self._hass.config_entries.async_update_entry(
            self._entry, data=data, options=options
        )

    def _build_flaresolverr_payload(self) -> dict[str, Any]:
        """Build a sessionless request so Chromium exits after every update."""
        return {
            "cmd": "request.get",
            "url": f"{self._api_url}?{urlencode(self._request_params())}",
            "maxTimeout": 60000,
            "disableMedia": True,
        }

    async def _flaresolverr_request(self) -> tuple[int, str, str]:
        """Fetch through a temporary FlareSolverr browser instance."""
        if not self._flaresolverr_url:
            raise UpdateFailed("FlareSolverr URL is not configured")

        async with self._http.post(
            self._flaresolverr_url,
            json=self._build_flaresolverr_payload(),
            timeout=_FLARESOLVERR_TIMEOUT,
        ) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)

        if result.get("status") != "ok":
            raise UpdateFailed(
                f"FlareSolverr error: {result.get('message', 'Unknown error')}"
            )

        solution = result.get("solution") or {}
        solution_headers = solution.get("headers") or {}
        content_type = next(
            (
                str(value)
                for key, value in solution_headers.items()
                if str(key).lower() == "content-type"
            ),
            "",
        )
        response_text = solution.get("response") or ""

        if "html" in content_type.lower() and "<pre" in response_text.lower():
            match = re.search(
                r"<pre[^>]*>(.*?)</pre>", response_text, re.IGNORECASE | re.DOTALL
            )
            if match:
                response_text = html.unescape(match.group(1).strip())
                content_type = "application/json"

        return int(solution.get("status", 0)), content_type, response_text

    @staticmethod
    def _looks_like_antibot(status: int, content_type: str) -> bool:
        return status in (202, 403, 429) or "html" in content_type.lower()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch balance, using FlareSolverr only for the current update."""
        self._last_used_flaresolverr = False
        if self.mini_program_enabled:
            return await self._async_update_mini_program()

        direct_error: Exception | None = None

        try:
            status, content_type, text = await self._direct_request()
            if not self._looks_like_antibot(status, content_type):
                try:
                    result = self._parse_response(status, content_type, text)
                    self.last_error = None
                    return result
                except UpdateFailed as err:
                    direct_error = err
                    _LOGGER.debug("Direct response could not be parsed; using fallback")
            else:
                _LOGGER.debug("Anti-bot response detected; using FlareSolverr")
        except (TimeoutError, aiohttp.ClientError) as err:
            direct_error = err
            _LOGGER.debug("Direct request failed; using FlareSolverr: %s", err)

        try:
            status, content_type, text = await self._flaresolverr_request()
            result = self._parse_response(status, content_type, text)
            self._last_used_flaresolverr = True
            self.last_error = None
            return result
        except TowngasAccountNotBound as err:
            self.last_error = str(err)
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError, UpdateFailed) as err:
            message = f"FlareSolverr request failed: {err}"
            if direct_error is not None:
                message += f"; direct request failed: {direct_error}"
            self.last_error = message
            raise UpdateFailed(message) from err

    async def _async_update_mini_program(self) -> dict[str, Any]:
        """Fetch balance through the authenticated mini-program API."""
        if not self._mini_api_token or not self._mini_account_id:
            error = TowngasMiniApiAuthenticationError(
                "Mini-program API configuration is incomplete"
            )
            self.last_error = str(error)
            raise error

        try:
            status, content_type, text, authorization, account_id = (
                await self._mini_program_detail_request()
            )
            result = self._parse_mini_response(status, content_type, text)
            self._persist_mini_session(authorization, account_id)

            status, content_type, text, authorization, account_id = (
                await self._mini_program_bill_request()
            )
            result.update(
                self._parse_mini_bill_response(status, content_type, text)
            )
            self._persist_mini_session(authorization, account_id)
            self.last_error = None
            return result
        except TowngasRecoverableError as err:
            self.last_error = str(err)
            raise
        except (TimeoutError, aiohttp.ClientError, ValueError, UpdateFailed) as err:
            message = f"Mini-program API request failed: {err}"
            self.last_error = message
            raise UpdateFailed(message) from err

    def _decode_response(
        self, status: int, content_type: str, text: str
    ) -> dict[str, Any]:
        """Decode a JSON, JSONP, or JSON-in-HTML response."""
        if status >= 400:
            raise UpdateFailed(f"HTTP error status {status}")

        candidate = html.unescape(text.strip())
        if candidate.startswith("callback(") and candidate.endswith(")"):
            candidate = candidate[9:-1]

        if "json" not in content_type.lower():
            pre_match = re.search(
                r"<pre[^>]*>(.*?)</pre>", candidate, re.IGNORECASE | re.DOTALL
            )
            if pre_match:
                candidate = html.unescape(pre_match.group(1).strip())
            else:
                json_match = re.search(r"(\{.*\}|\[.*\])", candidate, re.DOTALL)
                if not json_match:
                    raise UpdateFailed(
                        f"Response does not contain JSON (content-type={content_type})"
                    )
                candidate = json_match.group(1)

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as err:
            raise UpdateFailed(f"Invalid JSON response: {err}") from err

        if not isinstance(data, dict):
            raise UpdateFailed(
                f"Response is not a JSON object: {type(data).__name__}"
            )
        return data

    def _parse_mini_response(
        self, status: int, content_type: str, text: str
    ) -> dict[str, Any]:
        """Parse the account response returned by the mini-program API."""
        if status in (401, 403):
            raise TowngasMiniApiAuthenticationError(
                f"Mini-program authentication failed (HTTP {status})"
            )

        data = self._decode_response(status, content_type, text)
        code = data.get("code", 0)
        if code not in (None, "", 0, "0"):
            message = str(data.get("message", data.get("msg", "Unknown error")))
            error = f"Mini-program API error: {message} (code={code})"
            if any(word in message for word in ("登录", "身份", "令牌", "授权")):
                raise TowngasMiniApiAuthenticationError(error)
            raise UpdateFailed(error)

        payload = data.get("data")
        if not isinstance(payload, dict):
            raise UpdateFailed("Mini-program response is missing data")

        account = payload.get("data")
        if not isinstance(account, dict):
            account = payload
        tci = payload.get("tci")
        if not isinstance(tci, dict):
            tci = account.get("tci") or payload.get("tci_account")
        if not isinstance(tci, dict) or "presaving" not in tci:
            raise UpdateFailed("Mini-program response is missing tci.presaving")

        response_subs_code = account.get("account") or tci.get("userid")
        if response_subs_code and str(response_subs_code) != self._subs_code:
            raise UpdateFailed(
                "Mini-program account does not match the configured subsCode"
            )

        try:
            balance = float(str(tci["presaving"]).strip())
        except (TypeError, ValueError) as err:
            raise UpdateFailed("Mini-program presaving is not numeric") from err

        result: dict[str, Any] = {
            "savingSum": balance,
            "data_source": "mini_program",
        }
        last_reading = payload.get("last")
        if isinstance(last_reading, dict):
            if last_reading.get("currreading") not in (None, ""):
                try:
                    result["meter_reading"] = float(
                        str(last_reading["currreading"]).strip()
                    )
                except (TypeError, ValueError) as err:
                    raise UpdateFailed(
                        "Mini-program meter reading is not numeric"
                    ) from err
            if last_reading.get("recorddate"):
                result["meter_reading_date"] = last_reading["recorddate"]

        self.last_updated = dt_util.utcnow()
        _LOGGER.debug("Towngas balance updated successfully from mini-program API")
        return result

    def _parse_mini_bill_response(
        self, status: int, content_type: str, text: str
    ) -> dict[str, Any]:
        """Parse the most recent record returned by the monthly bill API."""
        if status in (401, 403):
            raise TowngasMiniApiAuthenticationError(
                f"Mini-program authentication failed (HTTP {status})"
            )

        data = self._decode_response(status, content_type, text)
        code = data.get("code", 0)
        if code not in (None, "", 0, "0"):
            message = str(data.get("message", data.get("msg", "Unknown error")))
            error = f"Mini-program bill API error: {message} (code={code})"
            if any(word in message for word in ("登录", "身份", "令牌", "授权")):
                raise TowngasMiniApiAuthenticationError(error)
            raise UpdateFailed(error)

        payload = data.get("data")
        if not isinstance(payload, dict):
            raise UpdateFailed("Mini-program bill response is missing data")
        records = payload.get("data")
        if not isinstance(records, list):
            raise UpdateFailed("Mini-program bill response is missing bill records")

        bills = [record for record in records if isinstance(record, dict)]
        result: dict[str, Any] = {
            "bill_count": payload.get("total", len(bills)),
        }
        if not bills:
            return result

        latest = max(bills, key=lambda record: str(record.get("yrmonth", "")))
        response_subs_code = latest.get("userid")
        if response_subs_code and str(response_subs_code) != self._subs_code:
            raise UpdateFailed(
                "Mini-program bill account does not match the configured subsCode"
            )

        period = str(latest.get("yrmonth", "")).strip()
        if len(period) == 6 and period.isdecimal():
            result["latest_bill_month"] = f"{period[:4]}-{period[4:]}"
        elif period:
            result["latest_bill_month"] = period

        numeric_fields = {
            "amount": "latest_bill_usage",
            "price": "latest_bill_unit_price",
            "chrgsum": "latest_bill_charge",
            "paidsum": "latest_bill_paid",
            "unpaidfee": "latest_bill_unpaid",
            "lastreading": "latest_bill_previous_reading",
            "currreading": "latest_bill_current_reading",
        }
        for source_key, result_key in numeric_fields.items():
            value = latest.get(source_key)
            if value in (None, ""):
                continue
            try:
                result[result_key] = float(str(value).strip())
            except (TypeError, ValueError) as err:
                raise UpdateFailed(
                    f"Mini-program bill field {source_key} is not numeric"
                ) from err

        if latest.get("issuedate"):
            result["latest_bill_issue_date"] = str(latest["issuedate"])
        return result

    def _parse_response(
        self, status: int, content_type: str, text: str
    ) -> dict[str, Any]:
        """Parse a JSON, JSONP, or JSON-in-HTML response."""
        data = self._decode_response(status, content_type, text)

        result_code = data.get("resultCode", data.get("result_code"))
        if result_code not in (None, "", 0, "0"):
            message = data.get("resultMsg", data.get("result_msg", "Unknown error"))
            error = f"API error: {message} (resultCode={result_code})"
            if str(result_code) == "60151":
                raise TowngasAccountNotBound(error)
            raise UpdateFailed(error)

        code = data.get("code", 0)
        if code not in (None, "", 0, "0"):
            raise UpdateFailed(
                f"API error: {data.get('msg', data.get('message', 'Unknown error'))} "
                f"(code={code})"
            )

        balance_data = data.get("data", data)
        if not isinstance(balance_data, dict) or "savingSum" not in balance_data:
            raise UpdateFailed("Response is missing savingSum")

        self.last_updated = dt_util.utcnow()
        _LOGGER.debug("Towngas balance updated successfully")
        return {**balance_data, "data_source": "legacy_web"}


class TowngasSensor(CoordinatorEntity[TowngasCoordinator], SensorEntity):
    """Towngas balance sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "CNY"
    _attr_icon = "mdi:currency-cny"

    def __init__(self, coordinator: TowngasCoordinator, config: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._subs_code = config[CONF_SUBS_CODE]
        self._org_code = config[CONF_ORG_CODE]
        self._host = config[CONF_HOST]

        self._attr_name = f"Towngas Balance {self._subs_code}"
        self._attr_unique_id = (
            f"towngas_balance_{self._subs_code}_{self._org_code}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._attr_unique_id)},
            "name": self._attr_name,
            "manufacturer": "Towngas",
            "configuration_url": self._host,
        }

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        return None if data is None else data.get("savingSum")

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes: dict[str, Any] = {
            "subs_code": self._subs_code,
            "org_code": self._org_code,
            "host": self._host,
            "using_flaresolverr": self.coordinator._last_used_flaresolverr,
        }
        if self.coordinator.last_error:
            attributes["last_error"] = self.coordinator.last_error
        if self.coordinator.last_updated:
            attributes["last_update"] = self.coordinator.last_updated.isoformat()
        data = self.coordinator.data or {}
        for key in ("data_source", "meter_reading", "meter_reading_date"):
            if key in data:
                attributes[key] = data[key]
        return attributes


class TowngasMiniProgramSensor(
    CoordinatorEntity[TowngasCoordinator], SensorEntity
):
    """Expose a non-sensitive reading from the mini-program APIs."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: TowngasCoordinator,
        config: dict[str, Any],
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._subs_code = config[CONF_SUBS_CODE]
        self._org_code = config[CONF_ORG_CODE]
        self._attr_name = description.name
        self._attr_unique_id = (
            f"towngas_{description.key}_{self._subs_code}_{self._org_code}"
        )
        self._attr_device_info = {
            "identifiers": {
                (
                    DOMAIN,
                    f"towngas_balance_{self._subs_code}_{self._org_code}",
                )
            },
            "name": f"Towngas {self._subs_code}",
            "manufacturer": "Towngas",
            "configuration_url": config[CONF_HOST],
        }

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data or {}
        return data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "latest_bill_charge":
            return None
        data = self.coordinator.data or {}
        attribute_keys = (
            "latest_bill_unit_price",
            "latest_bill_paid",
            "latest_bill_previous_reading",
            "latest_bill_current_reading",
            "latest_bill_issue_date",
            "bill_count",
        )
        return {key: data[key] for key in attribute_keys if key in data}

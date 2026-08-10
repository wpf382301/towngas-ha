"""Sensor platform for the Towngas integration."""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import aiohttp

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
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
    CONF_ORG_CODE,
    CONF_SUBS_CODE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_DIRECT_TIMEOUT = aiohttp.ClientTimeout(total=20)
_FLARESOLVERR_TIMEOUT = aiohttp.ClientTimeout(total=70)

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a Towngas sensor from a config entry."""
    config = entry.data
    options = entry.options

    coordinator = TowngasCoordinator(
        hass=hass,
        entry=entry,
        subs_code=config[CONF_SUBS_CODE],
        org_code=config[CONF_ORG_CODE],
        host=config[CONF_HOST],
        update_interval=options.get(
            CONF_UPDATE_INTERVAL,
            config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        ),
        flaresolverr_url=options.get(
            CONF_FLARESOLVERR_URL,
            config.get(CONF_FLARESOLVERR_URL, DEFAULT_FLARESOLVERR_URL),
        ),
    )

    await coordinator.async_config_entry_first_refresh()
    async_add_entities([TowngasSensor(coordinator, config)])


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
    ) -> None:
        self._subs_code = subs_code
        self._org_code = org_code
        self._host = host.rstrip("/")
        self._flaresolverr_url = (flaresolverr_url or "").rstrip("/")
        self._api_url = f"{self._host}/openapi/uv1/biz/checkRouters"
        self._http = async_get_clientsession(hass)
        self._last_used_flaresolverr = False
        self.last_updated: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{subs_code}_{org_code}",
            update_interval=timedelta(minutes=update_interval),
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
        direct_error: Exception | None = None

        try:
            status, content_type, text = await self._direct_request()
            if not self._looks_like_antibot(status, content_type):
                try:
                    return self._parse_response(status, content_type, text)
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
            return result
        except (TimeoutError, aiohttp.ClientError, ValueError, UpdateFailed) as err:
            message = f"FlareSolverr request failed: {err}"
            if direct_error is not None:
                message += f"; direct request failed: {direct_error}"
            raise UpdateFailed(message) from err

    def _parse_response(
        self, status: int, content_type: str, text: str
    ) -> dict[str, Any]:
        """Parse a JSON, JSONP, or JSON-in-HTML response."""
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
            raise UpdateFailed(f"Response is not a JSON object: {type(data).__name__}")

        if data.get("code", 0) != 0:
            raise UpdateFailed(
                f"API error: {data.get('msg', data.get('message', 'Unknown error'))} "
                f"(code={data['code']})"
            )

        balance_data = data.get("data", data)
        if not isinstance(balance_data, dict) or "savingSum" not in balance_data:
            raise UpdateFailed("Response is missing savingSum")

        self.last_updated = dt_util.utcnow()
        _LOGGER.debug("Towngas balance updated successfully")
        return balance_data


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
        if self.coordinator.data is None:
            return None

        attributes: dict[str, Any] = {
            "subs_code": self._subs_code,
            "org_code": self._org_code,
            "host": self._host,
            "using_flaresolverr": self.coordinator._last_used_flaresolverr,
        }
        if self.coordinator.last_updated:
            attributes["last_update"] = self.coordinator.last_updated.isoformat()
        return attributes

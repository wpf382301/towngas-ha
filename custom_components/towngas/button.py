"""Button platform for the Towngas integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HOST, CONF_ORG_CODE, CONF_SUBS_CODE, DOMAIN
from .sensor import TowngasCoordinator

_LOGGER = logging.getLogger(__name__)


def refresh_error_message(error: str | None) -> str:
    """Return an actionable message for a failed manual refresh."""
    if error and ("resultCode=60151" in error or "未绑定此户号" in error):
        return (
            "港华返回“未绑定此户号”（60151）。请先在“泰安泰山港华燃气"
            "有限公司”微信公众号中重新绑定燃气账户，然后再更新余额"
        )
    if error:
        return f"港华燃气余额更新失败：{error}"
    return "港华燃气余额更新失败，请查看 Home Assistant 日志"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Towngas manual-refresh button."""
    async_add_entities([TowngasRefreshButton(entry.runtime_data, entry.data)])


class TowngasRefreshButton(CoordinatorEntity[TowngasCoordinator], ButtonEntity):
    """Request an immediate Towngas balance refresh."""

    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: TowngasCoordinator, config: dict[str, Any]) -> None:
        super().__init__(coordinator)
        subs_code = config[CONF_SUBS_CODE]
        org_code = config[CONF_ORG_CODE]
        host = config[CONF_HOST]
        balance_unique_id = f"towngas_balance_{subs_code}_{org_code}"

        self._attr_name = "立即更新余额"
        self._attr_unique_id = f"towngas_refresh_{subs_code}_{org_code}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, balance_unique_id)},
            "name": f"Towngas Balance {subs_code}",
            "manufacturer": "Towngas",
            "configuration_url": host,
        }

    @property
    def available(self) -> bool:
        """Keep the retry button available after a failed refresh."""
        return True

    async def async_press(self) -> None:
        """Refresh the shared coordinator immediately."""
        await self.coordinator.async_request_refresh()
        if not self.coordinator.last_update_success:
            error = self.coordinator.last_error
            _LOGGER.warning("Manual Towngas balance refresh failed: %s", error)
            raise HomeAssistantError(refresh_error_message(error))

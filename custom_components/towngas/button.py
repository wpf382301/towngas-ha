"""Button platform for Towngas."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT_ID, DOMAIN
from .coordinator import TowngasCoordinator, config_value

_LOGGER = logging.getLogger(__name__)


def refresh_error_message(error: str | None) -> str:
    """Return an actionable error without exposing credentials."""
    if error and ("authentication" in error.lower() or "登录" in error):
        return "港华小程序 Authorization 已失效，请在集成选项中更新后重试"
    if error:
        return f"港华燃气数据同步失败：{error}"
    return "港华燃气数据同步失败，请查看 Home Assistant 日志"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the manual synchronization button."""
    async_add_entities([TowngasRefreshButton(entry.runtime_data, entry)])


class TowngasRefreshButton(CoordinatorEntity[TowngasCoordinator], ButtonEntity):
    """Synchronize details, bills and price tiers immediately."""

    _attr_name = "立即同步燃气数据"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: TowngasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        account_id = str(config_value(entry, CONF_ACCOUNT_ID))
        device_identifier = f"{DOMAIN}_{entry.entry_id}"
        self._attr_unique_id = f"{device_identifier}_refresh"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_identifier)},
            "name": f"港华燃气 {account_id}",
            "manufacturer": "港华燃气",
        }

    @property
    def available(self) -> bool:
        """Keep credential recovery available after a failed refresh."""
        return True

    async def async_press(self) -> None:
        """Request an immediate full synchronization."""
        await self.coordinator.async_request_refresh()
        if not self.coordinator.last_update_success:
            error = self.coordinator.last_error
            _LOGGER.warning("Manual Towngas synchronization failed: %s", error)
            raise HomeAssistantError(refresh_error_message(error))

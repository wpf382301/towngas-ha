"""Sensor platform for Towngas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ACCOUNT_ID, DOMAIN, HISTORY_ATTRIBUTE_LIMIT
from .coordinator import TowngasCoordinator, config_value


@dataclass(frozen=True, kw_only=True)
class TowngasSensorDescription(SensorEntityDescription):
    """Describe a Towngas sensor."""

    data_key: str


SENSORS = (
    TowngasSensorDescription(
        key="balance",
        data_key="balance",
        name="燃气余额",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:currency-cny",
    ),
    TowngasSensorDescription(
        key="meter_reading",
        data_key="meter_reading",
        name="燃气表当前读数",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement="m³",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:meter-gas",
    ),
    TowngasSensorDescription(
        key="current_month_usage",
        data_key="current_month_usage",
        name="本月用气量",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement="m³",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:fire",
    ),
    TowngasSensorDescription(
        key="current_month_estimated_cost",
        data_key="current_month_estimated_cost",
        name="本月预估燃气费",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="CNY",
        state_class=SensorStateClass.TOTAL,
        icon="mdi:calculator-variant",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all Towngas sensors."""
    async_add_entities(
        TowngasSensor(entry.runtime_data, entry, description)
        for description in SENSORS
    )


class TowngasSensor(CoordinatorEntity[TowngasCoordinator], SensorEntity):
    """Expose one value from the shared Towngas snapshot."""

    entity_description: TowngasSensorDescription

    def __init__(
        self,
        coordinator: TowngasCoordinator,
        entry: ConfigEntry,
        description: TowngasSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        account_id = str(config_value(entry, CONF_ACCOUNT_ID))
        device_identifier = f"{DOMAIN}_{entry.entry_id}"
        self._attr_unique_id = f"{device_identifier}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_identifier)},
            "name": f"港华燃气 {account_id}",
            "manufacturer": "港华燃气",
        }

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        data = self.coordinator.data or {}
        return data.get(self.entity_description.data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attach compact history and pricing metadata to the balance entity."""
        if self.entity_description.key != "balance":
            return None
        data = self.coordinator.data or {}
        keys = (
            "meter_reading",
            "meter_reading_date",
            "current_month",
            "current_month_usage",
            "current_month_estimated_cost",
            "annual_usage",
            "current_tier",
            "current_unit_price",
            "price_tiers",
            "latest_bill",
            "yearly_history",
            "monthlist",
            "yearlist",
            "计费标准",
            "data_updated_at",
            "meter_reset_detected",
        )
        attributes = {key: data[key] for key in keys if key in data}
        history = data.get("monthly_history", [])
        attributes["monthly_history"] = history[:HISTORY_ATTRIBUTE_LIMIT]
        if self.coordinator.last_error:
            attributes["last_error"] = self.coordinator.last_error
        return attributes

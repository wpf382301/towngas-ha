"""Tests for Towngas config-entry and entity-registry migration."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from custom_components.towngas import async_migrate_entry


class TowngasMigrationTests(unittest.IsolatedAsyncioTestCase):
    """Verify the legacy production identifiers migrate without entity churn."""

    @patch("custom_components.towngas.er.async_entries_for_config_entry")
    @patch("custom_components.towngas.er.async_get")
    async def test_migrates_settings_and_entity_unique_ids(
        self, async_get: MagicMock, async_entries: MagicMock
    ) -> None:
        registry = MagicMock()
        async_get.return_value = registry
        suffix = "1800342286_1_TA01"
        retained = {
            "sensor.towngas_balance_1800342286": f"towngas_balance_{suffix}",
            "sensor.towngas_1800342286_towngas_meter_reading": (
                f"towngas_meter_reading_{suffix}"
            ),
            "button.towngas_balance_1800342286_li_ji_geng_xin_yu_e": (
                f"towngas_refresh_{suffix}"
            ),
        }
        obsolete = {
            f"sensor.latest_{name}": f"towngas_latest_bill_{name}_{suffix}"
            for name in ("month", "usage", "charge", "unpaid")
        }
        async_entries.return_value = [
            SimpleNamespace(entity_id=entity_id, unique_id=unique_id)
            for entity_id, unique_id in {**retained, **obsolete}.items()
        ]
        entry = SimpleNamespace(
            entry_id="01KWKP61C1YX4TA35R816RGZPX",
            version=1,
            data={
                "host": "https://wx-api.towngas.com.cn",
                "orgCode": "TA01",
                "subsCode": "1800342286_1",
                "updatetime": 60,
            },
            options={
                "mini_api_url": (
                    "https://rqjf.jnyuxia.com/api/gas/detail?id=25076"
                ),
                "mini_account_id": "25076",
                "mini_api_token": "captured-token",
                "updatetime": 30,
            },
        )
        hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_update_entry=MagicMock())
        )

        result = await async_migrate_entry(hass, entry)

        self.assertTrue(result)
        updates = {
            call.args[0]: call.kwargs["new_unique_id"]
            for call in registry.async_update_entity.call_args_list
        }
        self.assertEqual(
            updates,
            {
                entity_id: (
                    f"towngas_{entry.entry_id}_"
                    f"{'meter_reading' if 'meter_reading' in unique_id else 'refresh' if 'refresh' in unique_id else 'balance'}"
                )
                for entity_id, unique_id in retained.items()
            },
        )
        self.assertEqual(
            {call.args[0] for call in registry.async_remove.call_args_list},
            set(obsolete),
        )
        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        self.assertEqual(kwargs["data"]["api_url"], "https://rqjf.jnyuxia.com")
        self.assertEqual(kwargs["data"]["account_id"], "25076")
        self.assertEqual(kwargs["data"]["authorization"], "captured-token")
        self.assertEqual(kwargs["data"]["update_interval"], 30)
        self.assertEqual(kwargs["options"], {})
        self.assertEqual(kwargs["version"], 2)


if __name__ == "__main__":
    unittest.main()

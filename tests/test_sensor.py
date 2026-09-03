"""Tests for Towngas sensor metadata."""
from __future__ import annotations

import unittest

from homeassistant.components.sensor import SensorStateClass

from custom_components.towngas.sensor import SENSORS


class TowngasSensorTests(unittest.TestCase):
    """Keep entity metadata accepted by Home Assistant."""

    def test_monetary_balance_uses_total_state_class(self) -> None:
        balance = next(sensor for sensor in SENSORS if sensor.key == "balance")

        self.assertEqual(balance.state_class, SensorStateClass.TOTAL)


if __name__ == "__main__":
    unittest.main()

"""Tests for Towngas payload sanitizing and tariff calculation."""
from __future__ import annotations

from decimal import Decimal
import unittest

from custom_components.towngas.models import (
    TowngasDataError,
    build_snapshot,
    calculate_tiered_cost,
    parse_bills,
    parse_detail,
    parse_price,
)


DETAIL_PAYLOAD = {
    "data": {"id": 25076, "account": "1800342286", "name": "private"},
    "last": {"currreading": "110", "recorddate": "2026-09-03"},
    "tci": {
        "userid": "1800342286",
        "presaving": "173.3",
        "mobile": "private",
        "certnum": "private",
        "useraddrdetail": "private",
    },
}
BILL_RECORDS = [
    {
        "userid": "1800342286",
        "yrmonth": "202607",
        "lastreading": "63",
        "currreading": "79",
        "amount": "16",
        "price": "2.97",
        "chrgsum": "47.52",
        "paidsum": "47.52",
        "unpaidfee": "0",
        "issuedate": "2026-07-25",
    },
    {
        "userid": "1800342286",
        "yrmonth": "202608",
        "lastreading": "79",
        "currreading": "104",
        "amount": "25",
        "price": "2.97",
        "chrgsum": "74.25",
        "paidsum": "74.25",
        "unpaidfee": "0",
        "issuedate": "2026-08-25",
    },
]
PRICE_PAYLOAD = {
    "price": [
        {"modleseq": "1", "minmount": "0", "maxmount": "240", "price": "2.97"},
        {"modleseq": "2", "minmount": "240", "maxmount": "360", "price": "3.52"},
        {"modleseq": "3", "minmount": "360", "maxmount": "-1", "price": "4.35"},
    ],
    "use": "110",
}


class TowngasModelTests(unittest.TestCase):
    """Verify the complete current API data model."""

    def test_detail_is_sanitized(self) -> None:
        detail = parse_detail(DETAIL_PAYLOAD, "25076")

        self.assertEqual(detail["balance"], 173.3)
        self.assertEqual(detail["meter_reading"], 110.0)
        self.assertEqual(
            set(detail),
            {"balance", "meter_reading", "meter_reading_date", "customer_number"},
        )

    def test_detail_rejects_wrong_account(self) -> None:
        with self.assertRaisesRegex(TowngasDataError, "does not match"):
            parse_detail(DETAIL_PAYLOAD, "99999")

    def test_bills_are_normalized_and_sorted(self) -> None:
        bills = parse_bills(BILL_RECORDS, "1800342286")

        self.assertEqual(bills[0]["month"], "2026-08")
        self.assertEqual(bills[0]["usage"], 25.0)
        self.assertEqual(bills[0]["charge"], 74.25)
        self.assertEqual(bills[0]["end_reading"], 104.0)
        self.assertNotIn("userid", bills[0])

    def test_price_and_current_month_estimate(self) -> None:
        detail = parse_detail(DETAIL_PAYLOAD, "25076")
        bills = parse_bills(BILL_RECORDS, detail["customer_number"])
        tiers, annual_usage = parse_price(PRICE_PAYLOAD)

        snapshot = build_snapshot(
            detail, bills, tiers, annual_usage, "2026-09"
        )

        self.assertEqual(snapshot["current_month_usage"], 6.0)
        self.assertEqual(snapshot["current_month_estimated_cost"], 17.82)
        self.assertEqual(snapshot["current_tier"], 1)
        self.assertTrue(snapshot["monthlist"][0]["estimated"])
        self.assertEqual(snapshot["monthlist"][0]["month"], "2026-09")
        self.assertEqual(snapshot["yearlist"][0]["yearEleNum"], 47.0)

    def test_cost_crosses_tier_boundary(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)

        previous = calculate_tiered_cost(230, tiers)
        current = calculate_tiered_cost(250, tiers)

        self.assertEqual(current - previous, Decimal("64.90"))

    def test_invalid_tier_gap_is_rejected(self) -> None:
        broken = {**PRICE_PAYLOAD, "price": [dict(item) for item in PRICE_PAYLOAD["price"]]}
        broken["price"][1]["minmount"] = "241"
        with self.assertRaisesRegex(TowngasDataError, "gap or overlap"):
            parse_price(broken)


if __name__ == "__main__":
    unittest.main()

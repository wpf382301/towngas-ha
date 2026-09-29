"""Tests for Towngas payload sanitizing and tariff calculation."""
from __future__ import annotations

import unittest

from custom_components.towngas.models import (
    TowngasDataError,
    build_snapshot,
    estimate_current_month_charge,
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

    def test_price_and_current_month_usage(self) -> None:
        detail = parse_detail(DETAIL_PAYLOAD, "25076")
        bills = parse_bills(BILL_RECORDS, detail["customer_number"])
        tiers, annual_usage = parse_price(PRICE_PAYLOAD)

        snapshot = build_snapshot(
            detail, bills, tiers, annual_usage, "2026-09"
        )

        self.assertEqual(snapshot["current_month_usage"], 6.0)
        self.assertEqual(snapshot["current_month_estimated_cost"], 17.82)
        self.assertEqual(snapshot["current_tier"], 1)
        self.assertEqual(snapshot["monthlist"][0]["month"], "2026-08")
        self.assertEqual(snapshot["yearlist"][0]["yearEleNum"], 41.0)
        self.assertNotIn("estimated", snapshot["monthlist"][0])

    def test_current_month_bill_usage_includes_billed_and_unbilled_gas(self) -> None:
        detail = parse_detail(
            {
                **DETAIL_PAYLOAD,
                "last": {"currreading": "117", "recorddate": "2026-09-28"},
            },
            "25076",
        )
        bills = parse_bills(
            [
                {
                    "userid": "1800342286",
                    "yrmonth": "202609",
                    "lastreading": "104",
                    "currreading": "117",
                    "amount": "12",
                    "price": "2.97",
                    "chrgsum": "35.64",
                    "paidsum": "38.61",
                    "unpaidfee": "0",
                }
            ],
            detail["customer_number"],
        )
        tiers, annual_usage = parse_price({**PRICE_PAYLOAD, "use": "12"})

        snapshot = build_snapshot(detail, bills, tiers, annual_usage, "2026-09")

        self.assertEqual(snapshot["current_month_usage"], 12.0)
        self.assertEqual(snapshot["current_month_estimated_cost"], 35.64)

    def test_estimate_crosses_tier_boundary(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)

        self.assertEqual(
            estimate_current_month_charge(245, 10, tiers),
            32.45,
        )

    def test_annual_usage_uses_bills_and_unbilled_meter_difference(self) -> None:
        tiers, reported_usage = parse_price({**PRICE_PAYLOAD, "use": "2"})
        usages = [0, 1, 0, 23, 21, 18, 16, 25, 12]
        bills = [
            {
                "month": f"2026-{month:02d}",
                "usage": usage,
                "charge": round(usage * 2.97, 2),
                "end_reading": 117,
            }
            for month, usage in enumerate(usages, start=1)
        ]
        bills.append(
            {"month": "2025-12", "usage": 80, "charge": 237.6, "end_reading": 0}
        )

        for meter, annual, monthly, estimate in (
            (117, 116, 12, 35.64),
            (118, 117, 13, 38.61),
        ):
            with self.subTest(meter=meter):
                snapshot = build_snapshot(
                    {"meter_reading": meter}, bills, tiers, reported_usage, "2026-09"
                )
                self.assertEqual(snapshot["annual_usage"], annual)
                self.assertEqual(snapshot["计费标准"]["年阶梯累计用气量"], annual)
                self.assertEqual(snapshot["current_month_usage"], monthly)
                self.assertEqual(snapshot["current_month_estimated_cost"], estimate)
                self.assertEqual(snapshot["yearly_history"][0]["usage"], 116)
                self.assertEqual(snapshot["yearly_history"][0]["charge"], 344.52)
                self.assertEqual(snapshot["monthlist"][0]["monthEleCost"], 35.64)

    def test_new_year_does_not_include_previous_year_billed_usage(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)
        snapshot = build_snapshot(
            {"meter_reading": 503},
            [{"month": "2026-12", "usage": 50, "charge": 148.5, "end_reading": 500}],
            tiers,
            500,
            "2027-01",
        )
        self.assertEqual(snapshot["annual_usage"], 3)
        self.assertEqual(snapshot["current_month_usage"], 3)
        self.assertEqual(snapshot["current_month_estimated_cost"], 8.91)

    def test_corrected_annual_usage_drives_tier_and_month_estimate(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)
        snapshot = build_snapshot(
            {"meter_reading": 249},
            [{"month": "2026-08", "usage": 239, "charge": 709.83, "end_reading": 239}],
            tiers,
            2,
            "2026-09",
        )
        self.assertEqual(snapshot["annual_usage"], 249)
        self.assertEqual(snapshot["current_tier"], 2)
        self.assertEqual(snapshot["current_month_estimated_cost"], 34.65)

    def test_meter_reset_does_not_subtract_already_billed_usage(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)
        snapshot = build_snapshot(
            {"meter_reading": 3},
            [{"month": "2026-09", "usage": 12, "charge": 35.64, "end_reading": 117}],
            tiers,
            2,
            "2026-09",
        )
        self.assertTrue(snapshot["meter_reset_detected"])
        self.assertEqual(snapshot["annual_usage"], 12)
        self.assertEqual(snapshot["current_month_usage"], 12)

    def test_estimate_rejects_missing_or_negative_usage(self) -> None:
        tiers, _ = parse_price(PRICE_PAYLOAD)

        self.assertIsNone(estimate_current_month_charge(None, 1, tiers))
        self.assertEqual(estimate_current_month_charge(10, 0, tiers), 0.0)
        self.assertIsNone(estimate_current_month_charge(10, -1, tiers))

    def test_invalid_tier_gap_is_rejected(self) -> None:
        broken = {**PRICE_PAYLOAD, "price": [dict(item) for item in PRICE_PAYLOAD["price"]]}
        broken["price"][1]["minmount"] = "241"
        with self.assertRaisesRegex(TowngasDataError, "gap or overlap"):
            parse_price(broken)


if __name__ == "__main__":
    unittest.main()

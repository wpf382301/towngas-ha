"""Sanitize Towngas payloads and build entity-ready history."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

MONEY_QUANTUM = Decimal("0.01")
USAGE_QUANTUM = Decimal("0.001")
PERIOD_PATTERN = re.compile(r"^(\d{4})(\d{2})$")


class TowngasDataError(ValueError):
    """Raised when a required field is absent or malformed."""


def _decimal(value: Any, field: str) -> Decimal:
    if value in (None, ""):
        raise TowngasDataError(f"{field} is missing")
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as err:
        raise TowngasDataError(f"{field} is not numeric") from err


def _number(value: Decimal, quantum: Decimal = USAGE_QUANTUM) -> float:
    return float(value.quantize(quantum).normalize())


def _money(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def parse_detail(payload: dict[str, Any], account_id: str) -> dict[str, Any]:
    """Extract only non-sensitive values from the account detail payload."""
    account = payload.get("data")
    if not isinstance(account, dict):
        account = {}
    returned_id = str(account.get("id", "")).strip()
    if returned_id and returned_id != str(account_id):
        raise TowngasDataError("detail account does not match configured account_id")

    tci = payload.get("tci")
    if not isinstance(tci, dict):
        raise TowngasDataError("detail response is missing tci")
    last = payload.get("last")
    if not isinstance(last, dict):
        raise TowngasDataError("detail response is missing last reading")

    customer_number = str(
        account.get("account") or tci.get("userid") or last.get("userid") or ""
    ).strip()
    return {
        "balance": _money(_decimal(tci.get("presaving"), "tci.presaving")),
        "meter_reading": _number(
            _decimal(last.get("currreading"), "last.currreading")
        ),
        "meter_reading_date": str(last.get("recorddate", "")).strip(),
        "customer_number": customer_number,
    }


def parse_bills(
    records: list[dict[str, Any]], customer_number: str
) -> list[dict[str, Any]]:
    """Normalize and whitelist bill records returned by the service."""
    bills: list[dict[str, Any]] = []
    for record in records:
        returned_customer = str(record.get("userid", "")).strip()
        if customer_number and returned_customer and returned_customer != customer_number:
            raise TowngasDataError("bill account does not match detail account")

        raw_period = str(record.get("yrmonth", "")).strip()
        match = PERIOD_PATTERN.fullmatch(raw_period)
        if match is None or not 1 <= int(match.group(2)) <= 12:
            raise TowngasDataError("bill yrmonth is invalid")
        period = f"{match.group(1)}-{match.group(2)}"

        bill = {
            "month": period,
            "usage": _number(_decimal(record.get("amount"), "bill.amount")),
            "charge": _money(_decimal(record.get("chrgsum"), "bill.chrgsum")),
            "start_reading": _number(
                _decimal(record.get("lastreading"), "bill.lastreading")
            ),
            "end_reading": _number(
                _decimal(record.get("currreading"), "bill.currreading")
            ),
        }
        optional_numbers = {
            "price": ("unit_price", USAGE_QUANTUM),
            "paidsum": ("paid", MONEY_QUANTUM),
            "unpaidfee": ("unpaid", MONEY_QUANTUM),
            "paidlatefee": ("paid_late_fee", MONEY_QUANTUM),
            "unpaidlatefee": ("unpaid_late_fee", MONEY_QUANTUM),
        }
        for source, (target, quantum) in optional_numbers.items():
            if record.get(source) not in (None, ""):
                value = _decimal(record[source], f"bill.{source}")
                bill[target] = _money(value) if quantum == MONEY_QUANTUM else _number(value)
        if record.get("issuedate"):
            bill["issue_date"] = str(record["issuedate"])
        bills.append(bill)

    return sorted(bills, key=lambda item: item["month"], reverse=True)


def parse_price(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """Normalize annual tier boundaries, prices and cumulative usage."""
    raw_tiers = payload.get("price")
    if not isinstance(raw_tiers, list) or not raw_tiers:
        raise TowngasDataError("price response is missing tiers")

    tiers: list[dict[str, Any]] = []
    for raw in raw_tiers:
        if not isinstance(raw, dict):
            raise TowngasDataError("price tier is invalid")
        minimum = _decimal(raw.get("minmount"), "price.minmount")
        raw_maximum = _decimal(raw.get("maxmount"), "price.maxmount")
        maximum = None if raw_maximum < 0 else _number(raw_maximum)
        tiers.append(
            {
                "tier": int(_decimal(raw.get("modleseq"), "price.modleseq")),
                "min_usage": _number(minimum),
                "max_usage": maximum,
                "unit_price": _number(_decimal(raw.get("price"), "price.price")),
                "effective_from": str(raw.get("effdate", "")).strip(),
                "effective_until": str(raw.get("expdate", "")).strip(),
            }
        )

    tiers.sort(key=lambda item: item["min_usage"])
    if tiers[0]["min_usage"] != 0:
        raise TowngasDataError("price tiers must start at zero")
    for previous, current in zip(tiers, tiers[1:], strict=False):
        if previous["max_usage"] != current["min_usage"]:
            raise TowngasDataError("price tiers have a gap or overlap")
    return tiers, _number(_decimal(payload.get("use"), "price.use"))


def current_tier(usage: float, tiers: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the tier reached by the cumulative annual usage."""
    value = Decimal(str(usage))
    for tier in tiers:
        maximum = tier.get("max_usage")
        if maximum is None or value <= Decimal(str(maximum)):
            return tier
    return tiers[-1]


def estimate_current_month_charge(
    annual_usage: float | None,
    month_usage: float | None,
    tiers: list[dict[str, Any]],
) -> float | None:
    """Estimate the current month's charge across annual tier boundaries.

    ``annual_usage`` includes the current month.  The current month's starting
    cumulative usage is therefore ``annual_usage - month_usage``.  Each
    overlapping portion is charged at the corresponding annual tier price.
    """
    if annual_usage is None or month_usage is None or not tiers:
        return None

    end = Decimal(str(annual_usage))
    usage = Decimal(str(month_usage))
    if end < 0 or usage <= 0:
        return None if usage < 0 else 0.0

    start = end - usage
    if start < 0:
        start = Decimal("0")

    charge = Decimal("0")
    for tier in sorted(tiers, key=lambda item: item["min_usage"]):
        minimum = Decimal(str(tier["min_usage"]))
        raw_maximum = tier.get("max_usage")
        maximum = None if raw_maximum is None else Decimal(str(raw_maximum))
        upper = end if maximum is None else min(end, maximum)
        lower = max(start, minimum)
        if upper > lower:
            amount = upper - lower
            charge += amount * Decimal(str(tier["unit_price"]))

    return _money(charge)


def _yearly_history(months: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Decimal | int]] = defaultdict(
        lambda: {"usage": Decimal("0"), "charge": Decimal("0"), "months": 0}
    )
    for month in months:
        year = month["month"][:4]
        totals[year]["usage"] += Decimal(str(month["usage"]))
        totals[year]["charge"] += Decimal(str(month["charge"]))
        totals[year]["months"] += 1
    return [
        {
            "year": year,
            "usage": _number(values["usage"]),
            "charge": _money(values["charge"]),
            "months": values["months"],
        }
        for year, values in sorted(totals.items(), reverse=True)
    ]


def build_snapshot(
    detail: dict[str, Any],
    bills: list[dict[str, Any]],
    tiers: list[dict[str, Any]],
    annual_usage: float,
    current_month: str,
) -> dict[str, Any]:
    """Build entity-ready values from current and persisted sanitized data."""
    sorted_bills = sorted(bills, key=lambda item: item["month"], reverse=True)
    latest = sorted_bills[0] if sorted_bills else None
    month_usage: float | None = None
    meter_reset_detected = False
    if latest is not None:
        raw_usage = Decimal(str(detail["meter_reading"])) - Decimal(
            str(latest["end_reading"])
        )
        if raw_usage < 0:
            meter_reset_detected = True
            raw_usage = Decimal("0")
        month_usage = _number(raw_usage)

    active_tier = current_tier(annual_usage, tiers)
    estimated_cost = estimate_current_month_charge(
        annual_usage,
        month_usage,
        tiers,
    )
    monthly_history = [dict(item) for item in sorted_bills]
    compatibility_months = [
        {
            "month": item["month"],
            "monthEleNum": item["usage"],
            "monthEleCost": item["charge"],
            "f_gas_total": item["usage"],
            "e_gas_total": item["charge"],
        }
        for item in sorted_bills
    ]

    compatibility_year_source = [
        {
            "month": item["month"],
            "usage": item["monthEleNum"],
            "charge": item["monthEleCost"],
        }
        for item in compatibility_months
    ]
    compatibility_years = [
        {
            "year": item["year"],
            "yearEleNum": item["usage"],
            "yearEleCost": item["charge"],
        }
        for item in _yearly_history(compatibility_year_source)
    ]
    billing_standard: dict[str, Any] = {
        "计费标准": "年阶梯",
        "当前年阶梯档": f"第{active_tier['tier']}档",
        "年阶梯累计用气量": annual_usage,
    }
    for tier in tiers:
        index = tier["tier"]
        billing_standard[f"年阶梯第{index}档气价"] = tier["unit_price"]
        if index > 1:
            billing_standard[f"年阶梯第{index}档起始气量"] = tier["min_usage"]

    return {
        **detail,
        "current_month": current_month,
        "current_month_usage": month_usage,
        "current_month_estimated_cost": estimated_cost,
        "meter_reset_detected": meter_reset_detected,
        "annual_usage": annual_usage,
        "current_tier": active_tier["tier"],
        "current_unit_price": active_tier["unit_price"],
        "price_tiers": tiers,
        "latest_bill": latest,
        "monthly_history": monthly_history,
        "yearly_history": _yearly_history(monthly_history),
        "monthlist": compatibility_months,
        "yearlist": compatibility_years,
        "计费标准": billing_standard,
    }

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ExchangeRate:
    """Conversion rate from a foreign currency to the base currency, including fees."""
    currency: str
    rate_to_base: Decimal              # 1 unit of currency = rate_to_base units of base currency
    fee_rate: Decimal = Decimal("0.00")  # e.g., Decimal("0.025") for 2.5% FX markup
    flat_fee_base: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class TravelExpense:
    """Individual planned or actual travel expense item."""
    expense_id: str
    description: str
    category: str
    amount: Decimal
    currency: str


@dataclass
class ConvertedExpense:
    """Expense converted into the base currency with FX fee breakdown."""
    expense: TravelExpense
    exchange_rate_used: Decimal
    base_converted_amount: Decimal
    conversion_fee_amount: Decimal
    total_base_cost: Decimal


@dataclass
class TravelBudgetReport:
    """Complete multi-currency travel budget evaluation."""
    trip_name: str
    base_currency: str
    total_budget: Decimal
    converted_expenses: list[ConvertedExpense]
    category_totals: dict[str, Decimal]
    total_base_spend: Decimal
    total_fx_fees: Decimal
    grand_total_spend: Decimal
    budget_variance: Decimal          # Positive = under budget, Negative = over budget
    is_within_budget: bool
    largest_category: str | None
    largest_category_amount: Decimal


def analyze_travel_budget(
    trip_name: str,
    base_currency: str,
    total_budget: Decimal,
    expenses: list[TravelExpense],
    rates: dict[str, ExchangeRate],
) -> TravelBudgetReport:
    """
    Convert all travel expenses to base_currency, apply conversion fees,
    compare against total_budget, and identify the highest-spend category.
    """
    base_curr = base_currency.upper()
    budget = money(total_budget)

    converted_list: list[ConvertedExpense] = []
    category_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_base_spend = Decimal("0.00")
    total_fx_fees = Decimal("0.00")

    for exp in expenses:
        curr = exp.currency.upper()
        if curr == base_curr:
            rate_to_base = Decimal("1.00")
            base_amt = money(exp.amount)
            fx_fee = Decimal("0.00")
        else:
            if curr not in rates:
                raise ValueError(f"Missing exchange rate for currency '{curr}' ({exp.expense_id}).")
            fx = rates[curr]
            rate_to_base = fx.rate_to_base
            base_amt = money(exp.amount * rate_to_base)
            pct_fee = money(base_amt * fx.fee_rate)
            fx_fee = money(pct_fee + fx.flat_fee_base)

        line_total = money(base_amt + fx_fee)

        converted_list.append(
            ConvertedExpense(
                expense=exp,
                exchange_rate_used=rate_to_base,
                base_converted_amount=base_amt,
                conversion_fee_amount=fx_fee,
                total_base_cost=line_total,
            )
        )

        category_totals[exp.category] = money(category_totals[exp.category] + line_total)
        total_base_spend = money(total_base_spend + base_amt)
        total_fx_fees = money(total_fx_fees + fx_fee)

    grand_total = money(total_base_spend + total_fx_fees)
    variance = money(budget - grand_total)

    if category_totals:
        largest_cat, largest_amt = max(category_totals.items(), key=lambda kv: kv[1])
    else:
        largest_cat, largest_amt = None, Decimal("0.00")

    return TravelBudgetReport(
        trip_name=trip_name,
        base_currency=base_curr,
        total_budget=budget,
        converted_expenses=converted_list,
        category_totals=dict(category_totals),
        total_base_spend=total_base_spend,
        total_fx_fees=total_fx_fees,
        grand_total_spend=grand_total,
        budget_variance=variance,
        is_within_budget=grand_total <= budget,
        largest_category=largest_cat,
        largest_category_amount=largest_amt,
    )


def format_travel_report(report: TravelBudgetReport) -> str:
    """Format a structured multi-currency travel budget summary."""
    bc = report.base_currency
    lines = [
        "=" * 94,
        f"{'MULTI-CURRENCY TRAVEL BUDGET ANALYSIS':^94}",
        "=" * 94,
        f"Trip          : {report.trip_name}",
        f"Base Currency : {bc:<15} Planned Budget : {report.total_budget:>12,.2f} {bc}",
        "-" * 94,
        f"{'Expense':<24} {'Category':<14} {'Original':>14} {'Rate':>8} {'Base Amt':>10} {'FX Fee':>8} {'Total':>10}",
        "-" * 94,
    ]

    for item in report.converted_expenses:
        e = item.expense
        orig_str = f"{money(e.amount):,.2f} {e.currency.upper()}"
        lines.append(
            f"{e.description[:24]:<24} {e.category[:14]:<14} {orig_str:>14} "
            f"{item.exchange_rate_used:>8.4f} {item.base_converted_amount:>10,.2f} "
            f"{item.conversion_fee_amount:>8,.2f} {item.total_base_cost:>10,.2f}"
        )

    lines.extend([
        "-" * 94,
        "CATEGORY BREAKDOWN",
    ])
    for cat, amt in sorted(report.category_totals.items(), key=lambda kv: kv[1], reverse=True):
        share = (amt / report.grand_total_spend * Decimal("100")) if report.grand_total_spend > 0 else Decimal("0.00")
        lines.append(f"  {cat:<24}: {amt:>12,.2f} {bc} ({share:>5.1f}%)")

    status = "WITHIN BUDGET" if report.is_within_budget else "OVER BUDGET"
    variance_label = "Remaining Buffer" if report.is_within_budget else "Budget Excess"

    lines.extend([
        "-" * 94,
        f"{'Base Converted Spend':<74}: {report.total_base_spend:>12,.2f} {bc}",
        f"{'Total FX Conversion Fees':<74}: {report.total_fx_fees:>12,.2f} {bc}",
        f"{'GRAND TOTAL PLANNED SPEND':<74}: {report.grand_total_spend:>12,.2f} {bc}",
        f"{f'{variance_label} ({status})':<74}: {abs(report.budget_variance):>12,.2f} {bc}",
        "=" * 94,
        f"LARGEST EXPENSE CATEGORY : {report.largest_category or 'N/A'} "
        f"({report.largest_category_amount:,.2f} {bc})",
        "=" * 94,
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    fx_rates = {
        "USD": ExchangeRate("USD", rate_to_base=Decimal("84.50"), fee_rate=Decimal("0.02"), flat_fee_base=Decimal("50.00")),
        "EUR": ExchangeRate("EUR", rate_to_base=Decimal("91.20"), fee_rate=Decimal("0.025"), flat_fee_base=Decimal("75.00")),
        "JPY": ExchangeRate("JPY", rate_to_base=Decimal("0.56"), fee_rate=Decimal("0.015"), flat_fee_base=Decimal("0.00")),
    }

    planned_expenses = [
        TravelExpense("EXP-01", "Round-Trip Flights", "Transport", Decimal("58000.00"), "INR"),
        TravelExpense("EXP-02", "Paris Hotel (4 Nights)", "Accommodation", Decimal("720.00"), "EUR"),
        TravelExpense("EXP-03", "Tokyo Hotel (3 Nights)", "Accommodation", Decimal("68000.00"), "JPY"),
        TravelExpense("EXP-04", "Rail Passes & Transfers", "Transport", Decimal("240.00"), "EUR"),
        TravelExpense("EXP-05", "Meals & Local Dining", "Food & Dining", Decimal("450.00"), "USD"),
        TravelExpense("EXP-06", "Museum & City Passes", "Activities", Decimal("180.00"), "USD"),
    ]

    report = analyze_travel_budget(
        trip_name="Europe & Japan Autumn Tour",
        base_currency="INR",
        total_budget=Decimal("225000.00"),
        expenses=planned_expenses,
        rates=fx_rates,
    )
    print(format_travel_report(report))
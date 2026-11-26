from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DeductionBracket:
    """Represents a progressive deduction tier."""
    lower: Decimal
    upper: Decimal | None  # None means no upper bound
    rate: Decimal        # e.g., Decimal("0.10") for 10%


@dataclass
class EmployeePayroll:
    employee_id: str
    name: str
    role: str
    pay_period: str
    basic_pay: Decimal
    hra: Decimal = Decimal("0.00")
    transport_allowance: Decimal = Decimal("0.00")
    other_allowances: Decimal = Decimal("0.00")
    overtime_hours: Decimal = Decimal("0.00")
    overtime_rate: Decimal = Decimal("0.00")
    incentives: Decimal = Decimal("0.00")
    fixed_deductions: Decimal = Decimal("0.00")

    @property
    def total_allowances(self) -> Decimal:
        return money(self.hra + self.transport_allowance + self.other_allowances)

    @property
    def overtime_pay(self) -> Decimal:
        return money(self.overtime_hours * self.overtime_rate)

    @property
    def gross_salary(self) -> Decimal:
        return money(
            self.basic_pay
            + self.total_allowances
            + self.overtime_pay
            + money(self.incentives)
        )


DEFAULT_PROGRESSIVE_BRACKETS: list[DeductionBracket] = [
    DeductionBracket(lower=Decimal("0"), upper=Decimal("25000"), rate=Decimal("0.00")),
    DeductionBracket(lower=Decimal("25000"), upper=Decimal("50000"), rate=Decimal("0.10")),
    DeductionBracket(lower=Decimal("50000"), upper=Decimal("100000"), rate=Decimal("0.20")),
    DeductionBracket(lower=Decimal("100000"), upper=None, rate=Decimal("0.30")),
]


def calculate_progressive_deduction(
    taxable_gross: Decimal,
    brackets: list[DeductionBracket] = DEFAULT_PROGRESSIVE_BRACKETS,
) -> tuple[Decimal, list[tuple[str, Decimal]]]:
    """
    Calculate progressive tax/deduction across marginal brackets.
    Returns total deduction and a breakdown per active bracket.
    """
    total_deduction = Decimal("0.00")
    breakdown: list[tuple[str, Decimal]] = []

    for bracket in brackets:
        if taxable_gross <= bracket.lower:
            break

        ceiling = taxable_gross if bracket.upper is None else min(taxable_gross, bracket.upper)
        taxable_in_tier = max(Decimal("0.00"), ceiling - bracket.lower)
        tier_amount = money(taxable_in_tier * bracket.rate)

        if taxable_in_tier > Decimal("0.00"):
            upper_label = "Above" if bracket.upper is None else f"Up to {bracket.upper:,.2f}"
            label = f"{bracket.lower:,.2f} - {upper_label} ({bracket.rate * 100:.0f}%)"
            breakdown.append((label, tier_amount))
            total_deduction = money(total_deduction + tier_amount)

    return total_deduction, breakdown


def generate_salary_statement(
    payroll: EmployeePayroll,
    brackets: list[DeductionBracket] = DEFAULT_PROGRESSIVE_BRACKETS,
) -> str:
    """Generate a formatted salary statement string for an employee."""
    gross = payroll.gross_salary
    progressive_total, bracket_breakdown = calculate_progressive_deduction(gross, brackets)
    fixed_total = money(payroll.fixed_deductions)
    total_deductions = money(progressive_total + fixed_total)
    net_salary = money(gross - total_deductions)
    effective_rate = (total_deductions / gross * Decimal("100")) if gross > 0 else Decimal("0.00")

    lines = [
        "=" * 62,
        f"{'EMPLOYEE SALARY STATEMENT':^62}",
        "=" * 62,
        f"Employee : {payroll.name} ({payroll.employee_id})",
        f"Role     : {payroll.role}",
        f"Period   : {payroll.pay_period}",
        "-" * 62,
        "EARNINGS",
        f"  Basic Pay              : {money(payroll.basic_pay):>12,.2f}",
        f"  HRA                    : {money(payroll.hra):>12,.2f}",
        f"  Transport Allowance    : {money(payroll.transport_allowance):>12,.2f}",
        f"  Other Allowances       : {money(payroll.other_allowances):>12,.2f}",
        f"  Overtime ({payroll.overtime_hours}h @ {money(payroll.overtime_rate)}) : {payroll.overtime_pay:>12,.2f}",
        f"  Incentives             : {money(payroll.incentives):>12,.2f}",
        "-" * 62,
        f"  GROSS SALARY           : {gross:>12,.2f}",
        "-" * 62,
        "DEDUCTIONS (PROGRESSIVE & FIXED)",
    ]

    for label, amount in bracket_breakdown:
        lines.append(f"  {label:<38}: {amount:>12,.2f}")

    lines.extend([
        f"  Progressive Subtotal   : {progressive_total:>12,.2f}",
        f"  Fixed Deductions       : {fixed_total:>12,.2f}",
        "-" * 62,
        f"  TOTAL DEDUCTIONS       : {total_deductions:>12,.2f}",
        "=" * 62,
        f"  NET PAYABLE SALARY     : {net_salary:>12,.2f}",
        f"  Effective Deduction %  : {effective_rate:>11.2f}%",
        "=" * 62,
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    sample_employee = EmployeePayroll(
        employee_id="EMP-1042",
        name="Ananya Rao",
        role="Senior Data Analyst",
        pay_period="November 2026",
        basic_pay=Decimal("55000"),
        hra=Decimal("16000"),
        transport_allowance=Decimal("4000"),
        other_allowances=Decimal("3500"),
        overtime_hours=Decimal("8"),
        overtime_rate=Decimal("750"),
        incentives=Decimal("10500"),
        fixed_deductions=Decimal("2500"),
    )

    statement = generate_salary_statement(sample_employee)
    print(statement)
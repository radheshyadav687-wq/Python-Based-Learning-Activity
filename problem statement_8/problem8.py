from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TransactionType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"


@dataclass(frozen=True)
class ATMTransaction:
    """Represents a single ATM operation request."""
    tx_id: str
    tx_type: TransactionType
    amount: Decimal
    day: str = "Day 1"
    description: str = ""


@dataclass(frozen=True)
class AccountLimits:
    """Account balance and ATM withdrawal constraints."""
    per_tx_withdrawal_limit: Decimal = Decimal("20000.00")
    daily_withdrawal_limit: Decimal = Decimal("40000.00")
    min_balance_required: Decimal = Decimal("0.00")
    cash_denomination_step: Decimal = Decimal("100.00")  # e.g., 100 or 500 notes


@dataclass
class TransactionLogEntry:
    """Recorded outcome of a processed ATM transaction."""
    tx: ATMTransaction
    status: str  # "APPROVED" or "REJECTED"
    reason: str
    balance_before: Decimal
    balance_after: Decimal


@dataclass
class ATMSummaryReport:
    """Overall summary of a simulated ATM transaction sequence."""
    account_number: str
    account_holder: str
    opening_balance: Decimal
    closing_balance: Decimal
    total_deposits_approved: Decimal
    total_withdrawals_approved: Decimal
    approved_count: int
    rejected_count: int
    daily_withdrawn: dict[str, Decimal]
    logs: list[TransactionLogEntry] = field(default_factory=list)


def simulate_atm_transactions(
    account_number: str,
    account_holder: str,
    opening_balance: Decimal,
    transactions: list[ATMTransaction],
    limits: AccountLimits = AccountLimits(),
) -> ATMSummaryReport:
    """
    Process a sequence of ATM deposits and withdrawals sequentially,
    enforcing limits and rejecting invalid requests without mutating
    the account balance on rejected transactions.
    """
    current_balance = money(opening_balance)
    if current_balance < Decimal("0.00"):
        raise ValueError("Opening balance cannot be negative.")

    total_deposits = Decimal("0.00")
    total_withdrawals = Decimal("0.00")
    approved_count = 0
    rejected_count = 0
    daily_withdrawn: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    logs: list[TransactionLogEntry] = []

    for tx in transactions:
        amt = money(tx.amount)
        before_bal = current_balance

        # 1. Validate amount positivity
        if amt <= Decimal("0.00"):
            rejected_count += 1
            logs.append(
                TransactionLogEntry(
                    tx=tx,
                    status="REJECTED",
                    reason="Transaction amount must be greater than 0.00.",
                    balance_before=before_bal,
                    balance_after=current_balance,
                )
            )
            continue

        if tx.tx_type == TransactionType.DEPOSIT:
            current_balance = money(current_balance + amt)
            total_deposits = money(total_deposits + amt)
            approved_count += 1
            logs.append(
                TransactionLogEntry(
                    tx=tx,
                    status="APPROVED",
                    reason="Deposit credited.",
                    balance_before=before_bal,
                    balance_after=current_balance,
                )
            )

        elif tx.tx_type == TransactionType.WITHDRAWAL:
            day_key = tx.day
            used_today = daily_withdrawn[day_key]
            rejection_reasons: list[str] = []

            if (
                limits.cash_denomination_step > Decimal("0.00")
                and (amt % limits.cash_denomination_step) != Decimal("0.00")
            ):
                rejection_reasons.append(
                    f"Amount must be a multiple of {limits.cash_denomination_step:,.2f}."
                )

            if amt > limits.per_tx_withdrawal_limit:
                rejection_reasons.append(
                    f"Exceeds per-transaction limit ({limits.per_tx_withdrawal_limit:,.2f})."
                )

            if money(used_today + amt) > limits.daily_withdrawal_limit:
                remaining_daily = max(Decimal("0.00"), money(limits.daily_withdrawal_limit - used_today))
                rejection_reasons.append(
                    f"Exceeds daily withdrawal limit ({limits.daily_withdrawal_limit:,.2f}; "
                    f"remaining today: {remaining_daily:,.2f})."
                )

            resulting_balance = money(current_balance - amt)
            if amt > current_balance:
                rejection_reasons.append(
                    f"Insufficient funds (available: {current_balance:,.2f})."
                )
            elif resulting_balance < limits.min_balance_required:
                rejection_reasons.append(
                    f"Would breach minimum required balance ({limits.min_balance_required:,.2f})."
                )

            if rejection_reasons:
                rejected_count += 1
                logs.append(
                    TransactionLogEntry(
                        tx=tx,
                        status="REJECTED",
                        reason=" | ".join(rejection_reasons),
                        balance_before=before_bal,
                        balance_after=current_balance,
                    )
                )
            else:
                current_balance = resulting_balance
                daily_withdrawn[day_key] = money(used_today + amt)
                total_withdrawals = money(total_withdrawals + amt)
                approved_count += 1
                logs.append(
                    TransactionLogEntry(
                        tx=tx,
                        status="APPROVED",
                        reason="Cash dispensed.",
                        balance_before=before_bal,
                        balance_after=current_balance,
                    )
                )
        else:
            rejected_count += 1
            logs.append(
                TransactionLogEntry(
                    tx=tx,
                    status="REJECTED",
                    reason=f"Unsupported transaction type: {tx.tx_type}",
                    balance_before=before_bal,
                    balance_after=current_balance,
                )
            )

    return ATMSummaryReport(
        account_number=account_number,
        account_holder=account_holder,
        opening_balance=money(opening_balance),
        closing_balance=current_balance,
        total_deposits_approved=total_deposits,
        total_withdrawals_approved=total_withdrawals,
        approved_count=approved_count,
        rejected_count=rejected_count,
        daily_withdrawn=dict(daily_withdrawn),
        logs=logs,
    )


def format_atm_summary(report: ATMSummaryReport) -> str:
    """Format a readable transaction log and end-of-simulation summary."""
    lines = [
        "=" * 96,
        f"{'ATM TRANSACTION SEQUENCE SIMULATION REPORT':^96}",
        "=" * 96,
        f"Account Holder : {report.account_holder} ({report.account_number})",
        f"Opening Balance: {report.opening_balance:>12,.2f} | Closing Balance: {report.closing_balance:>12,.2f}",
        "-" * 96,
        f"{'TX ID':<10} {'Day':<7} {'Type':<10} {'Amount':>11} {'Status':<10} {'Balance After':>13} {'Notes'}",
        "-" * 96,
    ]

    for entry in report.logs:
        t = entry.tx
        lines.append(
            f"{t.tx_id:<10} {t.day:<7} {t.tx_type.value:<10} {money(t.amount):>11,.2f} "
            f"{entry.status:<10} {entry.balance_after:>13,.2f} {entry.reason}"
        )

    lines.extend([
        "-" * 96,
        f"Approved Transactions : {report.approved_count:<8} Rejected Transactions : {report.rejected_count}",
        f"Total Approved Deposit: {report.total_deposits_approved:>12,.2f}",
        f"Total Approved Withdr.: {report.total_withdrawals_approved:>12,.2f}",
    ])

    if report.daily_withdrawn:
        daily_str = ", ".join(
            f"{day}: {amt:,.2f}" for day, amt in sorted(report.daily_withdrawn.items())
        )
        lines.append(f"Daily Withdrawals Used: {daily_str}")

    lines.append("=" * 96)
    return "\n".join(lines)


if __name__ == "__main__":
    account_limits = AccountLimits(
        per_tx_withdrawal_limit=Decimal("20000.00"),
        daily_withdrawal_limit=Decimal("35000.00"),
        min_balance_required=Decimal("2000.00"),
        cash_denomination_step=Decimal("100.00"),
    )

    tx_sequence = [
        ATMTransaction("TX-001", TransactionType.WITHDRAWAL, Decimal("15000.00"), day="Day 1"),
        ATMTransaction("TX-002", TransactionType.WITHDRAWAL, Decimal("22000.00"), day="Day 1"),  # > per-tx limit
        ATMTransaction("TX-003", TransactionType.WITHDRAWAL, Decimal("20000.00"), day="Day 1"),  # pushes Day 1 to 35k
        ATMTransaction("TX-004", TransactionType.WITHDRAWAL, Decimal("2000.00"), day="Day 1"),   # > daily limit
        ATMTransaction("TX-005", TransactionType.DEPOSIT, Decimal("12000.00"), day="Day 1"),
        ATMTransaction("TX-006", TransactionType.WITHDRAWAL, Decimal("250.00"), day="Day 2"),    # not multiple of 100
        ATMTransaction("TX-007", TransactionType.WITHDRAWAL, Decimal("16500.00"), day="Day 2"),  # breaches 2,000 min bal
        ATMTransaction("TX-008", TransactionType.WITHDRAWAL, Decimal("14000.00"), day="Day 2"),  # approved
        ATMTransaction("TX-009", TransactionType.DEPOSIT, Decimal("-500.00"), day="Day 2"),     # invalid amount
    ]

    report = simulate_atm_transactions(
        account_number="ACCT-7789201",
        account_holder="Arjun Nair",
        opening_balance=Decimal("32000.00"),
        transactions=tx_sequence,
        limits=account_limits,
    )
    print(format_atm_summary(report))
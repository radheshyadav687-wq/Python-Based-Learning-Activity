from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class VehicleParkingRate:
    """Rate card, daily cap, overnight surcharge, and penalty rules for a vehicle type."""
    category: str
    first_hour_rate: Decimal
    subsequent_hour_rate: Decimal
    daily_cap: Decimal | None = None
    overnight_surcharge_per_night: Decimal = Decimal("0.00")
    overnight_window_start_hour: int = 22  # 10:00 PM
    overnight_window_end_hour: int = 6     # 06:00 AM
    grace_period_minutes: int = 15
    overstay_penalty_rate_per_hour: Decimal = Decimal("0.00")
    lost_ticket_penalty: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class ParkingSession:
    """Represents a single vehicle parking record and penalty flags."""
    ticket_id: str
    vehicle_number: str
    category: str
    entry_time: datetime
    exit_time: datetime
    max_allowed_hours: Decimal | None = None
    lost_ticket: bool = False


@dataclass
class ParkingFeeBreakdown:
    """Itemized parking fee calculation result."""
    session: ParkingSession
    total_minutes: int
    billable_hours: int
    overnight_nights: int
    base_parking_fee: Decimal
    overnight_surcharge: Decimal
    capped_parking_fee: Decimal
    overstay_penalty: Decimal
    lost_ticket_penalty: Decimal
    total_payable: Decimal
    notes: list[str] = field(default_factory=list)


def count_overnight_windows(
    entry_time: datetime,
    exit_time: datetime,
    start_hour: int = 22,
    end_hour: int = 6,
) -> int:
    """
    Count how many overnight windows (e.g., 22:00 to 06:00 next day) overlap
    with the [entry_time, exit_time] parking interval.
    """
    if exit_time <= entry_time:
        return 0

    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        raise ValueError("Overnight window hours must be in range 0..23.")

    nights = 0
    # Start checking from the day before entry_time to capture an active overnight window at entry
    day_cursor = entry_time.date().fromordinal(entry_time.date().toordinal() - 1)
    last_day = exit_time.date()

    while day_cursor <= last_day:
        win_start = datetime(day_cursor.year, day_cursor.month, day_cursor.day, start_hour, 0)
        if end_hour <= start_hour:
            next_day = day_cursor.fromordinal(day_cursor.toordinal() + 1)
            win_end = datetime(next_day.year, next_day.month, next_day.day, end_hour, 0)
        else:
            win_end = datetime(day_cursor.year, day_cursor.month, day_cursor.day, end_hour, 0)

        overlap_start = max(entry_time, win_start)
        overlap_end = min(exit_time, win_end)
        if overlap_end > overlap_start:
            nights += 1

        day_cursor = day_cursor.fromordinal(day_cursor.toordinal() + 1)

    return nights


def calculate_parking_fee(
    session: ParkingSession,
    rate_cards: dict[str, VehicleParkingRate],
) -> ParkingFeeBreakdown:
    """
    Validate timestamps and calculate parking fees, overnight surcharges,
    daily caps, and penalties for a parking session.
    """
    if not isinstance(session.entry_time, datetime) or not isinstance(session.exit_time, datetime):
        raise TypeError("entry_time and exit_time must be datetime instances.")

    if session.exit_time < session.entry_time:
        raise ValueError(
            f"Invalid time input for {session.ticket_id}: exit_time ({session.exit_time}) "
            f"cannot be earlier than entry_time ({session.entry_time})."
        )

    cat_key = session.category.upper()
    if cat_key not in rate_cards:
        raise ValueError(f"Unknown vehicle category '{session.category}' for ticket {session.ticket_id}.")

    rate = rate_cards[cat_key]
    notes: list[str] = []

    elapsed_seconds = (session.exit_time - session.entry_time).total_seconds()
    total_minutes = int(math.ceil(elapsed_seconds / 60.0)) if elapsed_seconds > 0 else 0

    # Grace period check: if within grace window and no lost ticket, base & overnight charges are waived
    if total_minutes <= rate.grace_period_minutes and not session.lost_ticket:
        billable_hours = 0
        overnight_nights = 0
        base_fee = Decimal("0.00")
        overnight_fee = Decimal("0.00")
        capped_fee = Decimal("0.00")
        notes.append(f"Within {rate.grace_period_minutes}-minute grace period; hourly & overnight fees waived.")
    else:
        billable_hours = max(1, int(math.ceil(total_minutes / 60.0)))
        first_hr = money(rate.first_hour_rate)
        extra_hrs = max(0, billable_hours - 1)
        subseq_fee = money(Decimal(extra_hrs) * rate.subsequent_hour_rate)
        base_fee = money(first_hr + subseq_fee)

        overnight_nights = count_overnight_windows(
            session.entry_time,
            session.exit_time,
            start_hour=rate.overnight_window_start_hour,
            end_hour=rate.overnight_window_end_hour,
        )
        overnight_fee = money(Decimal(overnight_nights) * rate.overnight_surcharge_per_night)

        uncapped_parking = money(base_fee + overnight_fee)
        if rate.daily_cap is not None:
            calendar_days = max(
                1,
                (session.exit_time.date() - session.entry_time.date()).days + 1,
            )
            effective_cap = money(Decimal(calendar_days) * rate.daily_cap)
            if uncapped_parking > effective_cap:
                capped_fee = effective_cap
                notes.append(
                    f"Daily cap applied ({effective_cap:,.2f} across {calendar_days} day(s); "
                    f"saved {money(uncapped_parking - effective_cap):,.2f})."
                )
            else:
                capped_fee = uncapped_parking
        else:
            capped_fee = uncapped_parking

    # Penalty conditions: Overstay beyond max_allowed_hours and/or Lost Ticket
    overstay_penalty = Decimal("0.00")
    if session.max_allowed_hours is not None:
        actual_hours = Decimal(total_minutes) / Decimal("60")
        if actual_hours > session.max_allowed_hours:
            overstay_hours = Decimal(
                str(math.ceil(float(actual_hours - session.max_allowed_hours)))
            )
            overstay_penalty = money(overstay_hours * rate.overstay_penalty_rate_per_hour)
            notes.append(
                f"Overstay penalty for {overstay_hours} extra hour(s) beyond "
                f"{session.max_allowed_hours}h limit."
            )

    lost_penalty = Decimal("0.00")
    if session.lost_ticket:
        lost_penalty = money(rate.lost_ticket_penalty)
        notes.append("Lost ticket penalty assessed.")

    total_payable = money(capped_fee + overstay_penalty + lost_penalty)

    return ParkingFeeBreakdown(
        session=session,
        total_minutes=total_minutes,
        billable_hours=billable_hours,
        overnight_nights=overnight_nights,
        base_parking_fee=base_fee,
        overnight_surcharge=overnight_fee,
        capped_parking_fee=capped_fee,
        overstay_penalty=overstay_penalty,
        lost_ticket_penalty=lost_penalty,
        total_payable=total_payable,
        notes=notes,
    )


def format_parking_receipt(breakdown: ParkingFeeBreakdown) -> str:
    """Format a readable smart parking ticket receipt."""
    s = breakdown.session
    duration_hr_min = f"{breakdown.total_minutes // 60}h {breakdown.total_minutes % 60}m"
    lines = [
        "=" * 78,
        f"{'SMART PARKING FEE RECEIPT':^78}",
        "=" * 78,
        f"Ticket ID  : {s.ticket_id:<22} Vehicle : {s.vehicle_number} ({s.category.upper()})",
        f"Entry Time : {s.entry_time.strftime('%Y-%m-%d %H:%M')}",
        f"Exit Time  : {s.exit_time.strftime('%Y-%m-%d %H:%M')}  (Duration: {duration_hr_min})",
        "-" * 78,
        f"  Billable Hours          : {breakdown.billable_hours:>10} hr(s)",
        f"  Overnight Windows (22-06): {breakdown.overnight_nights:>10} night(s)",
        f"  Base Hourly Fee         : {breakdown.base_parking_fee:>13,.2f}",
        f"  Overnight Surcharge     : {breakdown.overnight_surcharge:>13,.2f}",
        f"  Parking Fee (After Cap) : {breakdown.capped_parking_fee:>13,.2f}",
        f"  Overstay Penalty        : {breakdown.overstay_penalty:>13,.2f}",
        f"  Lost Ticket Penalty     : {breakdown.lost_ticket_penalty:>13,.2f}",
        "=" * 78,
        f"  TOTAL PAYABLE           : {breakdown.total_payable:>13,.2f}",
        "=" * 78,
    ]
    if breakdown.notes:
        lines.append("NOTES:")
        for note in breakdown.notes:
            lines.append(f"  * {note}")
        lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    parking_rates = {
        "MOTORCYCLE": VehicleParkingRate(
            category="MOTORCYCLE",
            first_hour_rate=Decimal("20.00"),
            subsequent_hour_rate=Decimal("10.00"),
            daily_cap=Decimal("120.00"),
            overnight_surcharge_per_night=Decimal("30.00"),
            grace_period_minutes=15,
            overstay_penalty_rate_per_hour=Decimal("25.00"),
            lost_ticket_penalty=Decimal("150.00"),
        ),
        "CAR": VehicleParkingRate(
            category="CAR",
            first_hour_rate=Decimal("50.00"),
            subsequent_hour_rate=Decimal("30.00"),
            daily_cap=Decimal("300.00"),
            overnight_surcharge_per_night=Decimal("80.00"),
            grace_period_minutes=15,
            overstay_penalty_rate_per_hour=Decimal("60.00"),
            lost_ticket_penalty=Decimal("350.00"),
        ),
        "SUV": VehicleParkingRate(
            category="SUV",
            first_hour_rate=Decimal("70.00"),
            subsequent_hour_rate=Decimal("40.00"),
            daily_cap=Decimal("400.00"),
            overnight_surcharge_per_night=Decimal("100.00"),
            grace_period_minutes=15,
            overstay_penalty_rate_per_hour=Decimal("80.00"),
            lost_ticket_penalty=Decimal("500.00"),
        ),
    }

    sessions = [
        ParkingSession(
            ticket_id="PKG-1001",
            vehicle_number="AP16-CD-4412",
            category="CAR",
            entry_time=datetime(2026, 11, 25, 19, 30),
            exit_time=datetime(2026, 11, 26, 9, 15),
            max_allowed_hours=Decimal("12"),
        ),
        ParkingSession(
            ticket_id="PKG-1002",
            vehicle_number="AP07-AB-9021",
            category="MOTORCYCLE",
            entry_time=datetime(2026, 11, 26, 10, 0),
            exit_time=datetime(2026, 11, 26, 10, 12),
        ),
        ParkingSession(
            ticket_id="PKG-1003",
            vehicle_number="TS09-EF-7780",
            category="SUV",
            entry_time=datetime(2026, 11, 26, 8, 0),
            exit_time=datetime(2026, 11, 26, 11, 30),
            lost_ticket=True,
        ),
    ]

    for sess in sessions:
        result = calculate_parking_fee(sess, parking_rates)
        print(format_parking_receipt(result))
        print()
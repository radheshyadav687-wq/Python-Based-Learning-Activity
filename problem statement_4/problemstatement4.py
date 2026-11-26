from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class DistanceSlab:
    """Progressive distance fare tier (rate per km for distance within this slab)."""
    lower_km: Decimal
    upper_km: Optional[Decimal]  # None means no upper bound
    rate_per_km: Decimal


@dataclass(frozen=True)
class TravelClass:
    """Travel class configuration including distance slabs, fees, and tax."""
    code: str
    name: str
    reservation_fee: Decimal
    superfast_fee: Decimal
    gst_rate: Decimal  # e.g., Decimal("0.05") for 5%
    min_cancellation_fee: Decimal
    distance_slabs: list[DistanceSlab]

    def base_distance_fare(self, distance_km: Decimal) -> Decimal:
        """Compute cumulative distance fare across applicable slabs."""
        fare = Decimal("0.00")
        for slab in self.distance_slabs:
            if distance_km <= slab.lower_km:
                break
            ceiling = distance_km if slab.upper_km is None else min(distance_km, slab.upper_km)
            km_in_slab = max(Decimal("0.00"), ceiling - slab.lower_km)
            fare = money(fare + km_in_slab * slab.rate_per_km)
        return fare


@dataclass(frozen=True)
class Passenger:
    """Passenger details and concession eligibility."""
    name: str
    age: int
    gender: str = "M"  # "M", "F", or "O"
    concession_type: str = "NONE"  # "NONE", "DIVYANGJAN", "STUDENT", "MEDICAL"
    concession_rate: Decimal = Decimal("0.00")  # e.g., Decimal("0.50") for 50%
    requires_berth: bool = True


@dataclass(frozen=True)
class CancellationPolicy:
    """Time-slab cancellation deduction rules before scheduled departure."""
    hours_before_departure: Optional[Decimal]  # None means cancelled/no-show after cutoff
    rate_on_fare: Decimal  # e.g., Decimal("0.25") for 25%
    flat_fee_per_passenger: Decimal = Decimal("0.00")
    zero_refund: bool = False


DEFAULT_CANCELLATION_SLABS: list[CancellationPolicy] = [
    CancellationPolicy(hours_before_departure=Decimal("48"), rate_on_fare=Decimal("0.00"), flat_fee_per_passenger=Decimal("0.00")),
    CancellationPolicy(hours_before_departure=Decimal("12"), rate_on_fare=Decimal("0.25")),
    CancellationPolicy(hours_before_departure=Decimal("4"), rate_on_fare=Decimal("0.50")),
    CancellationPolicy(hours_before_departure=None, rate_on_fare=Decimal("1.00"), zero_refund=True),
]


@dataclass
class PassengerFareBreakdown:
    passenger: Passenger
    base_fare: Decimal
    concession_amount: Decimal
    net_base_fare: Decimal
    reservation_fee: Decimal
    superfast_fee: Decimal
    gst_amount: Decimal
    total_fare: Decimal
    cancellation_penalty: Decimal = Decimal("0.00")
    refund_amount: Decimal = Decimal("0.00")


@dataclass
class BookingSummary:
    booking_id: str
    train_number: str
    origin: str
    destination: str
    distance_km: Decimal
    travel_class: TravelClass
    passengers: list[PassengerFareBreakdown] = field(default_factory=list)
    hours_before_departure: Optional[Decimal] = None

    @property
    def total_booking_fare(self) -> Decimal:
        return money(sum((p.total_fare for p in self.passengers), Decimal("0.00")))

    @property
    def total_cancellation_penalty(self) -> Decimal:
        return money(sum((p.cancellation_penalty for p in self.passengers), Decimal("0.00")))

    @property
    def total_refund(self) -> Decimal:
        return money(sum((p.refund_amount for p in self.passengers), Decimal("0.00")))


def get_age_concession_rate(passenger: Passenger) -> Decimal:
    """
    Determine age-based concession rate.
    Note: Under standard Indian Railways rules, children under 5 without a berth
    pay zero fare (100% waived), while general senior citizen fare discounts are not
    applied unless explicitly passed via concession_rate.
    """
    if passenger.age < 5 and not passenger.requires_berth:
        return Decimal("1.00")
    return max(Decimal("0.00"), min(Decimal("1.00"), passenger.concession_rate))


def calculate_cancellation_penalty(
    fare_before_tax: Decimal,
    travel_class: TravelClass,
    hours_before_departure: Optional[Decimal],
    policies: list[CancellationPolicy] = DEFAULT_CANCELLATION_SLABS,
) -> tuple[Decimal, Decimal]:
    """
    Calculate cancellation penalty and net refund for a passenger ticket.
    Returns (penalty, refund).
    """
    if hours_before_departure is None:
        return money(fare_before_tax), Decimal("0.00")

    # Sort descending by threshold so highest hours_before_departure matched first
    timed_policies = sorted(
        [p for p in policies if p.hours_before_departure is not None],
        key=lambda p: p.hours_before_departure,
        reverse=True,
    )
    fallback = next((p for p in policies if p.hours_before_departure is None), None)

    selected: Optional[CancellationPolicy] = None
    for policy in timed_policies:
        if hours_before_departure >= policy.hours_before_departure:
            selected = policy
            break

    if selected is None:
        selected = fallback or CancellationPolicy(
            hours_before_departure=None, rate_on_fare=Decimal("1.00"), zero_refund=True
        )

    if selected.zero_refund:
        return money(fare_before_tax), Decimal("0.00")

    # >48h tier uses class minimum cancellation fee; percentage tiers enforce at least min_cancellation_fee
    if selected.rate_on_fare == Decimal("0.00"):
        penalty = money(max(travel_class.min_cancellation_fee, selected.flat_fee_per_passenger))
    else:
        pct_charge = money(fare_before_tax * selected.rate_on_fare)
        penalty = money(max(pct_charge, travel_class.min_cancellation_fee))

    penalty = min(penalty, money(fare_before_tax))
    refund = money(max(Decimal("0.00"), money(fare_before_tax) - penalty))
    return penalty, refund


def calculate_booking(
    booking_id: str,
    train_number: str,
    origin: str,
    destination: str,
    distance_km: Decimal,
    travel_class: TravelClass,
    passengers: list[Passenger],
    hours_before_departure: Optional[Decimal] = None,
    cancel_all: bool = False,
) -> BookingSummary:
    """Calculate fares and optional cancellation penalties for all passengers."""
    summary = BookingSummary(
        booking_id=booking_id,
        train_number=train_number,
        origin=origin,
        destination=destination,
        distance_km=Decimal(str(distance_km)),
        travel_class=travel_class,
        hours_before_departure=hours_before_departure,
    )

    raw_base_fare = travel_class.base_distance_fare(summary.distance_km)

    for pax in passengers:
        rate = get_age_concession_rate(pax)
        concession_amt = money(raw_base_fare * rate)
        net_base = money(max(Decimal("0.00"), raw_base_fare - concession_amt))

        # Infants (<5) traveling without berth do not pay reservation or superfast fees
        if pax.age < 5 and not pax.requires_berth:
            res_fee = Decimal("0.00")
            sf_fee = Decimal("0.00")
        else:
            res_fee = money(travel_class.reservation_fee)
            sf_fee = money(travel_class.superfast_fee)

        taxable_subtotal = money(net_base + res_fee + sf_fee)
        gst = money(taxable_subtotal * travel_class.gst_rate)
        total_pax_fare = money(taxable_subtotal + gst)

        penalty = Decimal("0.00")
        refund = Decimal("0.00")
        if cancel_all:
            penalty, refund = calculate_cancellation_penalty(
                fare_before_tax=taxable_subtotal,
                travel_class=travel_class,
                hours_before_departure=hours_before_departure,
            )

        summary.passengers.append(
            PassengerFareBreakdown(
                passenger=pax,
                base_fare=raw_base_fare,
                concession_amount=concession_amt,
                net_base_fare=net_base,
                reservation_fee=res_fee,
                superfast_fee=sf_fee,
                gst_amount=gst,
                total_fare=total_pax_fare,
                cancellation_penalty=penalty,
                refund_amount=refund,
            )
        )

    return summary


def format_booking_statement(summary: BookingSummary, show_cancellation: bool = False) -> str:
    """Render a readable ticket & reservation cost statement."""
    lines = [
        "=" * 86,
        f"{'RAILWAY FARE & RESERVATION STATEMENT':^86}",
        "=" * 86,
        f"Booking ID : {summary.booking_id:<18} Train : {summary.train_number}",
        f"Route      : {summary.origin} -> {summary.destination} ({summary.distance_km} km)",
        f"Class      : {summary.travel_class.name} ({summary.travel_class.code})",
        "-" * 86,
        f"{'Passenger':<20} {'Age/Gen':<8} {'Base':>9} {'Conc.':>9} {'Fees':>9} {'GST':>8} {'Total':>10}",
        "-" * 86,
    ]

    for item in summary.passengers:
        p = item.passenger
        age_gen = f"{p.age}/{p.gender}"
        fees = money(item.reservation_fee + item.superfast_fee)
        lines.append(
            f"{p.name:<20} {age_gen:<8} {item.base_fare:>9,.2f} {item.concession_amount:>9,.2f} "
            f"{fees:>9,.2f} {item.gst_amount:>8,.2f} {item.total_fare:>10,.2f}"
        )

    lines.extend([
        "-" * 86,
        f"{'TOTAL BOOKING FARE':<75}: {summary.total_booking_fare:>10,.2f}",
    ])

    if show_cancellation:
        lines.extend([
            "-" * 86,
            f"CANCELLATION ANALYSIS (Hours Before Departure: {summary.hours_before_departure})",
        ])
        for item in summary.passengers:
            lines.append(
                f"  {item.passenger.name:<22} Penalty: {item.cancellation_penalty:>9,.2f} | "
                f"Refund: {item.refund_amount:>9,.2f}"
            )
        lines.extend([
            "-" * 86,
            f"  {'Total Cancellation Penalty':<35}: {summary.total_cancellation_penalty:>10,.2f}",
            f"  {'Total Net Refund':<35}: {summary.total_refund:>10,.2f}",
        ])

    lines.append("=" * 86)
    return "\n".join(lines)


if __name__ == "__main__":
    ac_3_tier = TravelClass(
        code="3A",
        name="AC 3-Tier",
        reservation_fee=Decimal("40.00"),
        superfast_fee=Decimal("45.00"),
        gst_rate=Decimal("0.05"),
        min_cancellation_fee=Decimal("180.00"),
        distance_slabs=[
            DistanceSlab(Decimal("0"), Decimal("250"), Decimal("1.20")),
            DistanceSlab(Decimal("250"), Decimal("1000"), Decimal("0.95")),
            DistanceSlab(Decimal("1000"), None, Decimal("0.75")),
        ],
    )

    passenger_list = [
        Passenger(name="Ramesh Kumar", age=64, gender="M"),
        Passenger(name="Kavitha Rao", age=34, gender="F"),
        Passenger(name="Aarav Rao", age=4, gender="M", requires_berth=False),
        Passenger(name="Neha Verma", age=21, gender="F", concession_type="STUDENT", concession_rate=Decimal("0.50")),
    ]

    # Scenario 1: Active booking
    booking = calculate_booking(
        booking_id="PNR-8841209",
        train_number="12728",
        origin="Vijayawada (BZA)",
        destination="New Delhi (NDLS)",
        distance_km=Decimal("1660"),
        travel_class=ac_3_tier,
        passengers=passenger_list,
    )
    print(format_booking_statement(booking, show_cancellation=False))

    # Scenario 2: Same booking cancelled 20 hours before departure
    cancelled_booking = calculate_booking(
        booking_id="PNR-8841209",
        train_number="12728",
        origin="Vijayawada (BZA)",
        destination="New Delhi (NDLS)",
        distance_km=Decimal("1660"),
        travel_class=ac_3_tier,
        passengers=passenger_list,
        hours_before_departure=Decimal("20"),
        cancel_all=True,
    )
    print("\n" + format_booking_statement(cancelled_booking, show_cancellation=True))
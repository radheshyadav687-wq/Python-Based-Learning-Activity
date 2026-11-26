from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional


def money(value: Decimal | int | float | str) -> Decimal:
    """Round monetary values to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fuel_qty(value: Decimal | int | float | str) -> Decimal:
    """Round fuel quantities (liters) to three decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class VehicleProfile:
    """Vehicle fuel efficiency, tank capacity, reserve rule, and per-km wear/toll factor."""
    vehicle_id: str
    name: str
    fuel_type: str                 # e.g., "PETROL", "DIESEL", "CNG"
    mileage_km_per_l: Decimal      # e.g., Decimal("18.5") km/L
    tank_capacity_l: Decimal       # Total usable/physical tank size in liters
    min_reserve_l: Decimal         # Minimum fuel to keep in tank at destination/refuel point
    starting_fuel_l: Decimal       # Fuel currently in tank at trip start
    extra_cost_per_km: Decimal = Decimal("0.00")  # Optional maintenance/wear per km


@dataclass(frozen=True)
class RouteOption:
    """Candidate route specification, distance, fuel price, and fixed tolls/fees."""
    route_id: str
    name: str
    distance_km: Decimal
    fuel_price_per_l: Decimal
    toll_and_other_fees: Decimal = Decimal("0.00")
    max_single_leg_km: Optional[Decimal] = None  # Optional limit before refuel; None = unlimited stops


@dataclass
class OptionEvaluation:
    """Calculated fuel, feasibility, and journey cost result for a vehicle-route pair."""
    vehicle: VehicleProfile
    route: RouteOption
    journey_fuel_l: Decimal
    reserve_fuel_l: Decimal
    total_fuel_needed_l: Decimal
    fuel_to_purchase_l: Decimal
    fuel_cost: Decimal
    extra_km_cost: Decimal
    toll_cost: Decimal
    total_journey_cost: Decimal
    cost_per_km: Decimal
    is_feasible: bool
    infeasibility_reasons: list[str] = field(default_factory=list)


def evaluate_vehicle_route(
    vehicle: VehicleProfile,
    route: RouteOption,
    require_single_tank_without_refuel: bool = False,
) -> OptionEvaluation:
    """
    Evaluate a vehicle on a route against distance, mileage, fuel price,
    tank capacity, and reserve fuel requirements.
    """
    if route.distance_km < Decimal("0") or vehicle.mileage_km_per_l <= Decimal("0"):
        raise ValueError("Distance must be non-negative and mileage must be positive.")
    if route.fuel_price_per_l < Decimal("0"):
        raise ValueError("Fuel price per liter cannot be negative.")

    journey_fuel = fuel_qty(route.distance_km / vehicle.mileage_km_per_l)
    reserve_fuel = fuel_qty(vehicle.min_reserve_l)
    total_needed = fuel_qty(journey_fuel + reserve_fuel)

    starting = fuel_qty(vehicle.starting_fuel_l)
    fuel_to_buy = fuel_qty(max(Decimal("0.000"), total_needed - starting))

    fuel_cost = money(fuel_to_buy * route.fuel_price_per_l)
    extra_km_cost = money(route.distance_km * vehicle.extra_cost_per_km)
    toll_cost = money(route.toll_and_other_fees)
    total_cost = money(fuel_cost + extra_km_cost + toll_cost)
    per_km = money(total_cost / route.distance_km) if route.distance_km > Decimal("0") else Decimal("0.00")

    reasons: list[str] = []

    if reserve_fuel > vehicle.tank_capacity_l:
        reasons.append(
            f"Reserve requirement ({reserve_fuel} L) exceeds tank capacity ({vehicle.tank_capacity_l} L)."
        )

    if require_single_tank_without_refuel:
        if total_needed > vehicle.tank_capacity_l:
            reasons.append(
                f"Total fuel needed ({total_needed} L) exceeds single-tank capacity ({vehicle.tank_capacity_l} L)."
            )
        if starting < total_needed:
            reasons.append(
                f"Starting fuel ({starting} L) is below required ({total_needed} L) with no refueling allowed."
            )
    else:
        # Even with refueling stops, a single fill-up cannot exceed tank capacity
        if fuel_to_buy > Decimal("0.000") and vehicle.tank_capacity_l < reserve_fuel:
            reasons.append("Tank capacity cannot hold minimum reserve fuel.")

    if route.max_single_leg_km is not None and route.max_single_leg_km > Decimal("0"):
        # Max safe distance on a full tank while keeping reserve_fuel intact
        usable_full_tank_l = max(Decimal("0.000"), vehicle.tank_capacity_l - reserve_fuel)
        max_safe_leg_km = usable_full_tank_l * vehicle.mileage_km_per_l
        if route.max_single_leg_km > max_safe_leg_km:
            reasons.append(
                f"Leg without fuel station ({route.max_single_leg_km} km) exceeds safe range "
                f"({max_safe_leg_km:.1f} km keeping {reserve_fuel} L reserve)."
            )

    return OptionEvaluation(
        vehicle=vehicle,
        route=route,
        journey_fuel_l=journey_fuel,
        reserve_fuel_l=reserve_fuel,
        total_fuel_needed_l=total_needed,
        fuel_to_purchase_l=fuel_to_buy,
        fuel_cost=fuel_cost,
        extra_km_cost=extra_km_cost,
        toll_cost=toll_cost,
        total_journey_cost=total_cost,
        cost_per_km=per_km,
        is_feasible=len(reasons) == 0,
        infeasibility_reasons=reasons,
    )


def optimize_fuel_and_route(
    vehicles: list[VehicleProfile],
    routes: list[RouteOption],
    require_single_tank_without_refuel: bool = False,
) -> tuple[Optional[OptionEvaluation], list[OptionEvaluation]]:
    """
    Evaluate all vehicle-route combinations and return:
      1. The lowest-cost feasible option (or None if none are feasible).
      2. All evaluations sorted by total_journey_cost ascending.
    """
    evaluations = [
        evaluate_vehicle_route(
            veh,
            rt,
            require_single_tank_without_refuel=require_single_tank_without_refuel,
        )
        for veh in vehicles
        for rt in routes
    ]
    evaluations.sort(key=lambda e: (e.total_journey_cost, e.total_fuel_needed_l, e.vehicle.vehicle_id, e.route.route_id))

    feasible = [ev for ev in evaluations if ev.is_feasible]
    best_option = feasible[0] if feasible else None
    return best_option, evaluations


def format_comparison_report(
    best_option: Optional[OptionEvaluation],
    evaluations: list[OptionEvaluation],
) -> str:
    """Format a structured fuel requirement and route cost comparison report."""
    lines = [
        "=" * 98,
        f"{'FUEL CONSUMPTION & ROUTE COST COMPARISON REPORT':^98}",
        "=" * 98,
        f"{'Vehicle':<18} {'Route':<20} {'Dist(km)':>8} {'Fuel(L)':>9} {'Buy(L)':>8} {'Cost':>11} {'Status':<10}",
        "-" * 98,
    ]

    for ev in evaluations:
        status = "FEASIBLE" if ev.is_feasible else "INFEASIBLE"
        lines.append(
            f"{ev.vehicle.name[:18]:<18} {ev.route.name[:20]:<20} {ev.route.distance_km:>8.1f} "
            f"{ev.total_fuel_needed_l:>9.3f} {ev.fuel_to_purchase_l:>8.3f} "
            f"{ev.total_journey_cost:>11,.2f} {status:<10}"
        )
        if not ev.is_feasible:
            lines.append(f"   Reason(s): {'; '.join(ev.infeasibility_reasons)}")

    lines.append("=" * 98)
    if best_option:
        v = best_option.vehicle
        r = best_option.route
        lines.extend([
            f"LOWEST-COST FEASIBLE OPTION : {v.name} ({v.vehicle_id}) via {r.name} ({r.route_id})",
            f"Distance & Fuel Needed      : {r.distance_km} km | Journey: {best_option.journey_fuel_l} L "
            f"+ Reserve: {best_option.reserve_fuel_l} L = {best_option.total_fuel_needed_l} L Total",
            f"Fuel to Purchase & Cost     : {best_option.fuel_to_purchase_l} L @ {r.fuel_price_per_l}/L "
            f"= {best_option.fuel_cost:,.2f} (Tolls/Extra: {money(best_option.toll_cost + best_option.extra_km_cost):,.2f})",
            f"Total Journey Cost          : {best_option.total_journey_cost:,.2f} ({best_option.cost_per_km:,.2f}/km)",
        ])
    else:
        lines.append("LOWEST-COST FEASIBLE OPTION : None — No vehicle-route pair met all constraints.")
    lines.append("=" * 98)

    return "\n".join(lines)


if __name__ == "__main__":
    vehicles = [
        VehicleProfile(
            vehicle_id="VEH-01",
            name="Hatchback Petrol",
            fuel_type="PETROL",
            mileage_km_per_l=Decimal("18.0"),
            tank_capacity_l=Decimal("37.0"),
            min_reserve_l=Decimal("5.0"),
            starting_fuel_l=Decimal("10.0"),
            extra_cost_per_km=Decimal("0.40"),
        ),
        VehicleProfile(
            vehicle_id="VEH-02",
            name="Sedan Diesel",
            fuel_type="DIESEL",
            mileage_km_per_l=Decimal("22.5"),
            tank_capacity_l=Decimal("45.0"),
            min_reserve_l=Decimal("6.0"),
            starting_fuel_l=Decimal("12.0"),
            extra_cost_per_km=Decimal("0.55"),
        ),
        VehicleProfile(
            vehicle_id="VEH-03",
            name="Compact EV/Hybrid",
            fuel_type="PETROL",
            mileage_km_per_l=Decimal("24.0"),
            tank_capacity_l=Decimal("28.0"),
            min_reserve_l=Decimal("4.0"),
            starting_fuel_l=Decimal("8.0"),
            extra_cost_per_km=Decimal("0.35"),
        ),
    ]

    routes = [
        RouteOption(
            route_id="RT-A",
            name="NH Highway Direct",
            distance_km=Decimal("420.0"),
            fuel_price_per_l=Decimal("106.50"),
            toll_and_other_fees=Decimal("640.00"),
            max_single_leg_km=Decimal("360.0"),
        ),
        RouteOption(
            route_id="RT-B",
            name="Coastal Scenic Route",
            distance_km=Decimal("465.0"),
            fuel_price_per_l=Decimal("104.20"),
            toll_and_other_fees=Decimal("320.00"),
            max_single_leg_km=Decimal("465.0"),
        ),
    ]

    best, all_results = optimize_fuel_and_route(
        vehicles=vehicles,
        routes=routes,
        require_single_tank_without_refuel=False,
    )
    print(format_comparison_report(best, all_results))
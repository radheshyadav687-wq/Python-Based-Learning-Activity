from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Thresholds:
    """Upper-bound thresholds for classifying a metric (e.g., AQI, PM2.5, turbidity)."""
    good_max: float
    moderate_max: float
    poor_max: float

    def classify(self, value: float) -> str:
        if value <= self.good_max:
            return "Good"
        if value <= self.moderate_max:
            return "Moderate"
        if value <= self.poor_max:
            return "Poor"
        return "Severe"


def flatten_readings(nested_readings: Iterable[Iterable[float]]) -> list[float]:
    """Flatten a 2D (or deeper nested) iterable of numeric readings into a 1D list."""
    flat: list[float] = []
    for item in nested_readings:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            flat.append(float(item))
        else:
            flat.extend(flatten_readings(item))
    return flat


def analyze_station_series(
    station_readings: list[float],
    thresholds: Thresholds,
) -> dict:
    """Compute summary statistics and classifications for a single station/series."""
    if not station_readings:
        raise ValueError("station_readings must contain at least one numeric value.")

    average = sum(station_readings) / len(station_readings)
    minimum = min(station_readings)
    maximum = max(station_readings)
    classifications = [thresholds.classify(val) for val in station_readings]

    counts: dict[str, int] = {}
    for label in classifications:
        counts[label] = counts.get(label, 0) + 1

    return {
        "count": len(station_readings),
        "average": round(average, 2),
        "min": minimum,
        "max": maximum,
        "classifications": classifications,
        "category_counts": counts,
    }


def analyze_environmental_data(
    nested_data: list[list[float]],
    thresholds: Thresholds,
    station_names: list[str] | None = None,
) -> dict:
    """Analyze nested lists of readings across multiple stations or monitoring batches."""
    if not nested_data:
        raise ValueError("nested_data cannot be empty.")

    names = station_names or [f"Station_{i + 1}" for i in range(len(nested_data))]
    if len(names) != len(nested_data):
        raise ValueError("station_names must match the number of sublists in nested_data.")

    per_station: dict[str, dict] = {}
    for name, series in zip(names, nested_data):
        per_station[name] = analyze_station_series(series, thresholds)

    all_values = flatten_readings(nested_data)
    overall_summary = {
        "total_readings": len(all_values),
        "overall_average": round(sum(all_values) / len(all_values), 2),
        "overall_min": min(all_values),
        "overall_max": max(all_values),
        "overall_max_classification": thresholds.classify(max(all_values)),
    }

    return {
        "overall": overall_summary,
        "stations": per_station,
    }


# --- Example Usage ---
if __name__ == "__main__":
    # Example 1: Air Quality (e.g., PM2.5 in µg/m³) across 3 stations over multiple days
    pm25_readings = [
        [24.5, 31.0, 28.2, 45.8],  # Station A
        [62.0, 78.4, 91.5, 55.1],  # Station B
        [12.3, 18.9, 15.4, 22.0],  # Station C
    ]
    pm25_thresholds = Thresholds(good_max=30.0, moderate_max=60.0, poor_max=90.0)

    report = analyze_environmental_data(
        nested_data=pm25_readings,
        thresholds=pm25_thresholds,
        station_names=["Industrial Zone", "Highway Corridor", "Botanical Park"],
    )

    print("Overall Summary:", report["overall"])
    for station, stats in report["stations"].items():
        print(
            f"{station} -> avg: {stats['average']}, min: {stats['min']}, "
            f"max: {stats['max']}, counts: {stats['category_counts']}"
        )
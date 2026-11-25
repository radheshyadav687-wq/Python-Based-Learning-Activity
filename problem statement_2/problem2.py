from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PaymentPolicy:
    """Configurable billing constraints, concession rates, and tier thresholds."""
    max_allowed_bill: float = 500000.0
    max_concession_rate: float = 0.50
    senior_age_threshold: int = 60
    senior_discount_rate: float = 0.15
    loyalty_visit_threshold: int = 5
    loyalty_discount_rate: float = 0.10
    insurance_coverage_rate: float = 0.20
    low_tier_max: float = 2000.0
    standard_tier_max: float = 10000.0
    high_tier_max: float = 50000.0

    def classify_payable(self, net_payable: float) -> str:
        """Classify patient billing tier based on final net payable amount."""
        if net_payable == 0:
            return "Zero-Balance / Fully Covered"
        if net_payable <= self.low_tier_max:
            return "Standard Out-of-Pocket"
        if net_payable <= self.standard_tier_max:
            return "Moderate Care"
        if net_payable <= self.high_tier_max:
            return "High-Value Care"
        return "Critical / Installment Eligible"


@dataclass
class PatientRecord:
    """Represents a patient's demographic, eligibility, and itemized charge details."""
    patient_id: str
    name: str
    age: int
    visit_count: int
    has_insurance: bool
    is_emergency: bool
    consultation_charges: Iterable[float]
    diagnostic_charges: Iterable[float]
    treatment_charges: Iterable[float]


def validate_patient_billing(patient: PatientRecord, policy: PaymentPolicy) -> dict[str, list[float]]:
    """Validate demographic fields, charge lists, and policy constraints."""
    if not patient.patient_id.strip() or not patient.name.strip():
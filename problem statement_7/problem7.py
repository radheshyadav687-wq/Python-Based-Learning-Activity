from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP


def round_score(value: Decimal | int | float | str) -> Decimal:
    """Round marks or percentages to two decimal places using half-up rounding."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class SubjectRule:
    """Defines maximum marks and minimum passing marks for a subject."""
    code: str
    name: str
    max_marks: Decimal
    pass_marks: Decimal

    def __post_init__(self) -> None:
        if self.max_marks <= Decimal("0"):
            raise ValueError(f"{self.code}: max_marks must be positive.")
        if not (Decimal("0") <= self.pass_marks <= self.max_marks):
            raise ValueError(f"{self.code}: pass_marks must be between 0 and max_marks.")


@dataclass(frozen=True)
class GracePolicy:
    """
    Grace-mark allocation policy:
    - max_total_grace: Maximum total grace marks allowed across all subjects for a student.
    - max_grace_per_subject: Maximum grace marks that can be awarded to any single subject.
    - max_failed_subjects_eligible: Maximum number of failed subjects eligible for grace rescue.
    - merit_topup_enabled: Optional unused grace allocation to reach next classification,
      strictly capped by subject max_marks and remaining grace pool.
    """
    max_total_grace: Decimal = Decimal("10")
    max_grace_per_subject: Decimal = Decimal("5")
    max_failed_subjects_eligible: int = 2
    allow_classification_boost: bool = False


@dataclass(frozen=True)
class ClassificationRule:
    """Minimum overall percentage required for a classification label (must pass all subjects)."""
    min_percentage: Decimal
    label: str


DEFAULT_CLASSIFICATIONS: list[ClassificationRule] = [
    ClassificationRule(Decimal("75.00"), "FIRST CLASS WITH DISTINCTION"),
    ClassificationRule(Decimal("60.00"), "FIRST CLASS"),
    ClassificationRule(Decimal("50.00"), "SECOND CLASS"),
    ClassificationRule(Decimal("40.00"), "PASS CLASS"),
]


@dataclass
class SubjectResult:
    """Detailed evaluation for a single subject."""
    subject: SubjectRule
    raw_marks: Decimal
    grace_awarded: Decimal
    final_marks: Decimal
    passed_initially: bool
    passed_final: bool
    status: str  # "PASS", "PASS (GRACE)", or "FAIL"


@dataclass
class StudentResultReport:
    """Complete examination result and grace-mark audit for a student."""
    student_id: str
    student_name: str
    exam_session: str
    subject_results: list[SubjectResult]
    raw_total: Decimal
    total_grace_used: Decimal
    final_total: Decimal
    max_total: Decimal
    final_percentage: Decimal
    overall_passed: bool
    classification: str
    remarks: list[str] = field(default_factory=list)


def validate_and_evaluate_student(
    student_id: str,
    student_name: str,
    exam_session: str,
    subjects: list[SubjectRule],
    obtained_marks: dict[str, Decimal],
    grace_policy: GracePolicy = GracePolicy(),
    classifications: list[ClassificationRule] = DEFAULT_CLASSIFICATIONS,
) -> StudentResultReport:
    """
    Validate raw marks, apply grace marks under policy limits without exceeding
    subject max_marks, and determine overall pass status and classification.
    """
    remarks: list[str] = []

    # 1. Validate inputs and identify initial subject shortfalls
    entries: list[dict] = []
    for subj in subjects:
        if subj.code not in obtained_marks:
            raise ValueError(f"Missing marks for subject '{subj.code}' ({subj.name}).")
        raw = round_score(obtained_marks[subj.code])
        if raw < Decimal("0") or raw > subj.max_marks:
            raise ValueError(
                f"Invalid marks ({raw}) for {subj.code}: must be within [0, {subj.max_marks}]."
            )

        shortfall = max(Decimal("0.00"), subj.pass_marks - raw)
        entries.append({
            "subject": subj,
            "raw": raw,
            "shortfall": shortfall,
            "grace": Decimal("0.00"),
            "passed_initially": shortfall == Decimal("0.00"),
        })

    failed_entries = [e for e in entries if not e["passed_initially"]]
    remaining_grace = round_score(grace_policy.max_total_grace)

    # 2. Apply passing grace marks if student is within eligible failed-subject count
    if not failed_entries:
        remarks.append("Passed all subjects outright; no passing grace required.")
    elif len(failed_entries) > grace_policy.max_failed_subjects_eligible:
        remarks.append(
            f"Failed {len(failed_entries)} subjects (exceeds grace eligibility limit of "
            f"{grace_policy.max_failed_subjects_eligible}); no grace marks applied."
        )
    else:
        # Prioritize smallest shortfalls first to maximize subjects rescued
        for entry in sorted(failed_entries, key=lambda item: item["shortfall"]):
            subj: SubjectRule = entry["subject"]
            need = entry["shortfall"]
            room_to_max = subj.max_marks - entry["raw"]
            max_allowed = min(
                grace_policy.max_grace_per_subject,
                remaining_grace,
                room_to_max,
            )
            if need <= max_allowed:
                entry["grace"] = round_score(need)
                remaining_grace = round_score(remaining_grace - entry["grace"])
                remarks.append(
                    f"Awarded {entry['grace']} grace mark(s) in {subj.code} to reach pass mark ({subj.pass_marks})."
                )
            else:
                remarks.append(
                    f"Ineligible for grace rescue in {subj.code}: shortfall {need} exceeds "
                    f"available/allowed grace ({max_allowed})."
                )

    # 3. Build subject-level results enforcing final_marks <= max_marks
    subject_results: list[SubjectResult] = []
    raw_total = Decimal("0.00")
    total_grace_used = Decimal("0.00")
    final_total = Decimal("0.00")
    max_total = Decimal("0.00")

    for entry in entries:
        subj = entry["subject"]
        raw = entry["raw"]
        grace = entry["grace"]
        final_mark = min(subj.max_marks, round_score(raw + grace))
        passed_final = final_mark >= subj.pass_marks

        if entry["passed_initially"]:
            status = "PASS"
        elif passed_final:
            status = "PASS (GRACE)"
        else:
            status = "FAIL"

        raw_total = round_score(raw_total + raw)
        total_grace_used = round_score(total_grace_used + grace)
        final_total = round_score(final_total + final_mark)
        max_total = round_score(max_total + subj.max_marks)

        subject_results.append(
            SubjectResult(
                subject=subj,
                raw_marks=raw,
                grace_awarded=grace,
                final_marks=final_mark,
                passed_initially=entry["passed_initially"],
                passed_final=passed_final,
                status=status,
            )
        )

    # 4. Optional classification boundary boost (strictly capped at each subject's max_marks)
    overall_passed = all(sr.passed_final for sr in subject_results)
    final_percentage = round_score((final_total / max_total) * Decimal("100")) if max_total > 0 else Decimal("0.00")

    if overall_passed and grace_policy.allow_classification_boost and remaining_grace > Decimal("0.00"):
        sorted_tiers = sorted(classifications, key=lambda c: c.min_percentage, reverse=True)
        for tier in sorted_tiers:
            if final_percentage < tier.min_percentage:
                required_total = round_score((tier.min_percentage / Decimal("100")) * max_total)
                deficit = round_score(required_total - final_total)
                if Decimal("0.00") < deficit <= remaining_grace:
                    # Distribute deficit across subjects without exceeding max_marks or per-subject cap
                    available_headroom = sum(
                        min(
                            grace_policy.max_grace_per_subject - sr.grace_awarded,
                            sr.subject.max_marks - sr.final_marks,
                        )
                        for sr in subject_results
                    )
                    if available_headroom >= deficit:
                        to_allocate = deficit
                        for sr in subject_results:
                            if to_allocate <= Decimal("0.00"):
                                break
                            cap_left = min(
                                grace_policy.max_grace_per_subject - sr.grace_awarded,
                                sr.subject.max_marks - sr.final_marks,
                            )
                            add_mark = min(to_allocate, cap_left)
                            if add_mark > Decimal("0.00"):
                                sr.grace_awarded = round_score(sr.grace_awarded + add_mark)
                                sr.final_marks = round_score(sr.final_marks + add_mark)
                                to_allocate = round_score(to_allocate - add_mark)
                        total_grace_used = round_score(total_grace_used + deficit)
                        final_total = round_score(final_total + deficit)
                        final_percentage = round_score((final_total / max_total) * Decimal("100"))
                        remarks.append(
                            f"Awarded {deficit} classification grace mark(s) to attain {tier.label}."
                        )
                        break

    # 5. Determine final classification
    if not overall_passed:
        classification = "FAIL"
    else:
        sorted_tiers = sorted(classifications, key=lambda c: c.min_percentage, reverse=True)
        matched = next((t.label for t in sorted_tiers if final_percentage >= t.min_percentage), "FAIL")
        classification = matched

    return StudentResultReport(
        student_id=student_id,
        student_name=student_name,
        exam_session=exam_session,
        subject_results=subject_results,
        raw_total=raw_total,
        total_grace_used=total_grace_used,
        final_total=final_total,
        max_total=max_total,
        final_percentage=final_percentage,
        overall_passed=overall_passed,
        classification=classification,
        remarks=remarks,
    )


def format_result_sheet(report: StudentResultReport) -> str:
    """Format a clean, printable student mark sheet and grace audit."""
    lines = [
        "=" * 86,
        f"{'EXAMINATION RESULT & GRACE-MARK STATEMENT':^86}",
        "=" * 86,
        f"Student : {report.student_name} ({report.student_id})",
        f"Session : {report.exam_session}",
        "-" * 86,
        f"{'Code':<8} {'Subject':<26} {'Max':>7} {'Pass':>7} {'Raw':>8} {'Grace':>8} {'Final':>8} {'Status':<12}",
        "-" * 86,
    ]

    for sr in report.subject_results:
        s = sr.subject
        lines.append(
            f"{s.code:<8} {s.name[:26]:<26} {s.max_marks:>7.2f} {s.pass_marks:>7.2f} "
            f"{sr.raw_marks:>8.2f} {sr.grace_awarded:>8.2f} {sr.final_marks:>8.2f} {sr.status:<12}"
        )

    lines.extend([
        "-" * 86,
        f"Raw Total     : {report.raw_total:>8.2f} / {report.max_total:.2f}",
        f"Grace Awarded : {report.total_grace_used:>8.2f}",
        f"Final Total   : {report.final_total:>8.2f} / {report.max_total:.2f}  ({report.final_percentage:.2f}%)",
        f"Result        : {'PASS' if report.overall_passed else 'FAIL'}",
        f"Classification: {report.classification}",
        "-" * 86,
        "AUDIT REMARKS:",
    ])

    for r in report.remarks:
        lines.append(f"  * {r}")

    lines.append("=" * 86)
    return "\n".join(lines)


if __name__ == "__main__":
    exam_subjects = [
        SubjectRule("CS301", "Data Structures", Decimal("100"), Decimal("40")),
        SubjectRule("CS302", "Operating Systems", Decimal("100"), Decimal("40")),
        SubjectRule("CS303", "Database Systems", Decimal("100"), Decimal("40")),
        SubjectRule("CS304", "Computer Networks", Decimal("100"), Decimal("40")),
        SubjectRule("CS305", "Software Engineering", Decimal("50"), Decimal("20")),
    ]

    policy = GracePolicy(
        max_total_grace=Decimal("8"),
        max_grace_per_subject=Decimal("5"),
        max_failed_subjects_eligible=2,
        allow_classification_boost=False,
    )

    # Case 1: Rescued by grace marks across two subjects
    student_1 = validate_and_evaluate_student(
        student_id="24CS108",
        student_name="Divya Sharma",
        exam_session="Nov 2026 Semester III",
        subjects=exam_subjects,
        obtained_marks={
            "CS301": Decimal("72"),
            "CS302": Decimal("37"),  # 3 marks short -> rescued
            "CS303": Decimal("68"),
            "CS304": Decimal("36"),  # 4 marks short -> rescued (total grace = 7 <= 8)
            "CS305": Decimal("44"),
        },
        grace_policy=policy,
    )
    print(format_result_sheet(student_1))

    # Case 2: Shortfall exceeds per-subject cap -> cannot be rescued -> FAIL
    student_2 = validate_and_evaluate_student(
        student_id="24CS115",
        student_name="Rohan Verma",
        exam_session="Nov 2026 Semester III",
        subjects=exam_subjects,
        obtained_marks={
            "CS301": Decimal("81"),
            "CS302": Decimal("33"),  # 7 marks short > max_grace_per_subject (5)
            "CS303": Decimal("76"),
            "CS304": Decimal("74"),
            "CS305": Decimal("42"),
        },
        grace_policy=policy,
    )
    print("\n" + format_result_sheet(student_2))
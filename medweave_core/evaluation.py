from __future__ import annotations

import re
from typing import Any

from medweave_core.models import HarmonizedEvent
from medweave_core.utils import clean_patient_id
from medweave_core.utils import clean_text, dates_compatible


LABEL_SYNONYMS: dict[str, set[str]] = {
    "allergy": {"allergy", "allergies", "drug allergy", "medication allergy"},
    "amlodipine": {"amlodipine"},
    "asthma": {"asthma", "bronchial asthma", "acute asthma exacerbation", "asthma exacerbation"},
    "blood pressure": {"blood pressure", "bp"},
    "chest x ray": {"chest x ray", "chest xray", "x ray", "xray", "cxr"},
    "egfr": {"egfr", "estimated glomerular filtration rate"},
    "hba1c": {"hba1c", "hb a1c", "hb a one c", "glycohb", "a1c", "hemoglobin a1c"},
    "hypertension": {"hypertension", "htn", "high blood pressure", "uncontrolled hypertension"},
    "ldl cholesterol": {"ldl cholesterol", "ldl c", "ldl-c", "ldl"},
    "metformin": {"metformin", "metformin hcl"},
    "migraine": {"migraine", "migraines"},
    "peanut allergy": {"peanut allergy"},
    "type 2 diabetes mellitus": {
        "type 2 diabetes mellitus",
        "type 2 diabetes",
        "diabetes mellitus type 2",
        "diabetes type two",
        "diabetes type 2",
        "dm2",
        "t2dm",
    },
}


def split_patient_id_hint(patient_id_hint: str) -> tuple[str | None, str | None]:
    cleaned = clean_text(patient_id_hint)
    if not cleaned:
        return None, None
    match = re.match(r"^(.*)-(\d{4}-\d{2}-\d{2})$", cleaned)
    if match:
        return match.group(1), match.group(2)
    return clean_patient_id(cleaned) or cleaned, None


def _expected_patient_identity(expected: dict[str, Any]) -> tuple[str | None, str | None]:
    patient_id = clean_text(expected.get("patient_id")) or None
    patient_dob = clean_text(expected.get("patient_dob")) or None
    if patient_id:
        return patient_id, patient_dob
    return split_patient_id_hint(clean_text(expected.get("patient_id_hint")))


def _norm_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def _norm_label(value: Any) -> str:
    normalized = _norm_text(value)
    for canonical, aliases in LABEL_SYNONYMS.items():
        if normalized == canonical or normalized in aliases:
            return canonical
    return normalized


def _norm_patient_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _patient_matches(expected: dict[str, Any], actual_event: HarmonizedEvent) -> bool:
    actual = clean_text(actual_event.patient_id).lower()
    if not actual or actual == "unknown":
        actual = ""

    expected_patient_id, expected_dob = _expected_patient_identity(expected)
    patient_hint = clean_text(clean_patient_id(expected_patient_id)).lower()
    if patient_hint and actual == patient_hint:
        return True

    actual_dob = clean_text(actual_event.patient_dob)
    if patient_hint and expected_dob and actual == patient_hint and actual_dob == expected_dob:
        return True

    patient_name = clean_text(expected.get("patient_name")).lower()
    if patient_name:
        name_tokens = _norm_patient_tokens(patient_name)
        actual_tokens = _norm_patient_tokens(actual)
        if name_tokens and name_tokens.issubset(actual_tokens):
            if not expected_dob or not actual_dob or expected_dob == actual_dob:
                return True

    return False


def _value_matches(expected_value: Any, actual_value: Any) -> bool:
    if expected_value is None:
        return True
    if actual_value is None:
        return False

    try:
        return abs(float(expected_value) - float(actual_value)) < 0.001
    except Exception:
        return _norm_text(expected_value) == _norm_text(actual_value)


def _flag_matches(expected_flag: Any, actual_flag: Any) -> bool:
    if expected_flag is None:
        return True
    return _norm_text(expected_flag) == _norm_text(actual_flag)


def _unit_matches(expected_unit: Any, actual_unit: Any) -> bool:
    if expected_unit is None:
        return True
    return _norm_text(expected_unit) == _norm_text(actual_unit)


def _label_matches(expected: dict[str, Any], actual: HarmonizedEvent) -> bool:
    expected_code = clean_text(expected.get("standard_code"))
    if expected_code and expected_code == clean_text(actual.standard_code):
        return True

    expected_label = _norm_label(expected.get("label") or expected.get("should_not_extract"))
    if not expected_label:
        return True

    actual_candidates = {
        _norm_label(actual.label),
        _norm_label(actual.summary),
    }
    if expected_label == "allergy" and actual.category == "allergy":
        return True
    return expected_label in actual_candidates


def event_matches_expected(expected: dict[str, Any], actual: HarmonizedEvent) -> bool:
    if not _patient_matches(expected, actual):
        return False
    if clean_text(expected.get("category")) and expected.get("category") != actual.category:
        return False

    expected_date = expected.get("date")
    expected_precision = expected.get("date_precision", "unknown")
    if expected_date and not dates_compatible(expected_date, expected_precision, actual.date, actual.date_precision):
        return False

    if not _label_matches(expected, actual):
        return False
    if not _value_matches(expected.get("value"), actual.value):
        return False
    if not _unit_matches(expected.get("unit"), actual.unit):
        return False
    if not _flag_matches(expected.get("flag"), actual.flag):
        return False

    return True


def evaluate_against_ground_truth(
    ground_truth: dict[str, Any],
    actual_events: list[HarmonizedEvent],
) -> dict[str, Any]:
    expected_events = list(ground_truth.get("expected_events", []))
    expected_found: list[dict[str, Any]] = []
    expected_missing: list[dict[str, Any]] = []

    for expected in expected_events:
        matches = [event for event in actual_events if event_matches_expected(expected, event)]
        expected_patient_id, expected_patient_dob = _expected_patient_identity(expected)
        if matches:
            expected_found.append(
                {
                    **expected,
                    "patient_id": expected_patient_id,
                    "patient_dob": expected_patient_dob,
                    "matched_patient_id": matches[0].patient_id,
                    "matched_label": matches[0].label,
                    "matched_date": matches[0].date,
                }
            )
        else:
            expected_missing.append(
                {
                    **expected,
                    "patient_id": expected_patient_id,
                    "patient_dob": expected_patient_dob,
                }
            )

    negative_violations: list[dict[str, Any]] = []
    for negative in ground_truth.get("expected_negatives", []):
        prohibited = negative.get("should_not_extract")
        prohibited_labels = prohibited if isinstance(prohibited, list) else [prohibited]
        violations = []
        for event in actual_events:
            if not _patient_matches(negative, event):
                continue
            for label in prohibited_labels:
                if event_matches_expected(
                    {"patient_name": negative.get("patient_name"), "label": label, "category": event.category},
                    event,
                ):
                    violations.append(
                        {
                            "patient_id": event.patient_id,
                            "category": event.category,
                            "label": event.label,
                            "date": event.date,
                        }
                    )
                    break
        if violations:
            negative_violations.append({**negative, "violations": violations})

    actual_patient_ids = sorted({event.patient_id for event in actual_events if clean_text(event.patient_id) and clean_text(event.patient_id) != "unknown"})
    expected_patient_hints = sorted(
        {
            clean_text(_expected_patient_identity(event)[0])
            for event in expected_events
            if clean_text(_expected_patient_identity(event)[0])
        }
    )
    detected_patient_hints = [
        patient_hint
        for patient_hint in expected_patient_hints
        if any(_patient_matches({"patient_id": patient_hint}, event) for event in actual_events)
    ]

    return {
        "notes": ground_truth.get("notes", []),
        "expected_events_total": len(expected_events),
        "expected_events_found": expected_found,
        "expected_events_missing": expected_missing,
        "negative_assertions_violated": negative_violations,
        "patient_ids_detected": {
            "expected": expected_patient_hints,
            "detected": detected_patient_hints,
            "actual_ids": actual_patient_ids,
        },
    }

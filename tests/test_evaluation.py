from __future__ import annotations

from medweave_core.evaluation import evaluate_against_ground_truth, event_matches_expected, split_patient_id_hint
from medweave_core.models import HarmonizedEvent, Provenance


def make_event(**overrides) -> HarmonizedEvent:
    payload = {
        "patient_id": "laine-aava",
        "patient_name": "Aava Laine",
        "patient_dob": "1975-09-21",
        "date": "2022-03-01",
        "date_precision": "month",
        "category": "diagnosis",
        "label": "Hypertension",
        "summary": "Hypertension",
        "standard_code": "38341003",
        "standard_code_system": "SNOMED",
        "value": None,
        "unit": None,
        "flag": None,
        "confidence": 0.9,
        "provenance": [
            Provenance(
                source="test",
                source_file="sample.txt",
                record_id="rec-1",
                patient_id="laine-aava",
                patient_name="Aava Laine",
                patient_dob="1975-09-21",
                raw_text="HTN in early March 2022",
                date="2022-03-01",
                code=None,
                code_system=None,
                value=None,
                unit=None,
            )
        ],
        "conflicts": [],
    }
    payload.update(overrides)
    return HarmonizedEvent(**payload)


def test_event_matches_expected_with_synonym_and_precision():
    expected = {
        "patient_id_hint": "laine-aava-1975-09-21",
        "patient_name": "Aava Laine",
        "date": "2022-03-01",
        "date_precision": "month",
        "category": "diagnosis",
        "label": "Hypertension",
    }
    actual = make_event(label="Hypertension", summary="High blood pressure")

    assert event_matches_expected(expected, actual)


def test_split_patient_id_hint_splits_cleanly():
    assert split_patient_id_hint("laine-aava-1975-09-21") == ("laine-aava", "1975-09-21")


def test_evaluation_flags_negated_false_positive():
    ground_truth = {
        "expected_events": [],
        "expected_negatives": [
            {
                "patient_name": "Aava Laine",
                "statement": "She denies diabetes.",
                "should_not_extract": "Type 2 Diabetes Mellitus",
            }
        ],
    }
    actual_events = [
        make_event(
            label="Type 2 Diabetes Mellitus",
            summary="Type 2 Diabetes Mellitus",
            standard_code="44054006",
            standard_code_system="SNOMED",
        )
    ]

    scorecard = evaluate_against_ground_truth(ground_truth, actual_events)

    assert len(scorecard["negative_assertions_violated"]) == 1
    assert scorecard["negative_assertions_violated"][0]["patient_name"] == "Aava Laine"


def test_evaluation_tracks_found_missing_and_patient_ids():
    ground_truth = {
        "expected_events": [
            {
                "patient_id_hint": "laine-aava-1975-09-21",
                "patient_name": "Aava Laine",
                "date": "2022-03-01",
                "date_precision": "month",
                "category": "diagnosis",
                "label": "Hypertension",
            },
            {
                "patient_id_hint": "nieminen-otto-1962-02-03",
                "patient_name": "Otto Nieminen",
                "date": "2024-06-10",
                "date_precision": "day",
                "category": "lab",
                "label": "HbA1c",
                "value": 8.4,
                "unit": "%",
            },
        ],
        "expected_negatives": [],
    }
    actual_events = [
        make_event(),
        make_event(
            patient_id="nieminen-otto",
            patient_name="Otto Nieminen",
            patient_dob="1962-02-03",
            date="2024-06-10",
            date_precision="day",
            category="lab",
            label="HbA1c",
            summary="HbA1c 8.4%",
            standard_code="4548-4",
            standard_code_system="LOINC",
            value=8.4,
            unit="%",
        ),
    ]

    scorecard = evaluate_against_ground_truth(ground_truth, actual_events)

    assert len(scorecard["expected_events_found"]) == 2
    assert scorecard["expected_events_missing"] == []
    assert scorecard["patient_ids_detected"]["detected"] == ["laine-aava", "nieminen-otto"]


def test_evaluation_output_uses_clean_identity_fields():
    ground_truth = {
        "expected_events": [
            {
                "patient_id_hint": "laine-aava-1975-09-21",
                "patient_name": "Aava Laine",
                "date": "2025-01-01",
                "date_precision": "day",
                "category": "lab",
                "label": "HbA1c",
            }
        ],
        "expected_negatives": [],
    }

    scorecard = evaluate_against_ground_truth(ground_truth, [])
    missing = scorecard["expected_events_missing"][0]

    assert "patient_id_hint" in missing  # backward-compatible internal data
    assert missing["patient_id"] == "laine-aava"
    assert missing["patient_dob"] == "1975-09-21"


def test_missing_events_payload_contains_clean_identity_columns():
    ground_truth = {
        "expected_events": [
            {
                "patient_id": "nieminen-otto",
                "patient_name": "Otto Nieminen",
                "patient_dob": "1962-02-03",
                "date": "2025-01-01",
                "date_precision": "day",
                "category": "lab",
                "label": "HbA1c",
            }
        ],
        "expected_negatives": [],
    }

    scorecard = evaluate_against_ground_truth(ground_truth, [])
    missing = scorecard["expected_events_missing"][0]

    assert "patient_id" in missing
    assert "patient_dob" in missing

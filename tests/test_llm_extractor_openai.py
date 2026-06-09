from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from medweave_core.evaluation import evaluate_against_ground_truth
from medweave_core.harmonizer.llm_extractor_openai import (
    MEDWEAVE_EXTRACTION_SCHEMA,
    MissingOpenAIKeyError,
    OpenAIExtractionError,
    extract_events_from_documents,
    extract_events_from_documents_with_metadata,
)


def stress_test_documents() -> list[dict]:
    return [
        {
            "filename": "llm_free_text_discharge_aava.txt",
            "content": "Aava Laine DOB 21/09/1975. HTN / high blood pressure in early March 2022. Start amlodipine 5 mg once daily on 13/06/2024. She denies diabetes. No known drug allergies.",
            "file_type": "txt",
        },
        {
            "filename": "llm_mixed_patient_notes.txt",
            "content": "Otto Nieminen DOB 03-02-1962 HbA1c 8.4% HIGH on 10 June 2024. Leena Saarinen DOB 11.12.1988 Peanut allergy documented 02/04/2020. No diabetes, no hypertension.",
            "file_type": "txt",
        },
    ]


def mocked_extraction_response() -> dict:
    return {
        "events": [
            {
                "patient_id": "laine-aava-1975-09-21",
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
                "confidence": 0.93,
                "provenance": [
                    {
                        "source": "llm_free_text_discharge_aava.txt",
                        "source_file": "llm_free_text_discharge_aava.txt",
                        "record_id": "section-htn",
                        "patient_id": "laine-aava-1975-09-21",
                        "patient_name": "Aava Laine",
                        "raw_text": "high blood pressure in early March 2022",
                        "date": "early March 2022",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            },
            {
                "patient_id": "laine-aava-1975-09-21",
                "patient_name": "Aava Laine",
                "patient_dob": "1975-09-21",
                "date": None,
                "date_precision": "unknown",
                "category": "medication",
                "label": "Salbutamol",
                "summary": "Uses salbutamol rescue inhaler as needed.",
                "standard_code": None,
                "standard_code_system": None,
                "value": 100,
                "unit": "mcg",
                "flag": None,
                "confidence": 0.9,
                "provenance": [
                    {
                        "source": "llm_free_text_discharge_aava.txt",
                        "source_file": "llm_free_text_discharge_aava.txt",
                        "record_id": "section-salbutamol",
                        "patient_id": "laine-aava-1975-09-21",
                        "patient_name": "Aava Laine",
                        "patient_dob": "1975-09-21",
                        "raw_text": "Aava has asthma diagnosed around May 2019. She uses a blue rescue inhaler (Salbutamol 100 mcg), usually two puffs when needed.",
                        "date": "May 2019",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            },
            {
                "patient_id": "laine-aava-1975-09-21",
                "patient_name": "Aava Laine",
                "patient_dob": "1975-09-21",
                "date": "2024-06-13",
                "date_precision": "day",
                "category": "medication",
                "label": "Amlodipine",
                "summary": "Amlodipine 5 mg started",
                "standard_code": None,
                "standard_code_system": None,
                "value": 5,
                "unit": "mg",
                "flag": None,
                "confidence": 0.92,
                "provenance": [
                    {
                        "source": "llm_free_text_discharge_aava.txt",
                        "source_file": "llm_free_text_discharge_aava.txt",
                        "record_id": "section-med",
                        "patient_id": "laine-aava-1975-09-21",
                        "patient_name": "Aava Laine",
                        "raw_text": "Start amlodipine 5 mg once daily on 13/06/2024",
                        "date": "13/06/2024",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            },
            {
                "patient_id": "nieminen-otto-1962-02-03",
                "patient_name": "Otto Nieminen",
                "patient_dob": "1962-02-03",
                "date": "2024-06-10",
                "date_precision": "day",
                "category": "lab",
                "label": "HbA1c",
                "summary": "HbA1c 8.4%",
                "standard_code": "4548-4",
                "standard_code_system": "LOINC",
                "value": 8.4,
                "unit": "%",
                "flag": "H",
                "confidence": 0.95,
                "provenance": [
                    {
                        "source": "llm_mixed_patient_notes.txt",
                        "source_file": "llm_mixed_patient_notes.txt",
                        "record_id": "section-hba1c",
                        "patient_id": "nieminen-otto-1962-02-03",
                        "patient_name": "Otto Nieminen",
                        "raw_text": "HbA1c 8.4% HIGH on 10 June 2024",
                        "date": "10 June 2024",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            },
            {
                "patient_id": "saarinen-leena-1988-12-11",
                "patient_name": "Leena Saarinen",
                "patient_dob": "1988-12-11",
                "date": "2020-04-02",
                "date_precision": "day",
                "category": "allergy",
                "label": "Peanut allergy",
                "summary": "Peanut allergy",
                "standard_code": "91936005",
                "standard_code_system": "SNOMED",
                "value": None,
                "unit": None,
                "flag": "HIGH",
                "confidence": 0.94,
                "provenance": [
                    {
                        "source": "llm_mixed_patient_notes.txt",
                        "source_file": "llm_mixed_patient_notes.txt",
                        "record_id": "section-allergy",
                        "patient_id": "saarinen-leena-1988-12-11",
                        "patient_name": "Leena Saarinen",
                        "raw_text": "Peanut allergy documented 02/04/2020",
                        "date": "02/04/2020",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            },
        ],
        "extraction_notes": ["Synthetic mocked extraction response."],
    }


def assert_schema_required_matches_properties(schema: dict):
    schema_type = schema.get("type")
    if schema_type == "object":
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        assert set(properties.keys()) == required
        assert schema.get("additionalProperties") is False

        for prop in properties.values():
            assert_schema_required_matches_properties(prop)

    if schema_type == "array":
        assert_schema_required_matches_properties(schema["items"])


def test_openai_schema_is_valid_for_structured_outputs():
    assert_schema_required_matches_properties(MEDWEAVE_EXTRACTION_SCHEMA)


def test_extract_events_from_documents_validates_mocked_response(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text=json.dumps(mocked_extraction_response()))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    result = extract_events_from_documents_with_metadata(stress_test_documents())

    assert len(result.events) == 5
    assert result.events[0].patient_id == "laine-aava"
    assert "denies diabetes" in captured["input"][1]["content"][0]["text"]
    assert captured["model"] == "gpt-4.1-mini"
    assert result.raw_response is not None
    assert result.validation_errors == []


def test_extract_events_from_documents_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai.load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(MissingOpenAIKeyError):
        extract_events_from_documents(stress_test_documents())


def test_extract_events_from_documents_wraps_sdk_errors(monkeypatch: pytest.MonkeyPatch):
    class FakeResponses:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    with pytest.raises(OpenAIExtractionError, match="OpenAI extraction failed"):
        extract_events_from_documents(stress_test_documents())


def test_stress_test_expected_entities_are_present_without_negated_false_positives(monkeypatch: pytest.MonkeyPatch):
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps(mocked_extraction_response()))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    events = extract_events_from_documents(stress_test_documents())
    labels_by_patient = {(event.patient_id, event.label) for event in events}

    assert ("laine-aava", "Hypertension") in labels_by_patient
    assert ("laine-aava", "Salbutamol") in labels_by_patient
    assert ("laine-aava", "Amlodipine") in labels_by_patient
    assert ("nieminen-otto", "HbA1c") in labels_by_patient
    assert ("saarinen-leena", "Peanut allergy") in labels_by_patient
    assert ("laine-aava", "Type 2 Diabetes Mellitus") not in labels_by_patient
    assert ("saarinen-leena", "Type 2 Diabetes Mellitus") not in labels_by_patient
    assert ("saarinen-leena", "Hypertension") not in labels_by_patient


def test_mocked_extraction_scores_against_ground_truth(monkeypatch: pytest.MonkeyPatch):
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps(mocked_extraction_response()))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    events = extract_events_from_documents(stress_test_documents())
    ground_truth = {
        "expected_events": [
            {"patient_id_hint": "laine-aava-1975-09-21", "patient_name": "Aava Laine", "date": "2022-03-01", "date_precision": "month", "category": "diagnosis", "label": "Hypertension"},
            {"patient_id_hint": "laine-aava-1975-09-21", "patient_name": "Aava Laine", "date": "2024-06-13", "date_precision": "day", "category": "medication", "label": "Amlodipine", "value": 5, "unit": "mg"},
            {"patient_id_hint": "nieminen-otto-1962-02-03", "patient_name": "Otto Nieminen", "date": "2024-06-10", "date_precision": "day", "category": "lab", "label": "HbA1c", "value": 8.4, "unit": "%"},
            {"patient_id_hint": "saarinen-leena-1988-12-11", "patient_name": "Leena Saarinen", "date": "2020-04-02", "date_precision": "day", "category": "allergy", "label": "Peanut allergy"},
        ],
        "expected_negatives": [
            {"patient_name": "Aava Laine", "statement": "She denies diabetes.", "should_not_extract": "Type 2 Diabetes Mellitus"},
            {"patient_name": "Leena Saarinen", "statement": "No diabetes, no hypertension.", "should_not_extract": ["Type 2 Diabetes Mellitus", "Hypertension"]},
        ],
    }

    scorecard = evaluate_against_ground_truth(ground_truth, events)

    assert len(scorecard["expected_events_found"]) == 4
    assert scorecard["expected_events_missing"] == []
    assert scorecard["negative_assertions_violated"] == []


def test_salbutamol_infers_contextual_history_date(monkeypatch: pytest.MonkeyPatch):
    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps(mocked_extraction_response()))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    events = extract_events_from_documents(
        [
            {
                "filename": "llm_free_text_discharge_aava.txt",
                "content": (
                    "Aava has asthma diagnosed around May 2019. She uses a blue rescue inhaler "
                    "(Salbutamol 100 mcg), usually two puffs when needed."
                ),
                "file_type": "txt",
            }
        ]
    )

    salbutamol = next(event for event in events if event.label == "Salbutamol")
    assert salbutamol.patient_id == "laine-aava"
    assert salbutamol.patient_dob == "1975-09-21"
    assert salbutamol.category == "medication"
    assert salbutamol.date == "2019-05-01"
    assert salbutamol.date_precision == "month"

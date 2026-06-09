from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from medweave_core.harmonizer.llm_openai import (
    MissingOpenAIKeyError,
    OpenAIReviewError,
    build_openai_payload,
    openai_review_events,
)
from medweave_core.models import RawEvent


def make_raw_event(**overrides) -> RawEvent:
    payload = {
        "id": "evt-1",
        "patient_id": "P1",
        "source": "test_source",
        "source_file": "test.json",
        "category": "lab",
        "raw_text": "HbA1c 7.4%",
        "date": "2024-01-10",
        "date_precision": "day",
        "code": "4548-4",
        "code_system": "LOINC",
        "value": 7.4,
        "unit": "%",
    }
    payload.update(overrides)
    return RawEvent(**payload)


def test_build_openai_payload_minimizes_fields():
    raw_event = make_raw_event(metadata={"secret": "ignore-me"}, provider="Dr X", facility="Clinic A")

    payload = build_openai_payload([raw_event])

    assert payload == [
        {
            "patient_id": "P1",
            "category": "lab",
            "raw_text": "HbA1c 7.4%",
            "date": "2024-01-10",
            "date_precision": "day",
            "code": "4548-4",
            "code_system": "LOINC",
            "value": 7.4,
            "unit": "%",
            "source": "test_source",
            "source_file": "test.json",
            "record_id": "evt-1",
        }
    ]


def test_openai_review_events_validates_mocked_response(monkeypatch: pytest.MonkeyPatch):
    raw_event = make_raw_event(category="other", code=None, code_system=None, raw_text="Likely hypertension noted in free-text summary")
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            response_json = {
                "events": [
                    {
                        "patient_id": "P1",
                        "date": "2024-01-10",
                        "date_precision": "day",
                        "category": "diagnosis",
                        "label": "Hypertension",
                        "summary": "Hypertension",
                        "standard_code": "38341003",
                        "standard_code_system": "SNOMED",
                        "value": None,
                        "unit": None,
                        "flag": None,
                        "confidence": 0.81,
                        "provenance": [
                            {
                                "source": "test_source",
                                "source_file": "test.json",
                                "record_id": "evt-1",
                                "patient_id": "P1",
                                "raw_text": "Likely hypertension noted in free-text summary",
                                "date": "2024-01-10",
                                "code": None,
                                "code_system": None,
                                "value": None,
                                "unit": None,
                            }
                        ],
                        "conflicts": [],
                    }
                ],
                "conflicts": [
                    {
                        "field": "coding",
                        "values": ["free text only"],
                        "explanation": "Mapped from narrative text and should be clinician-reviewed.",
                    }
                ],
                "notes": ["Reviewed one ambiguous free-text event."],
            }
            return SimpleNamespace(output_text=json.dumps(response_json))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr("medweave_core.harmonizer.llm_openai._make_client", lambda: FakeClient())

    result = openai_review_events([raw_event])

    assert len(result.events) == 1
    assert result.events[0].label == "Hypertension"
    assert result.events[0].provenance[0].record_id == "evt-1"
    assert result.conflicts[0].field == "coding"
    assert result.notes == ["Reviewed one ambiguous free-text event."]
    assert captured["model"] == "gpt-5.4-mini"
    submitted_text = captured["input"][1]["content"][0]["text"]
    assert "record_id" in submitted_text
    assert "provider" not in submitted_text
    assert "facility" not in submitted_text
    assert "metadata" not in submitted_text


def test_openai_review_events_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("medweave_core.harmonizer.llm_openai.load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    with pytest.raises(MissingOpenAIKeyError):
        openai_review_events([make_raw_event()])


def test_openai_review_events_wraps_sdk_errors(monkeypatch: pytest.MonkeyPatch):
    class FakeResponses:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_openai._make_client", lambda: FakeClient())

    with pytest.raises(OpenAIReviewError, match="OpenAI review failed"):
        openai_review_events([make_raw_event()])

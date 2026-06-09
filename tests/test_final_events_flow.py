from __future__ import annotations

from pathlib import Path

from medweave_core.evaluation import evaluate_against_ground_truth
from medweave_core.harmonizer.llm_extractor_openai import extract_events_from_documents
from medweave_core.harmonizer.rules import harmonize_events
from medweave_core.models import HarmonizedEvent, Provenance
from medweave_core.parsers.autodetect import parse_uploaded_file
from medweave_core.timeline.builder import to_dataframe


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
LLM_SAMPLES = ROOT / "data" / "medweave_llm_test_samples"


def test_classic_single_patient_sample_still_works():
    raw = parse_uploaded_file("hospital_a_fhir.json", (SAMPLES / "hospital_a_fhir.json").read_bytes())
    final_events, _ = harmonize_events(raw)

    assert final_events
    assert any(event.patient_id for event in final_events)
    assert any(event.patient_name for event in final_events)
    assert any(event.patient_dob for event in final_events)
    assert all("-1968-" not in (event.patient_id or "") for event in final_events)


def test_classic_multi_patient_sample_still_works():
    raw = []
    for filename in ["hospital_a_fhir.json", "clinic_b_export.json", "lab_pharmacy_export.csv"]:
        raw.extend(parse_uploaded_file(filename, (SAMPLES / filename).read_bytes()))

    final_events, _ = harmonize_events(raw)

    assert final_events
    assert len({event.patient_id for event in final_events if event.patient_id}) >= 1


def test_to_dataframe_contains_patient_id_and_patient_dob():
    final_events = [
        HarmonizedEvent(
            patient_id="laine-aava",
            patient_name="Aava Laine",
            patient_dob="1975-09-21",
            date="2024-06-13",
            date_precision="day",
            category="medication",
            label="Amlodipine",
            summary="Amlodipine 5 mg started",
            standard_code=None,
            standard_code_system=None,
            value=5,
            unit="mg",
            flag=None,
            confidence=0.95,
            provenance=[
                Provenance(
                    source="demo",
                    source_file="demo.txt",
                    record_id="rec-1",
                    patient_id="laine-aava",
                    patient_name="Aava Laine",
                    patient_dob="1975-09-21",
                    raw_text="Amlodipine 5 mg",
                    date="2024-06-13",
                    code=None,
                    code_system=None,
                    value=None,
                    unit=None,
                )
            ],
            conflicts=[],
        )
    ]

    df = to_dataframe(final_events)

    assert list(df.columns) == [
        "patient_id",
        "patient_name",
        "patient_dob",
        "date",
        "precision",
        "category",
        "event",
        "standard_code",
        "code_system",
        "value",
        "unit",
        "flag",
        "sources",
        "source_count",
        "confidence",
        "conflicts",
    ]
    assert df.iloc[0]["patient_id"] == "laine-aava"
    assert df.iloc[0]["patient_name"] == "Aava Laine"
    assert df.iloc[0]["patient_dob"] == "1975-09-21"


def test_timeline_export_contains_patient_dob():
    final_events = [
        HarmonizedEvent(
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
            flag="H",
            confidence=0.95,
            provenance=[],
            conflicts=[],
        )
    ]

    csv_output = to_dataframe(final_events).to_csv(index=False)

    assert "patient_dob" in csv_output
    assert "patient_name" in csv_output
    assert "1962-02-03" in csv_output


def test_no_duplicate_openai_review_toggle_exists_in_app():
    app_text = (ROOT / "app.py").read_text()

    assert "Use OpenAI-assisted review" not in app_text
    assert "Use LLM extraction for messy/free-text files" in app_text


def test_llm_evaluation_uses_final_events():
    app_text = (ROOT / "app.py").read_text()

    assert "evaluate_against_ground_truth(ground_truth, final_events)" in app_text


def test_ui_source_does_not_display_patient_id_hint():
    app_text = (ROOT / "app.py").read_text()

    assert '"patient_id_hint"' not in app_text
    assert "`patient_id_hint`" not in app_text
    assert "Show developer evaluation diagnostics" in app_text


def test_llm_stress_test_files_can_populate_final_events_via_llm_path(monkeypatch):
    from types import SimpleNamespace
    import json

    from medweave_core.harmonizer.llm_extractor_openai import extract_events_from_documents

    response_json = {
        "events": [
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
                "confidence": 0.95,
                "provenance": [
                    {
                        "source": "llm_free_text_discharge_aava.txt",
                        "source_file": "llm_free_text_discharge_aava.txt",
                        "record_id": "section-med",
                        "patient_id": "laine-aava-1975-09-21",
                        "patient_name": "Aava Laine",
                        "patient_dob": "1975-09-21",
                        "raw_text": "Start amlodipine 5 mg once daily",
                        "date": "13/06/2024",
                        "code": None,
                        "code_system": None,
                        "value": None,
                        "unit": None,
                    }
                ],
                "conflicts": [],
            }
        ],
        "extraction_notes": [],
    }

    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text=json.dumps(response_json))

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("medweave_core.harmonizer.llm_extractor_openai._make_client", lambda: FakeClient())

    docs = [
        {
            "filename": "llm_free_text_discharge_aava.txt",
            "content": (LLM_SAMPLES / "llm_free_text_discharge_aava.txt").read_text(),
            "file_type": "txt",
        }
    ]
    final_events = extract_events_from_documents(docs)

    assert final_events
    assert final_events[0].patient_id == "laine-aava"
    assert final_events[0].patient_name == "Aava Laine"
    assert final_events[0].patient_dob == "1975-09-21"

from pathlib import Path
import pandas as pd

from medweave_core.parsers.autodetect import parse_uploaded_file
from medweave_core.harmonizer.rules import harmonize_events
from medweave_core.parsers.generic import dataframe_to_events


SAMPLES = Path("data/samples")


def test_fhir_sample_parses_with_patient_ids():
    warnings = []
    raw = parse_uploaded_file("hospital_a_fhir.json", (SAMPLES / "hospital_a_fhir.json").read_bytes(), warnings=warnings)

    assert raw
    assert not warnings
    assert all(r.patient_id for r in raw)
    assert {r.category for r in raw} >= {"diagnosis", "medication", "lab", "vitals", "encounter", "procedure"}


def test_clinic_b_sample_parses_with_patient_ids():
    warnings = []
    raw = parse_uploaded_file("clinic_b_export.json", (SAMPLES / "clinic_b_export.json").read_bytes(), warnings=warnings)

    assert raw
    assert not warnings
    assert all(r.patient_id for r in raw)
    assert {r.category for r in raw} >= {"diagnosis", "medication", "lab", "encounter"}


def test_csv_sample_parses_with_patient_ids():
    warnings = []
    raw = parse_uploaded_file("lab_pharmacy_export.csv", (SAMPLES / "lab_pharmacy_export.csv").read_bytes(), warnings=warnings)

    assert raw
    assert not warnings
    assert all(r.patient_id for r in raw)
    assert {r.category for r in raw} >= {"diagnosis", "medication", "lab", "encounter", "allergy", "procedure"}


def test_sample_files_parse_and_harmonize():
    files = [
        SAMPLES / "hospital_a_fhir.json",
        SAMPLES / "clinic_b_export.json",
        SAMPLES / "lab_pharmacy_export.csv",
    ]
    raw = []
    for p in files:
        raw.extend(parse_uploaded_file(p.name, p.read_bytes()))

    assert len(raw) >= 25
    assert all(r.patient_id for r in raw if r.source_file in {"hospital_a_fhir.json", "clinic_b_export.json", "lab_pharmacy_export.csv"})

    events, _ = harmonize_events(raw)
    labels = {e.label for e in events}

    assert "Hypertension" in labels
    assert "Type 2 Diabetes Mellitus" in labels
    assert "Dyslipidemia" in labels
    assert "HbA1c" in labels

    hba1c_2024 = [e for e in events if e.label == "HbA1c" and e.date == "2024-01-10"]
    assert hba1c_2024
    assert len(hba1c_2024[0].provenance) == 3
    assert hba1c_2024[0].patient_id


def test_generic_flat_csv_parses_flexible_columns():
    content = b"""mrn,event_date,type,text,loinc,result,unit\nP1,2024-05-01,lab,HbA1c,4548-4,7.1,%\n"""
    raw = parse_uploaded_file("generic.csv", content)

    assert len(raw) == 1
    assert raw[0].patient_id == "P1"
    assert raw[0].category == "lab"
    assert raw[0].code == "4548-4"
    assert raw[0].value == 7.1


def test_generic_csv_multi_patient_does_not_merge_across_patients():
    df = pd.DataFrame([
        {"patient_id": "P1", "date": "2024-01-01", "event_type": "diagnosis", "description": "HTN", "code": "38341003", "code_system": "SNOMED"},
        {"patient_id": "P2", "date": "2024-01-01", "event_type": "diagnosis", "description": "HTN", "code": "38341003", "code_system": "SNOMED"},
    ])
    raw = dataframe_to_events(df, source="test")
    events, _ = harmonize_events(raw)
    htn = [e for e in events if e.label == "Hypertension"]
    assert len(htn) == 2
    assert {e.patient_id for e in htn} == {"P1", "P2"}


def test_generic_json_record_parses():
    content = b'''[
      {"patient_id":"P1","date":"2024-05-01","event_type":"lab","test":"HbA1c","result":"7.1","unit":"%"},
      {"patient_id":"P1","date":"2024-05-02","event_type":"medication","name":"Metformin 500mg"}
    ]'''
    raw = parse_uploaded_file("generic.json", content)
    assert len(raw) == 2
    assert raw[0].patient_id == "P1"
    events, _ = harmonize_events(raw)
    assert {e.label for e in events} >= {"HbA1c", "Metformin"}


def test_generic_nested_json_parses_records_with_inherited_patient():
    content = b'''{
      "patient": {"mrn": "P9"},
      "events": [
        {"event_date": "2024-05-01", "type": "diagnosis", "description": "Hypertension", "snomed_code": "38341003"},
        {"collected": "2024-05-02", "category": "lab", "test": "HbA1c", "result": "7.4", "unit": "%", "loinc": "4548-4"}
      ]
    }'''
    raw = parse_uploaded_file("nested.json", content)

    assert len(raw) == 2
    assert {r.patient_id for r in raw} == {"P9"}
    assert {r.category for r in raw} == {"diagnosis", "lab"}


def test_generic_csv_aliases_handle_llm_stress_fields():
    content = b"""who_is_this,born,approx_when,thing_seen,kind_of_thing,extra_context,number,units-ish,source_note_id
Aava Laine,1975-09-21,early March 2022,HTN / high blood pressure,problem,clinic note says BP repeatedly elevated,,,MCSV-001
"""
    raw = parse_uploaded_file("llm_messy_legacy_csv.csv", content)

    assert len(raw) == 1
    assert raw[0].patient_id == "laine-aava"
    assert raw[0].patient_name == "Aava Laine"
    assert raw[0].patient_dob == "1975-09-21"
    assert raw[0].category == "diagnosis"
    assert raw[0].date == "2022-03-01"
    assert raw[0].date_precision == "month"
    assert raw[0].raw_text == "HTN / high blood pressure"
    assert raw[0].id == "MCSV-001"


def test_nested_json_child_records_inherit_parent_patient_context():
    content = b'''{
      "person": {
        "fullName": "Aava Laine",
        "birth": "1975/09/21",
        "legacyNo": "NW-AAVA-1"
      },
      "items": [
        {"kind": "dx-ish", "when_text": "May 2019", "clinical_phrase": "bronchial asthma"}
      ]
    }'''
    raw = parse_uploaded_file("nested_llm.json", content)

    assert len(raw) == 1
    assert raw[0].patient_id == "laine-aava"
    assert raw[0].patient_name == "Aava Laine"
    assert raw[0].patient_dob == "1975-09-21"
    assert raw[0].metadata["source_patient_id"] == "NW-AAVA-1"

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from medweave_core.models import RawEvent
from medweave_core.parsers.generic import infer_patient_dob
from medweave_core.utils import clean_patient_id, clean_text, compact_dict, first_present, make_patient_id_from_name, normalize_date, stable_id


PATIENT_ID_KEYS = [
    "patient_id", "patientid", "patient", "patient_local_id", "patient_identifier",
    "mrn", "medical_record_number", "subject", "subject_id", "person_id", "local_id",
    "local_mrn", "legacy_id", "legacyNo", "legacy_no", "source_patient_id", "identifier",
]
PATIENT_NAME_KEYS = ["who_is_this", "patient_name", "fullName", "full_name", "person_name", "name", "Patient", "PATIENT"]
DATE_KEYS = [
    "date", "event_date", "start_date", "onset", "onset_date", "onsetDateTime",
    "recordedDate", "effectiveDateTime", "authoredOn", "collected", "result_date",
    "performedDateTime", "timestamp", "time", "first_noted",
]
TEXT_KEYS = [
    "description", "display", "text", "raw_text", "name", "test", "medication", "medication_name",
    "diagnosis", "condition", "problem", "procedure", "summary", "title", "chief_complaint", "notes", "note",
]
CODE_KEYS = ["code", "snomed_code", "icd10", "icd_10", "loinc", "rxnorm", "standard_code"]
CODE_SYSTEM_KEYS = ["code_system", "coding_system", "system", "terminology", "standard_code_system"]
VALUE_KEYS = ["value", "result", "result_value", "measurement", "dose", "quantity"]
UNIT_KEYS = ["unit", "units", "dose_unit", "value_unit"]
FLAG_KEYS = ["flag", "abnormal_flag", "status", "clinical_status", "active"]
PROVIDER_KEYS = ["provider", "prescriber", "clinician", "doctor"]
FACILITY_KEYS = ["facility", "source_facility", "site", "organization"]
TYPE_KEYS = ["record_type", "type", "category", "event_type", "resourceType", "section"]


CATEGORY_MAP = {
    "problem": "diagnosis",
    "problems": "diagnosis",
    "condition": "diagnosis",
    "conditions": "diagnosis",
    "diagnosis": "diagnosis",
    "diagnoses": "diagnosis",
    "dx": "diagnosis",
    "med": "medication",
    "medication": "medication",
    "medications": "medication",
    "medicationrequest": "medication",
    "prescription": "medication",
    "drug": "medication",
    "lab": "lab",
    "labs": "lab",
    "laboratory": "lab",
    "lab_results": "lab",
    "observation": "lab",
    "vital": "vitals",
    "vitals": "vitals",
    "vital_signs": "vitals",
    "blood_pressure": "vitals",
    "procedure": "procedure",
    "procedures": "procedure",
    "imaging": "imaging",
    "radiology": "imaging",
    "encounter": "encounter",
    "encounters": "encounter",
    "visit": "encounter",
    "visits": "encounter",
    "appointment": "encounter",
    "allergy": "allergy",
    "allergies": "allergy",
}


def _norm_key(value: Any) -> str:
    return clean_text(value).lower().replace(" ", "_").replace("-", "_")


def infer_category(record: dict[str, Any], section: str | None = None) -> str:
    candidates = []
    if section:
        candidates.append(section)
    for key in TYPE_KEYS:
        value = first_present(record, [key])
        if value:
            candidates.append(value)
    for c in candidates:
        normalized = _norm_key(c)
        if normalized in CATEGORY_MAP:
            return CATEGORY_MAP[normalized]
        # Common mixed values like "LAB_RESULT" or "patient_condition".
        for token, category in CATEGORY_MAP.items():
            if token in normalized:
                return category
    return "other"


def infer_patient_id(record: dict[str, Any], default: str | None = None) -> str | None:
    value = first_present(record, PATIENT_ID_KEYS, default=default)
    if isinstance(value, dict):
        raw = clean_text(value.get("reference") or value.get("id") or value.get("value")) or default
        return clean_patient_id(raw) or raw
    text = clean_text(value)
    if text.startswith("Patient/"):
        text = text.split("/", 1)[1]
    return clean_patient_id(text) or text or default


def infer_patient_name(record: dict[str, Any], default: str | None = None) -> str | None:
    first = clean_text(first_present(record, ["first_name", "given", "given_name", "forename"]))
    last = clean_text(first_present(record, ["last_name", "family", "family_name", "surname"]))
    if first and last:
        return clean_text(f"{first} {last}") or default
    value = first_present(record, PATIENT_NAME_KEYS, default=default)
    if isinstance(value, dict):
        return clean_text(value.get("text") or value.get("display")) or default
    return clean_text(value) or default


def record_to_raw_event(
    record: dict[str, Any],
    *,
    section: str | None,
    source: str,
    source_file: str | None,
    default_patient_id: str | None = None,
    default_patient_name: str | None = None,
    row_number: int | None = None,
) -> RawEvent | None:
    patient_id = infer_patient_id(record, default_patient_id)
    patient_name = infer_patient_name(record, default_patient_name)
    if not patient_id and patient_name:
        family_first = bool(first_present(record, ["patient_name", "name"]))
        patient_id = make_patient_id_from_name(patient_name, family_first=family_first)
    category = infer_category(record, section=section)
    date, precision = normalize_date(first_present(record, DATE_KEYS))
    patient_dob = infer_patient_dob(record)

    raw_text = clean_text(first_present(record, TEXT_KEYS))
    code = clean_text(first_present(record, CODE_KEYS)) or None
    code_system = clean_text(first_present(record, CODE_SYSTEM_KEYS)) or None
    value = first_present(record, VALUE_KEYS)
    unit = clean_text(first_present(record, UNIT_KEYS)) or None
    flag = clean_text(first_present(record, FLAG_KEYS)) or None
    provider = clean_text(first_present(record, PROVIDER_KEYS)) or None
    facility = clean_text(first_present(record, FACILITY_KEYS)) or None

    # If there is no obvious text field, synthesize a useful label from the record.
    if not raw_text:
        simple = [f"{k}: {v}" for k, v in record.items() if not isinstance(v, (dict, list)) and clean_text(v)]
        raw_text = "; ".join(simple[:6])

    if not raw_text and not code and value is None:
        return None

    rid = clean_text(first_present(record, ["record_id", "id", "event_id", "problem_id", "med_id", "visit_id"]))
    if not rid:
        rid = stable_id(source_file or source, section, row_number, patient_id, date, raw_text)

    metadata = compact_dict({
        "section": section,
        "original_category": first_present(record, TYPE_KEYS),
        "all_fields": {k: v for k, v in record.items() if not isinstance(v, (dict, list))},
    })

    return RawEvent(
        id=rid,
        source=source,
        source_file=source_file,
        patient_id=patient_id,
        patient_name=patient_name,
        patient_dob=patient_dob,
        category=category,  # type: ignore[arg-type]
        raw_text=raw_text,
        date=date,
        date_precision=precision,  # type: ignore[arg-type]
        code=code,
        code_system=code_system,
        value=value,
        unit=unit,
        flag=flag,
        provider=provider,
        facility=facility,
        metadata=metadata,
    )


def parse_flat_dataframe(df: pd.DataFrame, source_file: str | None = None, source: str | None = None) -> list[RawEvent]:
    source = source or clean_text(source_file) or "Flat CSV export"
    events: list[RawEvent] = []
    for idx, row in df.iterrows():
        record = {str(k): v for k, v in row.to_dict().items()}
        event = record_to_raw_event(
            record,
            section=clean_text(record.get("record_type") or record.get("category")) or "csv_row",
            source=source,
            source_file=source_file,
            row_number=int(idx),
        )
        if event and event.category != "demographics":
            events.append(event)
    return events


def _walk_json_records(data: Any, section: str | None = None) -> Iterable[tuple[str | None, dict[str, Any]]]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield section, item
            else:
                yield section, {"value": item, "description": clean_text(item)}
    elif isinstance(data, dict):
        # A dict with several scalar fields can itself be a record.
        scalar_count = sum(1 for v in data.values() if not isinstance(v, (dict, list)))
        if scalar_count >= 2 and section not in {"patient", "export_meta"}:
            yield section, data
        for key, value in data.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        yield key, item
                    else:
                        yield key, {"value": item, "description": clean_text(item)}
            elif isinstance(value, dict) and key not in {"patient", "export_meta"}:
                yield from _walk_json_records(value, section=key)


def parse_generic_json(data: Any, source_file: str | None = None) -> list[RawEvent]:
    source = "Generic JSON export"
    default_patient_id = None
    default_patient_name = None

    if isinstance(data, dict):
        meta = data.get("export_meta") or data.get("meta") or {}
        source = clean_text(meta.get("source_system") or meta.get("source") or data.get("source_system")) or source
        patient = data.get("patient") or data.get("demographics") or {}
        if isinstance(patient, dict):
            default_patient_id = clean_text(
                patient.get("patient_id")
                or patient.get("patient_local_id")
                or (meta.get("patient_local_id") if isinstance(meta, dict) else None)
                or patient.get("id")
            ) or None
            first = clean_text(patient.get("first_name"))
            last = clean_text(patient.get("last_name"))
            default_patient_name = clean_text(patient.get("name") or f"{first} {last}") or None

    events: list[RawEvent] = []
    for i, (section, record) in enumerate(_walk_json_records(data)):
        event = record_to_raw_event(
            record,
            section=section,
            source=source,
            source_file=source_file,
            default_patient_id=default_patient_id,
            default_patient_name=default_patient_name,
            row_number=i,
        )
        if event and event.category != "demographics":
            events.append(event)
    return events

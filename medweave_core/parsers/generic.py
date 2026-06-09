from __future__ import annotations

from typing import Any
import re
import pandas as pd

from medweave_core.models import RawEvent
from medweave_core.utils import clean_text, clean_patient_id, first_present, make_patient_id_from_name, normalize_date, stable_id


UNKNOWN_PATIENT_ID = "unknown"


def _extract_patient_identifier(value: Any) -> str:
    if isinstance(value, dict):
        nested = clean_text(first_present(value, ["reference", "id", "value", "patient_id", "mrn", "legacyNo", "legacy_id", "legacy_no", "identifier"]))
        if nested:
            return nested

        identifier = value.get("identifier")
        if isinstance(identifier, list):
            for item in identifier:
                nested = _extract_patient_identifier(item)
                if nested:
                    return nested
        elif identifier:
            nested = _extract_patient_identifier(identifier)
            if nested:
                return nested
        return ""

    if isinstance(value, list):
        for item in value:
            nested = _extract_patient_identifier(item)
            if nested:
                return nested
        return ""

    return clean_text(value)


def _extract_name_text(value: Any) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("fullName") or value.get("display") or value.get("text"))
    return clean_text(value)


def canonical_patient_id_from_demographics(record: dict[str, Any]) -> str | None:
    first = clean_text(first_present(record, ["first_name", "given", "given_name", "forename"]))
    last = clean_text(first_present(record, ["last_name", "family", "family_name", "surname"]))
    explicit_given_family_name = _extract_name_text(first_present(record, ["who_is_this", "fullName", "full_name", "person_name", "Patient", "PATIENT"]))
    patient_name = _extract_name_text(first_present(record, ["patient_name", "name"])) or explicit_given_family_name

    if first and last:
        return make_patient_id_from_name(f"{first} {last}")

    if patient_name:
        family_first = bool(first_present(record, ["patient_name", "name"])) and not explicit_given_family_name
        if explicit_given_family_name:
            family_first = False
        return make_patient_id_from_name(patient_name, family_first=family_first)

    return None


PATIENT_ID_FIELDS = [
    "patient_id", "patientid", "patient", "subject", "subject_id", "mrn",
    "medical_record_number", "local_patient_id", "patient_local_id",
    "person_id", "id_patient", "patient_identifier", "local_mrn",
    "legacy_id", "legacyNo", "legacy_no", "source_patient_id", "identifier",
]
SOURCE_PATIENT_ID_FIELDS = [
    "mrn", "local_mrn", "local_patient_id", "patient_local_id",
    "legacy_id", "legacyNo", "legacy_no", "source_patient_id",
    "identifier", "patient_identifier", "medical_record_number",
    "person_id", "id_patient", "patientid", "patient_id",
]
PATIENT_NAME_FIELDS = ["who_is_this", "patient_name", "fullName", "full_name", "person_name", "name", "Patient", "PATIENT"]
DOB_FIELDS = ["born", "birth", "dob", "date_of_birth", "birthDate", "birth_date", "DOB"]

DATE_FIELDS = [
    "date", "approx_when", "when_text", "event_date", "approximate_date", "clinical_date",
    "onset", "onset_date", "onsetDateTime", "recordedDate",
    "authoredOn", "effectiveDateTime", "performedDateTime", "start_date",
    "collected", "result_date", "visit_date", "encounter_date", "timestamp",
]

CATEGORY_FIELDS = [
    "category", "event_type", "type", "record_type", "resourceType", "class",
    "kind_of_thing", "kind", "record_kind",
]

TEXT_FIELDS = [
    "raw_text", "description", "display", "text", "name", "label", "event", "summary",
    "thing_seen", "clinical_phrase", "extra_context", "note_text", "clinical_note",
    "test", "condition", "problem", "diagnosis", "medication", "drug", "procedure",
    "chief_complaint", "notes", "note", "title",
]

CODE_FIELDS = ["code", "snomed_code", "icd10", "icd_10", "loinc", "rxnorm", "coding_code"]
CODE_SYSTEM_FIELDS = ["code_system", "system", "coding_system", "terminology", "vocabulary"]
VALUE_FIELDS = ["value", "number", "result", "result_value", "measurement", "dose", "quantity"]
UNIT_FIELDS = ["unit", "units-ish", "units", "dose_unit", "result_unit"]
FLAG_FIELDS = ["flag", "abnormal_flag", "status", "clinicalStatus"]
PROVIDER_FIELDS = ["provider", "prescriber", "doctor", "clinician"]
FACILITY_FIELDS = ["facility", "organization", "hospital", "clinic", "source_system"]


def infer_patient_id(record: dict[str, Any], fallback: str | None = None) -> str | None:
    explicit_patient_id = clean_text(record.get("patient_id"))
    if explicit_patient_id and _looks_canonical_patient_id(explicit_patient_id.lower()):
        return explicit_patient_id

    canonical = canonical_patient_id_from_demographics(record)
    if canonical:
        return canonical

    value = first_present(record, PATIENT_ID_FIELDS, default=fallback)
    value = _extract_patient_identifier(value)
    if not value:
        return fallback
    # Normalize FHIR references like Patient/patient-001.
    if "/" in value:
        return value.split("/")[-1]
    return value


def infer_patient_name(record: dict[str, Any]) -> str | None:
    first = clean_text(first_present(record, ["first_name", "given", "given_name", "forename"]))
    last = clean_text(first_present(record, ["last_name", "family", "family_name", "surname"]))
    if first and last:
        return clean_text(f"{first} {last}") or None
    raw_value = first_present(record, PATIENT_NAME_FIELDS)
    return _extract_name_text(raw_value) or None


def infer_patient_dob(record: dict[str, Any]) -> str | None:
    dob_raw = first_present(record, DOB_FIELDS)
    dob, _ = normalize_date(dob_raw)
    return dob


def _looks_canonical_patient_id(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z]+(?:-[a-z]+)+", value))


def infer_source_patient_id(record: dict[str, Any]) -> str | None:
    value = first_present(record, SOURCE_PATIENT_ID_FIELDS)
    text = _extract_patient_identifier(value)
    if "/" in text:
        text = text.split("/")[-1]
    cleaned = clean_text(text)
    if _looks_canonical_patient_id(cleaned):
        return None
    return cleaned or None


def infer_category(record: dict[str, Any], text: str = "") -> str:
    value = clean_text(first_present(record, CATEGORY_FIELDS)).lower()
    combined = f"{value} {text.lower()}"

    if any(x in combined for x in ["condition", "diagnosis", "problem", "dx"]):
        return "diagnosis"
    if any(x in combined for x in ["medication", "medrequest", "drug", "rx", "prescription"]):
        return "medication"
    if any(x in combined for x in ["lab", "laboratory", "observation", "hba1c", "ldl", "egfr", "creatinine"]):
        return "lab"
    if any(x in combined for x in ["vital", "blood pressure", " bp "]):
        return "vitals"
    if any(x in combined for x in ["procedure", "surgery", "echocardiogram", "echo"]):
        return "procedure"
    if any(x in combined for x in ["imaging", "x-ray", "xray", "mri", "ct scan", "ultrasound"]):
        return "imaging"
    if any(x in combined for x in ["encounter", "visit", "consultation", "follow-up", "follow up"]):
        return "encounter"
    if any(x in combined for x in ["allergy", "allergies"]):
        return "allergy"
    return "other"


def infer_code_system(record: dict[str, Any], code: str | None = None) -> str | None:
    explicit = clean_text(first_present(record, CODE_SYSTEM_FIELDS))
    if explicit:
        return explicit
    if clean_text(record.get("snomed_code")):
        return "SNOMED"
    if clean_text(record.get("loinc")):
        return "LOINC"
    if clean_text(record.get("rxnorm")):
        return "RxNorm"
    if clean_text(record.get("icd10") or record.get("icd_10")):
        return "ICD-10"
    return None


def normalize_generic_date(value: Any) -> tuple[str | None, str]:
    raw = clean_text(value)
    lowered = raw.lower()
    month_match = re.search(
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})",
        lowered,
    )
    if month_match:
        month_names = {
            "january": "01",
            "february": "02",
            "march": "03",
            "april": "04",
            "may": "05",
            "june": "06",
            "july": "07",
            "august": "08",
            "september": "09",
            "october": "10",
            "november": "11",
            "december": "12",
        }
        return f"{month_match.group(2)}-{month_names[month_match.group(1)]}-01", "month"
    return normalize_date(value)


def record_to_raw_event(
    record: dict[str, Any],
    source: str,
    source_file: str | None = None,
    fallback_patient_id: str | None = None,
    fallback_category: str | None = None,
    row_index: int | None = None,
) -> RawEvent:
    patient_id = infer_patient_id(record, fallback=fallback_patient_id) or UNKNOWN_PATIENT_ID
    patient_name = infer_patient_name(record) or clean_text(record.get("patient_name")) or None
    patient_dob = infer_patient_dob(record) or clean_text(record.get("patient_dob")) or None
    text = clean_text(first_present(record, TEXT_FIELDS))
    if not text:
        # Use a compact representation as last resort.
        pairs = [f"{k}: {v}" for k, v in record.items() if clean_text(v)]
        text = "; ".join(pairs[:8]) or "Unlabeled event"

    date_raw = first_present(record, DATE_FIELDS)
    date, precision = normalize_generic_date(date_raw)

    category = fallback_category or infer_category(record, text)
    if category not in {
        "diagnosis", "medication", "lab", "vitals", "procedure",
        "imaging", "encounter", "allergy", "demographics", "other"
    }:
        category = "other"

    code = clean_text(first_present(record, CODE_FIELDS)) or None
    code_system = infer_code_system(record, code=code)

    value = first_present(record, VALUE_FIELDS)
    if value is not None and not clean_text(value):
        value = None

    record_id = clean_text(first_present(record, ["source_note_id", "note_id", "record_id", "id", "event_id", "resource_id", "problem_id", "med_id", "visit_id"]))
    if not record_id:
        record_id = stable_id(source_file, row_index, patient_id, category, date, text)

    metadata = {
        k: v for k, v in record.items()
        if k not in set(PATIENT_ID_FIELDS + DATE_FIELDS + CATEGORY_FIELDS + TEXT_FIELDS + CODE_FIELDS + CODE_SYSTEM_FIELDS + VALUE_FIELDS + UNIT_FIELDS + FLAG_FIELDS)
    }
    source_patient_id = infer_source_patient_id(record) or clean_text(record.get("source_patient_id")) or None
    if source_patient_id:
        metadata["source_patient_id"] = source_patient_id

    return RawEvent(
        id=record_id,
        patient_id=patient_id,
        patient_name=patient_name,
        patient_dob=patient_dob,
        source=source,
        source_file=source_file,
        category=category,  # type: ignore[arg-type]
        raw_text=text,
        date=date,
        date_precision=precision,
        code=code,
        code_system=code_system,
        value=value,
        unit=clean_text(first_present(record, UNIT_FIELDS)) or None,
        flag=clean_text(first_present(record, FLAG_FIELDS)) or None,
        provider=clean_text(first_present(record, PROVIDER_FIELDS)) or None,
        facility=clean_text(first_present(record, FACILITY_FIELDS)) or None,
        metadata=metadata,
    )


def dataframe_to_events(
    df: pd.DataFrame,
    source: str,
    source_file: str | None = None,
    fallback_patient_id: str | None = None,
    warnings: list[str] | None = None,
) -> list[RawEvent]:
    events: list[RawEvent] = []
    for i, row in df.iterrows():
        record = {str(k): (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        try:
            events.append(
                record_to_raw_event(
                    record=record,
                    source=source,
                    source_file=source_file,
                    fallback_patient_id=fallback_patient_id,
                    row_index=int(i),
                )
            )
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse CSV row {int(i) + 1}: {exc}")
    return events


def flatten_json_records(data: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of flat clinical records from arbitrary JSON.

    This intentionally avoids deep relational inference. It collects dictionaries that
    look event-like and skips high-level metadata/patient containers.
    """
    records: list[dict[str, Any]] = []

    def looks_event_like(obj: dict[str, Any]) -> bool:
        keys = {str(k).lower() for k in obj.keys()}
        signal = set(k.lower() for k in DATE_FIELDS + TEXT_FIELDS + CODE_FIELDS + CATEGORY_FIELDS + VALUE_FIELDS)
        return bool(keys & signal) and len(obj) >= 2

    def walk(obj: Any, inherited: dict[str, Any] | None = None):
        inherited = inherited or {}
        if isinstance(obj, dict):
            current_inherited = dict(inherited)
            possible_pid = infer_patient_id(obj, fallback=None)
            possible_name = infer_patient_name(obj)
            possible_dob = infer_patient_dob(obj)
            source_patient_id = infer_source_patient_id(obj)
            if not possible_name and source_patient_id == possible_pid:
                source_patient_id = None
            if not possible_pid:
                for patient_key in ("patient", "subject", "demographics", "person"):
                    candidate = obj.get(patient_key)
                    if isinstance(candidate, dict):
                        possible_pid = infer_patient_id(candidate, fallback=None)
                        possible_name = possible_name or infer_patient_name(candidate)
                        possible_dob = possible_dob or infer_patient_dob(candidate)
                        source_patient_id = source_patient_id or infer_source_patient_id(candidate)
                        if not possible_name and source_patient_id == possible_pid:
                            source_patient_id = None
                        if possible_pid:
                            break
            if possible_pid:
                current_inherited["patient_id"] = possible_pid
            if possible_name:
                current_inherited["patient_name"] = possible_name
            if possible_dob:
                current_inherited["patient_dob"] = possible_dob
            if source_patient_id:
                current_inherited["source_patient_id"] = source_patient_id

            if looks_event_like(obj):
                merged = dict(current_inherited)
                merged.update(obj)
                records.append(merged)

            for key, value in obj.items():
                key_l = str(key).lower()
                if key_l in {"patient", "patients", "person", "demographics"} and isinstance(value, dict):
                    pid = infer_patient_id(value, fallback=current_inherited.get("patient_id"))
                    nested_inherited = dict(current_inherited)
                    if pid:
                        nested_inherited["patient_id"] = pid
                    name = infer_patient_name(value)
                    dob = infer_patient_dob(value)
                    source_pid = infer_source_patient_id(value)
                    if not name and source_pid == pid:
                        source_pid = None
                    if name:
                        nested_inherited["patient_name"] = name
                    if dob:
                        nested_inherited["patient_dob"] = dob
                    if source_pid:
                        nested_inherited["source_patient_id"] = source_pid
                    walk(value, nested_inherited)
                elif key_l in {"export_meta", "meta", "metadata"}:
                    continue
                else:
                    walk(value, current_inherited)

        elif isinstance(obj, list):
            for item in obj:
                walk(item, inherited)

    walk(data)
    # Deduplicate exact dict objects.
    seen = set()
    unique = []
    for rec in records:
        marker = tuple(sorted((str(k), str(v)) for k, v in rec.items()))
        if marker not in seen:
            seen.add(marker)
            unique.append(rec)
    return unique

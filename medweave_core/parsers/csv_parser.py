from __future__ import annotations

import pandas as pd
from medweave_core.models import RawEvent
from medweave_core.utils import clean_text, first_present, normalize_date
from medweave_core.parsers.generic import UNKNOWN_PATIENT_ID, dataframe_to_events, infer_patient_dob, infer_patient_id, infer_patient_name, infer_source_patient_id, canonical_patient_id_from_demographics


CATEGORY_MAP = {
    "LAB": "lab",
    "MEDICATION": "medication",
    "IMAGING": "imaging",
    "ENCOUNTER": "encounter",
    "ALLERGY": "allergy",
    "CONDITION": "diagnosis",
    "DIAGNOSIS": "diagnosis",
    "PROCEDURE": "procedure",
    "VITALS": "vitals",
    "DEMOGRAPHICS": "demographics",
}


def parse_lab_pharmacy_csv(
    df: pd.DataFrame,
    source_file: str | None = None,
    warnings: list[str] | None = None,
) -> list[RawEvent]:
    """Parse the bundled demo CSV.

    If required columns are absent, fall back to the generic CSV parser.
    """
    normalized_columns = {str(c).strip().lower(): c for c in df.columns}
    record_type_column = normalized_columns.get("record_type")
    if record_type_column is None:
        return dataframe_to_events(df, source="Uploaded flat CSV", source_file=source_file, warnings=warnings)

    events: list[RawEvent] = []
    default_source = "Helsinki Central Lab CSV"

    # Try to infer a file-level patient id from a demographics row or patient columns.
    fallback_patient_id = None
    for _, row in df.iterrows():
        record = {str(k): (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        pid = canonical_patient_id_from_demographics(record) or infer_patient_id(record)
        if pid:
            fallback_patient_id = pid
            break

    for _, row in df.iterrows():
        record = {str(k): (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        try:
            record_type = clean_text(record.get(record_type_column)).upper()
            description = clean_text(first_present(record, ["description", "text", "name", "test", "diagnosis", "medication"]))
            dt, prec = normalize_date(first_present(record, ["date", "event_date", "onset_date", "collected", "start_date"]))
            value = first_present(record, ["value", "result"])
            if pd.isna(value):
                value = None
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse CSV row {len(events) + 1}: {exc}")
            continue

        category = CATEGORY_MAP.get(record_type, "other")

        # In the synthetic dataset, echocardiography is an imaging feed row
        # but clinically should harmonize with the FHIR Procedure.
        if record_type == "IMAGING" and clean_text(record.get("code")) == "40701008":
            category = "procedure"
        if category == "demographics":
            pid = infer_patient_id(record, fallback=fallback_patient_id)
            if pid:
                fallback_patient_id = pid
            continue

        events.append(RawEvent(
            id=clean_text(record.get("record_id")) or f"row-{len(events)}",
            patient_id=infer_patient_id(record, fallback=fallback_patient_id) or UNKNOWN_PATIENT_ID,
            patient_name=infer_patient_name(record),
            patient_dob=infer_patient_dob(record),
            source=default_source,
            source_file=source_file,
            category=category,  # type: ignore[arg-type]
            raw_text=description,
            date=dt,
            date_precision=prec,
            code=clean_text(first_present(record, ["code", "snomed_code", "loinc", "rxnorm", "icd10"])) or None,
            code_system=clean_text(first_present(record, ["code_system"])) or None,
            value=value,
            unit=clean_text(first_present(record, ["unit"])) or None,
            flag=clean_text(first_present(record, ["flag"])) or None,
            provider=clean_text(record.get("provider")) or None,
            facility=clean_text(record.get("facility")) or None,
            metadata={
                "category": clean_text(record.get("category")),
                "reference_range": clean_text(record.get("reference_range")),
                "notes": clean_text(record.get("notes")),
                "source_patient_id": infer_source_patient_id(record),
            },
        ))

    return events

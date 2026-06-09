from __future__ import annotations

import io
import json
from typing import Any
import pandas as pd

from medweave_core.models import RawEvent
from medweave_core.parsers.fhir_parser import parse_fhir_bundle
from medweave_core.parsers.clinic_b_parser import parse_clinic_b
from medweave_core.parsers.csv_parser import parse_lab_pharmacy_csv
from medweave_core.parsers.generic import UNKNOWN_PATIENT_ID, flatten_json_records, record_to_raw_event
from medweave_core.utils import clean_text


def _source_from_json(data: Any, filename: str) -> str:
    if isinstance(data, dict):
        source = (
            clean_text((data.get("export_meta") or {}).get("source_system"))
            or clean_text((data.get("meta") or {}).get("source"))
            or clean_text(data.get("source_system"))
            or clean_text(data.get("source"))
        )
        if source:
            return source
    return f"Uploaded JSON: {filename}"


def _parse_json(data: Any, filename: str, warnings: list[str] | None = None) -> list[RawEvent]:
    if isinstance(data, dict) and data.get("resourceType") == "Bundle":
        return parse_fhir_bundle(data, source_file=filename, warnings=warnings)

    if isinstance(data, dict) and "export_meta" in data and any(k in data for k in ["problems", "medications", "lab_results", "visits"]):
        return parse_clinic_b(data, source_file=filename, warnings=warnings)

    source = _source_from_json(data, filename)

    # JSON can be either a single flat record, a list of records, or a nested export.
    if isinstance(data, list):
        records = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        records = flatten_json_records(data)
        if not records:
            records = [data]
    else:
        raise ValueError("JSON root must be an object, array, or FHIR Bundle.")

    events = []
    for i, rec in enumerate(records):
        try:
            events.append(record_to_raw_event(rec, source=source, source_file=filename, row_index=i))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse JSON record {i + 1}: {exc}")
    return events


def _decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def parse_uploaded_file(filename: str, content: bytes, warnings: list[str] | None = None) -> list[RawEvent]:
    lower = filename.lower()

    if lower.endswith(".csv"):
        csv_text = _decode_text_bytes(content)
        read_errors = []
        for sep in (None, ",", ";", "\t", "|"):
            try:
                kwargs = {"sep": sep} if sep is not None else {"sep": None, "engine": "python"}
                df = pd.read_csv(io.StringIO(csv_text), **kwargs)
                return parse_lab_pharmacy_csv(df, source_file=filename, warnings=warnings)
            except Exception as exc:
                read_errors.append(str(exc))
        raise ValueError(f"Could not read CSV file {filename}. Tried common delimiters. Last error: {read_errors[-1]}")

    if lower.endswith(".json"):
        try:
            data = json.loads(_decode_text_bytes(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {filename}: {exc.msg}") from exc
        return _parse_json(data, filename, warnings=warnings)

    if lower.endswith(".txt"):
        text = _decode_text_bytes(content)
        return [RawEvent(
            id="txt-001",
            patient_id=UNKNOWN_PATIENT_ID,
            source="Free text upload",
            source_file=filename,
            category="other",
            raw_text=text[:4000],
            date=None,
            date_precision="unknown",
        )]

    raise ValueError(f"Unsupported file type: {filename}. Supported: .json, .csv, .txt")

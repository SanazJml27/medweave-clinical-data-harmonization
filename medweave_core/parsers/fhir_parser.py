from __future__ import annotations

from typing import Any
from medweave_core.models import RawEvent
from medweave_core.utils import clean_text, normalize_date, first_present
from medweave_core.parsers.generic import UNKNOWN_PATIENT_ID, infer_source_patient_id, record_to_raw_event, canonical_patient_id_from_demographics
from medweave_core.utils import make_patient_id_from_name


def _coding(codeable: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    coding = (codeable or {}).get("coding") or []
    first = coding[0] if coding else {}
    return first.get("code"), first.get("system"), first.get("display")


def _source(bundle: dict[str, Any]) -> str:
    return clean_text((bundle.get("meta") or {}).get("source")) or "FHIR Bundle"


def _patient_lookup(bundle: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    lookup: dict[str, dict[str, str | None]] = {}
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        if r.get("resourceType") != "Patient":
            continue
        fhir_id = clean_text(r.get("id"))
        identifiers = r.get("identifier") or []
        best_identifier = ""
        if identifiers:
            best_identifier = clean_text(identifiers[0].get("value"))

        name = r.get("name", [{}])[0] if r.get("name") else {}
        demo_record = {
            "first_name": (name.get("given") or [""])[0] if isinstance(name.get("given"), list) else name.get("given"),
            "last_name": name.get("family"),
            "dob": r.get("birthDate"),
        }
        canonical = canonical_patient_id_from_demographics(demo_record)
        patient_name = clean_text(" ".join([clean_text((name.get("given") or [""])[0] if isinstance(name.get("given"), list) else name.get("given")), clean_text(name.get("family"))]))
        patient_id = canonical or best_identifier or fhir_id or "unknown-patient"
        patient_dob = clean_text(r.get("birthDate")) or None
        patient_info = {"patient_id": patient_id, "patient_name": patient_name or None, "patient_dob": patient_dob}

        if fhir_id:
            lookup[f"Patient/{fhir_id}"] = patient_info
            lookup[fhir_id] = patient_info
        if best_identifier:
            lookup[best_identifier] = patient_info
    return lookup


def _patient_info_from_subject(resource: dict[str, Any], lookup: dict[str, dict[str, str | None]]) -> dict[str, str | None]:
    ref = clean_text((resource.get("subject") or {}).get("reference"))
    if not ref:
        # Some FHIR resources use patient instead of subject.
        ref = clean_text((resource.get("patient") or {}).get("reference"))
    if not ref:
        return {"patient_id": None, "patient_name": None, "patient_dob": None}
    return lookup.get(ref) or {"patient_id": ref.split("/")[-1], "patient_name": None, "patient_dob": None}


def parse_fhir_bundle(
    bundle: dict[str, Any],
    source_file: str | None = None,
    warnings: list[str] | None = None,
) -> list[RawEvent]:
    events: list[RawEvent] = []
    source = _source(bundle)
    lookup = _patient_lookup(bundle)

    for i, entry in enumerate(bundle.get("entry", [])):
        try:
            r = entry.get("resource", {})
            rtype = r.get("resourceType")
            rid = r.get("id") or f"unknown-{i}"
            patient_info = _patient_info_from_subject(r, lookup)
            patient_id = patient_info.get("patient_id") or UNKNOWN_PATIENT_ID
            patient_name = patient_info.get("patient_name")
            patient_dob = patient_info.get("patient_dob")

            if rtype == "Patient":
                patient_entry = lookup.get(r.get("id"), {"patient_id": clean_text(r.get("id")) or UNKNOWN_PATIENT_ID, "patient_name": None, "patient_dob": clean_text(r.get("birthDate")) or None})
                patient_id = patient_entry.get("patient_id") or UNKNOWN_PATIENT_ID
                patient_name = patient_entry.get("patient_name")
                patient_dob = patient_entry.get("patient_dob")
                name = r.get("name", [{}])[0] if r.get("name") else {}
                family = clean_text(name.get("family"))
                given = " ".join(name.get("given") or [])
                raw_text = clean_text(f"{given} {family}")
                events.append(RawEvent(
                    id=rid,
                    patient_id=patient_id,
                    patient_name=patient_name,
                    patient_dob=patient_dob,
                    source=source,
                    source_file=source_file,
                    category="demographics",
                    raw_text=raw_text or "Patient demographics",
                    date=r.get("birthDate"),
                    date_precision="day" if r.get("birthDate") else "unknown",
                    metadata={"resourceType": rtype, "gender": r.get("gender")},
                ))
                continue

            if rtype == "Condition":
                code, system, display = _coding(r.get("code", {}))
                raw_text = clean_text((r.get("code") or {}).get("text") or display)
                dt, prec = normalize_date(r.get("onsetDateTime") or r.get("recordedDate"))
                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category="diagnosis",
                    raw_text=raw_text, date=dt, date_precision=prec,
                    code=code, code_system=system, metadata={"resourceType": rtype},
                ))

            elif rtype in {"MedicationRequest", "MedicationStatement"}:
                med_field = r.get("medicationCodeableConcept", {}) or r.get("medicationReference", {})
                code, system, display = _coding(med_field if isinstance(med_field, dict) else {})
                raw_text = clean_text((med_field or {}).get("text") or display or (med_field or {}).get("display"))
                dosage = "; ".join(clean_text(d.get("text")) for d in r.get("dosageInstruction", []) if d.get("text"))
                dt, prec = normalize_date(r.get("authoredOn") or r.get("effectiveDateTime") or r.get("dateAsserted"))
                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category="medication",
                    raw_text=clean_text(f"{raw_text} {dosage}"), date=dt, date_precision=prec,
                    code=code, code_system=system, metadata={"resourceType": rtype, "status": r.get("status")},
                ))

            elif rtype == "Observation":
                code, system, display = _coding(r.get("code", {}))
                category_codes = [
                    c.get("code")
                    for cat in r.get("category", [])
                    for c in cat.get("coding", [])
                ]
                category = "vitals" if "vital-signs" in category_codes else "lab"
                raw_text = clean_text((r.get("code") or {}).get("text") or display)
                dt, prec = normalize_date(r.get("effectiveDateTime") or (r.get("effectivePeriod") or {}).get("start"))

                if r.get("component"):
                    parts = []
                    values = []
                    for comp in r.get("component", []):
                        _, _, comp_display = _coding(comp.get("code", {}))
                        vq = comp.get("valueQuantity") or {}
                        values.append(str(vq.get("value")))
                        parts.append(f"{comp_display}: {vq.get('value')} {vq.get('unit')}")
                    raw_text = clean_text(f"{raw_text} ({'; '.join(parts)})")
                    value = " / ".join(values)
                    unit = (r.get("component", [{}])[0].get("valueQuantity") or {}).get("unit")
                else:
                    vq = r.get("valueQuantity") or {}
                    value = vq.get("value")
                    unit = vq.get("unit")

                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category=category,
                    raw_text=raw_text, date=dt, date_precision=prec,
                    code=code, code_system=system, value=value, unit=unit,
                    metadata={"resourceType": rtype},
                ))

            elif rtype == "Encounter":
                label = clean_text((((r.get("type") or [{}])[0].get("coding") or [{}])[0]).get("display") or "Encounter")
                reason = clean_text(((r.get("reasonCode") or [{}])[0]).get("text"))
                period = r.get("period") or {}
                dt, prec = normalize_date(period.get("start"))
                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category="encounter",
                    raw_text=clean_text(f"{label}. {reason}"), date=dt, date_precision=prec,
                    metadata={"resourceType": rtype, "status": r.get("status")},
                ))

            elif rtype == "Procedure":
                code, system, display = _coding(r.get("code", {}))
                notes = "; ".join(clean_text(n.get("text")) for n in r.get("note", []) if n.get("text"))
                raw_text = clean_text((r.get("code") or {}).get("text") or display)
                dt, prec = normalize_date(r.get("performedDateTime") or (r.get("performedPeriod") or {}).get("start"))
                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category="procedure",
                    raw_text=clean_text(f"{raw_text}. {notes}"), date=dt, date_precision=prec,
                    code=code, code_system=system, metadata={"resourceType": rtype, "status": r.get("status")},
                ))

            elif rtype == "AllergyIntolerance":
                code, system, display = _coding(r.get("code", {}))
                raw_text = clean_text((r.get("code") or {}).get("text") or display)
                dt, prec = normalize_date(r.get("recordedDate") or r.get("onsetDateTime"))
                events.append(RawEvent(
                    id=rid, patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file, category="allergy",
                    raw_text=raw_text or "Allergy", date=dt, date_precision=prec,
                    code=code, code_system=system, metadata={"resourceType": rtype, "criticality": r.get("criticality")},
                ))

            elif rtype in {"DiagnosticReport", "DocumentReference", "Immunization"}:
                # Generic but useful fallback for common FHIR resources.
                code, system, _ = _coding(r.get("code", {}))
                record = {
                    "id": rid,
                    "patient_id": patient_id,
                    "patient_name": patient_name,
                    "patient_dob": patient_dob,
                    "resourceType": rtype,
                    "date": r.get("effectiveDateTime") or r.get("issued") or r.get("date") or r.get("occurrenceDateTime"),
                    "text": clean_text(((r.get("code") or {}).get("text")) or r.get("description") or r.get("status") or rtype),
                    "code": code,
                    "code_system": system,
                }
                events.append(record_to_raw_event(record, source=source, source_file=source_file, fallback_patient_id=patient_id))

            else:
                # Ignore unsupported resources rather than failing the whole upload.
                continue
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse FHIR entry {i + 1}: {exc}")

    return [e for e in events if e.category != "demographics"]

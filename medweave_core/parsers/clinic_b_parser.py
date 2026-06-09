from __future__ import annotations

from medweave_core.models import RawEvent
from medweave_core.utils import clean_text, normalize_date
from medweave_core.parsers.generic import UNKNOWN_PATIENT_ID, infer_patient_id, canonical_patient_id_from_demographics


def parse_clinic_b(
    data: dict,
    source_file: str | None = None,
    warnings: list[str] | None = None,
) -> list[RawEvent]:
    source = clean_text((data.get("export_meta") or {}).get("source_system")) or "Clinic B - Medisoft"
    patient = data.get("patient") or {}
    patient_id = (
        canonical_patient_id_from_demographics(patient)
        or clean_text((data.get("export_meta") or {}).get("patient_local_id"))
        or infer_patient_id(patient)
        or UNKNOWN_PATIENT_ID
    )
    patient_name = clean_text(f"{patient.get('first_name', '')} {patient.get('last_name', '')}") or clean_text(patient.get("name")) or None
    patient_dob, _ = normalize_date(patient.get("dob") or patient.get("birthDate") or patient.get("date_of_birth"))
    source_patient_id = clean_text((data.get("export_meta") or {}).get("patient_local_id")) or clean_text(patient.get("mrn")) or None
    events: list[RawEvent] = []

    for i, p in enumerate(data.get("problems", [])):
        try:
            dt, prec = normalize_date(p.get("first_noted"))
            events.append(RawEvent(
                id=p.get("problem_id", f"problem-{i}"), patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file,
                category="diagnosis", raw_text=clean_text(p.get("description")),
                date=dt, date_precision=prec, code=p.get("snomed_code"), code_system="SNOMED",
                flag=p.get("status"), metadata={"severity": p.get("severity"), "notes": p.get("notes"), "source_patient_id": source_patient_id},
            ))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse Clinic B problem {i + 1}: {exc}")

    for i, m in enumerate(data.get("medications", [])):
        try:
            dt, prec = normalize_date(m.get("start_date"))
            dose = clean_text(f"{m.get('dose', '')}{m.get('dose_unit', '')}")
            freq = clean_text(m.get("frequency"))
            events.append(RawEvent(
                id=m.get("med_id", f"medication-{i}"), patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file,
                category="medication", raw_text=clean_text(f"{m.get('name')} {dose} {freq}"),
                date=dt, date_precision=prec, value=m.get("dose"), unit=m.get("dose_unit"),
                provider=m.get("prescriber"), metadata={"active": m.get("active"), "notes": m.get("notes"), "source_patient_id": source_patient_id},
            ))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse Clinic B medication {i + 1}: {exc}")

    for i, lab in enumerate(data.get("lab_results", [])):
        try:
            dt, prec = normalize_date(lab.get("collected"))
            events.append(RawEvent(
                id=f"lab_results[{i}]", patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file,
                category="lab", raw_text=clean_text(lab.get("test")),
                date=dt, date_precision=prec, value=lab.get("result"), unit=lab.get("unit"),
                flag=lab.get("flag"), metadata={"ref_range": lab.get("ref_range"), "resulted": lab.get("resulted"), "source_patient_id": source_patient_id},
            ))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse Clinic B lab result {i + 1}: {exc}")

    for i, visit in enumerate(data.get("visits", [])):
        try:
            dt, prec = normalize_date(visit.get("date"))
            bp = ""
            if visit.get("bp_systolic") and visit.get("bp_diastolic"):
                bp = f"BP {visit.get('bp_systolic')}/{visit.get('bp_diastolic')}"
            events.append(RawEvent(
                id=visit.get("visit_id", f"visit-{i}"), patient_id=patient_id, patient_name=patient_name, patient_dob=patient_dob, source=source, source_file=source_file,
                category="encounter", raw_text=clean_text(f"{visit.get('type')} {visit.get('chief_complaint')} {bp}"),
                date=dt, date_precision=prec, provider=visit.get("provider"),
                metadata={**{k: v for k, v in visit.items() if k not in {"visit_id", "date"}}, "source_patient_id": source_patient_id},
            ))
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"Could not parse Clinic B visit {i + 1}: {exc}")

    return events

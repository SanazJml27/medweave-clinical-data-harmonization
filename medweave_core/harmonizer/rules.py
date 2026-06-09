from __future__ import annotations

import re
from collections import defaultdict
from medweave_core.models import RawEvent, HarmonizedEvent, Provenance, Conflict
from medweave_core.utils import clean_text, dates_compatible, most_precise_date, precision_rank


CODE_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("ICD-10", "I10"): ("Hypertension", "38341003", "SNOMED"),
    ("http://hl7.org/fhir/sid/icd-10", "I10"): ("Hypertension", "38341003", "SNOMED"),
    ("ICD10", "I10"): ("Hypertension", "38341003", "SNOMED"),
    ("ICD-10", "E11.9"): ("Type 2 Diabetes Mellitus", "44054006", "SNOMED"),
    ("http://hl7.org/fhir/sid/icd-10", "E11.9"): ("Type 2 Diabetes Mellitus", "44054006", "SNOMED"),
    ("ICD10", "E11.9"): ("Type 2 Diabetes Mellitus", "44054006", "SNOMED"),
    ("ICD-10", "E78.5"): ("Dyslipidemia", "370992007", "SNOMED"),
    ("http://hl7.org/fhir/sid/icd-10", "E78.5"): ("Dyslipidemia", "370992007", "SNOMED"),
    ("ICD10", "E78.5"): ("Dyslipidemia", "370992007", "SNOMED"),
    ("SNOMED", "38341003"): ("Hypertension", "38341003", "SNOMED"),
    ("SNOMED", "44054006"): ("Type 2 Diabetes Mellitus", "44054006", "SNOMED"),
    ("SNOMED", "370992007"): ("Dyslipidemia", "370992007", "SNOMED"),
    ("SNOMED", "414916001"): ("Obesity", "414916001", "SNOMED"),
    ("SNOMED", "40701008"): ("Echocardiogram", "40701008", "SNOMED"),
    ("SNOMED", "399208008"): ("Chest X-Ray", "399208008", "SNOMED"),
    ("SNOMED", "372687004"): ("Penicillin allergy", "372687004", "SNOMED"),
    ("LOINC", "4548-4"): ("HbA1c", "4548-4", "LOINC"),
    ("http://loinc.org", "4548-4"): ("HbA1c", "4548-4", "LOINC"),
    ("LOINC", "2089-1"): ("LDL Cholesterol", "2089-1", "LOINC"),
    ("LOINC", "2085-9"): ("HDL Cholesterol", "2085-9", "LOINC"),
    ("LOINC", "2571-8"): ("Triglycerides", "2571-8", "LOINC"),
    ("LOINC", "33914-3"): ("eGFR", "33914-3", "LOINC"),
    ("LOINC", "2160-0"): ("Serum Creatinine", "2160-0", "LOINC"),
    ("LOINC", "1742-6"): ("ALT", "1742-6", "LOINC"),
    ("LOINC", "55284-4"): ("Blood Pressure", "55284-4", "LOINC"),
    ("http://loinc.org", "55284-4"): ("Blood Pressure", "55284-4", "LOINC"),
    ("RXNORM", "29046"): ("Lisinopril", "29046", "RxNorm"),
    ("RxNorm", "29046"): ("Lisinopril", "29046", "RxNorm"),
    ("http://www.nlm.nih.gov/research/umls/rxnorm", "29046"): ("Lisinopril", "29046", "RxNorm"),
    ("RXNORM", "860975"): ("Metformin", "860975", "RxNorm"),
    ("RxNorm", "860975"): ("Metformin", "860975", "RxNorm"),
    ("http://www.nlm.nih.gov/research/umls/rxnorm", "860975"): ("Metformin", "860975", "RxNorm"),
    ("RXNORM", "617312"): ("Atorvastatin", "617312", "RxNorm"),
    ("RxNorm", "617312"): ("Atorvastatin", "617312", "RxNorm"),
    ("RXNORM", "1191"): ("Aspirin", "1191", "RxNorm"),
    ("RxNorm", "1191"): ("Aspirin", "1191", "RxNorm"),
}


TEXT_PATTERNS: list[tuple[str, tuple[str, str | None, str | None]]] = [
    (r"\bhtn\b|hypertension", ("Hypertension", "38341003", "SNOMED")),
    (r"dm type ii|type 2 diabetes|diabetes mellitus", ("Type 2 Diabetes Mellitus", "44054006", "SNOMED")),
    (r"dyslipid|hyperlipid", ("Dyslipidemia", "370992007", "SNOMED")),
    (r"obesity|bmi 31", ("Obesity", "414916001", "SNOMED")),
    (r"metformin", ("Metformin", "860975", "RxNorm")),
    (r"lisinopril", ("Lisinopril", "29046", "RxNorm")),
    (r"atorvastatin", ("Atorvastatin", "617312", "RxNorm")),
    (r"aspirin", ("Aspirin", "1191", "RxNorm")),
    (r"hba1c|hemoglobin a1c", ("HbA1c", "4548-4", "LOINC")),
    (r"ldl", ("LDL Cholesterol", "2089-1", "LOINC")),
    (r"hdl", ("HDL Cholesterol", "2085-9", "LOINC")),
    (r"triglycer", ("Triglycerides", "2571-8", "LOINC")),
    (r"egfr", ("eGFR", "33914-3", "LOINC")),
    (r"creatinine", ("Serum Creatinine", "2160-0", "LOINC")),
    (r"\balt\b", ("ALT", "1742-6", "LOINC")),
    (r"blood pressure|\bbp\b", ("Blood Pressure", "55284-4", "LOINC")),
    (r"echo|echocardiogram", ("Echocardiogram", "40701008", "SNOMED")),
    (r"chest x-ray|x-ray|xray", ("Chest X-Ray", "399208008", "SNOMED")),
    (r"penicillin", ("Penicillin allergy", "372687004", "SNOMED")),
]


def normalize_code_system(system: str | None) -> str:
    s = clean_text(system)
    if not s:
        return ""
    sl = s.lower()
    if "icd" in sl:
        return "ICD-10"
    if "snomed" in sl or "sct" in sl:
        return "SNOMED"
    if "loinc" in sl:
        return "LOINC"
    if "rxnorm" in sl or "umls/rxnorm" in sl:
        return "RxNorm"
    return s


def normalize_event_name(event: RawEvent) -> tuple[str, str | None, str | None]:
    code_system = normalize_code_system(event.code_system)
    code = clean_text(event.code)
    lookup_keys = [
        (code_system, code),
        ((event.code_system or ""), code),
        (code_system.upper(), code),
    ]
    for key in lookup_keys:
        if key in CODE_MAP:
            return CODE_MAP[key]

    text = clean_text(event.raw_text).lower()

    # Encounter labels should describe the visit, not every condition/vital mentioned inside it.
    if event.category == "encounter":
        encounter_patterns = [
            (r"cardiology", ("Cardiology Consultation", None, None)),
            (r"endocrinology", ("Endocrinology Follow-up", None, None)),
            (r"annual review", ("GP Annual Review", None, None)),
            (r"medication review", ("Medication review", None, None)),
            (r"follow-up|follow up|routine", ("Follow-up visit", None, None)),
        ]
        for pattern, out in encounter_patterns:
            if re.search(pattern, text):
                return out
        return clean_text(event.raw_text)[:80] or "Encounter", None, None

    for pattern, out in TEXT_PATTERNS:
        if re.search(pattern, text):
            return out

    label = clean_text(event.raw_text)
    return label[:80] or event.category.title(), None, None


def same_value(a, b) -> bool:
    if a is None or b is None:
        return True
    try:
        return float(a) == float(b)
    except Exception:
        return clean_text(a).lower() == clean_text(b).lower()


def compatible_for_merge(existing: HarmonizedEvent, new: RawEvent, label: str) -> bool:
    if (existing.patient_id or "unknown") != (new.patient_id or "unknown"):
        return False
    if existing.category != new.category:
        return False
    if existing.label.lower() != label.lower():
        return False
    if not dates_compatible(existing.date, existing.date_precision, new.date, new.date_precision):
        return False
    if existing.category == "lab" and not same_value(existing.value, new.value):
        # Do not merge conflicting lab values. Conflict detection can surface them.
        return False
    return True


def make_summary(event: HarmonizedEvent) -> str:
    if event.category == "lab":
        return f"{event.label} {event.value}{event.unit or ''}".strip()
    if event.category == "vitals":
        return f"{event.label}: {event.value} {event.unit or ''}".strip()
    if event.category == "medication":
        dose = f" {event.value}{event.unit}" if event.value and event.unit else ""
        return f"{event.label}{dose} started".strip()
    return event.label


def harmonize_events(raw_events: list[RawEvent]) -> tuple[list[HarmonizedEvent], list[Conflict]]:
    harmonized: list[HarmonizedEvent] = []

    for raw in raw_events:
        label, code, code_system = normalize_event_name(raw)
        prov = Provenance(
            source=raw.source,
            source_file=raw.source_file,
            record_id=raw.id,
            patient_id=raw.patient_id,
            patient_name=raw.patient_name,
            patient_dob=raw.patient_dob,
            source_patient_id=clean_text(raw.metadata.get("source_patient_id")) or None,
            raw_text=raw.raw_text,
            date=raw.date,
            code=raw.code,
            code_system=raw.code_system,
            value=raw.value,
            unit=raw.unit,
        )

        match = None
        for h in harmonized:
            if compatible_for_merge(h, raw, label):
                match = h
                break

        if match:
            match.provenance.append(prov)
            best_date, best_precision = most_precise_date(
                [(match.date, match.date_precision), (raw.date, raw.date_precision)]
            )
            match.date = best_date
            match.date_precision = best_precision
            if match.value is None:
                match.value = raw.value
            if not match.unit:
                match.unit = raw.unit
            if not match.flag:
                match.flag = raw.flag
            if not match.standard_code and code:
                match.standard_code = code
                match.standard_code_system = code_system
            match.confidence = min(0.99, 0.62 + 0.1 * len({p.source for p in match.provenance}))
            match.summary = make_summary(match)
        else:
            h = HarmonizedEvent(
                patient_id=raw.patient_id,
                patient_name=raw.patient_name,
                patient_dob=raw.patient_dob,
                date=raw.date,
                date_precision=raw.date_precision,
                category=raw.category,
                label=label,
                summary=label,
                standard_code=code,
                standard_code_system=code_system,
                value=raw.value,
                unit=raw.unit,
                flag=raw.flag,
                confidence=0.72,
                provenance=[prov],
            )
            h.summary = make_summary(h)
            if raw.code or raw.code_system:
                h.confidence += 0.07
            if precision_rank(raw.date_precision) == 3:
                h.confidence += 0.05
            harmonized.append(h)

    conflicts = detect_conflicts(harmonized)
    harmonized.sort(key=lambda e: (e.patient_id or "unknown", e.date or "9999-99-99", e.category, e.label))
    return harmonized, conflicts


def detect_conflicts(events: list[HarmonizedEvent]) -> list[Conflict]:
    conflicts: list[Conflict] = []

    # Same patient/label/category/day but incompatible values across different harmonized events.
    buckets = defaultdict(list)
    for e in events:
        key = (e.patient_id or "unknown", e.category, e.label.lower(), (e.date or "")[:10])
        buckets[key].append(e)

    for (patient_id, category, label, day), bucket in buckets.items():
        values = sorted({clean_text(e.value) for e in bucket if e.value is not None})
        if category == "lab" and len(values) > 1:
            conflict = Conflict(
                field="value",
                values=values,
                explanation=f"Different values found for patient {patient_id}, {label} on {day}.",
            )
            conflicts.append(conflict)
            for e in bucket:
                e.conflicts.append(conflict)

    # Date precision notes: not hard conflicts, but useful flags.
    for e in events:
        dates = sorted({p.date for p in e.provenance if p.date})
        if len(dates) > 1:
            conflict = Conflict(
                field="date_precision",
                values=dates,
                explanation=f"Source dates differ in precision for {e.label}; using most precise compatible date.",
            )
            e.conflicts.append(conflict)

    return conflicts

You are harmonizing heterogeneous EHR exports into a trusted patient timeline.

Inputs:
1. RAW_EVENTS_JSON: parsed events extracted from FHIR, flat JSON, flat CSV, or free text.
2. RULE_EVENTS_JSON: deterministic harmonizer output that may already contain good merges.

Your job:
- Extract clinically meaningful events from free text rows.
- Normalize fuzzy terms to a common label and standard code when clear.
- Deduplicate records that describe the same patient event.
- Preserve every source record in provenance.
- Preserve patient_id on every event. If patient_id is missing, use null; do not merge across conflicting patient IDs.
- Reconcile date precision. If one source says "2018" and another says "2018-06-01" for the same event, use "2018-06-01" and add a conflict/note explaining date precision.
- Flag true conflicts, such as same lab/date/test with different values or incompatible diagnosis dates.
- Do not invent unsupported events, codes, dates, values, or patient IDs.
- When uncertain, keep a lower confidence and explain the issue in conflicts.

Preferred terminology examples:
- HTN / Essential hypertension / ICD-10 I10 -> Hypertension, SNOMED 38341003
- DM Type II / Type 2 diabetes / ICD-10 E11.9 -> Type 2 Diabetes Mellitus, SNOMED 44054006
- Hyperlipidemia / Dyslipidaemia / ICD-10 E78.5 -> Dyslipidemia, SNOMED 370992007
- HbA1c -> LOINC 4548-4
- Blood pressure -> LOINC 55284-4
- Lisinopril -> RxNorm 29046
- Metformin -> RxNorm 860975

Return a JSON object matching this shape:
{
  "patient_summaries": [
    {"patient_id": "...", "name": "...", "dob": "...", "sex": "...", "city": "..."}
  ],
  "events": [
    {
      "patient_id": "...",
      "patient_name": "...",
      "date": "YYYY-MM-DD or null",
      "date_precision": "day|month|year|unknown",
      "category": "diagnosis|medication|lab|vitals|procedure|imaging|encounter|allergy|demographics|other",
      "label": "...",
      "summary": "...",
      "standard_code": "... or null",
      "standard_code_system": "SNOMED|LOINC|RxNorm|ICD-10|null",
      "value": null,
      "unit": null,
      "flag": null,
      "confidence": 0.0,
      "provenance": [
        {"source": "...", "source_file": "...", "record_id": "...", "patient_id": "...", "raw_text": "...", "date": "...", "code": "...", "code_system": "...", "value": null, "unit": null}
      ],
      "conflicts": []
    }
  ],
  "conflicts": []
}

RAW_EVENTS_JSON:
{{RAW_EVENTS_JSON}}

RULE_EVENTS_JSON:
{{RULE_EVENTS_JSON}}

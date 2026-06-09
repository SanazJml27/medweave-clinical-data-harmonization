# MedWeave — Synthetic Test Data

## Patient: Mikael Johan Virtanen | DOB: 1968-04-12 | Male | Helsinki, FI

Three sources describe the **same fictional patient** in different formats,
with deliberate inconsistencies to test your harmonization logic.

---

## Sources

| File | Format | System | Schema Style |
|---|---|---|---|
| `hospital_a_fhir.json` | FHIR R4 Bundle | Hospital A (Epic) | HL7 FHIR standard |
| `clinic_b_export.json` | Generic JSON | Clinic B (Medisoft) | Custom flat schema |
| `lab_pharmacy_export.csv` | CSV | Helsinki Central Lab | Flat tabular |

---

## Deliberate Harmonization Challenges

### 🔴 Terminology Conflicts (same condition, different codes)
| Condition | Hospital A (FHIR) | Clinic B (JSON) | Lab CSV |
|---|---|---|---|
| Hypertension | ICD-10: `I10` | SNOMED: `38341003` | SNOMED: `38341003` |
| Type 2 Diabetes | ICD-10: `E11.9` | SNOMED: `44054006` | SNOMED: `44054006` |
| Dyslipidemia | ICD-10: `E78.5` | SNOMED: `370992007` | SNOMED: `370992007` |

**Challenge:** Map ICD-10 ↔ SNOMED and unify display names
(`"HTN"` vs `"Essential (primary) hypertension"` vs `"Hypertension"`)

---

### 🟡 Date Precision Conflicts
| Event | Hospital A | Clinic B | Lab CSV |
|---|---|---|---|
| Hypertension onset | `2018-06-01` | `"2018"` (year only) | `2018-06-01` |
| Diabetes onset | `2020-02-10` | `"2020-02"` (month only) | `2020-02-10` |
| Dyslipidemia onset | `2020-02-20` | `"2020"` (year only) | `2020-02-20` |

**Challenge:** Infer/reconcile date granularity across sources.

---

### 🟠 Duplicate Events (same event, different records)
- **Echocardiogram on 2023-09-05**: appears in Hospital A FHIR (`proc-001`) AND Lab CSV (`I001`)
- **HbA1c on 2024-01-10**: appears in Hospital A FHIR (`obs-001`), Clinic B JSON (`lab_results[0]`), and Lab CSV (`L001`) — all showing `7.8%` ✅ consistent value
- **HbA1c on 2023-07-15**: appears in Clinic B JSON and Lab CSV — both showing `8.2%` ✅

**Challenge:** Deduplicate without losing provenance information.

---

### 🔵 Missing Data (present in some sources, absent in others)
| Data Point | Hospital A | Clinic B | Lab CSV |
|---|---|---|---|
| Allergy (Penicillin) | ❌ | ❌ | ✅ |
| Obesity diagnosis | ❌ | ✅ | ✅ |
| Aspirin prescription | ❌ | ❌ | ✅ |
| Chest X-Ray (2021) | ❌ | ❌ | ✅ |
| Atorvastatin | ❌ | ✅ | ✅ |

**Challenge:** The merged timeline must capture data that only appears in one source.

---

### 🟣 Naming Variations
| Field | Hospital A | Clinic B | Lab CSV |
|---|---|---|---|
| Medication | `"Metformin"` | `"Metformin HCl"` | `"Metformin 500mg tablets"` |
| Medication | `"Lisinopril 10mg"` | `"Lisinopril"` | `"Lisinopril 10mg tablets"` |
| Condition | `"Hyperlipidemia, unspecified"` | `"Dyslipidemia"` | `"Dyslipidaemia"` |

**Challenge:** Fuzzy-match medication and condition names across sources.

---

### ⚪ Schema Differences
- **Dates:** `"2024-01-10"` (ISO) vs `"12/04/1968"` (DD/MM/YYYY) vs `"2018"` (year only)
- **Gender:** `"male"` vs `"M"` vs `"Male"`
- **Medication frequency:** `"QD"` vs `"once daily"` vs FHIR timing object
- **BP:** Separate FHIR components vs flat `bp_systolic`/`bp_diastolic` fields vs not present in CSV

---

## Expected Merged Timeline (Ground Truth)

| Date | Category | Event | Sources |
|---|---|---|---|
| 2018-06-01 | Diagnosis | Hypertension | A, B, CSV |
| 2018-06-15 | Medication | Lisinopril 10mg started | A, B, CSV |
| 2019-03-10 | Allergy | Penicillin (rash) | CSV only |
| 2020-02-10 | Diagnosis | Type 2 Diabetes Mellitus | A, B, CSV |
| 2020-02-20 | Diagnosis | Dyslipidemia | A, B, CSV |
| 2020-02-20 | Medication | Metformin 500mg started | A, B, CSV |
| 2020-03-05 | Medication | Atorvastatin 20mg started | B, CSV |
| 2021-03-22 | Imaging | Chest X-Ray | CSV only |
| 2021-06-15 | Diagnosis | Obesity | B, CSV |
| 2022-12-05 | Lab | HbA1c 7.5% (HIGH) | CSV only |
| 2022-12-05 | Lab | LDL 2.9 mmol/L (HIGH) | CSV only |
| 2023-07-15 | Lab | HbA1c 8.2% (HIGH) | B, CSV |
| 2023-07-15 | Encounter | GP Annual Review | B, CSV |
| 2023-09-05 | Encounter | Cardiology Consultation | A, CSV |
| 2023-09-05 | Procedure | Echocardiogram (EF 55%) | A, CSV — DUPLICATE |
| 2024-01-10 | Lab | HbA1c 7.8% (HIGH) | A, B, CSV — 3-way duplicate |
| 2024-01-10 | Lab | LDL 2.4 mmol/L (NORMAL) | B, CSV |
| 2024-01-10 | Vitals | BP 148/92 mmHg | A only |
| 2024-02-10 | Medication | Aspirin 100mg started | CSV only |
| 2024-04-15 | Encounter | Follow-up visit | B only |
| 2024-10-01 | Encounter | Endocrinology Follow-up | B, CSV |

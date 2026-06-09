# MedWeave LLM Test Samples

These files are fully synthetic and designed to test the LLM-assisted extraction/review layer.

## Files

| File | Purpose |
|---|---|
| `llm_free_text_discharge_aava.txt` | Free-text discharge summary for Aava Laine |
| `llm_mixed_patient_notes.txt` | Batched free-text notes for Otto Nieminen and Leena Saarinen |
| `llm_weird_custom_json.json` | Odd nested JSON with non-standard field names |
| `llm_messy_legacy_csv.csv` | Messy CSV with columns that normal rule-based aliases may not understand |
| `expected_llm_ground_truth.json` | Approximate expected events and negative assertions |

## What this tests

- extraction from free text,
- patient separation,
- date normalization from phrases like `early March 2022`, `10 June 2024`, `Sept 2021`,
- negation handling, e.g. `denies diabetes`, `No known drug allergies`,
- terminology normalization:
  - HTN -> Hypertension
  - DM2 -> Type 2 Diabetes Mellitus
  - glycoHb / A1c -> HbA1c
  - CXR -> Chest X-Ray
- medication extraction:
  - Amlodipine 5 mg daily
  - Metformin HCl 500 mg twice daily
- avoiding false positives from negated statements.

## Suggested Cursor prompt

Paste this into Cursor after OpenAI-assisted mode exists:

```text
Add an LLM extraction test workflow using the files in data/samples/llm_tests/.

Requirements:
1. Add these files as a new bundled sample mode called "LLM stress-test demo".
2. When selected, load:
   - llm_free_text_discharge_aava.txt
   - llm_mixed_patient_notes.txt
   - llm_weird_custom_json.json
   - llm_messy_legacy_csv.csv
3. Add an evaluation helper that compares the final harmonized timeline against expected_llm_ground_truth.json.
4. Show a simple scorecard in the UI:
   - expected events found
   - expected events missing
   - negative assertions violated
   - patient IDs detected
5. Do not require exact wording matches. Match by patient, category, date/date precision, label synonym, and value where available.
```

## Expected behavior

The LLM-assisted review should extract events that the deterministic parser may miss, especially from TXT files and weird JSON/CSV fields.

The LLM should NOT extract:
- diabetes for Aava, because the note says she denies diabetes,
- diabetes or hypertension for Leena, because the note says no diabetes/no hypertension,
- drug allergy for Aava, because the note says no known drug allergies.

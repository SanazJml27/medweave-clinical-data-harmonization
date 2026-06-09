# Cursor prompts for MedWeave Clinical Data Harmonization

## 1. Run and inspect

Run:

```bash
pip install -r requirements.txt
pytest
streamlit run app.py
```

Then inspect the upload → harmonize → timeline workflow.

## 2. Improve generic parser coverage

Read `medweave_core/parsers/generic.py` and `medweave_core/parsers/autodetect.py`.
Improve support for arbitrary flat CSV and custom JSON schemas by adding more column aliases for:
- patient ID
- event date
- event category
- clinical text/label
- code/code system
- value/unit/flag
- provider/facility

Do not remove existing sample compatibility.

## 3. Improve multi-patient support

Verify that every parser populates `patient_id`.
Ensure the harmonizer never merges across patients.
Add tests with a CSV containing two patients with the same diagnosis and date.

## 4. Make the UI more polished

Refactor `app.py` into reusable functions/components.
Keep the title exactly: `MedWeave Clinical Data Harmonization`.

Add:
- better upload cards,
- parsing success/failure badges,
- patient selector,
- timeline search,
- conflict badges,
- source coverage chart,
- export buttons.

## 5. Add Claude-assisted mode

Use `prompts/harmonize_events.md` and `medweave_core/harmonizer/llm_anthropic.py`.
Add a Streamlit toggle for "Claude-assisted review".
Send only de-identified/minimized fields to Claude.
Validate all returned JSON with Pydantic before rendering.

## 6. Evaluation

Use `data/samples/README.md` as the expected ground truth.
Write tests that compare the harmonized output against the expected merged timeline.

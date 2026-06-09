from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from medweave_core.evaluation import evaluate_against_ground_truth
from medweave_core.harmonizer.llm_extractor_openai import (
    MissingOpenAIKeyError as MissingOpenAIExtractionKeyError,
)
from medweave_core.harmonizer.llm_extractor_openai import (
    OpenAIExtractionError,
    extract_events_from_documents_with_metadata,
)
from medweave_core.parsers.autodetect import parse_uploaded_file
from medweave_core.models import HarmonizedEvent, RawEvent
from medweave_core.harmonizer.rules import harmonize_events
from medweave_core.timeline.builder import to_dataframe


APP_TITLE = "MedWeave Clinical Data Harmonization"

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🧬",
    layout="wide",
)

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "results" not in st.session_state:
    st.session_state.results = None
if "selected_files" not in st.session_state:
    st.session_state.selected_files = []


def _normalize_uploaded_files(files) -> list[tuple[str, bytes]]:
    return [(f.name, f.getvalue()) for f in (files or [])]


def persist_uploaded_files(widget_key: str) -> None:
    normalized = _normalize_uploaded_files(st.session_state.get(widget_key))
    st.session_state.selected_files = normalized
    st.session_state.results = None


def reset_session():
    for key in list(st.session_state.keys()):
        if str(key).startswith("ehr_uploader_"):
            del st.session_state[key]
    st.session_state.uploader_key += 1
    st.session_state.results = None
    st.session_state.selected_files = []


def dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize mixed-value columns so Streamlit renders them without Arrow warnings."""
    if df.empty:
        return df

    display_df = df.copy()
    for column in display_df.columns:
        if pd.api.types.is_object_dtype(display_df[column]):
            display_df[column] = display_df[column].map(
                lambda value: None if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
            )
    return display_df


def format_patient_label(patient_id: str | None) -> str:
    value = (patient_id or "unknown").strip()
    if value == "unknown":
        return value

    parts = [part for part in value.split("-") if part]
    if len(parts) >= 3 and len(parts[-3]) == 4 and len(parts[-2]) == 2 and len(parts[-1]) == 2:
        name_parts = parts[:-3]
        if name_parts:
            return " ".join(part.capitalize() for part in name_parts)
    return value


def format_patient_name(event: HarmonizedEvent) -> str:
    return event.patient_name or format_patient_label(event.patient_id)


def load_ground_truth(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def decode_text_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def file_type_for_filename(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".txt"):
        return "txt"
    if lower.endswith(".csv"):
        return "csv"
    return "json"


def should_use_llm_extraction(filename: str, content: bytes) -> bool:
    lower = filename.lower()
    if lower.endswith(".txt"):
        return True
    if lower.endswith(".json"):
        text = decode_text_bytes(content)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return True
        if isinstance(data, dict) and data.get("resourceType") == "Bundle":
            return False
        if isinstance(data, dict) and "export_meta" in data and any(k in data for k in ["problems", "medications", "lab_results", "visits"]):
            return False
        return True
    if lower.endswith(".csv"):
        header = decode_text_bytes(content).splitlines()[:1]
        first_line = header[0].lower() if header else ""
        return "record_type" not in first_line
    return False


def deduplicate_harmonized_events(events: list[HarmonizedEvent]) -> list[HarmonizedEvent]:
    deduped: list[HarmonizedEvent] = []
    for event in events:
        match = None
        for existing in deduped:
            if (
                (existing.patient_id or "unknown") == (event.patient_id or "unknown")
                and existing.category == event.category
                and existing.label.lower() == event.label.lower()
                and existing.date == event.date
                and str(existing.value) == str(event.value)
                and (existing.unit or "") == (event.unit or "")
            ):
                match = existing
                break
        if match:
            seen = {(prov.source_file, prov.record_id, prov.raw_text) for prov in match.provenance}
            for provenance in event.provenance:
                marker = (provenance.source_file, provenance.record_id, provenance.raw_text)
                if marker not in seen:
                    match.provenance.append(provenance)
                    seen.add(marker)
            if event.confidence > match.confidence:
                match.confidence = event.confidence
            if not match.standard_code and event.standard_code:
                match.standard_code = event.standard_code
                match.standard_code_system = event.standard_code_system
            if not match.patient_dob and event.patient_dob:
                match.patient_dob = event.patient_dob
            if not match.patient_name and event.patient_name:
                match.patient_name = event.patient_name
        else:
            deduped.append(event.model_copy(deep=True))
    deduped.sort(key=lambda event: (event.patient_id or "", event.date or "9999-99-99", event.category, event.label))
    return deduped


st.markdown(
    """
<style>
.block-container {padding-top: 1.4rem;}
.hero {
    padding: 1.45rem 1.65rem;
    border-radius: 24px;
    background: linear-gradient(135deg, #f7b2ff 0%, #f0a6ff 42%, #d9f99d 100%);
    color: #3f124d;
    box-shadow: 0 18px 45px rgba(190, 24, 93, 0.14);
}
.hero h1 {font-size: 2.15rem; margin-bottom: .2rem;}
.hero p {font-size: 1.02rem; opacity: .92; margin-bottom: 0; color: #5b2167;}
.file-card {
    padding: .9rem 1rem;
    border-radius: 16px;
    border: 1px solid rgba(148,163,184,.35);
    background: #ffffff;
    margin-bottom: .5rem;
}
.section-label {
    font-size: .92rem;
    font-weight: 700;
    color: #6b7280;
    margin: 1rem 0 .65rem 0;
    letter-spacing: .01em;
}
.timeline-card {
    border-left: 6px solid #0f766e;
    padding: .85rem 1rem;
    margin: .55rem 0;
    border-radius: 14px;
    background: #ffffff;
    border-top: 1px solid #e5e7eb;
    border-right: 1px solid #e5e7eb;
    border-bottom: 1px solid #e5e7eb;
}
.chip {
    display: inline-block;
    padding: .15rem .5rem;
    margin-right: .25rem;
    border-radius: 999px;
    background: #ecfeff;
    color: #155e75;
    font-size: .78rem;
    font-weight: 700;
}
.patient-chip {
    display: inline-block;
    padding: .15rem .5rem;
    margin-right: .25rem;
    border-radius: 999px;
    background: #eef2ff;
    color: #3730a3;
    font-size: .78rem;
    font-weight: 700;
}
.warning-chip {
    display: inline-block;
    padding: .15rem .5rem;
    margin-left: .25rem;
    border-radius: 999px;
    background: #fef3c7;
    color: #92400e;
    font-size: .78rem;
    font-weight: 700;
}
.small-muted {font-size: .85rem; color: #64748b;}
[data-testid="stSidebar"] button[kind="secondary"] {
    background: #dbeafe;
    border: 1px solid #93c5fd;
    color: #1d4ed8;
}
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: #bfdbfe;
    color: #1e40af;
    border-color: #60a5fa;
}
[data-testid="stSidebar"] button[kind="primary"] {
    background: #bbf7d0;
    border: 1px solid #86efac;
    color: #166534;
}
[data-testid="stSidebar"] button[kind="primary"]:hover {
    background: #86efac;
    color: #14532d;
    border-color: #4ade80;
}
</style>
<div class="hero">
  <h1>MedWeave Clinical Data Harmonization</h1>
  <p>Upload FHIR, flat custom JSON, or flat CSV exports. Harmonize events into an explainable, multi-patient clinical timeline with provenance and conflict review, with an optional LLM-assisted review mode for messy inputs.</p>
</div>
""",
    unsafe_allow_html=True,
)

st.sidebar.header("1. Start session")
if st.sidebar.button("Refresh / new session", width="stretch"):
    reset_session()
    st.rerun()

st.sidebar.header("2. Upload files")
uploader_widget_key = f"ehr_uploader_{st.session_state.uploader_key}"
uploaded = st.sidebar.file_uploader(
    "Upload FHIR JSON, custom JSON, flat CSV, or TXT",
    type=["json", "csv", "txt"],
    accept_multiple_files=True,
    key=uploader_widget_key,
    on_change=persist_uploaded_files,
    args=(uploader_widget_key,),
)
current_uploaded_files = _normalize_uploaded_files(uploaded)
if current_uploaded_files != st.session_state.selected_files:
    st.session_state.selected_files = current_uploaded_files
    st.session_state.results = None

sample_dir = Path("data/samples")
llm_demo_dir = Path("data/medweave_llm_test_samples")
sample_mode = st.sidebar.selectbox(
    "Bundled sample mode",
    ["None", "Classic bundled sample data", "LLM stress-test demo"],
    index=0,
)

st.sidebar.header("3. Harmonize")
harmonize_clicked = st.sidebar.button("Harmonize uploaded files", type="primary", width="stretch")
use_openai_extraction = st.sidebar.toggle("Use LLM extraction for messy/free-text files", value=False)

st.sidebar.divider()
st.sidebar.header("View options")
show_raw = st.sidebar.checkbox("Show raw-event table", value=True)
min_conf = st.sidebar.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05)
debug_llm = st.sidebar.checkbox("Debug LLM JSON", value=False)


def get_input_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    if sample_mode == "Classic bundled sample data":
        for p in [
            sample_dir / "hospital_a_fhir.json",
            sample_dir / "clinic_b_export.json",
            sample_dir / "lab_pharmacy_export.csv",
        ]:
            if p.exists():
                files.append((p.name, p.read_bytes()))
    elif sample_mode == "LLM stress-test demo":
        for p in [
            llm_demo_dir / "llm_free_text_discharge_aava.txt",
            llm_demo_dir / "llm_mixed_patient_notes.txt",
            llm_demo_dir / "llm_weird_custom_json.json",
            llm_demo_dir / "llm_messy_legacy_csv.csv",
        ]:
            if p.exists():
                files.append((p.name, p.read_bytes()))
    if st.session_state.selected_files:
        files.extend(st.session_state.selected_files)
    return files


input_files = get_input_files()

st.markdown('<div class="section-label">Files ready for harmonization</div>', unsafe_allow_html=True)
if input_files:
    for name, content in input_files:
        st.markdown(
            f'<div class="file-card"><b>{name}</b><br><span class="small-muted">{len(content):,} bytes</span></div>',
            unsafe_allow_html=True,
        )
else:
    st.info("Upload one or more files in the sidebar, or choose a bundled sample mode.")

if harmonize_clicked:
    if not input_files:
        st.warning("Please upload at least one file or choose a bundled sample mode.")
    else:
        raw_events = []
        parse_errors = []
        parse_warnings = []
        evaluation_scorecard = None
        llm_extraction = {
            "enabled": use_openai_extraction,
            "status": "disabled",
            "message": None,
            "files": [],
            "events": [],
            "raw_response": None,
            "validation_errors": [],
        }
        final_events: list[HarmonizedEvent] = []
        with st.spinner("Parsing files and harmonizing events..."):
            llm_docs = []
            llm_fallback_raw_events = []
            for filename, content in input_files:
                file_warnings: list[str] = []
                use_llm_for_file = use_openai_extraction and should_use_llm_extraction(filename, content)
                if use_llm_for_file:
                    llm_docs.append(
                        {
                            "filename": filename,
                            "content": decode_text_bytes(content),
                            "file_type": file_type_for_filename(filename),
                        }
                    )
                    llm_extraction["files"].append({"filename": filename, "file_type": file_type_for_filename(filename)})
                    try:
                        fallback_parsed = parse_uploaded_file(filename, content, warnings=file_warnings)
                        llm_fallback_raw_events.extend(fallback_parsed)
                    except Exception as fallback_exc:
                        parse_warnings.append((filename, f"Rule-based fallback for LLM-targeted file was limited: {fallback_exc}"))
                else:
                    try:
                        parsed = parse_uploaded_file(filename, content, warnings=file_warnings)
                        raw_events.extend(parsed)
                    except Exception as e:
                        parse_errors.append((filename, str(e)))
                if file_warnings:
                    parse_warnings.extend((filename, warning) for warning in file_warnings)

            structured_harmonized, global_conflicts = harmonize_events(raw_events) if raw_events else ([], [])
            if use_openai_extraction and llm_docs:
                try:
                    extraction_result = extract_events_from_documents_with_metadata(llm_docs)
                    extracted_events = extraction_result.events
                    llm_extraction["status"] = "success"
                    llm_extraction["events"] = [event.model_dump() for event in extracted_events]
                    llm_extraction["raw_response"] = extraction_result.raw_response
                    llm_extraction["validation_errors"] = extraction_result.validation_errors
                except MissingOpenAIExtractionKeyError as exc:
                    llm_extraction["status"] = "missing_api_key"
                    llm_extraction["message"] = str(exc)
                except OpenAIExtractionError as exc:
                    llm_extraction["status"] = "error"
                    llm_extraction["message"] = str(exc)
            elif use_openai_extraction:
                llm_extraction["status"] = "not_needed"
                llm_extraction["message"] = "No messy files needed LLM extraction."

            llm_extracted_events = [HarmonizedEvent(**item) for item in llm_extraction.get("events", [])]
            fallback_harmonized, fallback_conflicts = harmonize_events(llm_fallback_raw_events) if llm_fallback_raw_events else ([], [])
            global_conflicts = global_conflicts + fallback_conflicts
            final_events = deduplicate_harmonized_events(structured_harmonized + fallback_harmonized + llm_extracted_events)

            if sample_mode == "LLM stress-test demo":
                ground_truth = load_ground_truth(llm_demo_dir / "expected_llm_ground_truth.json")
                if ground_truth is not None:
                    evaluation_scorecard = evaluate_against_ground_truth(ground_truth, final_events)

        st.session_state.results = {
            "files": [(name, len(content)) for name, content in input_files],
            "raw_events": [r.model_dump() for r in raw_events],
            "final_events": [event.model_dump() for event in final_events],
            "parse_errors": parse_errors,
            "parse_warnings": parse_warnings,
            "global_conflicts": [c.model_dump() for c in global_conflicts],
            "llm_extraction": llm_extraction,
            "sample_mode": sample_mode,
            "evaluation_scorecard": evaluation_scorecard,
            "debug_llm": debug_llm,
        }

if not st.session_state.results:
    st.stop()

results = st.session_state.results
raw_events = [RawEvent(**x) for x in results["raw_events"]]
final_events = [HarmonizedEvent(**x) for x in results.get("final_events", [])]
final_events = [event for event in final_events if event.confidence >= min_conf]
df = to_dataframe(final_events)
llm_extraction = results.get("llm_extraction", {"enabled": False, "status": "disabled"})
sample_mode = results.get("sample_mode", "None")
evaluation_scorecard = results.get("evaluation_scorecard")
debug_llm = results.get("debug_llm", False)

for filename, error in results.get("parse_errors", []):
    st.warning(f"Could not parse {filename}: {error}")

for filename, warning in results.get("parse_warnings", []):
    st.warning(f"{filename}: {warning}")

if llm_extraction.get("enabled") and llm_extraction.get("status") == "missing_api_key":
    st.warning(llm_extraction.get("message") or "OpenAI LLM extraction is unavailable because the API key is missing.")

patient_ids = sorted({e.patient_id or "unknown" for e in final_events})
patient_labels = {patient_id: format_patient_label(patient_id) for patient_id in patient_ids}
source_count = len({p.source for e in final_events for p in e.provenance})
duplicate_savings = max(0, len(raw_events) - len(final_events))
conflict_count = sum(len(e.conflicts) for e in final_events)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Files", len(results.get("files", [])))
m2.metric("Patients", len(patient_ids))
m3.metric("Raw events", len(raw_events))
m4.metric("Harmonized events", len(final_events))
m5.metric("Merged duplicates", duplicate_savings)

tab_names = ["Timeline", "Overview", "Conflicts", "Provenance", "Raw Events"]
if llm_extraction.get("enabled"):
    tab_names.append("LLM Extraction & Evaluation")
tab_names.append("Prompt")
tabs = st.tabs(tab_names)

with tabs[0]:
    st.subheader("Patient timeline")

    c1, c2 = st.columns([1, 2])
    with c1:
        selected_patients = st.multiselect(
            "Patient filter",
            patient_ids,
            default=patient_ids,
            format_func=lambda patient_id: patient_labels.get(patient_id, patient_id),
        )
    with c2:
        cats = sorted(df["category"].unique()) if not df.empty else []
        selected_cats = st.multiselect("Category filter", cats, default=cats)

    visible = [
        e for e in final_events
        if (e.patient_id or "unknown") in selected_patients and e.category in selected_cats
    ]

    for e in visible:
        conflict_badge = '<span class="warning-chip">needs review</span>' if e.conflicts else ""
        code = f"{e.standard_code_system}: {e.standard_code}" if e.standard_code else "No standard code"
        sources = ", ".join(sorted({p.source for p in e.provenance}))
        patient_id = e.patient_id or "unknown"
        patient_name = format_patient_name(e)
        patient_dob = e.patient_dob or "unknown DOB"
        st.markdown(
            f"""
<div class="timeline-card">
  <span class="patient-chip">patient_id: {patient_id}</span>
  <span class="chip">name: {patient_name}</span>
  <span class="chip">DOB: {patient_dob}</span>
  <span class="chip">{e.category}</span>
  <span class="chip">{len(set(p.source for p in e.provenance))} source(s)</span>
  {conflict_badge}
  <h4 style="margin:.4rem 0 .1rem 0;">{e.date or "Unknown date"} — {e.summary}</h4>
  <div class="small-muted">{code} · Confidence {e.confidence:.2f} · {sources}</div>
</div>
""",
            unsafe_allow_html=True,
        )
        with st.expander("Evidence and raw text"):
            for p in e.provenance:
                patient_label = p.patient_name or patient_labels.get(p.patient_id or "unknown", "unknown")
                source_patient_id = p.source_patient_id or ""
                st.markdown(f"**{p.source}** · `{p.source_file or ''}` · `{p.record_id}` · patient_id `{p.patient_id or ''}` · patient `{patient_label}` · DOB `{p.patient_dob or ''}` · source_patient_id `{source_patient_id}` · {p.date or 'no date'}")
                st.write(p.raw_text)

with tabs[1]:
    st.subheader("Harmonized table")
    st.dataframe(dataframe_for_display(df), width="stretch", hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download timeline CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="medweave_clinical_timeline.csv",
            mime="text/csv",
        )
    with c2:
        payload = json.dumps([e.model_dump() for e in final_events], indent=2, ensure_ascii=False)
        st.download_button(
            "Download harmonized JSON",
            data=payload.encode("utf-8"),
            file_name="medweave_harmonized_events.json",
            mime="application/json",
        )

    st.subheader("Category distribution")
    if not df.empty:
        st.bar_chart(df["category"].value_counts())

with tabs[2]:
    st.subheader("Review queue")
    rows = []
    for e in final_events:
        for c in e.conflicts:
            rows.append({
                "patient_id": e.patient_id,
                "patient_name": e.patient_name,
                "patient_dob": e.patient_dob,
                "date": e.date,
                "event": e.summary,
                "field": c.field,
                "values": ", ".join(map(str, c.values)),
                "explanation": c.explanation,
            })
    if rows:
        st.dataframe(dataframe_for_display(pd.DataFrame(rows)), width="stretch", hide_index=True)
    else:
        st.success("No hard conflicts detected. Date precision notes may still appear inside event evidence.")

with tabs[3]:
    st.subheader("Provenance matrix")
    prov_rows = []
    for e in final_events:
        for p in e.provenance:
            prov_rows.append({
                "patient_id": e.patient_id or p.patient_id,
                "patient_name": e.patient_name or p.patient_name,
                "patient_dob": e.patient_dob or p.patient_dob,
                "source_patient_id": p.source_patient_id,
                "harmonized_event": e.summary,
                "date": e.date,
                "source": p.source,
                "source_file": p.source_file,
                "record_id": p.record_id,
                "raw_text": p.raw_text,
            })
    st.dataframe(dataframe_for_display(pd.DataFrame(prov_rows)), width="stretch", hide_index=True)

with tabs[4]:
    if show_raw:
        st.subheader("Raw parsed intermediate events")
        raw_df = pd.DataFrame([r.model_dump() for r in raw_events])
        st.dataframe(dataframe_for_display(raw_df), width="stretch", hide_index=True)
    else:
        st.info("Enable raw events in the sidebar.")

next_tab_index = 5
extraction_tab_index = None
if llm_extraction.get("enabled"):
    extraction_tab_index = next_tab_index
    next_tab_index += 1
prompt_tab_index = next_tab_index

if extraction_tab_index is not None:
    with tabs[extraction_tab_index]:
        st.subheader("LLM Extraction & Evaluation")
        st.caption("Original messy TXT, CSV, and custom JSON files are sent directly to OpenAI for extraction when the LLM toggle is enabled.")

        extracted_events = [HarmonizedEvent(**item) for item in llm_extraction.get("events", [])]
        c1, c2, c3 = st.columns(3)
        c1.metric("LLM extraction enabled", "Yes" if llm_extraction.get("enabled") else "No")
        c2.metric("Files sent to LLM", len(llm_extraction.get("files", [])))
        c3.metric("Extracted events", len(extracted_events))

        if llm_extraction.get("files"):
            st.subheader("Files sent to LLM")
            st.dataframe(dataframe_for_display(pd.DataFrame(llm_extraction.get("files", []))), width="stretch", hide_index=True)

        if llm_extraction.get("status") == "success":
            if extracted_events:
                st.subheader("Extracted events table")
                st.dataframe(dataframe_for_display(to_dataframe(extracted_events)), width="stretch", hide_index=True)

                identity_debug_rows = []
                unknown_identity_rows = []
                for event in extracted_events:
                    provenances = event.provenance or [None]
                    for provenance in provenances:
                        source_file = provenance.source_file if provenance else None
                        record_id = provenance.record_id if provenance else None
                        source_patient_id = provenance.source_patient_id if provenance else None
                        raw_text = provenance.raw_text if provenance else event.summary
                        raw_patient_text = " | ".join(
                            part for part in [
                                provenance.patient_id if provenance else None,
                                provenance.patient_name if provenance else None,
                                provenance.patient_dob if provenance else None,
                                source_patient_id,
                            ]
                            if part
                        ) or None
                        row = {
                            "source_file": source_file,
                            "record_id": record_id,
                            "raw_patient_text": raw_patient_text,
                            "source_patient_id": source_patient_id,
                            "patient_id": event.patient_id,
                            "patient_name": event.patient_name,
                            "patient_dob": event.patient_dob,
                            "raw_text": raw_text,
                        }
                        identity_debug_rows.append(row)
                        if (event.patient_id or "").strip().lower() == "unknown":
                            unknown_identity_rows.append(row)

                st.subheader("Patient identity debug")
                st.dataframe(dataframe_for_display(pd.DataFrame(identity_debug_rows)), width="stretch", hide_index=True)

                if unknown_identity_rows:
                    st.warning(f"{len(unknown_identity_rows)} extracted event(s) still have `patient_id = unknown`.")
                    for row in unknown_identity_rows:
                        st.warning(
                            f"Unknown patient_id in `{row.get('source_file') or 'unknown source'}`"
                            f" · record `{row.get('record_id') or 'unknown record'}`"
                            f" · raw text: {row.get('raw_text') or 'n/a'}"
                        )
            else:
                st.info("LLM extraction completed but returned no events.")
        elif llm_extraction.get("status") == "missing_api_key":
            st.warning(llm_extraction.get("message") or "OpenAI LLM extraction is unavailable because the API key is missing.")
        elif llm_extraction.get("status") == "error":
            st.error(llm_extraction.get("message") or "OpenAI LLM extraction failed.")
        elif llm_extraction.get("status") == "not_needed":
            st.info(llm_extraction.get("message") or "No files needed LLM extraction.")
        else:
            st.info("OpenAI LLM extraction was not run for this harmonization.")

        validation_errors = llm_extraction.get("validation_errors", [])
        if validation_errors:
            st.subheader("Validation errors")
            st.dataframe(dataframe_for_display(pd.DataFrame(validation_errors)), width="stretch", hide_index=True)

        if debug_llm and llm_extraction.get("raw_response"):
            st.subheader("Raw JSON response")
            st.code(llm_extraction.get("raw_response"), language="json")
        if evaluation_scorecard:
            st.subheader("Evaluation scorecard")
            st.caption("Approximate matching based on patient, category, date/date precision, label synonyms, and value where available.")

            patient_scorecard = evaluation_scorecard.get("patient_ids_detected", {})
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Expected events found", len(evaluation_scorecard.get("expected_events_found", [])))
            c2.metric("Expected events missing", len(evaluation_scorecard.get("expected_events_missing", [])))
            c3.metric("Negative assertions violated", len(evaluation_scorecard.get("negative_assertions_violated", [])))
            c4.metric(
                "Extracted patient IDs",
                f"{len(patient_scorecard.get('detected', []))}/{len(patient_scorecard.get('expected', []))}",
            )
            c5.metric("Extracted event count", len(final_events))

            for note in evaluation_scorecard.get("notes", []):
                st.info(note)

            st.subheader("Detected patient IDs")
            st.write(", ".join(patient_scorecard.get("actual_ids", [])) or "None")
            show_eval_diagnostics = st.checkbox("Show developer evaluation diagnostics", value=False)
            if show_eval_diagnostics:
                st.caption(
                    "These diagnostics compare the extracted timeline against the synthetic ground-truth file. "
                    "Missing events are expected events that were not matched by the current extraction/evaluation logic. "
                    "This section is for testing only and is not part of the clinical timeline."
                )

                st.subheader("Expected events found")
                found_rows = [
                    {
                        "patient_id": item.get("patient_id"),
                        "patient_name": item.get("patient_name"),
                        "patient_dob": item.get("patient_dob"),
                        "category": item.get("category"),
                        "label": item.get("label"),
                        "date": item.get("date"),
                        "matched_label": item.get("matched_label"),
                        "matched_date": item.get("matched_date"),
                        "matched_patient_id": item.get("matched_patient_id"),
                    }
                    for item in evaluation_scorecard.get("expected_events_found", [])
                ]
                if found_rows:
                    st.dataframe(dataframe_for_display(pd.DataFrame(found_rows)), width="stretch", hide_index=True)
                else:
                    st.info("No expected events were matched.")

                st.subheader("Expected events missing")
                missing_rows = [
                    {
                        "patient_id": item.get("patient_id"),
                        "patient_name": item.get("patient_name"),
                        "patient_dob": item.get("patient_dob"),
                        "category": item.get("category"),
                        "label": item.get("label"),
                        "date": item.get("date"),
                        "value": item.get("value"),
                    }
                    for item in evaluation_scorecard.get("expected_events_missing", [])
                ]
                if missing_rows:
                    missing_df = pd.DataFrame(missing_rows)[["patient_id", "patient_name", "patient_dob", "category", "label", "date", "value"]]
                    st.dataframe(dataframe_for_display(missing_df), width="stretch", hide_index=True)
                else:
                    st.success("All expected events were found.")

                st.subheader("Negative assertions violated")
                violation_rows = []
                for item in evaluation_scorecard.get("negative_assertions_violated", []):
                    for violation in item.get("violations", []):
                        violation_rows.append(
                            {
                                "patient_id": violation.get("patient_id"),
                                "patient_name": item.get("patient_name"),
                                "patient_dob": item.get("patient_dob"),
                                "statement": item.get("statement"),
                                "should_not_extract": item.get("should_not_extract"),
                                "detected_label": violation.get("label"),
                                "detected_category": violation.get("category"),
                                "detected_date": violation.get("date"),
                            }
                        )
                if violation_rows:
                    st.dataframe(dataframe_for_display(pd.DataFrame(violation_rows)), width="stretch", hide_index=True)
                else:
                    st.success("No negative assertions were violated.")

                matching_debug_rows = found_rows + missing_rows
                if matching_debug_rows:
                    st.subheader("Matching debug table")
                    st.dataframe(dataframe_for_display(pd.DataFrame(matching_debug_rows)), width="stretch", hide_index=True)

with tabs[prompt_tab_index]:
    st.subheader("Harmonizer prompt template")
    prompt_path = Path("prompts/harmonize_events.md")
    if prompt_path.exists():
        st.code(prompt_path.read_text(), language="markdown")
    else:
        st.info("No prompt template found.")

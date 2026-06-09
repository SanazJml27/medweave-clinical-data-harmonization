from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from medweave_core.models import Conflict, HarmonizedEvent, RawEvent


MINIMIZED_EVENT_FIELDS = (
    "patient_id",
    "category",
    "raw_text",
    "date",
    "date_precision",
    "code",
    "code_system",
    "value",
    "unit",
    "source",
    "source_file",
    "record_id",
)


class OpenAIReviewError(RuntimeError):
    """Raised when the optional OpenAI review path cannot complete."""


class MissingOpenAIKeyError(OpenAIReviewError):
    """Raised when OpenAI review is enabled without an API key."""


class OpenAIReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[HarmonizedEvent] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _make_client() -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIReviewError(
            "The `openai` package is not installed. Install dependencies to use OpenAI-assisted review."
        ) from exc
    return OpenAI()


def build_openai_payload(raw_events: list[RawEvent]) -> list[dict[str, Any]]:
    """Return the minimized, de-identified event payload sent to OpenAI."""
    payload: list[dict[str, Any]] = []
    for raw in raw_events:
        payload.append(
            {
                "patient_id": raw.patient_id,
                "category": raw.category,
                "raw_text": raw.raw_text,
                "date": raw.date,
                "date_precision": raw.date_precision,
                "code": raw.code,
                "code_system": raw.code_system,
                "value": raw.value,
                "unit": raw.unit,
                "source": raw.source,
                "source_file": raw.source_file,
                "record_id": raw.id,
            }
        )
    return payload


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    if hasattr(response, "model_dump"):
        dumped = response.model_dump()
    elif isinstance(response, dict):
        dumped = response
    else:
        dumped = getattr(response, "__dict__", None)

    if isinstance(dumped, dict):
        for item in dumped.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return text

    raise OpenAIReviewError("OpenAI review returned no readable text payload.")


def _openai_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = {key: walk(value) for key, value in node.items()}
            if node.get("type") == "object":
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    return walk(schema)


def openai_review_events(raw_events: list[RawEvent], model: str | None = None) -> OpenAIReviewResult:
    """Run optional OpenAI review for ambiguous or free-text events only."""
    if not raw_events:
        return OpenAIReviewResult()

    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        raise MissingOpenAIKeyError(
            "OpenAI-assisted review is enabled, but `OPENAI_API_KEY` is missing. "
            "Add it to your `.env` file to use this optional review step."
        )

    client = _make_client()
    selected_model = model or os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
    payload = build_openai_payload(raw_events)
    response_schema = _openai_compatible_schema(OpenAIReviewResult.model_json_schema())

    instructions = (
        "Review the provided clinical events and return strict JSON only.\n"
        "This is a review step on top of a deterministic baseline, not a full re-harmonization.\n"
        "Only use evidence from the supplied records. Do not invent unsupported facts.\n"
        "Do not extract diagnoses, allergies, or medications from negated statements.\n"
        "Examples of negation that must remain unextracted include: "
        "'Aava denies diabetes', 'Aava has no known drug allergies', and "
        "'Leena has no diabetes or hypertension'.\n"
        "Return exactly one JSON object with keys: `events`, `conflicts`, and `notes`.\n"
        "`events` must contain harmonized events that validate against the MedWeave schema, "
        "including provenance for the reviewed records.\n"
        "`conflicts` must contain field, values, and explanation.\n"
        "`notes` must be an array of short strings.\n"
        f"Only rely on these input fields: {', '.join(MINIMIZED_EVENT_FIELDS)}."
    )

    try:
        response = client.responses.create(
            model=selected_model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a clinical data reviewer helping with ambiguous EHR harmonization. "
                                "Return strict JSON only."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"{instructions}\n\n"
                                "Reviewed events JSON:\n"
                                f"{json.dumps(payload, indent=2, ensure_ascii=False, default=str)}"
                            ),
                        }
                    ],
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "medweave_openai_review",
                    "strict": True,
                    "schema": response_schema,
                }
            },
        )
        result = OpenAIReviewResult.model_validate_json(_response_text(response))
    except ValidationError as exc:
        raise OpenAIReviewError(f"OpenAI review returned invalid JSON: {exc}") from exc
    except MissingOpenAIKeyError:
        raise
    except Exception as exc:
        raise OpenAIReviewError(f"OpenAI review failed: {exc}") from exc

    result.events.sort(key=lambda event: (event.patient_id or "", event.date or "9999-99-99", event.category, event.label))
    return result

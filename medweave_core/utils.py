from __future__ import annotations

import re
from typing import Any
from dateutil.parser import parse as date_parse


MISSING_STRINGS = {"", "nan", "none", "null", "nat"}


def clean_text(x: Any) -> str:
    if x is None:
        return ""
    s = str(x)
    if s.lower() in MISSING_STRINGS:
        return ""
    return " ".join(s.strip().split())


def first_present(mapping: dict[str, Any], candidates: list[str], default: Any = None) -> Any:
    if not mapping:
        return default

    # Exact match first.
    for key in candidates:
        if key in mapping and clean_text(mapping.get(key)):
            return mapping.get(key)

    # Case/spacing/underscore-insensitive match.
    norm = {re.sub(r"[^a-z0-9]+", "", str(k).lower()): k for k in mapping.keys()}
    for key in candidates:
        nk = re.sub(r"[^a-z0-9]+", "", key.lower())
        if nk in norm and clean_text(mapping.get(norm[nk])):
            return mapping.get(norm[nk])

    return default


def infer_date_precision(value: str | None) -> str:
    if not value:
        return "unknown"
    value = str(value).strip()
    if re.fullmatch(r"\d{4}", value):
        return "year"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return "month"
    return "day"


def normalize_date(value: Any) -> tuple[str | None, str]:
    if value is None:
        return None, "unknown"
    raw = str(value).strip()
    if raw.lower() in MISSING_STRINGS:
        return None, "unknown"

    # Preserve ISO dates and ISO datetimes exactly. Do not run these through
    # day-first parsing, because 2018-06-01 could become 2018-01-06.
    if re.fullmatch(r"\d{4}", raw):
        return f"{raw}-01-01", "year"
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        return f"{raw}-01", "month"
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        return raw[:10], "day"

    # For non-ISO dates, prefer European/Finnish day-first parsing.
    try:
        parsed = date_parse(raw, dayfirst=True).date()
        return parsed.isoformat(), "day"
    except Exception:
        return raw, "unknown"


def precision_rank(precision: str) -> int:
    return {"unknown": 0, "year": 1, "month": 2, "day": 3}.get(precision, 0)


def dates_compatible(a_date: str | None, a_precision: str, b_date: str | None, b_precision: str) -> bool:
    if not a_date or not b_date:
        return True
    a = str(a_date)
    b = str(b_date)
    least = min(precision_rank(a_precision), precision_rank(b_precision))
    if least <= 0:
        return True
    if least == 1:
        return a[:4] == b[:4]
    if least == 2:
        return a[:7] == b[:7]
    return a[:10] == b[:10]


def most_precise_date(items: list[tuple[str | None, str]]) -> tuple[str | None, str]:
    return max(items, key=lambda x: precision_rank(x[1]), default=(None, "unknown"))


def stable_id(*parts: object) -> str:
    raw = "|".join(clean_text(p).lower() for p in parts if p is not None)
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:96] or "event"


def slugify_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", clean_text(value).lower()).strip("-")


def make_patient_id_from_name(name: str, family_first: bool = False) -> str | None:
    cleaned = clean_text(name)
    if not cleaned:
        return None
    tokens = [token for token in re.split(r"\s+", cleaned) if token]
    if not tokens:
        return None
    if len(tokens) == 1:
        return slugify_name(tokens[0]) or None
    if family_first:
        family = tokens[0]
        given = tokens[1]
    else:
        given = tokens[0]
        family = tokens[-1]
    return slugify_name(f"{family}-{given}") or None


def clean_patient_id(value: Any) -> str | None:
    patient_id = clean_text(value).lower()
    if not patient_id:
        return None
    patient_id = re.sub(r"(?:-)?\d{4}-\d{2}-\d{2}$", "", patient_id).strip("-")
    patient_id = re.sub(r"[^a-z0-9-]+", "-", patient_id).strip("-")
    return patient_id or None

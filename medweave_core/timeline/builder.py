from __future__ import annotations

import pandas as pd
from medweave_core.models import HarmonizedEvent


def to_dataframe(events: list[HarmonizedEvent]) -> pd.DataFrame:
    rows = []
    for e in events:
        rows.append({
            "patient_id": e.patient_id or "unknown",
            "patient_name": e.patient_name,
            "patient_dob": e.patient_dob,
            "date": e.date,
            "precision": e.date_precision,
            "category": e.category,
            "event": e.summary,
            "standard_code": e.standard_code,
            "code_system": e.standard_code_system,
            "value": e.value,
            "unit": e.unit,
            "flag": e.flag,
            "sources": ", ".join(sorted({p.source for p in e.provenance})),
            "source_count": len({p.source for p in e.provenance}),
            "confidence": round(e.confidence, 2),
            "conflicts": len(e.conflicts),
        })
    if not rows:
        return pd.DataFrame(columns=[
            "patient_id", "patient_name", "patient_dob", "date", "precision", "category", "event",
            "standard_code", "code_system", "value", "unit", "flag",
            "sources", "source_count", "confidence", "conflicts",
        ])
    return pd.DataFrame(rows).sort_values(["patient_id", "date", "category", "event"], na_position="last")

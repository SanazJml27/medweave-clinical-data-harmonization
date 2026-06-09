from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


Category = Literal[
    "diagnosis",
    "medication",
    "lab",
    "vitals",
    "procedure",
    "imaging",
    "encounter",
    "allergy",
    "demographics",
    "other",
]


class RawEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_dob: Optional[str] = None
    source: str
    source_file: Optional[str] = None
    category: Category
    raw_text: str
    date: Optional[str] = None
    date_precision: Literal["day", "month", "year", "unknown"] = "unknown"
    code: Optional[str] = None
    code_system: Optional[str] = None
    value: Optional[Union[str, float, int]] = None
    unit: Optional[str] = None
    flag: Optional[str] = None
    provider: Optional[str] = None
    facility: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    source_file: Optional[str] = None
    record_id: str
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_dob: Optional[str] = None
    source_patient_id: Optional[str] = None
    raw_text: str
    date: Optional[str] = None
    code: Optional[str] = None
    code_system: Optional[str] = None
    value: Optional[Union[str, float, int]] = None
    unit: Optional[str] = None


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    values: List[Union[str, float, int, bool, None]]
    explanation: str


class HarmonizedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    patient_dob: Optional[str] = None
    date: Optional[str]
    date_precision: Literal["day", "month", "year", "unknown"] = "unknown"
    category: Category
    label: str
    summary: str
    standard_code: Optional[str] = None
    standard_code_system: Optional[str] = None
    value: Optional[Union[str, float, int]] = None
    unit: Optional[str] = None
    flag: Optional[str] = None
    confidence: float = 0.75
    provenance: List[Provenance] = Field(default_factory=list)
    conflicts: List[Conflict] = Field(default_factory=list)

"""Guitar IR Schema 1.0 — the core frozen contract."""

from fretpilot.ir.models import (
    SCHEMA_VERSION,
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRArticulation,
    IRFingering,
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
    Transformation,
)
from fretpilot.ir.serde import ir_from_dict, ir_to_dict, load_ir, save_ir

__all__ = [
    "SCHEMA_VERSION",
    "IRTempoEvent",
    "IRTimeSignatureEvent",
    "ScoreTiming",
    "PerformanceTiming",
    "IRFingering",
    "IRArticulation",
    "NoteConfidence",
    "GuitarNoteEvent",
    "GuitarMeasure",
    "GuitarTrackIR",
    "IRKnowledgeReference",
    "Transformation",
    "GuitarProjectIR",
    "ir_to_dict",
    "ir_from_dict",
    "save_ir",
    "load_ir",
]

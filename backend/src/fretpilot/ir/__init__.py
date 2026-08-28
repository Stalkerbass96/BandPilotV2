"""Canonical SongIR 2.0 plus versioned guitar/drum working contracts."""

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
from fretpilot.ir.raw_score_document import (
    blank_score_document,
    timeline_to_raw_score_document,
)
from fretpilot.ir.score_document_adapter import (
    score_document_to_song_ir,
    song_ir_to_score_document,
)
from fretpilot.ir.score_document_serde import (
    canonical_document_json,
    document_from_dict,
    document_hash,
    document_to_dict,
    load_score_document,
    save_score_document,
)
from fretpilot.ir.serde import ir_from_dict, ir_to_dict, load_ir, save_ir
from fretpilot.ir.song import SONG_SCHEMA_VERSION, SongIR
from fretpilot.ir.song_serde import load_song_ir, save_song_ir, song_ir_from_dict

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
    "SONG_SCHEMA_VERSION",
    "SongIR",
    "canonical_document_json",
    "document_from_dict",
    "document_hash",
    "document_to_dict",
    "load_score_document",
    "save_score_document",
    "song_ir_to_score_document",
    "score_document_to_song_ir",
    "blank_score_document",
    "timeline_to_raw_score_document",
    "song_ir_from_dict",
    "save_song_ir",
    "load_song_ir",
]

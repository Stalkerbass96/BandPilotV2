"""IR serialization and deserialization.

Guarantees round-trip consistency: ``ir_from_dict(ir_to_dict(ir)) == ir``.
The deserializer validates ``schema_version`` and reconstructs every nested
dataclass in a type-safe manner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fretpilot.ir.drum_models import (
    SCHEMA_VERSION as DRUM_SCHEMA_VERSION,
)
from fretpilot.ir.drum_models import (
    DrumHitLocation,
    DrumMeasure,
    DrumNoteEvent,
    DrumProjectIR,
    DrumTrackIR,
)
from fretpilot.ir.models import (
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


def _parse_articulation(raw: dict[str, Any]) -> IRArticulation:
    return IRArticulation(
        type=str(raw["type"]),
        confidence=float(raw["confidence"]),
        reason=str(raw["reason"]),
        source_note_id=raw.get("source_note_id"),
        parameters={
            str(k): float(v) for k, v in raw.get("parameters", {}).items()
        },
    )


def _parse_confidence(raw: dict[str, Any] | None) -> NoteConfidence | None:
    if not isinstance(raw, dict):
        return None
    return NoteConfidence(
        rhythm=float(raw["rhythm"]),
        fingering=float(raw["fingering"]),
        articulation=(
            float(raw["articulation"]) if raw.get("articulation") is not None else None
        ),
    )


def _parse_note_event(raw: dict[str, Any]) -> GuitarNoteEvent:
    score_raw = raw["score"]
    perf_raw = raw["performance"]
    fing_raw = raw["fingering"]
    return GuitarNoteEvent(
        id=str(raw["id"]),
        source_note_index=int(raw["source_note_index"]),
        pitch=int(raw["pitch"]),
        score=ScoreTiming(
            start_beat=float(score_raw["start_beat"]),
            duration_beats=float(score_raw["duration_beats"]),
            measure_number=int(score_raw["measure_number"]),
            beat_in_measure=float(score_raw["beat_in_measure"]),
            voice=int(score_raw.get("voice", 1)),
            tie_in=bool(score_raw.get("tie_in", False)),
            tie_out=bool(score_raw.get("tie_out", False)),
        ),
        performance=PerformanceTiming(
            source_start_beat=float(perf_raw["source_start_beat"]),
            source_duration_beats=float(perf_raw["source_duration_beats"]),
            velocity=int(perf_raw["velocity"]),
        ),
        fingering=IRFingering(
            string=fing_raw.get("string"),
            fret=fing_raw.get("fret"),
            fretting_digit=fing_raw.get("fretting_digit"),
            hand_position=fing_raw.get("hand_position"),
        ),
        articulations=[_parse_articulation(a) for a in raw.get("articulations", [])],
        confidence=_parse_confidence(raw.get("confidence")),
        source_note_origin=str(raw.get("source_note_origin", "midi")),
    )


def _parse_measure(raw: dict[str, Any]) -> GuitarMeasure:
    return GuitarMeasure(
        number=int(raw["number"]),
        start_beat=float(raw["start_beat"]),
        duration_beats=float(raw["duration_beats"]),
        numerator=int(raw["numerator"]),
        denominator=int(raw["denominator"]),
        events=[_parse_note_event(e) for e in raw.get("events", [])],
    )


def _parse_track(raw: dict[str, Any]) -> GuitarTrackIR:
    return GuitarTrackIR(
        id=str(raw["id"]),
        name=str(raw["name"]),
        source_track_index=raw.get("source_track_index"),
        role=str(raw.get("role", "unknown")),
        tuning=[int(p) for p in raw.get("tuning", [])],
        fret_count=int(raw.get("fret_count", 24)),
        measures=[_parse_measure(m) for m in raw.get("measures", [])],
    )


def _parse_knowledge(raw: dict[str, Any] | None) -> IRKnowledgeReference | None:
    if not isinstance(raw, dict):
        return None
    return IRKnowledgeReference(
        snapshot_version=str(raw["snapshot_version"]),
        kb_versions={str(k): str(v) for k, v in raw.get("kb_versions", {}).items()},
        entry_ids=[str(e) for e in raw.get("entry_ids", [])],
    )


def _parse_transformation(raw: dict[str, Any]) -> Transformation:
    return Transformation(
        id=str(raw["id"]),
        stage=str(raw["stage"]),
        source_note_index=int(raw["source_note_index"]),
        before=dict(raw.get("before", {})),
        after=dict(raw.get("after", {})),
        confidence=float(raw["confidence"]),
        reason=str(raw["reason"]),
        knowledge_ref=raw.get("knowledge_ref"),
    )


def ir_to_dict(ir: GuitarProjectIR) -> dict[str, Any]:
    """Serialize a GuitarProjectIR to a plain dict."""
    return ir.to_dict()


def ir_from_dict(data: dict[str, Any]) -> GuitarProjectIR:
    """Deserialize a dict into a GuitarProjectIR.

    Validates schema_version; raises ValueError on mismatch.
    """
    version = str(data.get("schema_version", "0.1"))
    if not version.startswith("1."):
        raise ValueError(
            f"Unsupported IR schema version: {version}, expected 1.x"
        )

    return GuitarProjectIR(
        title=str(data.get("title", "")),
        source=str(data.get("source", "")),
        schema_version=version,
        tempo_map=[
            IRTempoEvent(beat=float(e["beat"]), bpm=float(e["bpm"]))
            for e in data.get("tempo_map", [])
        ],
        time_signatures=[
            IRTimeSignatureEvent(
                beat=float(e["beat"]),
                numerator=int(e["numerator"]),
                denominator=int(e["denominator"]),
            )
            for e in data.get("time_signatures", [])
        ],
        tracks=[_parse_track(t) for t in data.get("tracks", [])],
        knowledge=_parse_knowledge(data.get("knowledge")),
        style_label=str(data.get("style_label", "unknown")),
        midi_fidelity=float(data.get("midi_fidelity", 0.5)),
        degraded_mode=bool(data.get("degraded_mode", False)),
        changes=[_parse_transformation(c) for c in data.get("changes", [])],
        warnings=[str(w) for w in data.get("warnings", [])],
    )


def save_ir(ir: GuitarProjectIR, path: Path | str) -> None:
    """Persist the IR to a JSON file."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(ir_to_dict(ir), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_ir(path: Path | str) -> GuitarProjectIR:
    """Load an IR from a JSON file."""
    return ir_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ─── Drum IR deserialization ───


def _parse_drum_hit_location(raw: dict[str, Any]) -> DrumHitLocation:
    return DrumHitLocation(
        piece=str(raw.get("piece", "unknown")),
        sticking=str(raw.get("sticking", "")),
        technique=str(raw.get("technique", "normal")),
    )


def _parse_drum_note_event(raw: dict[str, Any]) -> DrumNoteEvent:
    score_raw = raw["score"]
    perf_raw = raw["performance"]
    return DrumNoteEvent(
        id=str(raw["id"]),
        source_note_index=int(raw["source_note_index"]),
        pitch=int(raw["pitch"]),
        piece=str(raw.get("piece", "unknown")),
        score=ScoreTiming(
            start_beat=float(score_raw["start_beat"]),
            duration_beats=float(score_raw["duration_beats"]),
            measure_number=int(score_raw["measure_number"]),
            beat_in_measure=float(score_raw["beat_in_measure"]),
            voice=int(score_raw.get("voice", 1)),
            tie_in=bool(score_raw.get("tie_in", False)),
            tie_out=bool(score_raw.get("tie_out", False)),
        ),
        performance=PerformanceTiming(
            source_start_beat=float(perf_raw["source_start_beat"]),
            source_duration_beats=float(perf_raw["source_duration_beats"]),
            velocity=int(perf_raw["velocity"]),
        ),
        location=_parse_drum_hit_location(raw.get("location", {})),
        confidence=_parse_confidence(raw.get("confidence")),
    )


def _parse_drum_measure(raw: dict[str, Any]) -> DrumMeasure:
    return DrumMeasure(
        number=int(raw["number"]),
        start_beat=float(raw["start_beat"]),
        duration_beats=float(raw["duration_beats"]),
        numerator=int(raw["numerator"]),
        denominator=int(raw["denominator"]),
        pattern=str(raw.get("pattern", "unknown")),
        events=[_parse_drum_note_event(e) for e in raw.get("events", [])],
    )


def _parse_drum_track(raw: dict[str, Any]) -> DrumTrackIR:
    return DrumTrackIR(
        id=str(raw["id"]),
        name=str(raw["name"]),
        source_track_index=raw.get("source_track_index"),
        kit=str(raw.get("kit", "standard_5pc")),
        style=str(raw.get("style", "unknown")),
        measures=[_parse_drum_measure(m) for m in raw.get("measures", [])],
    )


def drum_ir_from_dict(data: dict[str, Any]) -> DrumProjectIR:
    """Deserialize a dict into a DrumProjectIR.

    Validates schema_version; raises ValueError on mismatch.
    """
    version = str(data.get("schema_version", DRUM_SCHEMA_VERSION))
    if not version.startswith("1."):
        raise ValueError(
            f"Unsupported drum IR schema version: {version}, expected 1.x"
        )

    return DrumProjectIR(
        title=str(data.get("title", "")),
        source=str(data.get("source", "")),
        schema_version=version,
        tempo_map=[
            IRTempoEvent(beat=float(e["beat"]), bpm=float(e["bpm"]))
            for e in data.get("tempo_map", [])
        ],
        time_signatures=[
            IRTimeSignatureEvent(
                beat=float(e["beat"]),
                numerator=int(e["numerator"]),
                denominator=int(e["denominator"]),
            )
            for e in data.get("time_signatures", [])
        ],
        tracks=[_parse_drum_track(t) for t in data.get("tracks", [])],
        knowledge=_parse_knowledge(data.get("knowledge")),
        style_label=str(data.get("style_label", "unknown")),
        changes=[_parse_transformation(c) for c in data.get("changes", [])],
        warnings=[str(w) for w in data.get("warnings", [])],
    )


def load_drum_ir(path: Path | str) -> DrumProjectIR:
    """Load a drum IR from a JSON file."""
    return drum_ir_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def load_merged_irs(path: Path | str) -> tuple[GuitarProjectIR | None, DrumProjectIR | None]:
    """Load merged IR file (ir_merged.json) produced by BandPilot orchestrator.

    The JSON structure is::

        {
            "guitar": { ...guitar IR dict... } | null,
            "drum":   { ...drum IR dict...   } | null,
        }

    Returns ``(guitar_ir, drum_ir)`` where either may be ``None``.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "guitar" not in data or "drum" not in data:
        raise ValueError(
            "Invalid merged IR file: expected top-level keys 'guitar' and "
            f"'drum', got {sorted(data.keys())}"
        )
    guitar_ir = ir_from_dict(data["guitar"]) if data.get("guitar") else None
    drum_ir = drum_ir_from_dict(data["drum"]) if data.get("drum") else None
    return guitar_ir, drum_ir


__all__ = [
    "ir_to_dict",
    "ir_from_dict",
    "save_ir",
    "load_ir",
    "drum_ir_from_dict",
    "load_drum_ir",
    "load_merged_irs",
]

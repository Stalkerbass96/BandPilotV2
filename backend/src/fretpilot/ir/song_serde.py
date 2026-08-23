"""Strict JSON serialization for canonical SongIR 2.x artifacts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from fretpilot.ir.models import (
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    ScoreTiming,
    Transformation,
)
from fretpilot.ir.song import (
    AnalysisLayer,
    InstrumentRealization,
    InstrumentTrackIR,
    PerformanceEventIR,
    PerformanceLayer,
    ReproducibilityPins,
    ScoreEventIR,
    ScoreLayer,
    ScoreMeasureIR,
    SongIR,
    SourceLayer,
    SourceNoteReference,
    SourceTrackIR,
    TechniqueIR,
    TrackAssignment,
    UnresolvedSourceEvent,
    ValidationIssue,
    ValidationLayer,
)


def _score_timing(raw: dict[str, Any]) -> ScoreTiming:
    return ScoreTiming(
        start_beat=float(raw["start_beat"]),
        duration_beats=float(raw["duration_beats"]),
        measure_number=int(raw["measure_number"]),
        beat_in_measure=float(raw["beat_in_measure"]),
        voice=int(raw.get("voice", 1)),
        tie_in=bool(raw.get("tie_in", False)),
        tie_out=bool(raw.get("tie_out", False)),
    )


def _confidence(raw: dict[str, Any] | None) -> NoteConfidence | None:
    if raw is None:
        return None
    return NoteConfidence(
        rhythm=float(raw["rhythm"]),
        fingering=float(raw["fingering"]),
        articulation=(float(raw["articulation"]) if raw.get("articulation") is not None else None),
    )


def _knowledge(raw: dict[str, Any] | None) -> IRKnowledgeReference | None:
    if raw is None:
        return None
    return IRKnowledgeReference(
        snapshot_version=str(raw["snapshot_version"]),
        kb_versions={str(k): str(v) for k, v in raw.get("kb_versions", {}).items()},
        entry_ids=[str(value) for value in raw.get("entry_ids", [])],
    )


def _transformation(raw: dict[str, Any]) -> Transformation:
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


def _score_tracks(raw_tracks: list[dict[str, Any]]) -> list[InstrumentTrackIR]:
    tracks: list[InstrumentTrackIR] = []
    for track_raw in raw_tracks:
        measures: list[ScoreMeasureIR] = []
        for measure_raw in track_raw.get("measures", []):
            events: list[ScoreEventIR] = []
            for event_raw in measure_raw.get("events", []):
                source_ref = event_raw["source"]
                realization_raw = event_raw["realization"]
                events.append(
                    ScoreEventIR(
                        id=str(event_raw["id"]),
                        pitch=int(event_raw["pitch"]),
                        score=_score_timing(event_raw["score"]),
                        source=SourceNoteReference(
                            source_track_index=int(source_ref["source_track_index"]),
                            source_note_index=int(source_ref["source_note_index"]),
                            origin=str(source_ref.get("origin", "midi")),
                        ),
                        realization=InstrumentRealization(
                            kind=str(realization_raw["kind"]),
                            string=realization_raw.get("string"),
                            fret=realization_raw.get("fret"),
                            fretting_digit=realization_raw.get("fretting_digit"),
                            hand_position=realization_raw.get("hand_position"),
                            piece=realization_raw.get("piece"),
                            sticking=realization_raw.get("sticking"),
                            hit_technique=realization_raw.get("hit_technique"),
                            hand=realization_raw.get("hand"),
                            finger=realization_raw.get("finger"),
                            pedal=realization_raw.get("pedal"),
                        ),
                        technique_ids=[str(value) for value in event_raw.get("technique_ids", [])],
                        confidence=_confidence(event_raw.get("confidence")),
                    )
                )
            measures.append(
                ScoreMeasureIR(
                    number=int(measure_raw["number"]),
                    start_beat=float(measure_raw["start_beat"]),
                    duration_beats=float(measure_raw["duration_beats"]),
                    numerator=int(measure_raw["numerator"]),
                    denominator=int(measure_raw["denominator"]),
                    events=events,
                    annotations=dict(measure_raw.get("annotations", {})),
                )
            )
        tracks.append(
            InstrumentTrackIR(
                id=str(track_raw["id"]),
                name=str(track_raw["name"]),
                family=str(track_raw["family"]),
                role=str(track_raw.get("role", "unknown")),
                source_track_indices=[int(value) for value in track_raw.get("source_track_indices", [])],
                instrument=dict(track_raw.get("instrument", {})),
                measures=measures,
            )
        )
    return tracks


def song_ir_from_dict(raw: dict[str, Any]) -> SongIR:
    version = str(raw.get("schema_version", ""))
    if not version.startswith("2."):
        raise ValueError(f"Unsupported SongIR schema version: {version!r}; expected 2.x")

    source_raw = raw["source"]
    analysis_raw = raw["analysis"]
    score_raw = raw["score"]
    performance_raw = raw["performance"]
    validation_raw = raw["validation"]
    pins_raw = raw["pins"]

    return SongIR(
        title=str(raw.get("title", "")),
        schema_version=version,
        source=SourceLayer(
            filename=str(source_raw["filename"]),
            sha256=str(source_raw["sha256"]),
            midi_type=int(source_raw["midi_type"]),
            ticks_per_beat=int(source_raw["ticks_per_beat"]),
            note_count=int(source_raw["note_count"]),
            duration_beats=float(source_raw["duration_beats"]),
            tracks=[
                SourceTrackIR(
                    index=int(item["index"]),
                    name=str(item["name"]),
                    instrument_name=item.get("instrument_name"),
                    program=item.get("program"),
                    note_count=int(item["note_count"]),
                )
                for item in source_raw.get("tracks", [])
            ],
        ),
        analysis=AnalysisLayer(
            style_label=str(analysis_raw.get("style_label", "unknown")),
            key_signature=analysis_raw.get("key_signature"),
            sections=list(analysis_raw.get("sections", [])),
            chord_symbols=list(analysis_raw.get("chord_symbols", [])),
            track_assignments=[
                TrackAssignment(
                    source_track_index=int(item["source_track_index"]),
                    family=str(item["family"]),
                    confidence=float(item["confidence"]),
                    reason=str(item["reason"]),
                    user_overridden=bool(item.get("user_overridden", False)),
                )
                for item in analysis_raw.get("track_assignments", [])
            ],
            unresolved_events=[
                UnresolvedSourceEvent(
                    source_track_index=int(item["source_track_index"]),
                    source_note_index=int(item["source_note_index"]),
                    pitch=int(item["pitch"]),
                    start_beat=float(item["start_beat"]),
                    duration_beats=float(item["duration_beats"]),
                    reason=str(item["reason"]),
                )
                for item in analysis_raw.get("unresolved_events", [])
            ],
        ),
        score=ScoreLayer(
            tempo_map=[IRTempoEvent(beat=float(item["beat"]), bpm=float(item["bpm"])) for item in score_raw.get("tempo_map", [])],
            time_signatures=[
                IRTimeSignatureEvent(
                    beat=float(item["beat"]),
                    numerator=int(item["numerator"]),
                    denominator=int(item["denominator"]),
                )
                for item in score_raw.get("time_signatures", [])
            ],
            tracks=_score_tracks(score_raw.get("tracks", [])),
            techniques=[
                TechniqueIR(
                    id=str(item["id"]),
                    type=str(item["type"]),
                    note_ids=[str(value) for value in item.get("note_ids", [])],
                    confidence=float(item["confidence"]),
                    reason=str(item["reason"]),
                    parameters={str(k): float(v) for k, v in item.get("parameters", {}).items()},
                )
                for item in score_raw.get("techniques", [])
            ],
        ),
        performance=PerformanceLayer(
            profile_id=str(performance_raw.get("profile_id", "source-preserved")),
            events=[
                PerformanceEventIR(
                    note_id=str(item["note_id"]),
                    start_beat=float(item["start_beat"]),
                    duration_beats=float(item["duration_beats"]),
                    velocity=int(item["velocity"]),
                    controls=list(item.get("controls", [])),
                )
                for item in performance_raw.get("events", [])
            ],
        ),
        validation=ValidationLayer(
            status=str(validation_raw.get("status", "not_validated")),
            issues=[
                ValidationIssue(
                    code=str(item["code"]),
                    severity=str(item["severity"]),
                    message=str(item["message"]),
                    track_id=item.get("track_id"),
                    note_ids=[str(value) for value in item.get("note_ids", [])],
                )
                for item in validation_raw.get("issues", [])
            ],
        ),
        pins=ReproducibilityPins(
            application_version=str(pins_raw["application_version"]),
            knowledge_snapshot=str(pins_raw["knowledge_snapshot"]),
            model_provider=str(pins_raw.get("model_provider", "none")),
            model_name=str(pins_raw.get("model_name", "none")),
            prompt_version=str(pins_raw.get("prompt_version", "none")),
            sound_profile=str(pins_raw.get("sound_profile", "none")),
        ),
        arrangement_mode=str(raw.get("arrangement_mode", "faithful")),
        knowledge=_knowledge(raw.get("knowledge")),
        changes=[_transformation(item) for item in raw.get("changes", [])],
        warnings=[str(value) for value in raw.get("warnings", [])],
    )


def save_song_ir(song: SongIR, path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(song.to_dict(), temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_song_ir(path: Path | str) -> SongIR:
    return song_ir_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


__all__ = ["load_song_ir", "save_song_ir", "song_ir_from_dict"]

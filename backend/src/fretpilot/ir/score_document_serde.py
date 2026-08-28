"""Deterministic serialization for ScoreDocument 3.x snapshots."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path
from typing import Any

from fretpilot.editor.document import (
    SCORE_DOCUMENT_SCHEMA_VERSION,
    AnalysisSnapshot,
    DocumentPins,
    DocumentSource,
    DocumentSourceTrack,
    DocumentTrackAssignment,
    DocumentTransformation,
    DocumentValidationIssue,
    DocumentValidationState,
    InstrumentRealization,
    KnowledgeReference,
    PerformanceEvent,
    PerformanceLayer,
    Rational,
    ScoreBeat,
    ScoreDocument,
    ScoreMeasure,
    ScoreNote,
    ScoreStaff,
    ScoreTechnique,
    ScoreTrack,
    SourceNoteReference,
    TempoChange,
    TimeSignatureChange,
    TrackMixer,
    UnresolvedSourceEvent,
)


def _rational(raw: dict[str, Any] | Rational | int | float | str) -> Rational:
    return Rational.from_value(raw)


def _realization(raw: dict[str, Any]) -> InstrumentRealization:
    return InstrumentRealization(
        kind=str(raw["kind"]),
        string=raw.get("string"),
        fret=raw.get("fret"),
        fretting_digit=raw.get("fretting_digit"),
        hand_position=raw.get("hand_position"),
        piece=raw.get("piece"),
        sticking=raw.get("sticking"),
        hit_technique=raw.get("hit_technique"),
        hand=raw.get("hand"),
        finger=raw.get("finger"),
        pedal=raw.get("pedal"),
    )


def _source_reference(raw: dict[str, Any] | None) -> SourceNoteReference | None:
    if raw is None:
        return None
    return SourceNoteReference(
        source_track_index=int(raw["source_track_index"]),
        source_note_index=int(raw["source_note_index"]),
        origin=str(raw.get("origin", "midi")),
    )


def _note(raw: dict[str, Any]) -> ScoreNote:
    return ScoreNote(
        id=str(raw["id"]),
        pitch=int(raw["pitch"]),
        source=_source_reference(raw.get("source")),
        realization=_realization(raw["realization"]),
        technique_ids=[str(value) for value in raw.get("technique_ids", [])],
        properties=dict(raw.get("properties", {})),
    )


def score_beat_from_dict(raw: dict[str, Any]) -> ScoreBeat:
    return ScoreBeat(
        id=str(raw["id"]),
        start=_rational(raw["start"]),
        duration=_rational(raw["duration"]),
        voice=int(raw["voice"]),
        staff_id=str(raw["staff_id"]),
        kind=str(raw.get("kind", "notes")),
        notes=[_note(note) for note in raw.get("notes", [])],
        tie_in=bool(raw.get("tie_in", False)),
        tie_out=bool(raw.get("tie_out", False)),
        properties=dict(raw.get("properties", {})),
    )


def score_measure_from_dict(raw: dict[str, Any]) -> ScoreMeasure:
    return ScoreMeasure(
        id=str(raw["id"]),
        number=int(raw["number"]),
        start=_rational(raw["start"]),
        duration=_rational(raw["duration"]),
        numerator=int(raw["numerator"]),
        denominator=int(raw["denominator"]),
        beats=[score_beat_from_dict(beat) for beat in raw.get("beats", [])],
        annotations=dict(raw.get("annotations", {})),
    )


def score_track_from_dict(raw: dict[str, Any]) -> ScoreTrack:
    mixer = raw.get("mixer", {})
    inferred_mode = (
        "standard_tab"
        if any("tab" in str(staff.get("kind", "")).lower() for staff in raw.get("staves", []))
        else "percussion"
        if str(raw.get("family", "")) == "drums"
        else "grand_staff"
        if str(raw.get("family", "")) == "keys" and len(raw.get("staves", [])) > 1
        else "standard"
    )
    return ScoreTrack(
        id=str(raw["id"]),
        order=int(raw["order"]),
        name=str(raw["name"]),
        family=str(raw["family"]),
        role=str(raw.get("role", "unknown")),
        source_track_indices=[int(value) for value in raw.get("source_track_indices", [])],
        instrument=dict(raw.get("instrument", {})),
        staves=[
            ScoreStaff(
                id=str(staff["id"]),
                order=int(staff["order"]),
                kind=str(staff["kind"]),
                line_count=int(staff.get("line_count", 5)),
            )
            for staff in raw.get("staves", [])
        ],
        measures=[score_measure_from_dict(measure) for measure in raw.get("measures", [])],
        notation_mode=str(raw.get("notation_mode", inferred_mode)),
        mixer=TrackMixer(
            volume=float(mixer.get("volume", 0.8)),
            pan=float(mixer.get("pan", 0.0)),
            mute=bool(mixer.get("mute", False)),
            solo=bool(mixer.get("solo", False)),
        ),
    )


def score_track_to_dict(track: ScoreTrack) -> dict[str, Any]:
    return asdict(track)


def _default_notation_mode(raw_track: dict[str, Any]) -> str:
    family = str(raw_track.get("family", ""))
    staves = raw_track.get("staves", [])
    if family in {"guitar", "bass"} and any(
        "tab" in str(staff.get("kind", "")).lower() for staff in staves
    ):
        return "standard_tab"
    if family == "drums":
        return "percussion"
    if family == "keys" and len(staves) > 1:
        return "grand_staff"
    return "standard"


def document_to_dict(document: ScoreDocument) -> dict[str, Any]:
    """Return a deterministic plain-data representation.

    Ordering of musical collections is made explicit before canonical JSON is
    hashed. Arbitrary metadata dictionaries are stabilized by JSON key sorting.
    """

    raw = asdict(document)
    raw["source"]["tracks"] = sorted(
        raw["source"].get("tracks", []), key=lambda item: (item["index"], item["id"])
    )
    raw["analysis"]["track_assignments"] = sorted(
        raw["analysis"].get("track_assignments", []),
        key=lambda item: (item["source_track_index"], item["family"]),
    )
    raw["tracks"] = sorted(raw.get("tracks", []), key=lambda item: (item["order"], item["id"]))
    for track in raw["tracks"]:
        track["source_track_indices"] = sorted(track.get("source_track_indices", []))
        track["staves"] = sorted(
            track.get("staves", []), key=lambda item: (item["order"], item["id"])
        )
        track["measures"] = sorted(
            track.get("measures", []), key=lambda item: (item["number"], item["id"])
        )
        for measure in track["measures"]:
            measure["beats"] = sorted(
                measure.get("beats", []),
                key=lambda item: (
                    Fraction(
                        item["start"]["numerator"], item["start"]["denominator"]
                    ),
                    item["voice"],
                    item["staff_id"],
                    item["id"],
                ),
            )
            for beat in measure["beats"]:
                beat["notes"] = sorted(beat.get("notes", []), key=lambda item: item["id"])
                for note in beat["notes"]:
                    note["technique_ids"] = sorted(note.get("technique_ids", []))
        # These E1-D fields were added as backwards-compatible 3.x extensions.
        # Omit inferred defaults from canonical snapshots so every historical
        # 3.0 revision retains its original content hash.
        if track.get("notation_mode") == _default_notation_mode(track):
            track.pop("notation_mode", None)
        if track.get("mixer") == asdict(TrackMixer()):
            track.pop("mixer", None)
    raw["tempo_map"] = sorted(
        raw.get("tempo_map", []),
        key=lambda item: (
            Fraction(
                item["position"]["numerator"], item["position"]["denominator"]
            ),
            item["id"],
        ),
    )
    raw["time_signatures"] = sorted(
        raw.get("time_signatures", []),
        key=lambda item: (
            Fraction(
                item["position"]["numerator"], item["position"]["denominator"]
            ),
            item["id"],
        ),
    )
    raw["techniques"] = sorted(raw.get("techniques", []), key=lambda item: item["id"])
    raw["performance"]["events"] = sorted(
        raw["performance"].get("events", []), key=lambda item: (item["note_id"], item["id"])
    )
    raw["unresolved_events"] = sorted(
        raw.get("unresolved_events", []), key=lambda item: item["id"]
    )
    raw["validation"]["issues"] = sorted(
        raw["validation"].get("issues", []),
        key=lambda item: (item["severity"], item["code"], tuple(item["entity_ids"])),
    )
    raw["transformations"] = sorted(
        raw.get("transformations", []), key=lambda item: item["id"]
    )
    raw["warnings"] = sorted(raw.get("warnings", []))
    if raw.get("knowledge") is not None:
        raw["knowledge"]["kb_versions"] = dict(
            sorted(raw["knowledge"].get("kb_versions", {}).items())
        )
        raw["knowledge"]["entry_ids"] = sorted(raw["knowledge"].get("entry_ids", []))
    return raw


def document_to_api_dict(document: ScoreDocument) -> dict[str, Any]:
    """Return canonical data plus explicit defaults required by editor clients."""

    raw = document_to_dict(document)
    model_by_id = {track.id: track for track in document.tracks}
    for track in raw.get("tracks", []):
        model = model_by_id[str(track["id"])]
        track["notation_mode"] = model.notation_mode
        track["mixer"] = asdict(model.mixer)
    return raw


def score_beat_to_dict(beat: ScoreBeat) -> dict[str, Any]:
    return asdict(beat)


def score_measure_to_dict(measure: ScoreMeasure) -> dict[str, Any]:
    return asdict(measure)


def canonical_document_json(document: ScoreDocument) -> str:
    return json.dumps(
        document_to_dict(document),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def document_hash(document: ScoreDocument) -> str:
    return hashlib.sha256(canonical_document_json(document).encode("utf-8")).hexdigest()


def document_from_dict(raw: dict[str, Any]) -> ScoreDocument:
    version = str(raw.get("schema_version", ""))
    if not version.startswith("3."):
        raise ValueError(f"Unsupported ScoreDocument schema version: {version!r}; expected 3.x")

    source_raw = raw["source"]
    analysis_raw = raw.get("analysis", {})
    performance_raw = raw.get("performance", {})
    validation_raw = raw.get("validation", {})
    pins_raw = raw["pins"]
    knowledge_raw = raw.get("knowledge")
    return ScoreDocument(
        id=str(raw["id"]),
        title=str(raw.get("title", "")),
        source=DocumentSource(
            filename=str(source_raw["filename"]),
            sha256=str(source_raw.get("sha256", "")),
            midi_type=int(source_raw["midi_type"]),
            ticks_per_beat=int(source_raw["ticks_per_beat"]),
            note_count=int(source_raw["note_count"]),
            duration=_rational(source_raw["duration"]),
            tracks=[
                DocumentSourceTrack(
                    id=str(item["id"]),
                    index=int(item["index"]),
                    name=str(item["name"]),
                    instrument_name=item.get("instrument_name"),
                    program=item.get("program"),
                    note_count=int(item["note_count"]),
                )
                for item in source_raw.get("tracks", [])
            ],
        ),
        analysis=AnalysisSnapshot(
            style_label=str(analysis_raw.get("style_label", "unknown")),
            key_signature=analysis_raw.get("key_signature"),
            sections=list(analysis_raw.get("sections", [])),
            chord_symbols=list(analysis_raw.get("chord_symbols", [])),
            track_assignments=[
                DocumentTrackAssignment(
                    source_track_index=int(item["source_track_index"]),
                    family=str(item["family"]),
                    confidence=float(item["confidence"]),
                    reason=str(item["reason"]),
                    user_overridden=bool(item.get("user_overridden", False)),
                )
                for item in analysis_raw.get("track_assignments", [])
            ],
        ),
        tracks=[score_track_from_dict(track) for track in raw.get("tracks", [])],
        tempo_map=[
            TempoChange(
                id=str(item["id"]),
                position=_rational(item["position"]),
                bpm=float(item["bpm"]),
            )
            for item in raw.get("tempo_map", [])
        ],
        time_signatures=[
            TimeSignatureChange(
                id=str(item["id"]),
                position=_rational(item["position"]),
                numerator=int(item["numerator"]),
                denominator=int(item["denominator"]),
            )
            for item in raw.get("time_signatures", [])
        ],
        techniques=[
            ScoreTechnique(
                id=str(item["id"]),
                type=str(item["type"]),
                note_ids=[str(value) for value in item.get("note_ids", [])],
                confidence=float(item["confidence"]),
                reason=str(item["reason"]),
                parameters={str(key): float(value) for key, value in item.get("parameters", {}).items()},
            )
            for item in raw.get("techniques", [])
        ],
        performance=PerformanceLayer(
            profile_id=str(performance_raw.get("profile_id", "source-preserved")),
            events=[
                PerformanceEvent(
                    id=str(item["id"]),
                    note_id=str(item["note_id"]),
                    start=_rational(item["start"]),
                    duration=_rational(item["duration"]),
                    velocity=int(item["velocity"]),
                    controls=list(item.get("controls", [])),
                )
                for item in performance_raw.get("events", [])
            ],
        ),
        unresolved_events=[
            UnresolvedSourceEvent(
                id=str(item["id"]),
                source_track_index=int(item["source_track_index"]),
                source_note_index=int(item["source_note_index"]),
                pitch=int(item["pitch"]),
                start=_rational(item["start"]),
                duration=_rational(item["duration"]),
                reason=str(item["reason"]),
            )
            for item in raw.get("unresolved_events", [])
        ],
        validation=DocumentValidationState(
            status=str(validation_raw.get("status", "not_validated")),
            issues=[
                DocumentValidationIssue(
                    code=str(item["code"]),
                    severity=str(item["severity"]),
                    message=str(item["message"]),
                    entity_ids=[str(value) for value in item.get("entity_ids", [])],
                )
                for item in validation_raw.get("issues", [])
            ],
        ),
        pins=DocumentPins(
            application_version=str(pins_raw["application_version"]),
            knowledge_snapshot=str(pins_raw["knowledge_snapshot"]),
            model_provider=str(pins_raw.get("model_provider", "none")),
            model_name=str(pins_raw.get("model_name", "none")),
            prompt_version=str(pins_raw.get("prompt_version", "none")),
            sound_profile=str(pins_raw.get("sound_profile", "none")),
        ),
        schema_version=version,
        arrangement_mode=str(raw.get("arrangement_mode", "faithful")),
        knowledge=(
            KnowledgeReference(
                snapshot_version=str(knowledge_raw["snapshot_version"]),
                kb_versions={
                    str(key): str(value)
                    for key, value in knowledge_raw.get("kb_versions", {}).items()
                },
                entry_ids=[str(value) for value in knowledge_raw.get("entry_ids", [])],
            )
            if knowledge_raw is not None
            else None
        ),
        transformations=[
            DocumentTransformation(
                id=str(item["id"]),
                stage=str(item["stage"]),
                source_note_index=int(item["source_note_index"]),
                before=dict(item.get("before", {})),
                after=dict(item.get("after", {})),
                confidence=float(item["confidence"]),
                reason=str(item["reason"]),
                knowledge_ref=item.get("knowledge_ref"),
            )
            for item in raw.get("transformations", [])
        ],
        warnings=[str(value) for value in raw.get("warnings", [])],
    )


def save_score_document(document: ScoreDocument, path: Path | str) -> None:
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
            json.dump(
                document_to_dict(document),
                temporary,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            )
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_score_document(path: Path | str) -> ScoreDocument:
    return document_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


__all__ = [
    "SCORE_DOCUMENT_SCHEMA_VERSION",
    "canonical_document_json",
    "document_from_dict",
    "document_hash",
    "document_to_dict",
    "load_score_document",
    "save_score_document",
    "score_beat_from_dict",
    "score_beat_to_dict",
    "score_measure_from_dict",
    "score_measure_to_dict",
]

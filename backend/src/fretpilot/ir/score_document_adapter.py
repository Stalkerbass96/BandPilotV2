"""One-way SongIR 2.x -> ScoreDocument 3.x migration adapter."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict

from fretpilot.editor.document import (
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
    InstrumentTrackIR,
    PerformanceEventIR,
    ReproducibilityPins,
    ScoreEventIR,
    ScoreLayer,
    ScoreMeasureIR,
    SongIR,
    SourceLayer,
    SourceTrackIR,
    TechniqueIR,
    TrackAssignment,
    ValidationIssue,
    ValidationLayer,
)
from fretpilot.ir.song import (
    InstrumentRealization as SongInstrumentRealization,
)
from fretpilot.ir.song import (
    PerformanceLayer as SongPerformanceLayer,
)
from fretpilot.ir.song import (
    SourceNoteReference as SongSourceNoteReference,
)
from fretpilot.ir.song import (
    UnresolvedSourceEvent as SongUnresolvedSourceEvent,
)


def _fallback_source_identity(song: SongIR) -> str:
    payload = json.dumps(
        song.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _staffs(track: InstrumentTrackIR) -> list[ScoreStaff]:
    if track.family in {"guitar", "bass"}:
        return [
            ScoreStaff(
                id=f"{track.id}:staff:standard-tab",
                order=0,
                kind="standard_tab",
                line_count=5,
            )
        ]
    if track.family == "drums":
        return [
            ScoreStaff(
                id=f"{track.id}:staff:percussion",
                order=0,
                kind="percussion",
                line_count=5,
            )
        ]
    if track.family == "keys":
        return [
            ScoreStaff(id=f"{track.id}:staff:treble", order=0, kind="treble"),
            ScoreStaff(id=f"{track.id}:staff:bass", order=1, kind="bass"),
        ]
    return [ScoreStaff(id=f"{track.id}:staff:standard", order=0, kind="standard")]


def _track_notation_mode(track: InstrumentTrackIR) -> str:
    value = track.instrument.get("notation_mode")
    if isinstance(value, str):
        return value
    if track.family in {"guitar", "bass"}:
        return "standard_tab"
    if track.family == "drums":
        return "percussion"
    if track.family == "keys":
        return "grand_staff"
    return "standard"


def _track_mixer(track: InstrumentTrackIR) -> TrackMixer:
    value = track.instrument.get("mixer")
    if not isinstance(value, dict):
        return TrackMixer()
    return TrackMixer(
        volume=float(value.get("volume", 0.8)),
        pan=float(value.get("pan", 0.0)),
        mute=bool(value.get("mute", False)),
        solo=bool(value.get("solo", False)),
    )


def _staff_id(track: InstrumentTrackIR, event: ScoreEventIR) -> str:
    if track.family in {"guitar", "bass"}:
        return f"{track.id}:staff:standard-tab"
    if track.family == "drums":
        return f"{track.id}:staff:percussion"
    if track.family == "keys":
        suffix = "bass" if event.realization.hand == "left" else "treble"
        return f"{track.id}:staff:{suffix}"
    return f"{track.id}:staff:standard"


def _realization(event: ScoreEventIR) -> InstrumentRealization:
    value = event.realization
    return InstrumentRealization(
        kind=value.kind,
        string=value.string,
        fret=value.fret,
        fretting_digit=value.fretting_digit,
        hand_position=value.hand_position,
        piece=value.piece,
        sticking=value.sticking,
        hit_technique=value.hit_technique,
        hand=value.hand,
        finger=value.finger,
        pedal=value.pedal,
    )


def _tracks(song: SongIR, dynamics_by_note: dict[str, str]) -> list[ScoreTrack]:
    result: list[ScoreTrack] = []
    for track_order, track in enumerate(song.score.tracks):
        measures: list[ScoreMeasure] = []
        for measure in track.measures:
            measure_id = f"{track.id}:measure:{measure.number}"
            grouped: dict[
                tuple[Rational, Rational, int, str, bool, bool], list[ScoreEventIR]
            ] = defaultdict(list)
            for event in measure.events:
                grouped[
                    (
                        Rational.from_value(event.score.start_beat),
                        Rational.from_value(event.score.duration_beats),
                        event.score.voice,
                        _staff_id(track, event),
                        event.score.tie_in,
                        event.score.tie_out,
                    )
                ].append(event)

            beats: list[ScoreBeat] = []
            ordered_groups = sorted(
                grouped.items(),
                key=lambda item: (
                    item[0][0].as_fraction(),
                    item[0][2],
                    item[0][3],
                    item[0][1].as_fraction(),
                    min(event.id for event in item[1]),
                ),
            )
            for beat_index, (key, events) in enumerate(ordered_groups, start=1):
                start, duration, voice, staff_id, tie_in, tie_out = key
                dynamics = {
                    dynamics_by_note[event.id]
                    for event in events
                    if event.id in dynamics_by_note
                }
                beats.append(
                    ScoreBeat(
                        id=f"{measure_id}:beat:{beat_index:04d}",
                        start=start,
                        duration=duration,
                        voice=voice,
                        staff_id=staff_id,
                        notes=[
                            ScoreNote(
                                id=event.id,
                                pitch=event.pitch,
                                source=SourceNoteReference(
                                    source_track_index=event.source.source_track_index,
                                    source_note_index=event.source.source_note_index,
                                    origin=event.source.origin,
                                ),
                                realization=_realization(event),
                                technique_ids=list(event.technique_ids),
                                properties=(
                                    {
                                        "confidence": {
                                            "rhythm": event.confidence.rhythm,
                                            "fingering": event.confidence.fingering,
                                            "articulation": event.confidence.articulation,
                                        }
                                    }
                                    if event.confidence is not None
                                    else {}
                                ),
                            )
                            for event in sorted(events, key=lambda value: value.id)
                        ],
                        tie_in=tie_in,
                        tie_out=tie_out,
                        properties=(
                            {"dynamic": next(iter(dynamics))}
                            if len(dynamics) == 1
                            else {}
                        ),
                    )
                )
            measures.append(
                ScoreMeasure(
                    id=measure_id,
                    number=measure.number,
                    start=Rational.from_value(measure.start_beat),
                    duration=Rational.from_value(measure.duration_beats),
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    beats=beats,
                    annotations=dict(measure.annotations),
                )
            )
        result.append(
            ScoreTrack(
                id=track.id,
                order=track_order,
                name=track.name,
                family=track.family,
                role=track.role,
                source_track_indices=list(track.source_track_indices),
                instrument={
                    key: value
                    for key, value in track.instrument.items()
                    if key not in {"notation_mode", "mixer"}
                },
                staves=_staffs(track),
                measures=measures,
                notation_mode=_track_notation_mode(track),
                mixer=_track_mixer(track),
            )
        )
    return result


def song_ir_to_score_document(
    song: SongIR, *, document_id: str | None = None
) -> ScoreDocument:
    """Convert SongIR without mutating it or changing the production write path."""

    source_identity = song.source.sha256 or _fallback_source_identity(song)
    dynamics_by_note = {
        event.note_id: str(control["value"])
        for event in song.performance.events
        for control in event.controls
        if control.get("type") == "dynamic" and control.get("value") is not None
    }
    return ScoreDocument(
        id=document_id or f"document:{source_identity}",
        title=song.title,
        source=DocumentSource(
            filename=song.source.filename,
            sha256=song.source.sha256,
            midi_type=song.source.midi_type,
            ticks_per_beat=song.source.ticks_per_beat,
            note_count=song.source.note_count,
            duration=Rational.from_value(song.source.duration_beats),
            tracks=[
                DocumentSourceTrack(
                    id=f"source-track:{track.index}",
                    index=track.index,
                    name=track.name,
                    instrument_name=track.instrument_name,
                    program=track.program,
                    note_count=track.note_count,
                )
                for track in song.source.tracks
            ],
        ),
        analysis=AnalysisSnapshot(
            style_label=song.analysis.style_label,
            key_signature=song.analysis.key_signature,
            sections=list(song.analysis.sections),
            chord_symbols=list(song.analysis.chord_symbols),
            track_assignments=[
                DocumentTrackAssignment(
                    source_track_index=value.source_track_index,
                    family=value.family,
                    confidence=value.confidence,
                    reason=value.reason,
                    user_overridden=value.user_overridden,
                )
                for value in song.analysis.track_assignments
            ],
        ),
        tracks=_tracks(song, dynamics_by_note),
        tempo_map=[
            TempoChange(
                id=f"tempo:{index:04d}",
                position=Rational.from_value(event.beat),
                bpm=event.bpm,
            )
            for index, event in enumerate(song.score.tempo_map, start=1)
        ],
        time_signatures=[
            TimeSignatureChange(
                id=f"time-signature:{index:04d}",
                position=Rational.from_value(event.beat),
                numerator=event.numerator,
                denominator=event.denominator,
            )
            for index, event in enumerate(song.score.time_signatures, start=1)
        ],
        techniques=[
            ScoreTechnique(
                id=value.id,
                type=value.type,
                note_ids=list(value.note_ids),
                confidence=value.confidence,
                reason=value.reason,
                parameters=dict(value.parameters),
            )
            for value in song.score.techniques
        ],
        performance=PerformanceLayer(
            profile_id=song.performance.profile_id,
            events=[
                PerformanceEvent(
                    id=f"performance:{value.note_id}",
                    note_id=value.note_id,
                    start=Rational.from_value(value.start_beat),
                    duration=Rational.from_value(value.duration_beats),
                    velocity=value.velocity,
                    controls=list(value.controls),
                )
                for value in song.performance.events
            ],
        ),
        unresolved_events=[
            UnresolvedSourceEvent(
                id=(
                    f"unresolved:{value.source_track_index}:"
                    f"{value.source_note_index}:{index:04d}"
                ),
                source_track_index=value.source_track_index,
                source_note_index=value.source_note_index,
                pitch=value.pitch,
                start=Rational.from_value(value.start_beat),
                duration=Rational.from_value(value.duration_beats),
                reason=value.reason,
            )
            for index, value in enumerate(song.analysis.unresolved_events, start=1)
        ],
        validation=DocumentValidationState(
            status=song.validation.status,
            issues=[
                DocumentValidationIssue(
                    code=value.code,
                    severity=value.severity,
                    message=value.message,
                    entity_ids=(
                        ([value.track_id] if value.track_id else []) + list(value.note_ids)
                    ),
                )
                for value in song.validation.issues
            ],
        ),
        pins=DocumentPins(
            application_version=song.pins.application_version,
            knowledge_snapshot=song.pins.knowledge_snapshot,
            model_provider=song.pins.model_provider,
            model_name=song.pins.model_name,
            prompt_version=song.pins.prompt_version,
            sound_profile=song.pins.sound_profile,
        ),
        arrangement_mode=song.arrangement_mode,
        knowledge=(
            KnowledgeReference(
                snapshot_version=song.knowledge.snapshot_version,
                kb_versions=dict(song.knowledge.kb_versions),
                entry_ids=list(song.knowledge.entry_ids),
            )
            if song.knowledge is not None
            else None
        ),
        transformations=[
            DocumentTransformation(
                id=value.id,
                stage=value.stage,
                source_note_index=value.source_note_index,
                before=dict(value.before),
                after=dict(value.after),
                confidence=value.confidence,
                reason=value.reason,
                knowledge_ref=value.knowledge_ref,
            )
            for value in song.changes
        ],
        warnings=list(song.warnings),
    )


def _song_realization(value: InstrumentRealization) -> SongInstrumentRealization:
    return SongInstrumentRealization(
        kind=value.kind,
        string=value.string,
        fret=value.fret,
        fretting_digit=value.fretting_digit,
        hand_position=value.hand_position,
        piece=value.piece,
        sticking=value.sticking,
        hit_technique=value.hit_technique,
        hand=value.hand,
        finger=value.finger,
        pedal=value.pedal,
    )


def _song_confidence(note: ScoreNote) -> NoteConfidence | None:
    raw = note.properties.get("confidence")
    if not isinstance(raw, dict):
        return None
    try:
        return NoteConfidence(
            rhythm=float(raw["rhythm"]),
            fingering=float(raw["fingering"]),
            articulation=(
                float(raw["articulation"])
                if raw.get("articulation") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def score_document_to_song_ir(document: ScoreDocument) -> SongIR:
    """Create a read-only SongIR exporter view of one pinned document revision."""

    tracks: list[InstrumentTrackIR] = []
    dynamics_by_note = {
        note.id: str(beat.properties["dynamic"])
        for track in document.tracks
        for measure in track.measures
        for beat in measure.beats
        if beat.properties.get("dynamic") is not None
        for note in beat.notes
    }
    for track in document.tracks:
        measures: list[ScoreMeasureIR] = []
        fallback_source_track = (
            track.source_track_indices[0] if track.source_track_indices else -1
        )
        for measure in track.measures:
            events: list[ScoreEventIR] = []
            for beat in measure.beats:
                if beat.kind == "rest":
                    continue
                for note in beat.notes:
                    source = note.source
                    events.append(
                        ScoreEventIR(
                            id=note.id,
                            pitch=note.pitch,
                            score=ScoreTiming(
                                start_beat=beat.start.to_float(),
                                duration_beats=beat.duration.to_float(),
                                measure_number=measure.number,
                                beat_in_measure=(beat.start - measure.start).to_float(),
                                voice=beat.voice,
                                tie_in=beat.tie_in,
                                tie_out=beat.tie_out,
                            ),
                            source=SongSourceNoteReference(
                                source_track_index=(
                                    source.source_track_index
                                    if source is not None
                                    else fallback_source_track
                                ),
                                source_note_index=(
                                    source.source_note_index if source is not None else -1
                                ),
                                origin=source.origin if source is not None else "editor",
                            ),
                            realization=_song_realization(note.realization),
                            technique_ids=list(note.technique_ids),
                            confidence=_song_confidence(note),
                        )
                    )
            measures.append(
                ScoreMeasureIR(
                    number=measure.number,
                    start_beat=measure.start.to_float(),
                    duration_beats=measure.duration.to_float(),
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    events=events,
                    annotations=dict(measure.annotations),
                )
            )
        tracks.append(
            InstrumentTrackIR(
                id=track.id,
                name=track.name,
                family=track.family,
                role=track.role,
                source_track_indices=list(track.source_track_indices),
                instrument={
                    **track.instrument,
                    "notation_mode": track.notation_mode,
                    "mixer": asdict(track.mixer),
                },
                measures=measures,
            )
        )

    issue_track_ids = {track.id for track in document.tracks}
    return SongIR(
        title=document.title,
        source=SourceLayer(
            filename=document.source.filename,
            sha256=document.source.sha256,
            midi_type=document.source.midi_type,
            ticks_per_beat=document.source.ticks_per_beat,
            note_count=document.source.note_count,
            duration_beats=document.source.duration.to_float(),
            tracks=[
                SourceTrackIR(
                    index=value.index,
                    name=value.name,
                    instrument_name=value.instrument_name,
                    program=value.program,
                    note_count=value.note_count,
                )
                for value in document.source.tracks
            ],
        ),
        analysis=AnalysisLayer(
            style_label=document.analysis.style_label,
            key_signature=document.analysis.key_signature,
            sections=list(document.analysis.sections),
            chord_symbols=list(document.analysis.chord_symbols),
            track_assignments=[
                TrackAssignment(
                    source_track_index=value.source_track_index,
                    family=value.family,
                    confidence=value.confidence,
                    reason=value.reason,
                    user_overridden=value.user_overridden,
                )
                for value in document.analysis.track_assignments
            ],
            unresolved_events=[
                SongUnresolvedSourceEvent(
                    source_track_index=value.source_track_index,
                    source_note_index=value.source_note_index,
                    pitch=value.pitch,
                    start_beat=value.start.to_float(),
                    duration_beats=value.duration.to_float(),
                    reason=value.reason,
                )
                for value in document.unresolved_events
            ],
        ),
        score=ScoreLayer(
            tempo_map=[
                IRTempoEvent(beat=value.position.to_float(), bpm=value.bpm)
                for value in document.tempo_map
            ],
            time_signatures=[
                IRTimeSignatureEvent(
                    beat=value.position.to_float(),
                    numerator=value.numerator,
                    denominator=value.denominator,
                )
                for value in document.time_signatures
            ],
            tracks=tracks,
            techniques=[
                TechniqueIR(
                    id=value.id,
                    type=value.type,
                    note_ids=list(value.note_ids),
                    confidence=value.confidence,
                    reason=value.reason,
                    parameters=dict(value.parameters),
                )
                for value in document.techniques
            ],
        ),
        performance=SongPerformanceLayer(
            profile_id=document.performance.profile_id,
            events=[
                PerformanceEventIR(
                    note_id=value.note_id,
                    start_beat=value.start.to_float(),
                    duration_beats=value.duration.to_float(),
                    velocity=value.velocity,
                    controls=(
                        [
                            control
                            for control in value.controls
                            if control.get("type") != "dynamic"
                        ]
                        + [{"type": "dynamic", "value": dynamics_by_note[value.note_id]}]
                        if value.note_id in dynamics_by_note
                        else list(value.controls)
                    ),
                )
                for value in document.performance.events
            ],
        ),
        validation=ValidationLayer(
            status=document.validation.status,
            issues=[
                ValidationIssue(
                    code=value.code,
                    severity=value.severity,
                    message=value.message,
                    track_id=next(
                        (entity for entity in value.entity_ids if entity in issue_track_ids),
                        None,
                    ),
                    note_ids=[
                        entity for entity in value.entity_ids if entity not in issue_track_ids
                    ],
                )
                for value in document.validation.issues
            ],
        ),
        pins=ReproducibilityPins(
            application_version=document.pins.application_version,
            knowledge_snapshot=document.pins.knowledge_snapshot,
            model_provider=document.pins.model_provider,
            model_name=document.pins.model_name,
            prompt_version=document.pins.prompt_version,
            sound_profile=document.pins.sound_profile,
        ),
        arrangement_mode=document.arrangement_mode,
        knowledge=(
            IRKnowledgeReference(
                snapshot_version=document.knowledge.snapshot_version,
                kb_versions=dict(document.knowledge.kb_versions),
                entry_ids=list(document.knowledge.entry_ids),
            )
            if document.knowledge is not None
            else None
        ),
        changes=[
            Transformation(
                id=value.id,
                stage=value.stage,
                source_note_index=value.source_note_index,
                before=dict(value.before),
                after=dict(value.after),
                confidence=value.confidence,
                reason=value.reason,
                knowledge_ref=value.knowledge_ref,
            )
            for value in document.transformations
        ],
        warnings=list(document.warnings),
    )


__all__ = ["score_document_to_song_ir", "song_ir_to_score_document"]

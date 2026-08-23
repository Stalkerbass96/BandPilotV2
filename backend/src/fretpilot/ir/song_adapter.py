"""Adapters between instrument working IRs and canonical SongIR 2.0."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from fretpilot import __version__
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
    PerformanceTiming,
    Transformation,
)
from fretpilot.ir.pitched_models import PitchedProjectIR
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
    ValidationLayer,
)
from fretpilot.midi.models import NormalizedTimeline
from fretpilot.orchestrator.detector import TrackFamilyClassification


def _source_hash(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _knowledge(
    guitar: GuitarProjectIR | None,
    drums: DrumProjectIR | None,
    pitched: Iterable[PitchedProjectIR] = (),
) -> IRKnowledgeReference | None:
    references = [
        ir.knowledge
        for ir in (guitar, drums, *pitched)
        if ir is not None and ir.knowledge is not None
    ]
    if not references:
        return None
    first = references[0]
    return IRKnowledgeReference(
        snapshot_version=first.snapshot_version,
        kb_versions={key: value for ref in references for key, value in ref.kb_versions.items()},
        entry_ids=list(dict.fromkeys(entry for ref in references for entry in ref.entry_ids)),
    )


def _canonical_note_id(track_id: str, local_id: str) -> str:
    return f"{track_id}:{local_id}"


def _guitar_tracks(
    guitar: GuitarProjectIR | None,
) -> tuple[
    list[InstrumentTrackIR],
    list[TechniqueIR],
    list[PerformanceEventIR],
    list[UnresolvedSourceEvent],
]:
    if guitar is None:
        return [], [], [], []
    tracks: list[InstrumentTrackIR] = []
    techniques: list[TechniqueIR] = []
    performance: list[PerformanceEventIR] = []
    unresolved: list[UnresolvedSourceEvent] = []
    for track in guitar.tracks:
        local_to_canonical = {
            event.id: _canonical_note_id(track.id, event.id)
            for measure in track.measures
            for event in measure.events
            if event.fingering.string is not None and event.fingering.fret is not None
        }
        measures: list[ScoreMeasureIR] = []
        for measure in track.measures:
            events: list[ScoreEventIR] = []
            for event in measure.events:
                if event.fingering.string is None or event.fingering.fret is None:
                    unresolved.append(
                        UnresolvedSourceEvent(
                            source_track_index=track.source_track_index or 0,
                            source_note_index=event.source_note_index,
                            pitch=event.pitch,
                            start_beat=event.performance.source_start_beat,
                            duration_beats=event.performance.source_duration_beats,
                            reason="pitch has no playable position on the resolved instrument",
                        )
                    )
                    continue
                note_id = local_to_canonical[event.id]
                technique_ids: list[str] = []
                for sequence, articulation in enumerate(event.articulations, start=1):
                    technique_id = f"tech:{note_id}:{sequence}"
                    related = []
                    if articulation.source_note_id:
                        source_id = local_to_canonical.get(articulation.source_note_id)
                        if source_id:
                            related.append(source_id)
                    related.append(note_id)
                    techniques.append(
                        TechniqueIR(
                            id=technique_id,
                            type=articulation.type,
                            note_ids=list(dict.fromkeys(related)),
                            confidence=articulation.confidence,
                            reason=articulation.reason,
                            parameters=dict(articulation.parameters),
                        )
                    )
                    technique_ids.append(technique_id)
                events.append(
                    ScoreEventIR(
                        id=note_id,
                        pitch=event.pitch,
                        score=event.score,
                        source=SourceNoteReference(
                            source_track_index=track.source_track_index or 0,
                            source_note_index=event.source_note_index,
                            origin=event.source_note_origin,
                        ),
                        realization=InstrumentRealization(
                            kind="guitar",
                            string=event.fingering.string,
                            fret=event.fingering.fret,
                            fretting_digit=event.fingering.fretting_digit,
                            hand_position=event.fingering.hand_position,
                        ),
                        technique_ids=technique_ids,
                        confidence=event.confidence,
                    )
                )
                performance.append(
                    PerformanceEventIR(
                        note_id=note_id,
                        start_beat=event.performance.source_start_beat,
                        duration_beats=event.performance.source_duration_beats,
                        velocity=event.performance.velocity,
                    )
                )
            measures.append(
                ScoreMeasureIR(
                    number=measure.number,
                    start_beat=measure.start_beat,
                    duration_beats=measure.duration_beats,
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    events=events,
                )
            )
        tracks.append(
            InstrumentTrackIR(
                id=track.id,
                name=track.name,
                family="guitar",
                role=track.role,
                source_track_indices=(
                    [track.source_track_index] if track.source_track_index is not None else []
                ),
                instrument={"tuning": list(track.tuning), "fret_count": track.fret_count},
                measures=measures,
            )
        )
    return tracks, techniques, performance, unresolved


def _drum_tracks(
    drums: DrumProjectIR | None,
) -> tuple[list[InstrumentTrackIR], list[TechniqueIR], list[PerformanceEventIR]]:
    if drums is None:
        return [], [], []
    tracks: list[InstrumentTrackIR] = []
    techniques: list[TechniqueIR] = []
    performance: list[PerformanceEventIR] = []
    for track in drums.tracks:
        measures: list[ScoreMeasureIR] = []
        for measure in track.measures:
            events: list[ScoreEventIR] = []
            for event in measure.events:
                note_id = _canonical_note_id(track.id, event.id)
                technique_ids: list[str] = []
                if event.location.technique and event.location.technique != "normal":
                    technique_id = f"tech:{note_id}:1"
                    techniques.append(
                        TechniqueIR(
                            id=technique_id,
                            type=event.location.technique,
                            note_ids=[note_id],
                            confidence=(event.confidence.articulation if event.confidence else 0.5) or 0.5,
                            reason="drum pipeline technique",
                        )
                    )
                    technique_ids.append(technique_id)
                events.append(
                    ScoreEventIR(
                        id=note_id,
                        pitch=event.pitch,
                        score=event.score,
                        source=SourceNoteReference(
                            source_track_index=track.source_track_index or 0,
                            source_note_index=event.source_note_index,
                        ),
                        realization=InstrumentRealization(
                            kind="drums",
                            piece=event.piece,
                            sticking=event.location.sticking,
                            hit_technique=event.location.technique,
                        ),
                        technique_ids=technique_ids,
                        confidence=event.confidence,
                    )
                )
                performance.append(
                    PerformanceEventIR(
                        note_id=note_id,
                        start_beat=event.performance.source_start_beat,
                        duration_beats=event.performance.source_duration_beats,
                        velocity=event.performance.velocity,
                    )
                )
            measures.append(
                ScoreMeasureIR(
                    number=measure.number,
                    start_beat=measure.start_beat,
                    duration_beats=measure.duration_beats,
                    numerator=measure.numerator,
                    denominator=measure.denominator,
                    events=events,
                    annotations={"pattern": measure.pattern},
                )
            )
        tracks.append(
            InstrumentTrackIR(
                id=track.id,
                name=track.name,
                family="drums",
                role="drums",
                source_track_indices=(
                    [track.source_track_index] if track.source_track_index is not None else []
                ),
                instrument={"kit": track.kit, "style": track.style},
                measures=measures,
            )
        )
    return tracks, techniques, performance


def _pitched_tracks(
    projects: Iterable[PitchedProjectIR],
) -> tuple[list[InstrumentTrackIR], list[PerformanceEventIR], list[UnresolvedSourceEvent]]:
    tracks: list[InstrumentTrackIR] = []
    performance: list[PerformanceEventIR] = []
    unresolved: list[UnresolvedSourceEvent] = []
    for project in projects:
        for track in project.tracks:
            measures: list[ScoreMeasureIR] = []
            for measure in track.measures:
                events: list[ScoreEventIR] = []
                for event in measure.events:
                    if event.unresolved_reason:
                        unresolved.append(
                            UnresolvedSourceEvent(
                                source_track_index=track.source_track_index,
                                source_note_index=event.source_note_index,
                                pitch=event.pitch,
                                start_beat=event.performance.source_start_beat,
                                duration_beats=event.performance.source_duration_beats,
                                reason=event.unresolved_reason,
                            )
                        )
                        continue
                    note_id = _canonical_note_id(track.id, event.id)
                    realization = event.realization
                    events.append(
                        ScoreEventIR(
                            id=note_id,
                            pitch=event.pitch,
                            score=event.score,
                            source=SourceNoteReference(
                                source_track_index=track.source_track_index,
                                source_note_index=event.source_note_index,
                            ),
                            realization=InstrumentRealization(
                                kind=realization.kind,
                                string=realization.string,
                                fret=realization.fret,
                                fretting_digit=realization.fretting_digit,
                                hand_position=realization.hand_position,
                                hand=realization.hand,
                                finger=realization.finger,
                                pedal=realization.pedal,
                            ),
                            confidence=event.confidence,
                        )
                    )
                    performance.append(
                        PerformanceEventIR(
                            note_id=note_id,
                            start_beat=event.performance.source_start_beat,
                            duration_beats=event.performance.source_duration_beats,
                            velocity=event.performance.velocity,
                        )
                    )
                measures.append(
                    ScoreMeasureIR(
                        number=measure.number,
                        start_beat=measure.start_beat,
                        duration_beats=measure.duration_beats,
                        numerator=measure.numerator,
                        denominator=measure.denominator,
                        events=events,
                    )
                )
            tracks.append(
                InstrumentTrackIR(
                    id=track.id,
                    name=track.name,
                    family=track.family,
                    role=track.role,
                    source_track_indices=[track.source_track_index],
                    instrument=dict(track.instrument),
                    measures=measures,
                )
            )
    return tracks, performance, unresolved


def build_song_ir(
    *,
    title: str,
    source_path: Path | None,
    source_filename: str,
    timeline: NormalizedTimeline,
    classifications: Iterable[TrackFamilyClassification],
    guitar: GuitarProjectIR | None,
    drums: DrumProjectIR | None,
    pitched: Iterable[PitchedProjectIR] = (),
    arrangement_mode: str = "faithful",
    model_provider: str = "none",
    model_name: str = "none",
    prompt_version: str = "none",
) -> SongIR:
    pitched = list(pitched)
    guitar_tracks, guitar_techniques, guitar_performance, unresolved = _guitar_tracks(guitar)
    drum_tracks, drum_techniques, drum_performance = _drum_tracks(drums)
    pitched_tracks, pitched_performance, pitched_unresolved = _pitched_tracks(pitched)
    unresolved.extend(pitched_unresolved)
    knowledge = _knowledge(guitar, drums, pitched)
    style_label = "unknown"
    if guitar and guitar.style_label != "unknown":
        style_label = guitar.style_label
    elif drums and drums.style_label != "unknown":
        style_label = drums.style_label
    elif next((ir.style_label for ir in pitched if ir.style_label != "unknown"), None):
        style_label = next(ir.style_label for ir in pitched if ir.style_label != "unknown")

    changes: list[Transformation] = []
    warnings: list[str] = []
    for ir in (guitar, drums, *pitched):
        if ir is not None:
            changes.extend(ir.changes)
            warnings.extend(ir.warnings)

    return SongIR(
        title=title,
        source=SourceLayer(
            filename=source_filename,
            sha256=_source_hash(source_path),
            midi_type=timeline.midi_type,
            ticks_per_beat=timeline.ticks_per_beat,
            note_count=timeline.note_count,
            duration_beats=timeline.duration_beats,
            tracks=[
                SourceTrackIR(
                    index=track.index,
                    name=track.name,
                    instrument_name=track.instrument_name,
                    program=track.program,
                    note_count=len(track.notes),
                )
                for track in timeline.tracks
            ],
        ),
        analysis=AnalysisLayer(
            style_label=style_label,
            track_assignments=[
                TrackAssignment(
                    source_track_index=item.track_index,
                    family=item.family.value,
                    confidence=item.confidence,
                    reason=item.reason,
                    user_overridden=getattr(item, "user_overridden", False),
                )
                for item in classifications
            ],
            unresolved_events=unresolved,
        ),
        score=ScoreLayer(
            tempo_map=list((guitar or drums or (pitched[0] if pitched else None)).tempo_map)
            if (guitar or drums or pitched)
            else [],
            time_signatures=list(
                (guitar or drums or (pitched[0] if pitched else None)).time_signatures
            )
            if (guitar or drums or pitched)
            else [],
            tracks=[*guitar_tracks, *drum_tracks, *pitched_tracks],
            techniques=[*guitar_techniques, *drum_techniques],
        ),
        performance=PerformanceLayer(
            events=[*guitar_performance, *drum_performance, *pitched_performance]
        ),
        validation=ValidationLayer(),
        pins=ReproducibilityPins(
            application_version=__version__,
            knowledge_snapshot=knowledge.snapshot_version if knowledge else "unknown",
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
        ),
        arrangement_mode=arrangement_mode,
        knowledge=knowledge,
        changes=changes,
        warnings=warnings,
    )


def _local_note_id(canonical_id: str) -> str:
    return canonical_id.rsplit(":", 1)[-1]


def _techniques_for_event(
    song: SongIR,
    technique_ids: list[str],
    event_id: str,
) -> list[IRArticulation]:
    by_id = {technique.id: technique for technique in song.score.techniques}
    articulations: list[IRArticulation] = []
    for technique_id in technique_ids:
        technique = by_id.get(technique_id)
        if technique is None:
            continue
        source_note_id = next(
            (
                _local_note_id(note_id)
                for note_id in technique.note_ids
                if note_id != event_id
            ),
            None,
        )
        articulations.append(
            IRArticulation(
                type=technique.type,
                confidence=technique.confidence,
                reason=technique.reason,
                source_note_id=source_note_id,
                parameters=dict(technique.parameters),
            )
        )
    return articulations


def song_to_legacy(
    song: SongIR,
) -> tuple[GuitarProjectIR | None, DrumProjectIR | None]:
    """Create read-only exporter views from canonical SongIR.

    These views are derived at the export boundary and are never persisted as
    a second editable source of truth.
    """

    performance = {event.note_id: event for event in song.performance.events}
    guitar_tracks: list[GuitarTrackIR] = []
    drum_tracks: list[DrumTrackIR] = []

    for track in song.score.tracks:
        if track.family in {"guitar", "bass"}:
            measures: list[GuitarMeasure] = []
            for measure in track.measures:
                events: list[GuitarNoteEvent] = []
                for event in measure.events:
                    perf = performance[event.id]
                    events.append(
                        GuitarNoteEvent(
                            id=_local_note_id(event.id),
                            source_note_index=event.source.source_note_index,
                            pitch=event.pitch,
                            score=event.score,
                            performance=PerformanceTiming(
                                source_start_beat=perf.start_beat,
                                source_duration_beats=perf.duration_beats,
                                velocity=perf.velocity,
                            ),
                            fingering=IRFingering(
                                string=event.realization.string,
                                fret=event.realization.fret,
                                fretting_digit=event.realization.fretting_digit,
                                hand_position=event.realization.hand_position,
                            ),
                            articulations=_techniques_for_event(
                                song, event.technique_ids, event.id
                            ),
                            confidence=event.confidence,
                            source_note_origin=event.source.origin,
                        )
                    )
                measures.append(
                    GuitarMeasure(
                        number=measure.number,
                        start_beat=measure.start_beat,
                        duration_beats=measure.duration_beats,
                        numerator=measure.numerator,
                        denominator=measure.denominator,
                        events=events,
                    )
                )
            guitar_tracks.append(
                GuitarTrackIR(
                    id=track.id,
                    name=track.name,
                    source_track_index=(
                        track.source_track_indices[0] if track.source_track_indices else None
                    ),
                    role=track.family if track.family == "bass" else track.role,
                    tuning=[int(value) for value in track.instrument.get("tuning", [])],
                    fret_count=int(track.instrument.get("fret_count", 24)),
                    measures=measures,
                )
            )
        elif track.family == "drums":
            measures_drum: list[DrumMeasure] = []
            for measure in track.measures:
                events_drum: list[DrumNoteEvent] = []
                for event in measure.events:
                    perf = performance[event.id]
                    events_drum.append(
                        DrumNoteEvent(
                            id=_local_note_id(event.id),
                            source_note_index=event.source.source_note_index,
                            pitch=event.pitch,
                            piece=event.realization.piece or "unknown",
                            score=event.score,
                            performance=PerformanceTiming(
                                source_start_beat=perf.start_beat,
                                source_duration_beats=perf.duration_beats,
                                velocity=perf.velocity,
                            ),
                            location=DrumHitLocation(
                                piece=event.realization.piece or "unknown",
                                sticking=event.realization.sticking or "",
                                technique=event.realization.hit_technique or "normal",
                            ),
                            confidence=event.confidence,
                        )
                    )
                measures_drum.append(
                    DrumMeasure(
                        number=measure.number,
                        start_beat=measure.start_beat,
                        duration_beats=measure.duration_beats,
                        numerator=measure.numerator,
                        denominator=measure.denominator,
                        pattern=str(measure.annotations.get("pattern", "unknown")),
                        events=events_drum,
                    )
                )
            drum_tracks.append(
                DrumTrackIR(
                    id=track.id,
                    name=track.name,
                    source_track_index=(
                        track.source_track_indices[0] if track.source_track_indices else None
                    ),
                    kit=str(track.instrument.get("kit", "standard_5pc")),
                    style=str(track.instrument.get("style", "unknown")),
                    measures=measures_drum,
                )
            )

    guitar = (
        GuitarProjectIR(
            title=song.title,
            source=song.source.filename,
            tempo_map=list(song.score.tempo_map),
            time_signatures=list(song.score.time_signatures),
            tracks=guitar_tracks,
            knowledge=song.knowledge,
            style_label=song.analysis.style_label,
            changes=list(song.changes),
            warnings=list(song.warnings),
        )
        if guitar_tracks
        else None
    )
    drums = (
        DrumProjectIR(
            title=song.title,
            source=song.source.filename,
            tempo_map=list(song.score.tempo_map),
            time_signatures=list(song.score.time_signatures),
            tracks=drum_tracks,
            knowledge=song.knowledge,
            style_label=song.analysis.style_label,
            changes=list(song.changes),
            warnings=list(song.warnings),
        )
        if drum_tracks
        else None
    )
    return guitar, drums


__all__ = ["build_song_ir", "song_to_legacy"]

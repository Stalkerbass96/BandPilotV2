"""Create truthful revision-zero ScoreDocuments from blank input or raw MIDI.

Raw MIDI is deliberately represented as generic standard notation.  Detected
instrument families remain analysis metadata until the prepare/playability
workflow proposes a validated physical realization; import never invents
guitar fingering, drum pieces or keyboard hands merely to satisfy a schema.
"""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction

from fretpilot import __version__
from fretpilot.editor.document import (
    AnalysisSnapshot,
    DocumentPins,
    DocumentSource,
    DocumentSourceTrack,
    DocumentTrackAssignment,
    DocumentValidationState,
    InstrumentRealization,
    PerformanceEvent,
    PerformanceLayer,
    Rational,
    ScoreBeat,
    ScoreDocument,
    ScoreMeasure,
    ScoreNote,
    ScoreStaff,
    ScoreTrack,
    SourceNoteReference,
    TempoChange,
    TimeSignatureChange,
    UnresolvedSourceEvent,
)
from fretpilot.midi.models import NormalizedTimeline
from fretpilot.orchestrator.detector import TrackFamilyClassification

MAX_RAW_IMPORT_MEASURES = 10_000
_BLANK_FAMILIES = frozenset({"guitar", "drums", "bass", "keys", "generic"})


def _measure_length(numerator: int, denominator: int) -> Rational:
    value = Fraction(numerator * 4, denominator)
    return Rational(value.numerator, value.denominator)


def _signature_events(timeline: NormalizedTimeline) -> list[tuple[Rational, int, int]]:
    by_position: dict[Rational, tuple[int, int]] = {}
    for event in timeline.time_signature_events:
        by_position[Rational(event.tick, timeline.ticks_per_beat)] = (
            event.numerator,
            event.denominator,
        )
    by_position.setdefault(Rational(0), timeline.initial_time_signature)
    return [
        (position, values[0], values[1])
        for position, values in sorted(by_position.items(), key=lambda item: item[0])
    ]


def _measure_grid(timeline: NormalizedTimeline) -> list[ScoreMeasure]:
    signatures = _signature_events(timeline)
    source_end = max(
        (
            Rational(note.end_tick, timeline.ticks_per_beat)
            for track in timeline.tracks
            for note in track.notes
        ),
        default=Rational(0),
    )
    measures: list[ScoreMeasure] = []
    start = Rational(0)
    signature_index = 0
    while not measures or start < source_end:
        while (
            signature_index + 1 < len(signatures)
            and signatures[signature_index + 1][0] <= start
        ):
            signature_index += 1
        _position, numerator, denominator = signatures[signature_index]
        natural_end = start + _measure_length(numerator, denominator)
        next_signature = (
            signatures[signature_index + 1][0]
            if signature_index + 1 < len(signatures)
            else None
        )
        end = (
            next_signature
            if next_signature is not None and start < next_signature < natural_end
            else natural_end
        )
        if end <= start:
            raise ValueError("MIDI time-signature map cannot produce a positive measure")
        number = len(measures) + 1
        measures.append(
            ScoreMeasure(
                id=f"raw-measure:{number}",
                number=number,
                start=start,
                duration=end - start,
                numerator=numerator,
                denominator=denominator,
            )
        )
        if len(measures) > MAX_RAW_IMPORT_MEASURES:
            raise ValueError(
                f"Raw MIDI exceeds the {MAX_RAW_IMPORT_MEASURES}-measure import limit"
            )
        start = end
    return measures


def _blank_staffs(track_id: str, family: str) -> list[ScoreStaff]:
    if family in {"guitar", "bass"}:
        return [
            ScoreStaff(
                id=f"{track_id}:staff:standard-tab",
                order=0,
                kind="standard_tab",
            )
        ]
    if family == "drums":
        return [
            ScoreStaff(
                id=f"{track_id}:staff:percussion",
                order=0,
                kind="percussion",
            )
        ]
    if family == "keys":
        return [
            ScoreStaff(id=f"{track_id}:staff:treble", order=0, kind="treble"),
            ScoreStaff(id=f"{track_id}:staff:bass", order=1, kind="bass"),
        ]
    return [ScoreStaff(id=f"{track_id}:staff:standard", order=0, kind="standard")]


def _blank_instrument(family: str) -> dict[str, object]:
    if family == "guitar":
        return {"tuning": [40, 45, 50, 55, 59, 64], "fret_count": 24}
    if family == "bass":
        return {"tuning": [28, 33, 38, 43], "fret_count": 24}
    if family == "drums":
        return {"kit": "standard_5pc"}
    return {}


def blank_score_document(
    *,
    document_id: str,
    title: str,
    family: str = "guitar",
    bpm: float = 120.0,
    numerator: int = 4,
    denominator: int = 4,
) -> ScoreDocument:
    """Build one empty, valid measure for a new score project."""

    if family not in _BLANK_FAMILIES:
        raise ValueError(f"Unsupported blank score family: {family!r}")
    if bpm <= 0 or numerator <= 0 or denominator <= 0:
        raise ValueError("Tempo and time signature must be positive")
    track_id = "track:1"
    duration = _measure_length(numerator, denominator)
    staff = _blank_staffs(track_id, family)
    return ScoreDocument(
        id=document_id,
        title=title,
        source=DocumentSource(
            filename="",
            sha256="",
            midi_type=1,
            ticks_per_beat=480,
            note_count=0,
            duration=duration,
        ),
        analysis=AnalysisSnapshot(),
        tracks=[
            ScoreTrack(
                id=track_id,
                order=0,
                name=family.title(),
                family=family,
                role="unknown",
                source_track_indices=[],
                instrument=_blank_instrument(family),
                staves=staff,
                notation_mode=(
                    "standard_tab"
                    if family in {"guitar", "bass"}
                    else "percussion"
                    if family == "drums"
                    else "grand_staff"
                    if family == "keys"
                    else "standard"
                ),
                measures=[
                    ScoreMeasure(
                        id=f"{track_id}:measure:1",
                        number=1,
                        start=Rational(0),
                        duration=duration,
                        numerator=numerator,
                        denominator=denominator,
                    )
                ],
            )
        ],
        tempo_map=[TempoChange(id="tempo:1", position=Rational(0), bpm=bpm)],
        time_signatures=[
            TimeSignatureChange(
                id="time-signature:1",
                position=Rational(0),
                numerator=numerator,
                denominator=denominator,
            )
        ],
        techniques=[],
        performance=PerformanceLayer(profile_id="source-preserved"),
        unresolved_events=[],
        validation=DocumentValidationState(),
        pins=DocumentPins(
            application_version=__version__, knowledge_snapshot="not-applied"
        ),
    )


def timeline_to_raw_score_document(
    timeline: NormalizedTimeline,
    *,
    document_id: str,
    title: str,
    source_filename: str,
    source_sha256: str,
    classifications: list[TrackFamilyClassification],
) -> ScoreDocument:
    """Convert normalized MIDI into an exact-tick, non-fabricated score view."""

    classification_by_track = {value.track_index: value for value in classifications}
    measure_templates = _measure_grid(timeline)
    tracks: list[ScoreTrack] = []
    performance_events: list[PerformanceEvent] = []
    unresolved: list[UnresolvedSourceEvent] = []

    for track_order, source_track in enumerate(track for track in timeline.tracks if track.notes):
        track_id = f"raw-track:{source_track.index}"
        staff_id = f"{track_id}:staff:standard"
        measures = [
            ScoreMeasure(
                id=f"{track_id}:measure:{template.number}",
                number=template.number,
                start=template.start,
                duration=template.duration,
                numerator=template.numerator,
                denominator=template.denominator,
            )
            for template in measure_templates
        ]
        grouped: dict[
            tuple[int, Rational, Rational], list[tuple[ScoreNote, bool, bool]]
        ] = defaultdict(list)
        for source_note_index, source_note in enumerate(source_track.notes):
            if source_note.duration_ticks <= 0:
                unresolved.append(
                    UnresolvedSourceEvent(
                        id=(
                            f"unresolved:track:{source_track.index}:"
                            f"note:{source_note_index}"
                        ),
                        source_track_index=source_track.index,
                        source_note_index=source_note_index,
                        pitch=source_note.pitch,
                        start=Rational(source_note.start_tick, timeline.ticks_per_beat),
                        duration=Rational(0),
                        reason="MIDI note has zero written duration and needs review.",
                    )
                )
                continue
            note_start = Rational(source_note.start_tick, timeline.ticks_per_beat)
            note_end = Rational(source_note.end_tick, timeline.ticks_per_beat)
            covered = [
                (index, measure)
                for index, measure in enumerate(measures)
                if measure.start < note_end and measure.start + measure.duration > note_start
            ]
            for segment_index, (measure_index, measure) in enumerate(covered):
                segment_start = max(note_start, measure.start)
                segment_end = min(note_end, measure.start + measure.duration)
                if segment_end <= segment_start:
                    continue
                note_id = (
                    f"raw-note:track:{source_track.index}:source:{source_note_index}:"
                    f"segment:{segment_index}"
                )
                note = ScoreNote(
                    id=note_id,
                    pitch=source_note.pitch,
                    source=SourceNoteReference(
                        source_track_index=source_track.index,
                        source_note_index=source_note_index,
                    ),
                    realization=InstrumentRealization(kind="generic"),
                )
                duration = segment_end - segment_start
                grouped[(measure_index, segment_start, duration)].append(
                    (note, segment_index > 0, segment_index < len(covered) - 1)
                )
                performance_events.append(
                    PerformanceEvent(
                        id=f"performance:{note_id}",
                        note_id=note_id,
                        start=segment_start,
                        duration=duration,
                        velocity=max(1, min(127, source_note.velocity)),
                    )
                )

        beat_counter = 0
        for (measure_index, start, duration), values in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
        ):
            beat_counter += 1
            measures[measure_index].beats.append(
                ScoreBeat(
                    id=f"{track_id}:beat:{beat_counter}",
                    start=start,
                    duration=duration,
                    voice=1,
                    staff_id=staff_id,
                    notes=[value[0] for value in values],
                    tie_in=any(value[1] for value in values),
                    tie_out=any(value[2] for value in values),
                )
            )
        detected = classification_by_track.get(source_track.index)
        detected_family = detected.family.value if detected is not None else "unknown"
        tracks.append(
            ScoreTrack(
                id=track_id,
                order=track_order,
                name=source_track.name or f"Track {source_track.index + 1}",
                family="generic",
                role=f"raw_{detected_family}",
                source_track_indices=[source_track.index],
                instrument={
                    "detected_family": detected_family,
                    "source_program": source_track.program,
                    "realization_status": "unprepared",
                },
                staves=[
                    ScoreStaff(id=staff_id, order=0, kind="standard", line_count=5)
                ],
                measures=measures,
                notation_mode="standard",
            )
        )

    source_duration = max(
        (
            Rational(note.end_tick, timeline.ticks_per_beat)
            for track in timeline.tracks
            for note in track.notes
        ),
        default=Rational(0),
    )
    signatures = _signature_events(timeline)
    return ScoreDocument(
        id=document_id,
        title=title,
        source=DocumentSource(
            filename=source_filename,
            sha256=source_sha256,
            midi_type=timeline.midi_type,
            ticks_per_beat=timeline.ticks_per_beat,
            note_count=timeline.note_count,
            duration=source_duration,
            tracks=[
                DocumentSourceTrack(
                    id=f"source-track:{track.index}",
                    index=track.index,
                    name=track.name or f"Track {track.index + 1}",
                    instrument_name=track.instrument_name,
                    program=track.program,
                    note_count=len(track.notes),
                )
                for track in timeline.tracks
            ],
        ),
        analysis=AnalysisSnapshot(
            track_assignments=[
                DocumentTrackAssignment(
                    source_track_index=value.track_index,
                    family=value.family.value,
                    confidence=value.confidence,
                    reason=value.reason,
                    user_overridden=value.user_overridden,
                )
                for value in classifications
            ]
        ),
        tracks=tracks,
        tempo_map=(
            [
                TempoChange(
                    id=f"tempo:{index}",
                    position=Rational(event.tick, timeline.ticks_per_beat),
                    bpm=event.bpm,
                )
                for index, event in enumerate(timeline.tempo_events, start=1)
            ]
            if timeline.tempo_events
            else [TempoChange(id="tempo:1", position=Rational(0), bpm=120.0)]
        ),
        time_signatures=[
            TimeSignatureChange(
                id=f"time-signature:{index}",
                position=position,
                numerator=numerator,
                denominator=denominator,
            )
            for index, (position, numerator, denominator) in enumerate(
                signatures, start=1
            )
        ],
        techniques=[],
        performance=PerformanceLayer(
            profile_id="source-preserved", events=performance_events
        ),
        unresolved_events=unresolved,
        validation=DocumentValidationState(),
        pins=DocumentPins(
            application_version=__version__, knowledge_snapshot="not-applied"
        ),
        warnings=[
            "Raw MIDI uses generic standard notation until Prepare Score is applied."
        ],
    )


__all__ = ["blank_score_document", "timeline_to_raw_score_document"]

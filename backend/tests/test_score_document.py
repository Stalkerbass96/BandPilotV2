"""E0 contracts for ScoreDocument 3.0 and typed editor transactions."""

from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import fretpilot.editor.operations as editor_operations
from fretpilot.db.models import (
    Base,
    ExportRecord,
    Project,
    ScoreCommand,
    ScoreDocumentRecord,
    ScoreRevision,
    User,
)
from fretpilot.editor.document import (
    InstrumentRealization as DocumentInstrumentRealization,
)
from fretpilot.editor.document import (
    PerformanceEvent,
    Rational,
    ScoreBeat,
    ScoreMeasure,
    ScoreNote,
    ScoreStaff,
    ScoreTechnique,
    ScoreTrack,
    TempoChange,
    TimeSignatureChange,
    TrackMixer,
    UnresolvedSourceEvent,
)
from fretpilot.editor.operations import (
    AddNote,
    AddTechnique,
    DeleteBeat,
    DeleteNote,
    InsertBeat,
    InsertMeasureGroup,
    InsertTrack,
    ReorderTracks,
    ScoreConflictError,
    ScoreEditor,
    ScoreOperationError,
    ScoreTransaction,
    SetBeatDuration,
    SetBeatDynamic,
    SetBeatTie,
    SetBeatVoice,
    SetNoteFretting,
    SetNotePitch,
    SetPerformanceVelocity,
    SetTrackInstrument,
    SetTrackMixer,
    SetTrackName,
    SetTrackNotationMode,
    TrackMeasureEntry,
    transaction_fingerprint,
    transaction_from_dict,
    transaction_to_dict,
)
from fretpilot.editor.validation import (
    validate_score_document,
    validate_score_document_changes,
)
from fretpilot.ir.models import IRTempoEvent, IRTimeSignatureEvent, ScoreTiming
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
    document_to_api_dict,
    document_to_dict,
    load_score_document,
    save_score_document,
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
    ValidationLayer,
)
from fretpilot.midi.models import (
    NormalizedNote,
    NormalizedTimeline,
    NormalizedTrack,
    TempoEvent,
    TimeSignatureEvent,
)
from fretpilot.orchestrator.detector import InstrumentFamily, TrackFamilyClassification
from fretpilot.services.score_documents import (
    ScoreDocumentIntegrityError,
    append_system_snapshot,
    apply_score_transaction,
    create_score_document,
    load_score_document_revision,
)


def _event(
    note_id: str,
    pitch: int,
    *,
    track_index: int,
    start: float,
    duration: float = 0.5,
    voice: int = 1,
    realization: InstrumentRealization,
) -> ScoreEventIR:
    return ScoreEventIR(
        id=note_id,
        pitch=pitch,
        score=ScoreTiming(
            start_beat=start,
            duration_beats=duration,
            measure_number=1,
            beat_in_measure=start,
            voice=voice,
        ),
        source=SourceNoteReference(
            source_track_index=track_index,
            source_note_index=0,
        ),
        realization=realization,
    )


def _track(
    track_id: str,
    family: str,
    index: int,
    events: list[ScoreEventIR],
    *,
    instrument: dict,
) -> InstrumentTrackIR:
    return InstrumentTrackIR(
        id=track_id,
        name=family.title(),
        family=family,
        role=family,
        source_track_indices=[index],
        instrument=instrument,
        measures=[
            ScoreMeasureIR(
                number=1,
                start_beat=0.0,
                duration_beats=4.0,
                numerator=4,
                denominator=4,
                events=events,
            )
        ],
    )


def _mixed_song_ir() -> SongIR:
    guitar = _track(
        "track:guitar",
        "guitar",
        0,
        [
            _event(
                "note:guitar:e4",
                64,
                track_index=0,
                start=0.0,
                realization=InstrumentRealization(kind="guitar", string=1, fret=0),
            ),
            _event(
                "note:guitar:b3",
                59,
                track_index=0,
                start=0.0,
                realization=InstrumentRealization(kind="guitar", string=2, fret=0),
            ),
        ],
        instrument={"tuning": [40, 45, 50, 55, 59, 64], "fret_count": 24},
    )
    bass = _track(
        "track:bass",
        "bass",
        1,
        [
            _event(
                "note:bass:g2",
                43,
                track_index=1,
                start=1.0 / 3.0,
                realization=InstrumentRealization(kind="bass", string=1, fret=0),
            )
        ],
        instrument={"tuning": [28, 33, 38, 43], "fret_count": 24},
    )
    drums = _track(
        "track:drums",
        "drums",
        2,
        [
            _event(
                "note:drums:kick",
                36,
                track_index=2,
                start=0.0,
                voice=2,
                realization=InstrumentRealization(kind="drums", piece="kick"),
            ),
            _event(
                "note:drums:snare",
                38,
                track_index=2,
                start=0.0,
                voice=1,
                realization=InstrumentRealization(kind="drums", piece="snare"),
            ),
        ],
        instrument={"kit": "standard_5pc"},
    )
    keys = _track(
        "track:keys",
        "keys",
        3,
        [
            _event(
                "note:keys:left",
                48,
                track_index=3,
                start=0.0,
                realization=InstrumentRealization(kind="keys", hand="left", finger=1),
            ),
            _event(
                "note:keys:right",
                72,
                track_index=3,
                start=0.0,
                realization=InstrumentRealization(kind="keys", hand="right", finger=1),
            ),
        ],
        instrument={},
    )
    generic = _track(
        "track:generic",
        "generic",
        4,
        [
            _event(
                "note:generic:c4",
                60,
                track_index=4,
                start=1.0,
                realization=InstrumentRealization(kind="generic"),
            )
        ],
        instrument={},
    )
    tracks = [guitar, bass, drums, keys, generic]
    events = [event for track in tracks for measure in track.measures for event in measure.events]
    return SongIR(
        title="Editor mixed contract",
        source=SourceLayer(
            filename="mixed.mid",
            sha256="a" * 64,
            midi_type=1,
            ticks_per_beat=480,
            note_count=len(events),
            duration_beats=4.0,
            tracks=[
                SourceTrackIR(
                    index=index,
                    name=track.name,
                    instrument_name=track.family,
                    program=None,
                    note_count=sum(len(measure.events) for measure in track.measures),
                )
                for index, track in enumerate(tracks)
            ],
        ),
        analysis=AnalysisLayer(style_label="rock"),
        score=ScoreLayer(
            tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
            time_signatures=[IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)],
            tracks=tracks,
        ),
        performance=PerformanceLayer(
            events=[
                PerformanceEventIR(
                    note_id=event.id,
                    start_beat=event.score.start_beat,
                    duration_beats=event.score.duration_beats,
                    velocity=80,
                )
                for event in events
            ]
        ),
        validation=ValidationLayer(status="passed"),
        pins=ReproducibilityPins(
            application_version="test",
            knowledge_snapshot="test",
        ),
    )


def _document():
    return song_ir_to_score_document(_mixed_song_ir())


def _beat_for_note(document, note_id: str):
    return next(
        beat
        for track in document.tracks
        for measure in track.measures
        for beat in measure.beats
        if any(note.id == note_id for note in beat.notes)
    )


def _validation_issue_keys(state):
    return sorted(
        (
            issue.severity,
            issue.code,
            issue.message,
            tuple(issue.entity_ids),
        )
        for issue in state.issues
    )


def test_song_ir_adapter_has_stable_ids_exact_time_and_all_instrument_staves() -> None:
    first = _document()
    second = _document()

    assert validate_score_document(first).status == "passed"
    assert document_hash(first) == document_hash(second)
    assert canonical_document_json(first) == canonical_document_json(second)
    assert {track.family for track in first.tracks} == {
        "guitar",
        "drums",
        "bass",
        "keys",
        "generic",
    }
    assert {staff.kind for track in first.tracks for staff in track.staves} >= {
        "standard_tab",
        "percussion",
        "treble",
        "bass",
        "standard",
    }
    bass_beat = _beat_for_note(first, "note:bass:g2")
    assert bass_beat.start == Rational(1, 3)
    assert all(
        entity.id for track in first.tracks for entity in [track, *track.staves, *track.measures]
    )


def test_incremental_track_validation_matches_full_validation_and_preserves_warnings() -> None:
    document = _document()
    document.unresolved_events.append(
        UnresolvedSourceEvent(
            id="unresolved:test",
            source_track_index=0,
            source_note_index=99,
            pitch=67,
            start=Rational(2),
            duration=Rational(1, 2),
            reason="Keep this unrelated source warning.",
        )
    )
    previous = validate_score_document(document)
    assert previous.status == "passed"

    valid_candidate = copy.deepcopy(document)
    generic_note = next(
        note
        for track in valid_candidate.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
        if note.id == "note:generic:c4"
    )
    generic_note.pitch = 61
    incremental = validate_score_document_changes(
        valid_candidate,
        previous=previous,
        track_ids={"track:generic"},
        performance_note_ids=set(),
    )
    complete = validate_score_document(valid_candidate)
    assert _validation_issue_keys(incremental) == _validation_issue_keys(complete)
    assert any(issue.code == "source.unresolved_event" for issue in incremental.issues)

    invalid_candidate = copy.deepcopy(document)
    guitar_note = next(
        note
        for track in invalid_candidate.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
        if note.id == "note:guitar:e4"
    )
    guitar_note.pitch = 65
    incremental_invalid = validate_score_document_changes(
        invalid_candidate,
        previous=previous,
        track_ids={"track:guitar"},
        performance_note_ids=set(),
    )
    complete_invalid = validate_score_document(invalid_candidate)
    assert incremental_invalid.status == "failed"
    assert _validation_issue_keys(incremental_invalid) == _validation_issue_keys(
        complete_invalid
    )


def test_incremental_performance_validation_matches_full_validation() -> None:
    document = _document()
    previous = validate_score_document(document)
    candidate = copy.deepcopy(document)
    event = next(
        value
        for value in candidate.performance.events
        if value.note_id == "note:generic:c4"
    )
    event.velocity = 0

    incremental = validate_score_document_changes(
        candidate,
        previous=previous,
        track_ids=set(),
        performance_note_ids={event.note_id},
    )
    complete = validate_score_document(candidate)

    assert incremental.status == "failed"
    assert _validation_issue_keys(incremental) == _validation_issue_keys(complete)


def test_editor_uses_incremental_validation_only_for_narrow_field_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = ScoreEditor(_document())
    calls = {"complete": 0, "incremental": 0}
    complete_validator = editor_operations.validate_score_document
    incremental_validator = editor_operations.validate_score_document_changes

    def record_complete(document):
        calls["complete"] += 1
        return complete_validator(document)

    def record_incremental(document, **kwargs):
        calls["incremental"] += 1
        return incremental_validator(document, **kwargs)

    monkeypatch.setattr(editor_operations, "validate_score_document", record_complete)
    monkeypatch.setattr(
        editor_operations,
        "validate_score_document_changes",
        record_incremental,
    )

    editor.apply(
        ScoreTransaction(
            command_id="command:incremental-validation",
            document_id=editor.document.id,
            actor_id="user:1",
            base_revision=0,
            origin="manual",
            intent="Change one generic pitch",
            operations=(SetNotePitch("note:generic:c4", 61, 60),),
        )
    )
    assert calls == {"complete": 0, "incremental": 1}

    technique = ScoreTechnique(
        id="technique:full-validation",
        type="palm_mute",
        note_ids=["note:guitar:e4"],
        confidence=1.0,
        reason="structural validation routing test",
    )
    editor.apply(
        ScoreTransaction(
            command_id="command:full-validation",
            document_id=editor.document.id,
            actor_id="user:1",
            base_revision=1,
            origin="manual",
            intent="Add one technique",
            operations=(AddTechnique(technique),),
        )
    )
    assert calls == {"complete": 1, "incremental": 1}


def test_score_document_round_trip_and_canonical_hash_ignore_collection_order(tmp_path) -> None:
    document = _document()
    raw = document_to_dict(document)
    parsed = document_from_dict(raw)
    assert document_to_dict(parsed) == raw

    destination = tmp_path / "score_document.json"
    save_score_document(document, destination)
    assert document_to_dict(load_score_document(destination)) == raw

    reordered = copy.deepcopy(document)
    reordered.tracks.reverse()
    reordered.tempo_map.reverse()
    for track in reordered.tracks:
        track.measures.reverse()
        for measure in track.measures:
            measure.beats.reverse()
            for beat in measure.beats:
                beat.notes.reverse()
    assert document_hash(reordered) == document_hash(document)


def test_track_extension_defaults_preserve_old_hash_shape_but_api_is_explicit() -> None:
    document = _document()
    canonical = document_to_dict(document)
    assert all("mixer" not in track for track in canonical["tracks"])
    assert all("notation_mode" not in track for track in canonical["tracks"])
    api = document_to_api_dict(document)
    assert all("mixer" in track and "notation_mode" in track for track in api["tracks"])

    document.tracks[0].mixer.volume = 0.6
    changed = document_to_dict(document)
    assert changed["tracks"][0]["mixer"]["volume"] == 0.6


def test_score_document_rejects_unknown_major_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported ScoreDocument"):
        document_from_dict({"schema_version": "4.0"})


def test_score_document_export_view_preserves_score_and_performance_semantics() -> None:
    document = _document()
    song = score_document_to_song_ir(document)
    assert [track.family for track in song.score.tracks] == [
        track.family for track in document.tracks
    ]
    assert {
        event.id: (event.pitch, event.score.start_beat, event.score.duration_beats)
        for track in song.score.tracks
        for measure in track.measures
        for event in measure.events
    } == {
        note.id: (note.pitch, beat.start.to_float(), beat.duration.to_float())
        for track in document.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
    }
    assert {event.note_id for event in song.performance.events} == {
        event.note_id for event in document.performance.events
    }


def test_rational_normalizes_and_compares_exactly_with_integers() -> None:
    assert Rational(2, 6) == Rational(1, 3)
    assert Rational(0) == 0
    assert Rational(0) <= 0
    assert Rational(-1, 8) < 0
    assert len({Rational(1, 3), Rational(2, 6)}) == 1


def test_transaction_round_trip_apply_idempotency_and_one_step_undo() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    transaction = ScoreTransaction(
        command_id="command:set-generic-pitch",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Raise selected note",
        operations=(
            SetNotePitch(
                note_id="note:generic:c4",
                pitch=62,
                expected_pitch=60,
            ),
        ),
        created_at="2026-08-26T00:00:00+00:00",
    )
    parsed = transaction_from_dict(transaction_to_dict(transaction))
    assert parsed == transaction
    assert transaction_fingerprint(parsed) == transaction_fingerprint(transaction)

    applied = editor.apply(transaction)
    assert applied.revision == 1
    assert applied.document_hash != before_hash
    replayed = editor.apply(transaction)
    assert replayed.idempotent_replay is True
    assert editor.revision == 1

    undone = editor.undo(
        transaction.command_id,
        command_id="command:undo-generic-pitch",
        actor_id="user:1",
    )
    assert undone.revision == 2
    assert editor.document_hash == before_hash


def test_add_chord_note_round_trips_and_undo_restores_document_hash() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    beat = _beat_for_note(editor.document, "note:generic:c4")
    note = ScoreNote(
        id="note:generic:e4:manual",
        pitch=64,
        source=None,
        realization=DocumentInstrumentRealization(kind="generic"),
    )
    event = PerformanceEvent(
        id="performance:generic:e4:manual",
        note_id=note.id,
        start=beat.start,
        duration=beat.duration,
        velocity=84,
    )
    transaction = ScoreTransaction(
        command_id="command:add-chord-note",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Add E4 to selected chord",
        operations=(
            AddNote(
                beat_id=beat.id,
                note=note,
                performance_event=event,
                expected_beat_kind="notes",
            ),
        ),
        created_at="2026-08-27T00:00:00+00:00",
    )

    parsed = transaction_from_dict(transaction_to_dict(transaction))
    assert parsed == transaction
    editor.apply(parsed)
    changed = _beat_for_note(editor.document, note.id)
    assert {value.id for value in changed.notes} >= {"note:generic:c4", note.id}
    assert any(value.note_id == note.id for value in editor.document.performance.events)

    editor.undo(
        transaction.command_id,
        command_id="command:undo-add-chord-note",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_set_beat_voice_round_trips_and_undoes_atomically() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    beat = _beat_for_note(editor.document, "note:generic:c4")
    transaction = ScoreTransaction(
        command_id="command:set-voice-two",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Move selected beat to voice two",
        operations=(SetBeatVoice(beat.id, 2, expected_voice=beat.voice),),
    )

    assert transaction_from_dict(transaction_to_dict(transaction)) == transaction
    editor.apply(transaction)
    assert _beat_for_note(editor.document, "note:generic:c4").voice == 2
    editor.undo(
        transaction.command_id,
        command_id="command:undo-set-voice-two",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_tie_dynamic_and_velocity_round_trip_with_exact_undo() -> None:
    document = _document()
    source = _beat_for_note(document, "note:generic:c4")
    track = next(value for value in document.tracks if value.family == "generic")
    measure = track.measures[0]
    target = copy.deepcopy(source)
    target.id = "track:generic:measure:1:beat:tie-target"
    target.start = source.start + source.duration
    target.tie_in = False
    target.tie_out = False
    target.notes[0].id = "note:generic:c4:tie-target"
    target.notes[0].source = None
    measure.beats.append(target)
    document.performance.events.append(
        PerformanceEvent(
            id="performance:generic:c4:tie-target",
            note_id=target.notes[0].id,
            start=target.start,
            duration=target.duration,
            velocity=80,
        )
    )
    editor = ScoreEditor(document)
    before_hash = editor.document_hash
    transaction = ScoreTransaction(
        command_id="command:tie-and-dynamic",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Tie adjacent notes at forte",
        operations=(
            SetBeatTie(
                source.id,
                tie_in=False,
                tie_out=True,
                expected_tie_in=False,
                expected_tie_out=False,
            ),
            SetBeatTie(
                target.id,
                tie_in=True,
                tie_out=False,
                expected_tie_in=False,
                expected_tie_out=False,
            ),
            SetBeatDynamic(source.id, "f", expected_dynamic=None),
            SetPerformanceVelocity(
                "note:generic:c4",
                96,
                expected_velocity=80,
            ),
        ),
    )

    assert transaction_from_dict(transaction_to_dict(transaction)) == transaction
    editor.apply(transaction)
    changed_source = _beat_for_note(editor.document, "note:generic:c4")
    changed_target = _beat_for_note(editor.document, target.notes[0].id)
    assert changed_source.tie_out is True
    assert changed_target.tie_in is True
    assert changed_source.properties["dynamic"] == "f"
    assert next(
        value
        for value in editor.document.performance.events
        if value.note_id == "note:generic:c4"
    ).velocity == 96

    editor.undo(
        transaction.command_id,
        command_id="command:undo-tie-and-dynamic",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_manual_technique_updates_forward_and_reverse_references() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    technique = ScoreTechnique(
        id="technique:manual:palm-mute",
        type="palm_mute",
        note_ids=["note:guitar:e4"],
        confidence=1.0,
        reason="manual editor command",
    )
    transaction = ScoreTransaction(
        command_id="command:add-palm-mute",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Add palm mute",
        operations=(AddTechnique(technique),),
    )

    assert transaction_from_dict(transaction_to_dict(transaction)) == transaction
    editor.apply(transaction)
    changed = editor.document
    assert next(value for value in changed.techniques if value.id == technique.id) == technique
    changed_note = next(
        note
        for track in changed.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
        if note.id == "note:guitar:e4"
    )
    assert technique.id in changed_note.technique_ids

    editor.undo(
        transaction.command_id,
        command_id="command:undo-add-palm-mute",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_delete_last_note_converts_beat_to_rest_and_undo_restores_note() -> None:
    document = _document()
    beat = _beat_for_note(document, "note:generic:c4")
    removed_ids = {value.id for value in beat.notes if value.id != "note:generic:c4"}
    beat.notes = [value for value in beat.notes if value.id == "note:generic:c4"]
    document.performance.events = [
        value
        for value in document.performance.events
        if value.note_id not in removed_ids
    ]
    editor = ScoreEditor(document)
    before_hash = editor.document_hash
    transaction = ScoreTransaction(
        command_id="command:delete-last-note",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Turn the selected beat into a rest",
        operations=(
            DeleteNote(
                beat_id=beat.id,
                note_id="note:generic:c4",
            ),
        ),
    )

    editor.apply(transaction)
    changed = next(
        candidate
        for track in editor.document.tracks
        for measure in track.measures
        for candidate in measure.beats
        if candidate.id == beat.id
    )
    assert changed.kind == "rest"
    assert changed.notes == []
    assert all(
        value.note_id != "note:generic:c4" for value in editor.document.performance.events
    )

    editor.undo(
        transaction.command_id,
        command_id="command:undo-delete-last-note",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_insert_measure_group_shifts_score_wide_timeline_and_undoes_exactly() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    original = editor.document
    entries = tuple(
        TrackMeasureEntry(
            track_id=track.id,
            measure=ScoreMeasure(
                id=f"measure:inserted:{track.id}",
                number=1,
                start=Rational(0),
                duration=Rational(4),
                numerator=4,
                denominator=4,
            ),
        )
        for track in original.tracks
    )
    transaction = ScoreTransaction(
        command_id="command:insert-measure-group",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Insert a measure before bar one",
        operations=(
            InsertMeasureGroup(
                entries=entries,
                tempo_changes=(
                    TempoChange("tempo:inserted", Rational(0), 120.0),
                ),
                time_signatures=(
                    TimeSignatureChange("timesig:inserted", Rational(0), 4, 4),
                ),
            ),
        ),
    )

    assert transaction_from_dict(transaction_to_dict(transaction)) == transaction
    editor.apply(transaction)
    changed = editor.document
    assert all(len(track.measures) == 2 for track in changed.tracks)
    assert all(
        [measure.number for measure in track.measures] == [1, 2]
        for track in changed.tracks
    )
    shifted = _beat_for_note(changed, "note:generic:c4")
    assert shifted.start == Rational(5)
    shifted_event = next(
        value for value in changed.performance.events if value.note_id == "note:generic:c4"
    )
    assert shifted_event.start == Rational(5)
    assert sorted(value.position for value in changed.tempo_map) == [Rational(0), Rational(4)]

    editor.undo(
        transaction.command_id,
        command_id="command:undo-insert-measure-group",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_track_surface_operations_serialize_and_undo_exactly() -> None:
    editor = ScoreEditor(
        blank_score_document(document_id="document:tracks", title="Track surface")
    )
    before_hash = editor.document_hash
    measure = copy.deepcopy(editor.document.tracks[0].measures[0])
    measure.id = "track:bass:measure:1"
    measure.beats = []
    track = ScoreTrack(
        id="track:bass",
        order=1,
        name="Bass 2",
        family="bass",
        role="bass",
        source_track_indices=[],
        instrument={"tuning": [28, 33, 38, 43], "fret_count": 24, "capo": 0},
        staves=[
            ScoreStaff("track:bass:staff:standard-tab", 0, "standard_tab")
        ],
        measures=[measure],
        notation_mode="standard_tab",
        mixer=TrackMixer(),
    )
    transaction = ScoreTransaction(
        command_id="command:track-surface",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Create and configure a bass track",
        operations=(
            InsertTrack(track),
            SetTrackName("track:bass", "Low Bass", "Bass 2"),
            SetTrackInstrument(
                "track:bass",
                {"tuning": [28, 33, 38, 43], "fret_count": 24, "capo": 2, "program": 33},
                track.instrument,
            ),
            SetTrackNotationMode("track:bass", "tablature", "standard_tab"),
            SetTrackMixer(
                "track:bass",
                TrackMixer(volume=0.65, pan=-0.2, mute=True, solo=False),
                TrackMixer(),
            ),
            ReorderTracks(("track:bass", "track:1"), ("track:1", "track:bass")),
        ),
    )

    assert transaction_from_dict(transaction_to_dict(transaction)) == transaction
    editor.apply(transaction)
    changed = sorted(editor.document.tracks, key=lambda value: value.order)
    assert [value.id for value in changed] == ["track:bass", "track:1"]
    assert changed[0].name == "Low Bass"
    assert changed[0].instrument["capo"] == 2
    assert changed[0].notation_mode == "tablature"
    assert changed[0].mixer.mute

    editor.undo(
        transaction.command_id,
        command_id="command:undo-track-surface",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_duplicate_measure_group_preserves_content_references_and_undoes() -> None:
    document = _document()
    technique = ScoreTechnique(
        id="technique:source:palm",
        type="palm_mute",
        note_ids=["note:guitar:e4"],
        confidence=1.0,
        reason="manual",
    )
    document.techniques.append(technique)
    source_note = next(
        note
        for track in document.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
        if note.id == "note:guitar:e4"
    )
    source_note.technique_ids.append(technique.id)
    editor = ScoreEditor(document)
    before_hash = editor.document_hash

    note_id_map: dict[str, str] = {}
    entries: list[TrackMeasureEntry] = []
    for track in document.tracks:
        measure = copy.deepcopy(track.measures[0])
        measure.id = f"measure:copy:{track.id}"
        measure.number = 2
        measure.start = Rational(4)
        for beat in measure.beats:
            beat.id = f"beat:copy:{beat.id}"
            beat.start = beat.start + Rational(4)
            beat.tie_in = False
            beat.tie_out = False
            for note in beat.notes:
                source_id = note.id
                note.id = f"note:copy:{source_id}"
                note.source = None
                note_id_map[source_id] = note.id
                note.technique_ids = [
                    "technique:copy:palm"
                    for value in note.technique_ids
                    if value == technique.id
                ]
        entries.append(TrackMeasureEntry(track.id, measure))
    events = tuple(
        PerformanceEvent(
            id=f"performance:copy:{event.id}",
            note_id=note_id_map[event.note_id],
            start=event.start + Rational(4),
            duration=event.duration,
            velocity=event.velocity,
            controls=copy.deepcopy(event.controls),
        )
        for event in document.performance.events
    )
    copied_technique = ScoreTechnique(
        id="technique:copy:palm",
        type=technique.type,
        note_ids=[note_id_map["note:guitar:e4"]],
        confidence=1.0,
        reason="duplicated measure",
    )
    transaction = ScoreTransaction(
        command_id="command:duplicate-measure-group",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Duplicate bar one",
        operations=(
            InsertMeasureGroup(
                entries=tuple(entries),
                performance_events=events,
                techniques=(copied_technique,),
            ),
        ),
    )

    editor.apply(transaction)
    changed = editor.document
    assert all(len(track.measures) == 2 for track in changed.tracks)
    assert any(value.id == copied_technique.id for value in changed.techniques)
    copied_note = next(
        note
        for track in changed.tracks
        for measure in track.measures
        for beat in measure.beats
        for note in beat.notes
        if note.id == note_id_map["note:guitar:e4"]
    )
    assert copied_note.technique_ids == [copied_technique.id]
    assert any(value.note_id == copied_note.id for value in changed.performance.events)

    editor.undo(
        transaction.command_id,
        command_id="command:undo-duplicate-measure-group",
        actor_id="user:1",
    )
    assert editor.document_hash == before_hash


def test_one_hundred_edit_undo_pairs_restore_the_same_hash() -> None:
    editor = ScoreEditor(_document())
    before_hash = editor.document_hash
    for index in range(100):
        command_id = f"command:randomized:{index}"
        editor.apply(
            ScoreTransaction(
                command_id=command_id,
                document_id=editor.document.id,
                actor_id="user:1",
                base_revision=editor.revision,
                origin="manual",
                intent=f"Randomized pitch edit {index}",
                operations=(
                    SetNotePitch(
                        note_id="note:generic:c4",
                        pitch=61 + (index % 6),
                        expected_pitch=60,
                    ),
                ),
            )
        )
        editor.undo(
            command_id,
            command_id=f"command:randomized:undo:{index}",
            actor_id="user:1",
        )
        assert editor.document_hash == before_hash


def test_disjoint_stale_transaction_rebases_but_same_field_conflicts() -> None:
    editor = ScoreEditor(_document())
    generic_beat = _beat_for_note(editor.document, "note:generic:c4")
    first = ScoreTransaction(
        command_id="command:first",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Change pitch",
        operations=(SetNotePitch("note:generic:c4", 62, 60),),
    )
    disjoint = ScoreTransaction(
        command_id="command:disjoint",
        document_id=editor.document.id,
        actor_id="user:2",
        base_revision=0,
        origin="manual",
        intent="Shorten beat",
        operations=(
            SetBeatDuration(
                generic_beat.id,
                Rational(1, 4),
                expected_duration=Rational(1, 2),
            ),
        ),
    )
    conflicting = ScoreTransaction(
        command_id="command:conflict",
        document_id=editor.document.id,
        actor_id="user:2",
        base_revision=0,
        origin="manual",
        intent="Change the same pitch",
        operations=(SetNotePitch("note:generic:c4", 64, 60),),
    )

    editor.apply(first)
    assert editor.apply(disjoint).rebased is True
    with pytest.raises(ScoreConflictError):
        editor.apply(conflicting)


def test_invalid_duration_and_unplayable_string_collision_are_atomic() -> None:
    editor = ScoreEditor(_document())
    original_hash = editor.document_hash
    generic_beat = _beat_for_note(editor.document, "note:generic:c4")
    invalid_duration = ScoreTransaction(
        command_id="command:invalid-duration",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Invalid duration",
        operations=(SetBeatDuration(generic_beat.id, Rational(-1), Rational(1, 2)),),
    )
    with pytest.raises(ScoreOperationError, match="duration"):
        editor.apply(invalid_duration)
    assert editor.revision == 0
    assert editor.document_hash == original_hash

    collision = ScoreTransaction(
        command_id="command:string-collision",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Create impossible chord",
        operations=(
            SetNotePitch("note:guitar:b3", 64, 59),
            SetNoteFretting(
                "note:guitar:b3",
                string=1,
                fret=0,
                expected_string=2,
                expected_fret=0,
            ),
        ),
    )
    with pytest.raises(ScoreOperationError, match="string_collision"):
        editor.apply(collision)
    assert editor.revision == 0
    assert editor.document_hash == original_hash


def test_same_staff_voice_overlap_is_rejected_atomically() -> None:
    document = _document()
    generic_beat = _beat_for_note(document, "note:generic:c4")
    generic_track = next(track for track in document.tracks if track.id == "track:generic")
    generic_measure = generic_track.measures[0]
    generic_measure.beats.append(
        ScoreBeat(
            id="beat:generic:rest",
            start=Rational(2),
            duration=Rational(1),
            voice=generic_beat.voice,
            staff_id=generic_beat.staff_id,
            kind="rest",
        )
    )
    editor = ScoreEditor(document)
    original_hash = editor.document_hash

    with pytest.raises(ScoreOperationError, match="beat.overlap"):
        editor.apply(
            ScoreTransaction(
                command_id="command:overlap",
                document_id=editor.document.id,
                actor_id="user:1",
                base_revision=0,
                origin="manual",
                intent="Create an overlap",
                operations=(
                    SetBeatDuration(
                        generic_beat.id,
                        Rational(2),
                        expected_duration=generic_beat.duration,
                    ),
                ),
            )
        )

    assert editor.revision == 0
    assert editor.document_hash == original_hash


def test_blank_score_first_note_insert_requires_and_accepts_performance_event() -> None:
    document = blank_score_document(document_id="document:blank", title="Blank")
    track = document.tracks[0]
    measure = track.measures[0]
    staff = track.staves[0]
    note = ScoreNote(
        id="note:first",
        pitch=64,
        source=None,
        realization=DocumentInstrumentRealization(kind="guitar", string=1, fret=0),
    )
    beat = ScoreBeat(
        id="beat:first",
        start=measure.start,
        duration=Rational(1),
        voice=1,
        staff_id=staff.id,
        notes=[note],
    )
    editor = ScoreEditor(document)
    result = editor.apply(
        ScoreTransaction(
            command_id="command:first-note",
            document_id=document.id,
            actor_id="user:1",
            base_revision=0,
            origin="manual",
            intent="Add first note",
            operations=(
                InsertBeat(
                    track_id=track.id,
                    measure_id=measure.id,
                    beat=beat,
                    performance_events=(
                        PerformanceEvent(
                            id="performance:first",
                            note_id=note.id,
                            start=beat.start,
                            duration=beat.duration,
                            velocity=80,
                        ),
                    ),
                ),
            ),
        )
    )

    assert result.revision == 1
    assert _beat_for_note(editor.document, note.id).id == beat.id


def test_delete_versus_edit_conflict_is_explicit() -> None:
    editor = ScoreEditor(_document())
    beat = _beat_for_note(editor.document, "note:generic:c4")
    delete = ScoreTransaction(
        command_id="command:delete",
        document_id=editor.document.id,
        actor_id="user:1",
        base_revision=0,
        origin="manual",
        intent="Delete beat",
        operations=(
            DeleteBeat(
                beat_id=beat.id,
                note_ids=tuple(note.id for note in beat.notes),
            ),
        ),
    )
    stale_edit = ScoreTransaction(
        command_id="command:stale-edit",
        document_id=editor.document.id,
        actor_id="user:2",
        base_revision=0,
        origin="manual",
        intent="Edit deleted note",
        operations=(SetNotePitch("note:generic:c4", 62, 60),),
    )
    editor.apply(delete)
    with pytest.raises(ScoreConflictError):
        editor.apply(stale_edit)


def test_persistent_store_is_atomic_idempotent_and_preserves_stale_conflicts() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="editor@example.test", password_hash="test")
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            title="Persistent score",
            source_filename="mixed.mid",
        )
        db.add(project)
        db.flush()
        document = _document()
        revision_zero = create_score_document(
            db,
            project_id=project.id,
            document=document,
            actor_user_id=user.id,
        )
        db.add(
            ExportRecord(
                project_id=project.id,
                format_id="gp5",
                file_path="/tmp/revision-zero.gp5",
                note_count=8,
                revision_id=revision_zero.revision_id,
                revision_hash=revision_zero.content_hash,
            )
        )
        db.commit()
        user_id = user.id
        document_id = document.id

    first = ScoreTransaction(
        command_id="command:persisted-pitch",
        document_id=document_id,
        actor_id=f"user:{user_id}",
        base_revision=0,
        origin="manual",
        intent="Raise selected note",
        operations=(SetNotePitch("note:generic:c4", 62, 60),),
        created_at="2026-08-26T00:00:00+00:00",
    )
    with Session(engine) as db:
        applied = apply_score_transaction(db, first, actor_user_id=user_id)
        assert applied.revision == 1
        db.commit()

    # A fresh session proves idempotency and revision loading do not depend on
    # the in-memory ScoreEditor ledger from the accepting request.
    with Session(engine) as db:
        replayed = apply_score_transaction(db, first, actor_user_id=user_id)
        assert replayed.idempotent_replay is True
        assert replayed.revision == 1
        current = load_score_document_revision(db, document_id)
        original = load_score_document_revision(db, document_id, revision=0)
        pinned_export = db.scalar(select(ExportRecord))
        assert pinned_export.revision_id == original.revision_id
        assert pinned_export.revision_hash == original.content_hash
        assert current.revision == 1
        assert original.content_hash == revision_zero.content_hash
        assert _beat_for_note(current.document, "note:generic:c4").notes[0].pitch == 62
        assert _beat_for_note(original.document, "note:generic:c4").notes[0].pitch == 60

        generic_beat = _beat_for_note(current.document, "note:generic:c4")
        disjoint = ScoreTransaction(
            command_id="command:persisted-disjoint",
            document_id=document_id,
            actor_id=f"user:{user_id}",
            base_revision=0,
            origin="manual",
            intent="Shorten selected beat",
            operations=(
                SetBeatDuration(
                    generic_beat.id,
                    Rational(1, 4),
                    expected_duration=Rational(1, 2),
                ),
            ),
        )
        assert apply_score_transaction(db, disjoint, actor_user_id=user_id).rebased is True
        db.commit()

    with Session(engine) as db:
        conflicting = ScoreTransaction(
            command_id="command:persisted-conflict",
            document_id=document_id,
            actor_id=f"user:{user_id}",
            base_revision=0,
            origin="manual",
            intent="Edit stale pitch",
            operations=(SetNotePitch("note:generic:c4", 64, 60),),
        )
        with pytest.raises(ScoreConflictError):
            apply_score_transaction(db, conflicting, actor_user_id=user_id)

        before_revision_count = db.scalar(select(func.count()).select_from(ScoreRevision))
        before_command_count = db.scalar(select(func.count()).select_from(ScoreCommand))
        invalid = ScoreTransaction(
            command_id="command:persisted-invalid",
            document_id=document_id,
            actor_id=f"user:{user_id}",
            base_revision=2,
            origin="manual",
            intent="Create invalid duration",
            operations=(
                SetBeatDuration(
                    _beat_for_note(
                        load_score_document_revision(db, document_id).document,
                        "note:generic:c4",
                    ).id,
                    Rational(-1),
                    Rational(1, 4),
                ),
            ),
        )
        with pytest.raises(ScoreOperationError):
            apply_score_transaction(db, invalid, actor_user_id=user_id)
        assert db.scalar(select(func.count()).select_from(ScoreRevision)) == before_revision_count
        assert db.scalar(select(func.count()).select_from(ScoreCommand)) == before_command_count
        assert db.get(ScoreDocumentRecord, document_id).current_revision == 2


def test_persistent_store_detects_snapshot_tampering() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="integrity@example.test", password_hash="test")
        db.add(user)
        db.flush()
        project = Project(
            user_id=user.id,
            title="Integrity score",
            source_filename="mixed.mid",
        )
        db.add(project)
        db.flush()
        document = _document()
        stored = create_score_document(
            db,
            project_id=project.id,
            document=document,
            actor_user_id=user.id,
        )
        stored_row = db.get(ScoreRevision, stored.revision_id)
        stored_row.snapshot.document_json = stored_row.snapshot.document_json.replace(
            "Editor mixed contract", "Tampered score"
        )
        stored_row.snapshot.byte_count = len(stored_row.snapshot.document_json.encode("utf-8"))
        db.flush()
        with pytest.raises(ScoreDocumentIntegrityError, match="content hash"):
            load_score_document_revision(db, document.id)


def test_system_snapshot_is_idempotent_and_fences_stale_entity_edits() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="system-snapshot@example.test", password_hash="test")
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, title="Prepare", source_filename="source.mid")
        db.add(project)
        db.flush()
        raw = _document()
        create_score_document(db, project_id=project.id, document=raw, actor_user_id=user.id)
        prepared = copy.deepcopy(raw)
        prepared.title = "Prepared score"
        first = append_system_snapshot(
            db,
            document_id=raw.id,
            document=prepared,
            command_id="prepare:one",
            origin="repair",
            intent="Promote prepared score",
            author_user_id=user.id,
        )
        replay = append_system_snapshot(
            db,
            document_id=raw.id,
            document=prepared,
            command_id="prepare:one",
            origin="repair",
            intent="Promote prepared score",
            author_user_id=user.id,
        )
        assert first.revision == 1
        assert replay.idempotent_replay is True
        command = db.execute(
            select(ScoreCommand).where(ScoreCommand.command_id == "prepare:one")
        ).scalar_one()
        assert command.actor_user_id is None
        assert json.loads(command.touched_fields_json) == [["document", raw.id, "*"]]

        stale = ScoreTransaction(
            command_id="manual:stale-after-prepare",
            document_id=raw.id,
            actor_id=f"user:{user.id}",
            base_revision=0,
            origin="manual",
            intent="Edit from stale raw score",
            operations=(SetNotePitch("note:generic:c4", 61, 60),),
        )
        with pytest.raises(ScoreConflictError):
            apply_score_transaction(db, stale, actor_user_id=user.id)


def test_raw_midi_revision_zero_uses_exact_time_without_fake_fingering() -> None:
    note = NormalizedNote(
        track_index=0,
        track_name="Guitar",
        channel=0,
        pitch=64,
        velocity=91,
        start_tick=1680,
        duration_ticks=480,
        start_beat=3.5,
        duration_beats=1.0,
        program=30,
    )
    timeline = NormalizedTimeline(
        source="raw.mid",
        midi_type=1,
        ticks_per_beat=480,
        tempo_events=[TempoEvent(tick=0, beat=0.0, bpm=120.0)],
        time_signature_events=[TimeSignatureEvent(tick=0, beat=0.0, numerator=4, denominator=4)],
        tracks=[
            NormalizedTrack(
                index=0,
                name="Guitar",
                notes=[note],
                instrument_name="Electric Guitar",
                program=30,
            )
        ],
    )
    classifications = [
        TrackFamilyClassification(
            track_index=0,
            track_name="Guitar",
            family=InstrumentFamily.GUITAR,
            confidence=0.9,
            reason="GM guitar program 30",
            is_guitar=True,
            note_count=1,
        )
    ]
    first = timeline_to_raw_score_document(
        timeline,
        document_id="project:1:document",
        title="Raw import",
        source_filename="raw.mid",
        source_sha256="b" * 64,
        classifications=classifications,
    )
    second = timeline_to_raw_score_document(
        timeline,
        document_id="project:1:document",
        title="Raw import",
        source_filename="raw.mid",
        source_sha256="b" * 64,
        classifications=classifications,
    )
    assert validate_score_document(first).status == "passed"
    assert document_hash(first) == document_hash(second)
    assert first.source.duration == Rational(9, 2)
    assert first.analysis.track_assignments[0].family == "guitar"
    assert first.tracks[0].family == "generic"
    assert first.tracks[0].instrument["realization_status"] == "unprepared"
    beats = [beat for measure in first.tracks[0].measures for beat in measure.beats]
    assert len(beats) == 2
    assert beats[0].tie_out is True
    assert beats[1].tie_in is True
    assert [beat.duration for beat in beats] == [Rational(1, 2), Rational(1, 2)]
    assert all(note.realization.kind == "generic" for beat in beats for note in beat.notes)


@pytest.mark.parametrize("family", ["guitar", "drums", "bass", "keys", "generic"])
def test_blank_revision_zero_is_valid_for_first_editor_families(family: str) -> None:
    document = blank_score_document(
        document_id=f"blank:{family}",
        title=f"Blank {family}",
        family=family,
    )
    assert validate_score_document(document).status == "passed"
    assert document.tracks[0].family == family
    assert len(document.tracks[0].measures) == 1

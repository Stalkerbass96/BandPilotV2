"""Typed ScoreDocument operations, conflict detection and in-memory command ledger.

This is the pure domain foundation used by E0 tests. Database persistence,
membership authorization and WebSocket fan-out are intentionally left for the
later persistence/collaboration slices; they must call this contract instead of
creating another mutation path.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, TypeAlias

from fretpilot.editor.document import (
    InstrumentRealization,
    PerformanceEvent,
    Rational,
    ScoreBeat,
    ScoreDocument,
    ScoreMeasure,
    ScoreNote,
    ScoreTechnique,
    ScoreTrack,
    SourceNoteReference,
    TempoChange,
    TimeSignatureChange,
    TrackMixer,
)
from fretpilot.editor.validation import (
    validate_score_document,
    validate_score_document_changes,
)
from fretpilot.ir.score_document_serde import (
    canonical_document_json,
    document_from_dict,
    document_to_dict,
    score_beat_from_dict,
    score_beat_to_dict,
    score_measure_from_dict,
    score_measure_to_dict,
    score_track_from_dict,
    score_track_to_dict,
)

CommandOrigin: TypeAlias = Literal[
    "manual", "import", "repair", "humanize", "ai", "migration"
]
FieldTouch: TypeAlias = tuple[str, str, str]


class ScoreCommandError(ValueError):
    """Base error for rejected score transactions."""

    code = "command_rejected"


class ScoreConflictError(ScoreCommandError):
    code = "revision_conflict"


class ScoreOperationError(ScoreCommandError):
    code = "validation_failed"


def _find_note(document: ScoreDocument, note_id: str) -> ScoreNote:
    return _find_note_context(document, note_id)[3]


def _find_note_context(
    document: ScoreDocument, note_id: str
) -> tuple[ScoreTrack, ScoreMeasure, ScoreBeat, ScoreNote]:
    for track in document.tracks:
        for measure in track.measures:
            for beat in measure.beats:
                for note in beat.notes:
                    if note.id == note_id:
                        return track, measure, beat, note
    raise ScoreOperationError(f"Note {note_id!r} does not exist")


def _find_beat(
    document: ScoreDocument, beat_id: str
) -> tuple[ScoreTrack, ScoreMeasure, ScoreBeat]:
    for track in document.tracks:
        for measure in track.measures:
            for beat in measure.beats:
                if beat.id == beat_id:
                    return track, measure, beat
    raise ScoreOperationError(f"Beat {beat_id!r} does not exist")


def _find_measure(
    document: ScoreDocument, track_id: str, measure_id: str
) -> tuple[ScoreTrack, ScoreMeasure]:
    for track in document.tracks:
        if track.id != track_id:
            continue
        for measure in track.measures:
            if measure.id == measure_id:
                return track, measure
        raise ScoreOperationError(f"Measure {measure_id!r} does not exist in track {track_id!r}")
    raise ScoreOperationError(f"Track {track_id!r} does not exist")


def _find_track(document: ScoreDocument, track_id: str) -> ScoreTrack:
    for track in document.tracks:
        if track.id == track_id:
            return track
    raise ScoreOperationError(f"Track {track_id!r} does not exist")


def _find_performance_event(document: ScoreDocument, note_id: str) -> PerformanceEvent:
    matches = [value for value in document.performance.events if value.note_id == note_id]
    if not matches:
        raise ScoreOperationError(f"Performance event for note {note_id!r} does not exist")
    if len(matches) > 1:
        raise ScoreOperationError(f"Note {note_id!r} has multiple performance events")
    return matches[0]


def _beat_hash(beat: ScoreBeat) -> str:
    payload = json.dumps(
        score_beat_to_dict(beat),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _measure_hash(measure: ScoreMeasure) -> str:
    payload = json.dumps(
        score_measure_to_dict(measure),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _track_hash(track: ScoreTrack) -> str:
    payload = json.dumps(
        score_track_to_dict(track),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _ordered_measures(track: ScoreTrack) -> list[ScoreMeasure]:
    return sorted(track.measures, key=lambda value: (value.number, value.id))


def _shift_measure_tail(
    document: ScoreDocument,
    insertion_index: int,
    delta: Rational,
) -> None:
    """Shift notation and performance events for measures at/after an index."""

    shifted_note_ids: set[str] = set()
    for track in document.tracks:
        ordered = _ordered_measures(track)
        if insertion_index < 0 or insertion_index > len(ordered):
            raise ScoreOperationError("Measure insertion index is outside the score")
        for measure in ordered[insertion_index:]:
            measure.start = measure.start + delta
            for beat in measure.beats:
                beat.start = beat.start + delta
                shifted_note_ids.update(note.id for note in beat.notes)
    for event in document.performance.events:
        if event.note_id in shifted_note_ids:
            event.start = event.start + delta


def _renumber_measures(document: ScoreDocument) -> None:
    for track in document.tracks:
        track.measures.sort(key=lambda value: (value.start, value.number, value.id))
        for index, measure in enumerate(track.measures, start=1):
            measure.number = index


def _note_hash(note: ScoreNote) -> str:
    payload = json.dumps(
        asdict(note),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _find_technique(document: ScoreDocument, technique_id: str) -> ScoreTechnique:
    for technique in document.techniques:
        if technique.id == technique_id:
            return technique
    raise ScoreOperationError(f"Technique {technique_id!r} does not exist")


def _technique_hash(technique: ScoreTechnique) -> str:
    payload = json.dumps(
        asdict(technique),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expect(actual: object, expected: object | None, label: str) -> None:
    if expected is not None and actual != expected:
        raise ScoreConflictError(f"{label} changed from the transaction precondition")


class ScoreOperation:
    kind: ClassVar[str]

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        raise NotImplementedError

    def touches(self) -> set[FieldTouch]:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SetNotePitch(ScoreOperation):
    kind: ClassVar[str] = "set_note_pitch"
    note_id: str
    pitch: int
    expected_pitch: int | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        note = _find_note(document, self.note_id)
        _expect(note.pitch, self.expected_pitch, f"Pitch for {self.note_id}")
        previous = note.pitch
        note.pitch = self.pitch
        return SetNotePitch(
            note_id=self.note_id,
            pitch=previous,
            expected_pitch=self.pitch,
        )

    def touches(self) -> set[FieldTouch]:
        return {("note", self.note_id, "pitch")}


@dataclass(frozen=True, slots=True)
class SetBeatDuration(ScoreOperation):
    kind: ClassVar[str] = "set_beat_duration"
    beat_id: str
    duration: Rational
    expected_duration: Rational | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat = _find_beat(document, self.beat_id)
        _expect(beat.duration, self.expected_duration, f"Duration for {self.beat_id}")
        previous = beat.duration
        beat.duration = Rational.from_value(self.duration)
        return SetBeatDuration(
            beat_id=self.beat_id,
            duration=previous,
            expected_duration=beat.duration,
        )

    def touches(self) -> set[FieldTouch]:
        return {("beat", self.beat_id, "duration")}


@dataclass(frozen=True, slots=True)
class SetBeatTie(ScoreOperation):
    kind: ClassVar[str] = "set_beat_tie"
    beat_id: str
    tie_in: bool
    tie_out: bool
    expected_tie_in: bool | None = None
    expected_tie_out: bool | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat = _find_beat(document, self.beat_id)
        _expect(beat.tie_in, self.expected_tie_in, f"Tie-in for {self.beat_id}")
        _expect(beat.tie_out, self.expected_tie_out, f"Tie-out for {self.beat_id}")
        previous_in = beat.tie_in
        previous_out = beat.tie_out
        beat.tie_in = self.tie_in
        beat.tie_out = self.tie_out
        return SetBeatTie(
            beat_id=self.beat_id,
            tie_in=previous_in,
            tie_out=previous_out,
            expected_tie_in=self.tie_in,
            expected_tie_out=self.tie_out,
        )

    def touches(self) -> set[FieldTouch]:
        return {
            ("beat", self.beat_id, "tie_in"),
            ("beat", self.beat_id, "tie_out"),
        }


@dataclass(frozen=True, slots=True)
class SetBeatDynamic(ScoreOperation):
    kind: ClassVar[str] = "set_beat_dynamic"
    beat_id: str
    dynamic: str | None
    expected_dynamic: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat = _find_beat(document, self.beat_id)
        previous = beat.properties.get("dynamic")
        _expect(previous, self.expected_dynamic, f"Dynamic for {self.beat_id}")
        if self.dynamic is None:
            beat.properties.pop("dynamic", None)
        else:
            beat.properties["dynamic"] = self.dynamic
        return SetBeatDynamic(
            beat_id=self.beat_id,
            dynamic=str(previous) if previous is not None else None,
            expected_dynamic=self.dynamic,
        )

    def touches(self) -> set[FieldTouch]:
        return {("beat", self.beat_id, "dynamic")}


@dataclass(frozen=True, slots=True)
class SetPerformanceVelocity(ScoreOperation):
    kind: ClassVar[str] = "set_performance_velocity"
    note_id: str
    velocity: int
    expected_velocity: int | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        event = _find_performance_event(document, self.note_id)
        _expect(event.velocity, self.expected_velocity, f"Velocity for {self.note_id}")
        previous = event.velocity
        event.velocity = self.velocity
        return SetPerformanceVelocity(
            note_id=self.note_id,
            velocity=previous,
            expected_velocity=self.velocity,
        )

    def touches(self) -> set[FieldTouch]:
        return {("performance", self.note_id, "velocity")}


@dataclass(frozen=True, slots=True)
class SetBeatVoice(ScoreOperation):
    kind: ClassVar[str] = "set_beat_voice"
    beat_id: str
    voice: int
    expected_voice: int | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat = _find_beat(document, self.beat_id)
        _expect(beat.voice, self.expected_voice, f"Voice for {self.beat_id}")
        previous = beat.voice
        beat.voice = self.voice
        return SetBeatVoice(
            beat_id=self.beat_id,
            voice=previous,
            expected_voice=self.voice,
        )

    def touches(self) -> set[FieldTouch]:
        return {("beat", self.beat_id, "voice")}


@dataclass(frozen=True, slots=True)
class SetNoteFretting(ScoreOperation):
    kind: ClassVar[str] = "set_note_fretting"
    note_id: str
    string: int
    fret: int
    expected_string: int | None = None
    expected_fret: int | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        note = _find_note(document, self.note_id)
        _expect(note.realization.string, self.expected_string, f"String for {self.note_id}")
        _expect(note.realization.fret, self.expected_fret, f"Fret for {self.note_id}")
        previous_string = note.realization.string
        previous_fret = note.realization.fret
        if previous_string is None or previous_fret is None:
            raise ScoreOperationError("SetNoteFretting requires an already fretted note")
        note.realization.string = self.string
        note.realization.fret = self.fret
        return SetNoteFretting(
            note_id=self.note_id,
            string=previous_string,
            fret=previous_fret,
            expected_string=self.string,
            expected_fret=self.fret,
        )

    def touches(self) -> set[FieldTouch]:
        return {
            ("note", self.note_id, "realization.string"),
            ("note", self.note_id, "realization.fret"),
        }


@dataclass(frozen=True, slots=True)
class AddNote(ScoreOperation):
    """Add one note to a beat, converting an explicit rest into a note beat.

    A performance event is mandatory because ScoreDocument keeps written and
    performed layers referentially complete at every committed revision.
    """

    kind: ClassVar[str] = "add_note"
    beat_id: str
    note: ScoreNote
    performance_event: PerformanceEvent
    expected_beat_kind: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat = _find_beat(document, self.beat_id)
        _expect(beat.kind, self.expected_beat_kind, f"Kind for {self.beat_id}")
        try:
            _find_note(document, self.note.id)
        except ScoreOperationError:
            pass
        else:
            raise ScoreConflictError(f"Note {self.note.id!r} already exists")
        if any(
            value.id == self.performance_event.id for value in document.performance.events
        ):
            raise ScoreConflictError(
                f"Performance event {self.performance_event.id!r} already exists"
            )
        if self.performance_event.note_id != self.note.id:
            raise ScoreOperationError("Added note and performance event must use the same note ID")
        if beat.kind == "rest" and beat.notes:
            raise ScoreOperationError("A rest beat cannot contain existing notes")
        beat.kind = "notes"
        beat.notes.append(copy.deepcopy(self.note))
        document.performance.events.append(copy.deepcopy(self.performance_event))
        return DeleteNote(
            beat_id=beat.id,
            note_id=self.note.id,
            expected_note_hash=_note_hash(self.note),
        )

    def touches(self) -> set[FieldTouch]:
        return {
            ("beat", self.beat_id, "kind"),
            ("note", self.note.id, "*"),
            ("performance", self.note.id, "note"),
        }


@dataclass(frozen=True, slots=True)
class DeleteNote(ScoreOperation):
    """Remove one chord tone; the final note turns the beat into a rest."""

    kind: ClassVar[str] = "delete_note"
    beat_id: str
    note_id: str
    expected_note_hash: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, _measure, beat, note = _find_note_context(document, self.note_id)
        if beat.id != self.beat_id:
            raise ScoreConflictError(
                f"Note {self.note_id!r} is no longer in beat {self.beat_id!r}"
            )
        _expect(_note_hash(note), self.expected_note_hash, f"Note {self.note_id}")
        referenced_techniques = [
            technique.id
            for technique in document.techniques
            if self.note_id in technique.note_ids
        ]
        if referenced_techniques:
            raise ScoreOperationError(
                "DeleteNote cannot remove a note with techniques; remove or retarget "
                "the technique in the same editing workflow first"
            )
        events = [
            value for value in document.performance.events if value.note_id == self.note_id
        ]
        if len(events) != 1:
            raise ScoreOperationError(
                f"Note {self.note_id!r} requires exactly one performance event"
            )
        event = copy.deepcopy(events[0])
        beat.notes.remove(note)
        document.performance.events = [
            value for value in document.performance.events if value.note_id != self.note_id
        ]
        beat.kind = "notes" if beat.notes else "rest"
        return AddNote(
            beat_id=beat.id,
            note=copy.deepcopy(note),
            performance_event=event,
            expected_beat_kind=beat.kind,
        )

    def touches(self) -> set[FieldTouch]:
        return {
            ("beat", self.beat_id, "kind"),
            ("note", self.note_id, "*"),
            ("performance", self.note_id, "note"),
        }


@dataclass(frozen=True, slots=True)
class AddTechnique(ScoreOperation):
    kind: ClassVar[str] = "add_technique"
    technique: ScoreTechnique

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        try:
            _find_technique(document, self.technique.id)
        except ScoreOperationError:
            pass
        else:
            raise ScoreConflictError(f"Technique {self.technique.id!r} already exists")
        if not self.technique.note_ids:
            raise ScoreOperationError("A technique must target at least one note")
        notes = [_find_note(document, note_id) for note_id in self.technique.note_ids]
        document.techniques.append(copy.deepcopy(self.technique))
        for note in notes:
            if self.technique.id not in note.technique_ids:
                note.technique_ids.append(self.technique.id)
        return DeleteTechnique(
            technique_id=self.technique.id,
            expected_technique_hash=_technique_hash(self.technique),
        )

    def touches(self) -> set[FieldTouch]:
        touches = {("technique", self.technique.id, "*")}
        touches.update(
            ("note", note_id, "technique_ids") for note_id in self.technique.note_ids
        )
        return touches


@dataclass(frozen=True, slots=True)
class DeleteTechnique(ScoreOperation):
    kind: ClassVar[str] = "delete_technique"
    technique_id: str
    expected_technique_hash: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        technique = _find_technique(document, self.technique_id)
        _expect(
            _technique_hash(technique),
            self.expected_technique_hash,
            f"Technique {self.technique_id}",
        )
        previous = copy.deepcopy(technique)
        document.techniques.remove(technique)
        for note_id in technique.note_ids:
            note = _find_note(document, note_id)
            note.technique_ids = [
                value for value in note.technique_ids if value != self.technique_id
            ]
        return AddTechnique(previous)

    def touches(self) -> set[FieldTouch]:
        return {("technique", self.technique_id, "*")}


@dataclass(frozen=True, slots=True)
class InsertBeat(ScoreOperation):
    kind: ClassVar[str] = "insert_beat"
    track_id: str
    measure_id: str
    beat: ScoreBeat
    performance_events: tuple[PerformanceEvent, ...] = ()

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        _track, measure = _find_measure(document, self.track_id, self.measure_id)
        try:
            _find_beat(document, self.beat.id)
        except ScoreOperationError:
            pass
        else:
            raise ScoreConflictError(f"Beat {self.beat.id!r} already exists")
        measure.beats.append(copy.deepcopy(self.beat))
        document.performance.events.extend(copy.deepcopy(list(self.performance_events)))
        return DeleteBeat(
            beat_id=self.beat.id,
            note_ids=tuple(note.id for note in self.beat.notes),
            expected_beat_hash=_beat_hash(self.beat),
        )

    def touches(self) -> set[FieldTouch]:
        touches = {("beat", self.beat.id, "*")}
        touches.update(("note", note.id, "*") for note in self.beat.notes)
        return touches


@dataclass(frozen=True, slots=True)
class DeleteBeat(ScoreOperation):
    kind: ClassVar[str] = "delete_beat"
    beat_id: str
    note_ids: tuple[str, ...] = ()
    expected_beat_hash: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        track, measure, beat = _find_beat(document, self.beat_id)
        _expect(_beat_hash(beat), self.expected_beat_hash, f"Beat {self.beat_id}")
        note_ids = {note.id for note in beat.notes}
        if self.note_ids and note_ids != set(self.note_ids):
            raise ScoreConflictError(f"Notes in beat {self.beat_id!r} changed")
        referenced_techniques = [
            technique.id
            for technique in document.techniques
            if note_ids.intersection(technique.note_ids)
        ]
        if referenced_techniques:
            raise ScoreOperationError(
                "DeleteBeat cannot remove notes with techniques until the transaction "
                "also supports explicit technique deletion"
            )
        performance_events = tuple(
            copy.deepcopy(value)
            for value in document.performance.events
            if value.note_id in note_ids
        )
        measure.beats.remove(beat)
        document.performance.events = [
            value for value in document.performance.events if value.note_id not in note_ids
        ]
        return InsertBeat(
            track_id=track.id,
            measure_id=measure.id,
            beat=copy.deepcopy(beat),
            performance_events=performance_events,
        )

    def touches(self) -> set[FieldTouch]:
        touches = {("beat", self.beat_id, "*")}
        touches.update(("note", note_id, "*") for note_id in self.note_ids)
        return touches


@dataclass(frozen=True, slots=True)
class TrackMeasureEntry:
    track_id: str
    measure: ScoreMeasure


@dataclass(frozen=True, slots=True)
class InsertMeasureGroup(ScoreOperation):
    """Insert one score-wide measure group at a shared structural index."""

    kind: ClassVar[str] = "insert_measure_group"
    entries: tuple[TrackMeasureEntry, ...]
    performance_events: tuple[PerformanceEvent, ...] = ()
    techniques: tuple[ScoreTechnique, ...] = ()
    tempo_changes: tuple[TempoChange, ...] = ()
    time_signatures: tuple[TimeSignatureChange, ...] = ()

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        if not self.entries:
            raise ScoreOperationError("A measure group requires one entry per track")
        track_by_id = {track.id: track for track in document.tracks}
        entry_by_track = {entry.track_id: entry for entry in self.entries}
        if len(entry_by_track) != len(self.entries):
            raise ScoreOperationError("A measure group cannot repeat a track")
        if set(entry_by_track) != set(track_by_id):
            raise ScoreOperationError("A measure group must cover every score track")

        first = self.entries[0].measure
        insertion_index = first.number - 1
        if insertion_index < 0:
            raise ScoreOperationError("Measure number must be positive")
        for entry in self.entries:
            measure = entry.measure
            if (
                measure.number != first.number
                or measure.start != first.start
                or measure.duration != first.duration
                or measure.numerator != first.numerator
                or measure.denominator != first.denominator
            ):
                raise ScoreOperationError(
                    "All inserted track measures must share number, time and signature"
                )
            if len(_ordered_measures(track_by_id[entry.track_id])) < insertion_index:
                raise ScoreOperationError("Measure insertion index is not present in every track")
            try:
                _find_measure(document, entry.track_id, measure.id)
            except ScoreOperationError:
                pass
            else:
                raise ScoreConflictError(f"Measure {measure.id!r} already exists")

        inserted_note_ids = {
            note.id
            for entry in self.entries
            for beat in entry.measure.beats
            for note in beat.notes
        }
        inserted_beat_ids = {
            beat.id for entry in self.entries for beat in entry.measure.beats
        }
        for beat_id in inserted_beat_ids:
            try:
                _find_beat(document, beat_id)
            except ScoreOperationError:
                pass
            else:
                raise ScoreConflictError(f"Beat {beat_id!r} already exists")
        for note_id in inserted_note_ids:
            try:
                _find_note(document, note_id)
            except ScoreOperationError:
                pass
            else:
                raise ScoreConflictError(f"Note {note_id!r} already exists")

        event_ids = {event.id for event in self.performance_events}
        if len(event_ids) != len(self.performance_events):
            raise ScoreOperationError("Inserted performance event IDs must be unique")
        existing_event_ids = {event.id for event in document.performance.events}
        if event_ids.intersection(existing_event_ids):
            raise ScoreConflictError("An inserted performance event ID already exists")
        if (
            len(self.performance_events) != len(inserted_note_ids)
            or {event.note_id for event in self.performance_events} != inserted_note_ids
        ):
            raise ScoreOperationError(
                "An inserted measure group requires exactly one performance event per note"
            )
        technique_ids = {technique.id for technique in self.techniques}
        if len(technique_ids) != len(self.techniques):
            raise ScoreOperationError("Inserted technique IDs must be unique")
        if technique_ids.intersection({value.id for value in document.techniques}):
            raise ScoreConflictError("An inserted technique ID already exists")
        for technique in self.techniques:
            if not technique.note_ids or not set(technique.note_ids).issubset(inserted_note_ids):
                raise ScoreOperationError(
                    "Inserted techniques may target only notes in the inserted measure group"
                )

        _shift_measure_tail(document, insertion_index, first.duration)
        for tempo in document.tempo_map:
            if tempo.position >= first.start:
                tempo.position = tempo.position + first.duration
        for signature in document.time_signatures:
            if signature.position >= first.start:
                signature.position = signature.position + first.duration

        inserted_measures: list[ScoreMeasure] = []
        for entry in self.entries:
            track = track_by_id[entry.track_id]
            measure = copy.deepcopy(entry.measure)
            track.measures.insert(insertion_index, measure)
            inserted_measures.append(measure)
        document.performance.events.extend(copy.deepcopy(list(self.performance_events)))
        document.techniques.extend(copy.deepcopy(list(self.techniques)))
        note_by_id = {
            note.id: note
            for measure in inserted_measures
            for beat in measure.beats
            for note in beat.notes
        }
        for technique in self.techniques:
            for note_id in technique.note_ids:
                if technique.id not in note_by_id[note_id].technique_ids:
                    note_by_id[note_id].technique_ids.append(technique.id)
        document.tempo_map.extend(copy.deepcopy(list(self.tempo_changes)))
        document.time_signatures.extend(copy.deepcopy(list(self.time_signatures)))
        _renumber_measures(document)
        return DeleteMeasureGroup(
            measure_ids=tuple(measure.id for measure in inserted_measures),
            expected_measure_hashes=tuple(
                (measure.id, _measure_hash(measure)) for measure in inserted_measures
            ),
        )

    def touches(self) -> set[FieldTouch]:
        return {("structure", "measure_sequence", "*")}


@dataclass(frozen=True, slots=True)
class DeleteMeasureGroup(ScoreOperation):
    """Delete one aligned score-wide measure group and close the timeline gap."""

    kind: ClassVar[str] = "delete_measure_group"
    measure_ids: tuple[str, ...]
    expected_measure_hashes: tuple[tuple[str, str], ...] = ()

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        if not self.measure_ids:
            raise ScoreOperationError("A measure group requires measure IDs")
        resolved: list[tuple[ScoreTrack, ScoreMeasure]] = []
        for measure_id in self.measure_ids:
            matches = [
                (track, measure)
                for track in document.tracks
                for measure in track.measures
                if measure.id == measure_id
            ]
            if len(matches) != 1:
                raise ScoreOperationError(f"Measure {measure_id!r} does not exist uniquely")
            resolved.append(matches[0])
        if {track.id for track, _measure in resolved} != {track.id for track in document.tracks}:
            raise ScoreOperationError("A deleted measure group must cover every score track")
        if len(resolved) != len(document.tracks):
            raise ScoreOperationError("A deleted measure group cannot repeat a track")
        if any(len(track.measures) <= 1 for track, _measure in resolved):
            raise ScoreOperationError("A score must retain at least one measure")

        first = resolved[0][1]
        ordered_first = _ordered_measures(resolved[0][0])
        deletion_index = ordered_first.index(first)
        for track, measure in resolved:
            ordered = _ordered_measures(track)
            if (
                ordered.index(measure) != deletion_index
                or measure.start != first.start
                or measure.duration != first.duration
                or measure.numerator != first.numerator
                or measure.denominator != first.denominator
            ):
                raise ScoreOperationError("Deleted track measures are not one aligned measure")
        expected = dict(self.expected_measure_hashes)
        for _track, measure in resolved:
            _expect(_measure_hash(measure), expected.get(measure.id), f"Measure {measure.id}")

        note_ids = {
            note.id for _track, measure in resolved for beat in measure.beats for note in beat.notes
        }
        crossing = [
            technique.id
            for technique in document.techniques
            if note_ids.intersection(technique.note_ids)
            and not set(technique.note_ids).issubset(note_ids)
        ]
        if crossing:
            raise ScoreOperationError(
                "Delete the linked technique before deleting a measure boundary it crosses"
            )
        techniques = tuple(
            copy.deepcopy(technique)
            for technique in document.techniques
            if set(technique.note_ids).intersection(note_ids)
        )
        performance_events = tuple(
            copy.deepcopy(event)
            for event in document.performance.events
            if event.note_id in note_ids
        )
        if (
            len(performance_events) != len(note_ids)
            or {event.note_id for event in performance_events} != note_ids
        ):
            raise ScoreOperationError(
                "A deleted measure group requires exactly one performance event per note"
            )
        end = first.start + first.duration
        tempo_changes = tuple(
            copy.deepcopy(value)
            for value in document.tempo_map
            if first.start <= value.position < end
        )
        time_signatures = tuple(
            copy.deepcopy(value)
            for value in document.time_signatures
            if first.start <= value.position < end
        )
        entries = tuple(
            TrackMeasureEntry(track.id, copy.deepcopy(measure))
            for track, measure in resolved
        )

        for track, measure in resolved:
            track.measures.remove(measure)
        document.performance.events = [
            event for event in document.performance.events if event.note_id not in note_ids
        ]
        removed_technique_ids = {value.id for value in techniques}
        document.techniques = [
            technique
            for technique in document.techniques
            if technique.id not in removed_technique_ids
        ]
        document.tempo_map = [
            value for value in document.tempo_map if not (first.start <= value.position < end)
        ]
        document.time_signatures = [
            value
            for value in document.time_signatures
            if not (first.start <= value.position < end)
        ]
        _shift_measure_tail(document, deletion_index, Rational(-first.duration.numerator, first.duration.denominator))
        for tempo in document.tempo_map:
            if tempo.position >= end:
                tempo.position = tempo.position - first.duration
        for signature in document.time_signatures:
            if signature.position >= end:
                signature.position = signature.position - first.duration
        _renumber_measures(document)
        return InsertMeasureGroup(
            entries=entries,
            performance_events=performance_events,
            techniques=techniques,
            tempo_changes=tempo_changes,
            time_signatures=time_signatures,
        )

    def touches(self) -> set[FieldTouch]:
        return {("structure", "measure_sequence", "*")}


@dataclass(frozen=True, slots=True)
class SetTrackName(ScoreOperation):
    kind: ClassVar[str] = "set_track_name"
    track_id: str
    name: str
    expected_name: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        track = _find_track(document, self.track_id)
        _expect(track.name, self.expected_name, f"Name for {self.track_id}")
        previous = track.name
        track.name = self.name
        return SetTrackName(self.track_id, previous, self.name)

    def touches(self) -> set[FieldTouch]:
        return {("track", self.track_id, "name")}


@dataclass(frozen=True, slots=True)
class SetTrackInstrument(ScoreOperation):
    kind: ClassVar[str] = "set_track_instrument"
    track_id: str
    instrument: dict[str, Any]
    expected_instrument: dict[str, Any] | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        track = _find_track(document, self.track_id)
        _expect(track.instrument, self.expected_instrument, f"Instrument for {self.track_id}")
        previous = copy.deepcopy(track.instrument)
        track.instrument = copy.deepcopy(self.instrument)
        return SetTrackInstrument(self.track_id, previous, copy.deepcopy(self.instrument))

    def touches(self) -> set[FieldTouch]:
        return {("track", self.track_id, "instrument")}


@dataclass(frozen=True, slots=True)
class SetTrackNotationMode(ScoreOperation):
    kind: ClassVar[str] = "set_track_notation_mode"
    track_id: str
    notation_mode: str
    expected_notation_mode: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        track = _find_track(document, self.track_id)
        _expect(
            track.notation_mode,
            self.expected_notation_mode,
            f"Notation mode for {self.track_id}",
        )
        previous = track.notation_mode
        track.notation_mode = self.notation_mode
        return SetTrackNotationMode(self.track_id, previous, self.notation_mode)

    def touches(self) -> set[FieldTouch]:
        return {("track", self.track_id, "notation_mode")}


@dataclass(frozen=True, slots=True)
class SetTrackMixer(ScoreOperation):
    kind: ClassVar[str] = "set_track_mixer"
    track_id: str
    mixer: TrackMixer
    expected_mixer: TrackMixer | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        track = _find_track(document, self.track_id)
        _expect(track.mixer, self.expected_mixer, f"Mixer for {self.track_id}")
        previous = copy.deepcopy(track.mixer)
        track.mixer = copy.deepcopy(self.mixer)
        return SetTrackMixer(self.track_id, previous, copy.deepcopy(self.mixer))

    def touches(self) -> set[FieldTouch]:
        return {("track", self.track_id, "mixer")}


@dataclass(frozen=True, slots=True)
class ReorderTracks(ScoreOperation):
    kind: ClassVar[str] = "reorder_tracks"
    track_ids: tuple[str, ...]
    expected_track_ids: tuple[str, ...] | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        current = tuple(track.id for track in sorted(document.tracks, key=lambda value: value.order))
        _expect(current, self.expected_track_ids, "Track order")
        if len(self.track_ids) != len(set(self.track_ids)) or set(self.track_ids) != set(current):
            raise ScoreOperationError("Track order must contain every track exactly once")
        order_by_id = {track_id: order for order, track_id in enumerate(self.track_ids)}
        for track in document.tracks:
            track.order = order_by_id[track.id]
        return ReorderTracks(current, self.track_ids)

    def touches(self) -> set[FieldTouch]:
        return {("structure", "track_sequence", "*")}


@dataclass(frozen=True, slots=True)
class InsertTrack(ScoreOperation):
    kind: ClassVar[str] = "insert_track"
    track: ScoreTrack

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        if any(value.id == self.track.id for value in document.tracks):
            raise ScoreConflictError(f"Track {self.track.id!r} already exists")
        if not 0 <= self.track.order <= len(document.tracks):
            raise ScoreOperationError("Inserted track order is outside the score")
        if document.tracks:
            reference = _ordered_measures(document.tracks[0])
            candidate = _ordered_measures(self.track)
            reference_shape = [
                (value.number, value.start, value.duration, value.numerator, value.denominator)
                for value in reference
            ]
            candidate_shape = [
                (value.number, value.start, value.duration, value.numerator, value.denominator)
                for value in candidate
            ]
            if candidate_shape != reference_shape:
                raise ScoreOperationError("Inserted track measures must align with the score")
        for value in document.tracks:
            if value.order >= self.track.order:
                value.order += 1
        inserted = copy.deepcopy(self.track)
        document.tracks.append(inserted)
        return DeleteTrack(inserted.id, _track_hash(inserted))

    def touches(self) -> set[FieldTouch]:
        return {("structure", "track_sequence", "*")}


@dataclass(frozen=True, slots=True)
class DeleteTrack(ScoreOperation):
    kind: ClassVar[str] = "delete_track"
    track_id: str
    expected_track_hash: str | None = None

    def apply(self, document: ScoreDocument) -> ScoreOperation:
        if len(document.tracks) <= 1:
            raise ScoreOperationError("A score must retain at least one track")
        track = _find_track(document, self.track_id)
        _expect(_track_hash(track), self.expected_track_hash, f"Track {self.track_id}")
        if any(beat.notes for measure in track.measures for beat in measure.beats):
            raise ScoreOperationError("Only an empty track can be deleted safely")
        removed = copy.deepcopy(track)
        document.tracks.remove(track)
        for value in document.tracks:
            if value.order > removed.order:
                value.order -= 1
        return InsertTrack(removed)

    def touches(self) -> set[FieldTouch]:
        return {("structure", "track_sequence", "*")}


ScoreOperationType: TypeAlias = (
    SetNotePitch
    | SetBeatDuration
    | SetBeatTie
    | SetBeatDynamic
    | SetPerformanceVelocity
    | SetBeatVoice
    | SetNoteFretting
    | AddNote
    | DeleteNote
    | AddTechnique
    | DeleteTechnique
    | InsertBeat
    | DeleteBeat
    | InsertMeasureGroup
    | DeleteMeasureGroup
    | SetTrackName
    | SetTrackInstrument
    | SetTrackNotationMode
    | SetTrackMixer
    | ReorderTracks
    | InsertTrack
    | DeleteTrack
)


_TRACK_FIELD_OPERATION_TYPES = (
    SetNotePitch,
    SetBeatDuration,
    SetBeatTie,
    SetBeatDynamic,
    SetBeatVoice,
    SetNoteFretting,
    SetTrackName,
    SetTrackInstrument,
    SetTrackNotationMode,
    SetTrackMixer,
)


def _incremental_validation_scope(
    document: ScoreDocument,
    operations: tuple[ScoreOperationType, ...],
) -> tuple[set[str], set[str]] | None:
    if any(
        not isinstance(operation, (*_TRACK_FIELD_OPERATION_TYPES, SetPerformanceVelocity))
        for operation in operations
    ):
        return None

    needs_note_lookup = any(
        isinstance(operation, (SetNotePitch, SetNoteFretting))
        for operation in operations
    )
    needs_beat_lookup = any(
        isinstance(
            operation,
            (SetBeatDuration, SetBeatTie, SetBeatDynamic, SetBeatVoice),
        )
        for operation in operations
    )
    track_by_note_id: dict[str, str] = {}
    track_by_beat_id: dict[str, str] = {}
    if needs_note_lookup or needs_beat_lookup:
        for track in document.tracks:
            for measure in track.measures:
                for beat in measure.beats:
                    if needs_beat_lookup:
                        track_by_beat_id[beat.id] = track.id
                    if needs_note_lookup:
                        track_by_note_id.update((note.id, track.id) for note in beat.notes)

    track_ids: set[str] = set()
    performance_note_ids: set[str] = set()
    for operation in operations:
        if isinstance(operation, (SetNotePitch, SetNoteFretting)):
            track_ids.add(track_by_note_id[operation.note_id])
        elif isinstance(
            operation,
            (SetBeatDuration, SetBeatTie, SetBeatDynamic, SetBeatVoice),
        ):
            track_ids.add(track_by_beat_id[operation.beat_id])
        elif isinstance(
            operation,
            (SetTrackName, SetTrackInstrument, SetTrackNotationMode, SetTrackMixer),
        ):
            track_ids.add(operation.track_id)
        elif isinstance(operation, SetPerformanceVelocity):
            performance_note_ids.add(operation.note_id)
    return track_ids, performance_note_ids


@dataclass(frozen=True, slots=True)
class SelectionAnchor:
    scope: str
    track_ids: tuple[str, ...] = ()
    measure_ids: tuple[str, ...] = ()
    beat_ids: tuple[str, ...] = ()
    note_ids: tuple[str, ...] = ()
    start: Rational | None = None
    end: Rational | None = None


@dataclass(frozen=True, slots=True)
class ScoreTransaction:
    command_id: str
    document_id: str
    actor_id: str
    base_revision: int
    origin: CommandOrigin
    intent: str
    operations: tuple[ScoreOperationType, ...]
    selection: SelectionAnchor | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class AcceptedCommand:
    transaction: ScoreTransaction
    revision: int
    document_hash: str
    inverse_operations: tuple[ScoreOperationType, ...]
    touched_fields: frozenset[FieldTouch]
    fingerprint: str
    rebased: bool


@dataclass(frozen=True, slots=True)
class CommandApplyResult:
    command_id: str
    revision: int
    document_hash: str
    rebased: bool
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class CanonicalScoreSnapshot:
    """Immutable persistence view of the editor's current canonical document."""

    payload: str
    content_hash: str
    schema_version: str
    validation_status: str


def operation_to_dict(operation: ScoreOperationType) -> dict[str, Any]:
    if isinstance(operation, SetNotePitch):
        return {
            "kind": operation.kind,
            "note_id": operation.note_id,
            "pitch": operation.pitch,
            "expected_pitch": operation.expected_pitch,
        }
    if isinstance(operation, SetBeatDuration):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "duration": operation.duration.to_dict(),
            "expected_duration": (
                operation.expected_duration.to_dict()
                if operation.expected_duration is not None
                else None
            ),
        }
    if isinstance(operation, SetBeatTie):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "tie_in": operation.tie_in,
            "tie_out": operation.tie_out,
            "expected_tie_in": operation.expected_tie_in,
            "expected_tie_out": operation.expected_tie_out,
        }
    if isinstance(operation, SetBeatDynamic):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "dynamic": operation.dynamic,
            "expected_dynamic": operation.expected_dynamic,
        }
    if isinstance(operation, SetPerformanceVelocity):
        return {
            "kind": operation.kind,
            "note_id": operation.note_id,
            "velocity": operation.velocity,
            "expected_velocity": operation.expected_velocity,
        }
    if isinstance(operation, SetBeatVoice):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "voice": operation.voice,
            "expected_voice": operation.expected_voice,
        }
    if isinstance(operation, SetNoteFretting):
        return {
            "kind": operation.kind,
            "note_id": operation.note_id,
            "string": operation.string,
            "fret": operation.fret,
            "expected_string": operation.expected_string,
            "expected_fret": operation.expected_fret,
        }
    if isinstance(operation, AddNote):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "note": asdict(operation.note),
            "performance_event": asdict(operation.performance_event),
            "expected_beat_kind": operation.expected_beat_kind,
        }
    if isinstance(operation, DeleteNote):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "note_id": operation.note_id,
            "expected_note_hash": operation.expected_note_hash,
        }
    if isinstance(operation, AddTechnique):
        return {
            "kind": operation.kind,
            "technique": asdict(operation.technique),
        }
    if isinstance(operation, DeleteTechnique):
        return {
            "kind": operation.kind,
            "technique_id": operation.technique_id,
            "expected_technique_hash": operation.expected_technique_hash,
        }
    if isinstance(operation, InsertBeat):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "measure_id": operation.measure_id,
            "beat": score_beat_to_dict(operation.beat),
            "performance_events": [asdict(value) for value in operation.performance_events],
        }
    if isinstance(operation, DeleteBeat):
        return {
            "kind": operation.kind,
            "beat_id": operation.beat_id,
            "note_ids": list(operation.note_ids),
            "expected_beat_hash": operation.expected_beat_hash,
        }
    if isinstance(operation, InsertMeasureGroup):
        return {
            "kind": operation.kind,
            "entries": [
                {
                    "track_id": entry.track_id,
                    "measure": score_measure_to_dict(entry.measure),
                }
                for entry in operation.entries
            ],
            "performance_events": [asdict(value) for value in operation.performance_events],
            "techniques": [asdict(value) for value in operation.techniques],
            "tempo_changes": [asdict(value) for value in operation.tempo_changes],
            "time_signatures": [asdict(value) for value in operation.time_signatures],
        }
    if isinstance(operation, DeleteMeasureGroup):
        return {
            "kind": operation.kind,
            "measure_ids": list(operation.measure_ids),
            "expected_measure_hashes": dict(operation.expected_measure_hashes),
        }
    if isinstance(operation, SetTrackName):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "name": operation.name,
            "expected_name": operation.expected_name,
        }
    if isinstance(operation, SetTrackInstrument):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "instrument": copy.deepcopy(operation.instrument),
            "expected_instrument": copy.deepcopy(operation.expected_instrument),
        }
    if isinstance(operation, SetTrackNotationMode):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "notation_mode": operation.notation_mode,
            "expected_notation_mode": operation.expected_notation_mode,
        }
    if isinstance(operation, SetTrackMixer):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "mixer": asdict(operation.mixer),
            "expected_mixer": (
                asdict(operation.expected_mixer)
                if operation.expected_mixer is not None
                else None
            ),
        }
    if isinstance(operation, ReorderTracks):
        return {
            "kind": operation.kind,
            "track_ids": list(operation.track_ids),
            "expected_track_ids": (
                list(operation.expected_track_ids)
                if operation.expected_track_ids is not None
                else None
            ),
        }
    if isinstance(operation, InsertTrack):
        return {"kind": operation.kind, "track": score_track_to_dict(operation.track)}
    if isinstance(operation, DeleteTrack):
        return {
            "kind": operation.kind,
            "track_id": operation.track_id,
            "expected_track_hash": operation.expected_track_hash,
        }
    raise TypeError(f"Unsupported ScoreOperation: {type(operation).__name__}")


def operation_from_dict(raw: dict[str, Any]) -> ScoreOperationType:
    kind = str(raw.get("kind", ""))
    if kind == SetNotePitch.kind:
        return SetNotePitch(
            note_id=str(raw["note_id"]),
            pitch=int(raw["pitch"]),
            expected_pitch=(
                int(raw["expected_pitch"]) if raw.get("expected_pitch") is not None else None
            ),
        )
    if kind == SetBeatDuration.kind:
        return SetBeatDuration(
            beat_id=str(raw["beat_id"]),
            duration=Rational.from_value(raw["duration"]),
            expected_duration=(
                Rational.from_value(raw["expected_duration"])
                if raw.get("expected_duration") is not None
                else None
            ),
        )
    if kind == SetBeatTie.kind:
        return SetBeatTie(
            beat_id=str(raw["beat_id"]),
            tie_in=bool(raw["tie_in"]),
            tie_out=bool(raw["tie_out"]),
            expected_tie_in=(
                bool(raw["expected_tie_in"])
                if raw.get("expected_tie_in") is not None
                else None
            ),
            expected_tie_out=(
                bool(raw["expected_tie_out"])
                if raw.get("expected_tie_out") is not None
                else None
            ),
        )
    if kind == SetBeatDynamic.kind:
        return SetBeatDynamic(
            beat_id=str(raw["beat_id"]),
            dynamic=(str(raw["dynamic"]) if raw.get("dynamic") is not None else None),
            expected_dynamic=(
                str(raw["expected_dynamic"])
                if raw.get("expected_dynamic") is not None
                else None
            ),
        )
    if kind == SetPerformanceVelocity.kind:
        return SetPerformanceVelocity(
            note_id=str(raw["note_id"]),
            velocity=int(raw["velocity"]),
            expected_velocity=(
                int(raw["expected_velocity"])
                if raw.get("expected_velocity") is not None
                else None
            ),
        )
    if kind == SetBeatVoice.kind:
        return SetBeatVoice(
            beat_id=str(raw["beat_id"]),
            voice=int(raw["voice"]),
            expected_voice=(
                int(raw["expected_voice"])
                if raw.get("expected_voice") is not None
                else None
            ),
        )
    if kind == SetNoteFretting.kind:
        return SetNoteFretting(
            note_id=str(raw["note_id"]),
            string=int(raw["string"]),
            fret=int(raw["fret"]),
            expected_string=(
                int(raw["expected_string"]) if raw.get("expected_string") is not None else None
            ),
            expected_fret=(
                int(raw["expected_fret"]) if raw.get("expected_fret") is not None else None
            ),
        )
    if kind == AddNote.kind:
        raw_note = raw["note"]
        raw_realization = raw_note["realization"]
        raw_source = raw_note.get("source")
        event = raw["performance_event"]
        return AddNote(
            beat_id=str(raw["beat_id"]),
            note=ScoreNote(
                id=str(raw_note["id"]),
                pitch=int(raw_note["pitch"]),
                source=(
                    SourceNoteReference(
                        source_track_index=int(raw_source["source_track_index"]),
                        source_note_index=int(raw_source["source_note_index"]),
                        origin=str(raw_source.get("origin", "midi")),
                    )
                    if raw_source is not None
                    else None
                ),
                realization=InstrumentRealization(
                    kind=str(raw_realization["kind"]),
                    string=raw_realization.get("string"),
                    fret=raw_realization.get("fret"),
                    fretting_digit=raw_realization.get("fretting_digit"),
                    hand_position=raw_realization.get("hand_position"),
                    piece=raw_realization.get("piece"),
                    sticking=raw_realization.get("sticking"),
                    hit_technique=raw_realization.get("hit_technique"),
                    hand=raw_realization.get("hand"),
                    finger=raw_realization.get("finger"),
                    pedal=raw_realization.get("pedal"),
                ),
                technique_ids=[str(value) for value in raw_note.get("technique_ids", [])],
                properties=dict(raw_note.get("properties", {})),
            ),
            performance_event=PerformanceEvent(
                id=str(event["id"]),
                note_id=str(event["note_id"]),
                start=Rational.from_value(event["start"]),
                duration=Rational.from_value(event["duration"]),
                velocity=int(event["velocity"]),
                controls=list(event.get("controls", [])),
            ),
            expected_beat_kind=(
                str(raw["expected_beat_kind"])
                if raw.get("expected_beat_kind") is not None
                else None
            ),
        )
    if kind == DeleteNote.kind:
        return DeleteNote(
            beat_id=str(raw["beat_id"]),
            note_id=str(raw["note_id"]),
            expected_note_hash=raw.get("expected_note_hash"),
        )
    if kind == AddTechnique.kind:
        technique = raw["technique"]
        return AddTechnique(
            ScoreTechnique(
                id=str(technique["id"]),
                type=str(technique["type"]),
                note_ids=[str(value) for value in technique.get("note_ids", [])],
                confidence=float(technique.get("confidence", 1.0)),
                reason=str(technique.get("reason", "manual")),
                parameters={
                    str(key): float(value)
                    for key, value in technique.get("parameters", {}).items()
                },
            )
        )
    if kind == DeleteTechnique.kind:
        return DeleteTechnique(
            technique_id=str(raw["technique_id"]),
            expected_technique_hash=raw.get("expected_technique_hash"),
        )
    if kind == InsertBeat.kind:
        return InsertBeat(
            track_id=str(raw["track_id"]),
            measure_id=str(raw["measure_id"]),
            beat=score_beat_from_dict(raw["beat"]),
            performance_events=tuple(
                PerformanceEvent(
                    id=str(value["id"]),
                    note_id=str(value["note_id"]),
                    start=Rational.from_value(value["start"]),
                    duration=Rational.from_value(value["duration"]),
                    velocity=int(value["velocity"]),
                    controls=list(value.get("controls", [])),
                )
                for value in raw.get("performance_events", [])
            ),
        )
    if kind == DeleteBeat.kind:
        return DeleteBeat(
            beat_id=str(raw["beat_id"]),
            note_ids=tuple(str(value) for value in raw.get("note_ids", [])),
            expected_beat_hash=raw.get("expected_beat_hash"),
        )
    if kind == InsertMeasureGroup.kind:
        return InsertMeasureGroup(
            entries=tuple(
                TrackMeasureEntry(
                    track_id=str(value["track_id"]),
                    measure=score_measure_from_dict(value["measure"]),
                )
                for value in raw.get("entries", [])
            ),
            performance_events=tuple(
                PerformanceEvent(
                    id=str(value["id"]),
                    note_id=str(value["note_id"]),
                    start=Rational.from_value(value["start"]),
                    duration=Rational.from_value(value["duration"]),
                    velocity=int(value["velocity"]),
                    controls=list(value.get("controls", [])),
                )
                for value in raw.get("performance_events", [])
            ),
            techniques=tuple(
                ScoreTechnique(
                    id=str(value["id"]),
                    type=str(value["type"]),
                    note_ids=[str(note_id) for note_id in value.get("note_ids", [])],
                    confidence=float(value.get("confidence", 1.0)),
                    reason=str(value.get("reason", "manual")),
                    parameters={
                        str(key): float(parameter)
                        for key, parameter in value.get("parameters", {}).items()
                    },
                )
                for value in raw.get("techniques", [])
            ),
            tempo_changes=tuple(
                TempoChange(
                    id=str(value["id"]),
                    position=Rational.from_value(value["position"]),
                    bpm=float(value["bpm"]),
                )
                for value in raw.get("tempo_changes", [])
            ),
            time_signatures=tuple(
                TimeSignatureChange(
                    id=str(value["id"]),
                    position=Rational.from_value(value["position"]),
                    numerator=int(value["numerator"]),
                    denominator=int(value["denominator"]),
                )
                for value in raw.get("time_signatures", [])
            ),
        )
    if kind == DeleteMeasureGroup.kind:
        hashes = raw.get("expected_measure_hashes", {})
        return DeleteMeasureGroup(
            measure_ids=tuple(str(value) for value in raw.get("measure_ids", [])),
            expected_measure_hashes=tuple(
                (str(measure_id), str(value))
                for measure_id, value in hashes.items()
            ),
        )
    if kind == SetTrackName.kind:
        return SetTrackName(
            track_id=str(raw["track_id"]),
            name=str(raw["name"]),
            expected_name=(
                str(raw["expected_name"]) if raw.get("expected_name") is not None else None
            ),
        )
    if kind == SetTrackInstrument.kind:
        return SetTrackInstrument(
            track_id=str(raw["track_id"]),
            instrument=dict(raw.get("instrument", {})),
            expected_instrument=(
                dict(raw["expected_instrument"])
                if raw.get("expected_instrument") is not None
                else None
            ),
        )
    if kind == SetTrackNotationMode.kind:
        return SetTrackNotationMode(
            track_id=str(raw["track_id"]),
            notation_mode=str(raw["notation_mode"]),
            expected_notation_mode=(
                str(raw["expected_notation_mode"])
                if raw.get("expected_notation_mode") is not None
                else None
            ),
        )
    if kind == SetTrackMixer.kind:
        mixer = raw.get("mixer", {})
        expected = raw.get("expected_mixer")
        return SetTrackMixer(
            track_id=str(raw["track_id"]),
            mixer=TrackMixer(
                volume=float(mixer.get("volume", 0.8)),
                pan=float(mixer.get("pan", 0.0)),
                mute=bool(mixer.get("mute", False)),
                solo=bool(mixer.get("solo", False)),
            ),
            expected_mixer=(
                TrackMixer(
                    volume=float(expected.get("volume", 0.8)),
                    pan=float(expected.get("pan", 0.0)),
                    mute=bool(expected.get("mute", False)),
                    solo=bool(expected.get("solo", False)),
                )
                if isinstance(expected, dict)
                else None
            ),
        )
    if kind == ReorderTracks.kind:
        expected = raw.get("expected_track_ids")
        return ReorderTracks(
            track_ids=tuple(str(value) for value in raw.get("track_ids", [])),
            expected_track_ids=(
                tuple(str(value) for value in expected)
                if isinstance(expected, list)
                else None
            ),
        )
    if kind == InsertTrack.kind:
        return InsertTrack(score_track_from_dict(raw["track"]))
    if kind == DeleteTrack.kind:
        return DeleteTrack(
            track_id=str(raw["track_id"]),
            expected_track_hash=raw.get("expected_track_hash"),
        )
    raise ValueError(f"Unsupported ScoreOperation kind: {kind!r}")


def transaction_to_dict(transaction: ScoreTransaction) -> dict[str, Any]:
    return {
        "schema_version": transaction.schema_version,
        "command_id": transaction.command_id,
        "document_id": transaction.document_id,
        "actor_id": transaction.actor_id,
        "base_revision": transaction.base_revision,
        "origin": transaction.origin,
        "intent": transaction.intent,
        "selection": (
            {
                "scope": transaction.selection.scope,
                "track_ids": list(transaction.selection.track_ids),
                "measure_ids": list(transaction.selection.measure_ids),
                "beat_ids": list(transaction.selection.beat_ids),
                "note_ids": list(transaction.selection.note_ids),
                "start": (
                    transaction.selection.start.to_dict()
                    if transaction.selection.start is not None
                    else None
                ),
                "end": (
                    transaction.selection.end.to_dict()
                    if transaction.selection.end is not None
                    else None
                ),
            }
            if transaction.selection is not None
            else None
        ),
        "operations": [operation_to_dict(value) for value in transaction.operations],
        "created_at": transaction.created_at,
    }


def transaction_from_dict(raw: dict[str, Any]) -> ScoreTransaction:
    version = str(raw.get("schema_version", ""))
    if not version.startswith("1."):
        raise ValueError(f"Unsupported ScoreTransaction version: {version!r}")
    origin = str(raw["origin"])
    allowed_origins = {"manual", "import", "repair", "humanize", "ai", "migration"}
    if origin not in allowed_origins:
        raise ValueError(f"Unsupported command origin: {origin!r}")
    selection_raw = raw.get("selection")
    return ScoreTransaction(
        schema_version=version,
        command_id=str(raw["command_id"]),
        document_id=str(raw["document_id"]),
        actor_id=str(raw["actor_id"]),
        base_revision=int(raw["base_revision"]),
        origin=origin,  # type: ignore[arg-type]
        intent=str(raw["intent"]),
        operations=tuple(operation_from_dict(value) for value in raw.get("operations", [])),
        selection=(
            SelectionAnchor(
                scope=str(selection_raw["scope"]),
                track_ids=tuple(str(value) for value in selection_raw.get("track_ids", [])),
                measure_ids=tuple(
                    str(value) for value in selection_raw.get("measure_ids", [])
                ),
                beat_ids=tuple(str(value) for value in selection_raw.get("beat_ids", [])),
                note_ids=tuple(str(value) for value in selection_raw.get("note_ids", [])),
                start=(
                    Rational.from_value(selection_raw["start"])
                    if selection_raw.get("start") is not None
                    else None
                ),
                end=(
                    Rational.from_value(selection_raw["end"])
                    if selection_raw.get("end") is not None
                    else None
                ),
            )
            if selection_raw is not None
            else None
        ),
        created_at=str(raw["created_at"]),
    )


def transaction_fingerprint(transaction: ScoreTransaction) -> str:
    payload = json.dumps(
        transaction_to_dict(transaction),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def touches_conflict(left: FieldTouch, right: FieldTouch) -> bool:
    """Return whether two persisted field touches cannot be safely rebased."""

    left_kind, left_id, left_field = left
    right_kind, right_id, right_field = right
    # Commands in this check are already scoped to one document. A trusted
    # whole-snapshot transition therefore conflicts with every entity edit.
    if left_kind == "document" or right_kind == "document":
        return True
    return (
        left_kind == right_kind
        and left_id == right_id
        and (left_field == right_field or left_field == "*" or right_field == "*")
    )


class ScoreEditor:
    """Pure revision/command engine used before persistence is introduced."""

    def __init__(self, document: ScoreDocument, *, revision: int = 0) -> None:
        if revision < 0:
            raise ValueError("Revision cannot be negative")
        validation = validate_score_document(document)
        if validation.has_errors:
            raise ScoreOperationError(
                "; ".join(f"{issue.code}: {issue.message}" for issue in validation.issues[:5])
            )
        self._document = document_from_dict(document_to_dict(document))
        self._document.validation = validation
        self._initialize(revision)

    def _initialize(self, revision: int) -> None:
        self._canonical_payload: str | None = None
        self._document_hash: str | None = None
        self._revision = revision
        self._records: dict[str, AcceptedCommand] = {}
        self._history: list[AcceptedCommand] = []

    @classmethod
    def from_verified_snapshot(
        cls,
        document: ScoreDocument,
        *,
        revision: int,
        canonical_payload: str,
        content_hash: str,
    ) -> ScoreEditor:
        """Take ownership of a freshly decoded, hash-verified durable snapshot.

        The next transaction still validates the complete candidate before it
        becomes visible. This entry point only avoids validating and cloning
        the unchanged current revision a second time in the persistence path.
        """

        if revision < 0:
            raise ValueError("Revision cannot be negative")
        editor = cls.__new__(cls)
        editor._document = document
        editor._initialize(revision)
        editor._canonical_payload = canonical_payload
        editor._document_hash = content_hash
        return editor

    @property
    def document(self) -> ScoreDocument:
        return document_from_dict(document_to_dict(self._document))

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def document_hash(self) -> str:
        return self.canonical_snapshot().content_hash

    def canonical_snapshot(self) -> CanonicalScoreSnapshot:
        """Serialize once for durable storage without exposing mutable state."""

        if self._canonical_payload is None or self._document_hash is None:
            self._canonical_payload = canonical_document_json(self._document)
            self._document_hash = hashlib.sha256(
                self._canonical_payload.encode("utf-8")
            ).hexdigest()
        return CanonicalScoreSnapshot(
            payload=self._canonical_payload,
            content_hash=self._document_hash,
            schema_version=self._document.schema_version,
            validation_status=self._document.validation.status,
        )

    def apply(self, transaction: ScoreTransaction) -> CommandApplyResult:
        if not transaction.command_id or not transaction.actor_id or not transaction.intent:
            raise ScoreCommandError("Command ID, actor and intent are required")
        if transaction.document_id != self._document.id:
            raise ScoreCommandError("Transaction targets a different document")
        if not transaction.operations:
            raise ScoreCommandError("A score transaction requires at least one operation")
        if transaction.base_revision < 0 or transaction.base_revision > self._revision:
            raise ScoreConflictError("Transaction base revision is not available")

        fingerprint = transaction_fingerprint(transaction)
        existing = self._records.get(transaction.command_id)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise ScoreConflictError("Command ID was already used for a different payload")
            return CommandApplyResult(
                command_id=transaction.command_id,
                revision=existing.revision,
                document_hash=existing.document_hash,
                rebased=existing.rebased,
                idempotent_replay=True,
            )

        touched = frozenset(
            touch for operation in transaction.operations for touch in operation.touches()
        )
        intervening = [
            touch
            for record in self._history
            if record.revision > transaction.base_revision
            for touch in record.touched_fields
        ]
        conflicts = [
            (left, right)
            for left in touched
            for right in intervening
            if touches_conflict(left, right)
        ]
        if conflicts:
            raise ScoreConflictError(
                "Transaction conflicts with accepted changes after its base revision"
            )

        candidate = document_from_dict(json.loads(self.canonical_snapshot().payload))
        inverse: list[ScoreOperationType] = []
        for operation in transaction.operations:
            inverse.append(operation.apply(candidate))
        validation_scope = _incremental_validation_scope(
            candidate,
            transaction.operations,
        )
        if validation_scope is None:
            validation = validate_score_document(candidate)
        else:
            track_ids, performance_note_ids = validation_scope
            validation = validate_score_document_changes(
                candidate,
                previous=self._document.validation,
                track_ids=track_ids,
                performance_note_ids=performance_note_ids,
            )
        if validation.has_errors:
            raise ScoreOperationError(
                "; ".join(
                    f"{issue.code}: {issue.message}"
                    for issue in validation.issues
                    if issue.severity == "error"
                )
            )
        candidate.validation = validation
        revision = self._revision + 1
        revision_payload = canonical_document_json(candidate)
        revision_hash = hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()
        record = AcceptedCommand(
            transaction=transaction,
            revision=revision,
            document_hash=revision_hash,
            inverse_operations=tuple(reversed(inverse)),
            touched_fields=touched,
            fingerprint=fingerprint,
            rebased=transaction.base_revision != self._revision,
        )
        self._document = candidate
        self._canonical_payload = revision_payload
        self._document_hash = revision_hash
        self._revision = revision
        self._records[transaction.command_id] = record
        self._history.append(record)
        return CommandApplyResult(
            command_id=transaction.command_id,
            revision=revision,
            document_hash=revision_hash,
            rebased=record.rebased,
        )

    def accepted_command(self, command_id: str) -> AcceptedCommand | None:
        """Return immutable metadata required by a durable command ledger."""

        return self._records.get(command_id)

    def undo(
        self,
        target_command_id: str,
        *,
        command_id: str,
        actor_id: str,
    ) -> CommandApplyResult:
        target = self._records.get(target_command_id)
        if target is None:
            raise ScoreOperationError(f"Command {target_command_id!r} does not exist")
        if target.transaction.actor_id != actor_id:
            raise ScoreCommandError("An actor may undo only their own command")
        return self.apply(
            ScoreTransaction(
                command_id=command_id,
                document_id=self._document.id,
                actor_id=actor_id,
                base_revision=self._revision,
                origin="manual",
                intent=f"Undo {target.transaction.intent}",
                operations=copy.deepcopy(target.inverse_operations),
                selection=target.transaction.selection,
            )
        )


__all__ = [
    "AcceptedCommand",
    "AddNote",
    "AddTechnique",
    "CanonicalScoreSnapshot",
    "CommandApplyResult",
    "DeleteBeat",
    "DeleteMeasureGroup",
    "DeleteNote",
    "DeleteTechnique",
    "DeleteTrack",
    "InsertBeat",
    "InsertMeasureGroup",
    "InsertTrack",
    "ReorderTracks",
    "ScoreCommandError",
    "ScoreConflictError",
    "ScoreEditor",
    "ScoreOperationError",
    "ScoreOperationType",
    "ScoreTransaction",
    "SelectionAnchor",
    "SetBeatDuration",
    "SetBeatDynamic",
    "SetBeatTie",
    "SetBeatVoice",
    "SetNoteFretting",
    "SetNotePitch",
    "SetPerformanceVelocity",
    "SetTrackInstrument",
    "SetTrackMixer",
    "SetTrackName",
    "SetTrackNotationMode",
    "TrackMeasureEntry",
    "operation_from_dict",
    "operation_to_dict",
    "transaction_fingerprint",
    "transaction_from_dict",
    "transaction_to_dict",
    "touches_conflict",
]

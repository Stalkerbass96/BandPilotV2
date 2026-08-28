"""Independent structural and playability validation for ScoreDocument 3.x."""

from __future__ import annotations

import math
from collections import Counter

from fretpilot.drum.notation import notation_voice
from fretpilot.editor.document import (
    DocumentValidationIssue,
    DocumentValidationState,
    ScoreBeat,
    ScoreDocument,
    ScoreTrack,
)

_LINKED_FRETTED_TECHNIQUES = frozenset({"hammer_on", "pull_off", "slide"})
_DYNAMIC_MARKS = frozenset({"ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"})
_NOTATION_MODES = {
    "guitar": frozenset({"standard_tab", "tablature", "standard"}),
    "bass": frozenset({"standard_tab", "tablature", "standard"}),
    "drums": frozenset({"percussion"}),
    "keys": frozenset({"grand_staff", "standard"}),
    "generic": frozenset({"standard"}),
}


class ScoreDocumentValidationError(ValueError):
    def __init__(self, issues: list[DocumentValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues[:5])
        super().__init__(f"ScoreDocument contains {len(issues)} blocking issue(s): {summary}")


def _issue(
    issues: list[DocumentValidationIssue],
    code: str,
    message: str,
    *entity_ids: str,
    severity: str = "error",
) -> None:
    issues.append(
        DocumentValidationIssue(
            code=code,
            severity=severity,
            message=message,
            entity_ids=[value for value in entity_ids if value],
        )
    )


def _register_id(
    seen: set[str], issues: list[DocumentValidationIssue], entity_id: str, kind: str
) -> None:
    if not entity_id:
        _issue(issues, "document.empty_id", f"{kind} requires a stable ID.")
    elif entity_id in seen:
        _issue(
            issues,
            "document.duplicate_id",
            f"Stable ID {entity_id!r} is used by more than one entity.",
            entity_id,
        )
    seen.add(entity_id)


def _validate_fretted_beat(
    track: ScoreTrack, beat: ScoreBeat, issues: list[DocumentValidationIssue]
) -> None:
    tuning = [int(value) for value in track.instrument.get("tuning", [])]
    fret_count = int(track.instrument.get("fret_count", 24))
    capo = int(track.instrument.get("capo", 0))
    if not tuning:
        _issue(
            issues,
            f"{track.family}.tuning_missing",
            "Fretted track requires an explicit tuning.",
            track.id,
        )
        return
    strings: list[int] = []
    for note in beat.notes:
        realization = note.realization
        if realization.kind != track.family:
            _issue(
                issues,
                f"{track.family}.realization_kind",
                "Note realization kind does not match its track family.",
                track.id,
                note.id,
            )
            continue
        if realization.string is None or realization.fret is None:
            _issue(
                issues,
                f"{track.family}.fingering_missing",
                "Fretted note requires string and fret.",
                track.id,
                note.id,
            )
            continue
        if not 1 <= realization.string <= len(tuning):
            _issue(
                issues,
                f"{track.family}.string_range",
                "String is outside the track tuning.",
                track.id,
                note.id,
            )
            continue
        if not 0 <= realization.fret <= fret_count:
            _issue(
                issues,
                f"{track.family}.fret_range",
                "Fret is outside the supported fretboard.",
                track.id,
                note.id,
            )
            continue
        open_pitch = tuning[len(tuning) - realization.string]
        if open_pitch + capo + realization.fret != note.pitch:
            _issue(
                issues,
                f"{track.family}.pitch_mismatch",
                "String and fret do not produce the note pitch.",
                track.id,
                note.id,
            )
        strings.append(realization.string)
    if len(strings) != len(set(strings)):
        _issue(
            issues,
            f"{track.family}.string_collision",
            "Simultaneous fretted notes cannot occupy the same string.",
            track.id,
            beat.id,
        )


def _validate_drum_beat(
    track: ScoreTrack, beat: ScoreBeat, issues: list[DocumentValidationIssue]
) -> None:
    for note in beat.notes:
        if note.realization.kind != "drums":
            _issue(
                issues,
                "drums.realization_kind",
                "Drum note requires a drum realization.",
                track.id,
                note.id,
            )
            continue
        piece = note.realization.piece
        if not piece:
            _issue(
                issues,
                "drums.piece_missing",
                "Drum note requires a resolved kit piece.",
                track.id,
                note.id,
            )
        elif notation_voice(piece) != beat.voice:
            _issue(
                issues,
                "drums.voice_policy",
                "Hands/cymbals use voice 1 and feet use voice 2.",
                track.id,
                beat.id,
                note.id,
            )


def _tie_note_keys(track: ScoreTrack, beat: ScoreBeat) -> set[object]:
    if track.family in {"guitar", "bass"}:
        return {(note.pitch, note.realization.string) for note in beat.notes}
    return {note.pitch for note in beat.notes}


def _validate_track_ties(
    track: ScoreTrack,
    beats: list[ScoreBeat],
    issues: list[DocumentValidationIssue],
) -> None:
    lanes: dict[tuple[str, int], list[ScoreBeat]] = {}
    for beat in beats:
        lanes.setdefault((beat.staff_id, beat.voice), []).append(beat)
        if not (beat.tie_in or beat.tie_out):
            continue
        if beat.kind != "notes" or not beat.notes:
            _issue(issues, "tie.rest", "A rest cannot start or stop a tie.", beat.id)
        if track.family == "drums":
            _issue(issues, "tie.drums", "Drum notes do not use sustain ties.", beat.id)

    for lane_beats in lanes.values():
        ordered = sorted(lane_beats, key=lambda value: (value.start, value.duration, value.id))
        for index, beat in enumerate(ordered):
            if beat.kind != "notes" or not beat.notes or track.family == "drums":
                continue
            previous = ordered[index - 1] if index > 0 else None
            following = ordered[index + 1] if index + 1 < len(ordered) else None
            if beat.tie_out:
                if (
                    following is None
                    or following.start != beat.start + beat.duration
                    or not following.tie_in
                ):
                    _issue(
                        issues,
                        "tie.destination",
                        "A tie-out requires an adjacent tie-in in the same staff and voice.",
                        beat.id,
                    )
                elif not (_tie_note_keys(track, beat) & _tie_note_keys(track, following)):
                    _issue(
                        issues,
                        "tie.pitch_mismatch",
                        "A tie must connect at least one matching pitch and string.",
                        beat.id,
                        following.id,
                    )
            if beat.tie_in and (
                previous is None
                or previous.start + previous.duration != beat.start
                or not previous.tie_out
            ):
                _issue(
                    issues,
                    "tie.origin",
                    "A tie-in requires an adjacent tie-out in the same staff and voice.",
                    beat.id,
                )


def _validate_track(
    track: ScoreTrack,
    seen: set[str],
    note_to_beat: dict[str, ScoreBeat],
    issues: list[DocumentValidationIssue],
) -> None:
    _register_id(seen, issues, track.id, "track")
    if not track.name.strip():
        _issue(issues, "track.name", "Track name cannot be empty.", track.id)
    allowed_modes = _NOTATION_MODES.get(track.family)
    if allowed_modes is None or track.notation_mode not in allowed_modes:
        _issue(
            issues,
            "track.notation_mode",
            "Notation mode is not supported for this instrument family.",
            track.id,
        )
    if (
        not math.isfinite(track.mixer.volume)
        or not 0 <= track.mixer.volume <= 1
        or not math.isfinite(track.mixer.pan)
        or not -1 <= track.mixer.pan <= 1
    ):
        _issue(
            issues,
            "track.mixer",
            "Track volume must be 0..1 and pan must be -1..1.",
            track.id,
        )
    program = track.instrument.get("program")
    if program is not None and (
        isinstance(program, bool) or not isinstance(program, int) or not 0 <= program <= 127
    ):
        _issue(issues, "track.program", "MIDI program must be in 0..127.", track.id)
    capo = track.instrument.get("capo", 0)
    if isinstance(capo, bool) or not isinstance(capo, int) or not 0 <= capo <= 24:
        _issue(issues, "track.capo", "Capo must be an integer in 0..24.", track.id)
    staff_ids: set[str] = set()
    for staff in track.staves:
        _register_id(seen, issues, staff.id, "staff")
        staff_ids.add(staff.id)
        if staff.line_count <= 0:
            _issue(issues, "staff.line_count", "Staff line count must be positive.", staff.id)
    if not staff_ids:
        _issue(issues, "track.staff_missing", "Every score track requires a staff.", track.id)

    measure_numbers: set[int] = set()
    track_beats: list[ScoreBeat] = []
    for measure in track.measures:
        _register_id(seen, issues, measure.id, "measure")
        if measure.number in measure_numbers:
            _issue(
                issues,
                "measure.duplicate_number",
                "Measure number is duplicated in a track.",
                track.id,
                measure.id,
            )
        measure_numbers.add(measure.number)
        if measure.duration <= 0 or measure.numerator <= 0 or measure.denominator <= 0:
            _issue(
                issues,
                "measure.invalid",
                "Measure duration and time signature must be positive.",
                measure.id,
            )
        measure_end = measure.start + measure.duration
        beats_by_lane: dict[tuple[str, int], list[ScoreBeat]] = {}
        for beat in measure.beats:
            track_beats.append(beat)
            _register_id(seen, issues, beat.id, "beat")
            if beat.staff_id not in staff_ids:
                _issue(
                    issues,
                    "beat.staff_missing",
                    "Beat references a staff outside its track.",
                    beat.id,
                    beat.staff_id,
                )
            if beat.kind not in {"notes", "rest"}:
                _issue(issues, "beat.kind", "Beat kind must be notes or rest.", beat.id)
            if beat.kind == "notes" and not beat.notes:
                _issue(
                    issues, "beat.empty_notes", "A note beat requires at least one note.", beat.id
                )
            if beat.kind == "rest" and beat.notes:
                _issue(issues, "beat.rest_has_notes", "A rest beat cannot contain notes.", beat.id)
            if beat.voice not in {1, 2, 3, 4}:
                _issue(issues, "beat.voice", "Beat voice must be in 1..4.", beat.id)
            if beat.duration <= 0:
                _issue(issues, "beat.duration", "Beat duration must be positive.", beat.id)
            dynamic = beat.properties.get("dynamic")
            if dynamic is not None and dynamic not in _DYNAMIC_MARKS:
                _issue(
                    issues,
                    "beat.dynamic",
                    "Beat dynamic must be one of ppp, pp, p, mp, mf, f, ff or fff.",
                    beat.id,
                )
            if beat.start < measure.start or beat.start >= measure_end:
                _issue(issues, "beat.measure_bounds", "Beat onset is outside its measure.", beat.id)
            if beat.start + beat.duration > measure_end:
                _issue(issues, "beat.measure_overflow", "Beat extends beyond its measure.", beat.id)
            beats_by_lane.setdefault((beat.staff_id, beat.voice), []).append(beat)
            for note in beat.notes:
                _register_id(seen, issues, note.id, "note")
                note_to_beat[note.id] = beat
                if not 0 <= note.pitch <= 127:
                    _issue(issues, "note.pitch", "MIDI pitch must be in 0..127.", note.id)
            if track.family in {"guitar", "bass"}:
                _validate_fretted_beat(track, beat, issues)
            elif track.family == "drums":
                _validate_drum_beat(track, beat, issues)
            else:
                for note in beat.notes:
                    if note.realization.kind != track.family:
                        _issue(
                            issues,
                            f"{track.family}.realization_kind",
                            "Note realization kind does not match its track family.",
                            track.id,
                            note.id,
                        )
        for lane_beats in beats_by_lane.values():
            ordered = sorted(lane_beats, key=lambda value: (value.start, value.duration, value.id))
            previous: ScoreBeat | None = None
            previous_end = measure.start
            for beat in ordered:
                if previous is not None and beat.start < previous_end:
                    _issue(
                        issues,
                        "beat.overlap",
                        "Beats in the same staff and voice cannot overlap.",
                        measure.id,
                        previous.id,
                        beat.id,
                        severity=(
                            "warning"
                            if track.instrument.get("realization_status") == "unprepared"
                            else "error"
                        ),
                    )
                candidate_end = beat.start + beat.duration
                if previous is None or candidate_end > previous_end:
                    previous = beat
                    previous_end = candidate_end
    _validate_track_ties(track, track_beats, issues)


def _validate_techniques(
    document: ScoreDocument,
    seen: set[str],
    note_to_beat: dict[str, ScoreBeat],
    issues: list[DocumentValidationIssue],
) -> None:
    techniques = {value.id: value for value in document.techniques}
    for technique in document.techniques:
        _register_id(seen, issues, technique.id, "technique")
        missing = [note_id for note_id in technique.note_ids if note_id not in note_to_beat]
        if missing:
            _issue(
                issues,
                "technique.note_missing",
                "Technique references a missing note.",
                technique.id,
                *missing,
            )
            continue
        if technique.type in _LINKED_FRETTED_TECHNIQUES:
            if len(technique.note_ids) != 2:
                _issue(
                    issues,
                    "technique.link_arity",
                    "Linked fretted technique requires two notes.",
                    technique.id,
                )
            elif (
                note_to_beat[technique.note_ids[0]].start
                >= note_to_beat[technique.note_ids[1]].start
            ):
                _issue(
                    issues,
                    "technique.order",
                    "Linked technique source must precede its target.",
                    technique.id,
                )
    for track in document.tracks:
        for measure in track.measures:
            for beat in measure.beats:
                for note in beat.notes:
                    for technique_id in note.technique_ids:
                        technique = techniques.get(technique_id)
                        if technique is None:
                            _issue(
                                issues,
                                "technique.reference_missing",
                                "Note references a missing technique.",
                                note.id,
                                technique_id,
                            )
                        elif note.id not in technique.note_ids:
                            _issue(
                                issues,
                                "technique.reverse_reference",
                                "Technique and note references disagree.",
                                note.id,
                                technique_id,
                            )


def _track_entity_ids(track: ScoreTrack) -> set[str]:
    return {
        track.id,
        *(staff.id for staff in track.staves),
        *(measure.id for measure in track.measures),
        *(
            beat.id
            for measure in track.measures
            for beat in measure.beats
        ),
        *(
            note.id
            for measure in track.measures
            for beat in measure.beats
            for note in beat.notes
        ),
    }


def validate_score_document_changes(
    document: ScoreDocument,
    *,
    previous: DocumentValidationState,
    track_ids: set[str],
    performance_note_ids: set[str],
) -> DocumentValidationState:
    """Revalidate field-only changes while preserving unaffected diagnostics.

    This fast path is valid only after a hash-verified, previously passing
    revision and for operations that cannot add, remove or rename entities.
    Callers classify the operation union; uncertain or structural changes fall
    back to the complete validator.
    """

    if previous.status != "passed" or previous.has_errors:
        return validate_score_document(document)

    tracks_by_id = {track.id: track for track in document.tracks}
    if not track_ids.issubset(tracks_by_id):
        return validate_score_document(document)

    invalidated_entity_ids: set[str] = set()
    refreshed_issues: list[DocumentValidationIssue] = []
    seen: set[str] = set()
    note_to_beat: dict[str, ScoreBeat] = {}
    for track in document.tracks:
        if track.id not in track_ids:
            continue
        invalidated_entity_ids.update(_track_entity_ids(track))
        _validate_track(track, seen, note_to_beat, refreshed_issues)

    for note_id in performance_note_ids:
        events = [event for event in document.performance.events if event.note_id == note_id]
        if len(events) != 1:
            return validate_score_document(document)
        event = events[0]
        invalidated_entity_ids.update({note_id, event.id})
        if event.duration <= 0 or not 1 <= event.velocity <= 127:
            _issue(
                refreshed_issues,
                "performance.invalid",
                "Performance duration and velocity must be valid.",
                event.id,
            )

    preserved_issues = [
        issue
        for issue in previous.issues
        if invalidated_entity_ids.isdisjoint(issue.entity_ids)
    ]
    issues = [*preserved_issues, *refreshed_issues]
    status = "failed" if any(issue.severity == "error" for issue in issues) else "passed"
    return DocumentValidationState(status=status, issues=issues)


def validate_score_document(
    document: ScoreDocument, *, raise_on_error: bool = False
) -> DocumentValidationState:
    """Validate without repairing or mutating the supplied document."""

    issues: list[DocumentValidationIssue] = []
    if not document.schema_version.startswith("3."):
        _issue(issues, "document.schema", "ScoreDocument major version must be 3.", document.id)
    seen: set[str] = set()
    _register_id(seen, issues, document.id, "document")
    for source_track in document.source.tracks:
        _register_id(seen, issues, source_track.id, "source track")
    note_to_beat: dict[str, ScoreBeat] = {}
    orders = [track.order for track in document.tracks]
    if sorted(orders) != list(range(len(document.tracks))):
        _issue(
            issues,
            "track.order",
            "Track order must be contiguous and unique from zero.",
            *(track.id for track in document.tracks),
        )
    for track in document.tracks:
        _validate_track(track, seen, note_to_beat, issues)
    for tempo in document.tempo_map:
        _register_id(seen, issues, tempo.id, "tempo change")
        if tempo.position < 0 or tempo.bpm <= 0:
            _issue(issues, "tempo.invalid", "Tempo position and BPM must be valid.", tempo.id)
    for signature in document.time_signatures:
        _register_id(seen, issues, signature.id, "time signature")
        if signature.position < 0 or signature.numerator <= 0 or signature.denominator <= 0:
            _issue(
                issues,
                "time_signature.invalid",
                "Time signature position and values must be valid.",
                signature.id,
            )
    _validate_techniques(document, seen, note_to_beat, issues)
    performance_note_ids = [value.note_id for value in document.performance.events]
    for note_id, count in Counter(performance_note_ids).items():
        if count > 1:
            _issue(
                issues,
                "performance.duplicate_note",
                "A note has more than one performance event.",
                note_id,
            )
    for event in document.performance.events:
        _register_id(seen, issues, event.id, "performance event")
        if event.note_id not in note_to_beat:
            _issue(
                issues,
                "performance.note_missing",
                "Performance event references a missing note.",
                event.id,
                event.note_id,
            )
        if event.duration <= 0 or not 1 <= event.velocity <= 127:
            _issue(
                issues,
                "performance.invalid",
                "Performance duration and velocity must be valid.",
                event.id,
            )
    performance_ids = set(performance_note_ids)
    for note_id in note_to_beat:
        if note_id not in performance_ids:
            _issue(
                issues,
                "performance.event_missing",
                "Every score note requires a performance event.",
                note_id,
            )
    for unresolved in document.unresolved_events:
        _register_id(seen, issues, unresolved.id, "unresolved source event")
        _issue(
            issues,
            "source.unresolved_event",
            unresolved.reason,
            unresolved.id,
            severity="warning",
        )
    for transformation in document.transformations:
        _register_id(seen, issues, transformation.id, "transformation")

    status = "failed" if any(issue.severity == "error" for issue in issues) else "passed"
    result = DocumentValidationState(status=status, issues=issues)
    if raise_on_error and result.has_errors:
        raise ScoreDocumentValidationError([issue for issue in issues if issue.severity == "error"])
    return result


__all__ = [
    "ScoreDocumentValidationError",
    "validate_score_document_changes",
    "validate_score_document",
]

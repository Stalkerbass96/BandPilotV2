"""Hard playability and notation validation for SongIR 2.0."""

from __future__ import annotations

from collections import Counter, defaultdict

from fretpilot.ir.song import SongIR, ValidationIssue, ValidationLayer

_LINKED_GUITAR_TECHNIQUES = frozenset({"hammer_on", "pull_off", "slide"})


class ScoreValidationError(ValueError):
    """Raised when an exporter is asked to serialize an invalid score."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues[:5])
        super().__init__(f"Score contains {len(issues)} blocking issue(s): {summary}")


def _issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    *,
    track_id: str | None = None,
    note_ids: list[str] | None = None,
    severity: str = "error",
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=severity,
            message=message,
            track_id=track_id,
            note_ids=note_ids or [],
        )
    )


def _validate_fretted_track(song: SongIR, track, issues: list[ValidationIssue]) -> None:
    family = track.family
    label = "Bass" if family == "bass" else "Guitar"
    code = family
    tuning = [int(value) for value in track.instrument.get("tuning", [])]
    fret_count = int(track.instrument.get("fret_count", 24))
    if not tuning:
        _issue(issues, f"{code}.tuning_missing", f"{label} track has no tuning.", track_id=track.id)
        return

    onsets: dict[tuple[int, float], list] = defaultdict(list)
    for measure in track.measures:
        for event in measure.events:
            onsets[(measure.number, round(event.score.start_beat, 6))].append(event)
            realization = event.realization
            if realization.kind != family:
                _issue(
                    issues,
                    f"{code}.realization_kind",
                    f"{label} event does not have a {family} realization.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
                continue
            if realization.string is None or realization.fret is None:
                _issue(
                    issues,
                    f"{code}.unassigned_fingering",
                    f"Every exported {family} note requires an assigned string and fret.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
                continue
            if not 1 <= realization.string <= len(tuning):
                _issue(
                    issues,
                    f"{code}.string_range",
                    f"String {realization.string} is outside this instrument's tuning.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
                continue
            if not 0 <= realization.fret <= fret_count:
                _issue(
                    issues,
                    f"{code}.fret_range",
                    f"Fret {realization.fret} is outside 0..{fret_count}.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
                continue
            open_pitch = tuning[len(tuning) - realization.string]
            if open_pitch + realization.fret != event.pitch:
                _issue(
                    issues,
                    f"{code}.pitch_mismatch",
                    "Assigned string/fret does not produce the event pitch.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
            if realization.fretting_digit is not None and not 0 <= realization.fretting_digit <= 4:
                _issue(
                    issues,
                    f"{code}.finger_range",
                    "Fretting digit must be 0 (open) or 1..4.",
                    track_id=track.id,
                    note_ids=[event.id],
                )

    for chord in onsets.values():
        strings = [event.realization.string for event in chord if event.realization.string is not None]
        if len(strings) != len(set(strings)):
            _issue(
                issues,
                f"{code}.chord_string_collision",
                f"Simultaneous {family} notes cannot occupy the same string.",
                track_id=track.id,
                note_ids=[event.id for event in chord],
            )
        frets = [
            event.realization.fret
            for event in chord
            if event.realization.fret is not None and event.realization.fret > 0
        ]
        if frets and max(frets) - min(frets) > 4:
            _issue(
                issues,
                f"{code}.chord_span",
                "Chord requires a fret span greater than four frets.",
                track_id=track.id,
                note_ids=[event.id for event in chord],
            )


def _validate_keys(track, issues: list[ValidationIssue]) -> None:
    maximum_hand_notes = int(track.instrument.get("maximum_hand_notes", 5))
    maximum_span = int(track.instrument.get("maximum_hand_span_semitones", 12))
    onsets: dict[tuple[int, float, str], list] = defaultdict(list)
    for measure in track.measures:
        for event in measure.events:
            realization = event.realization
            if realization.kind != "keys":
                _issue(
                    issues,
                    "keys.realization_kind",
                    "Keyboard event does not have a keys realization.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
                continue
            if realization.hand not in {"left", "right"}:
                _issue(
                    issues,
                    "keys.hand_missing",
                    "Every keyboard note requires a left/right hand assignment.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
            if realization.finger is None or not 1 <= realization.finger <= 5:
                _issue(
                    issues,
                    "keys.finger_range",
                    "Keyboard finger must be in the range 1..5.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
            if realization.hand:
                onsets[(measure.number, round(event.score.start_beat, 6), realization.hand)].append(event)
    for (_measure, _onset, hand), chord in onsets.items():
        fingers = [event.realization.finger for event in chord]
        if len(chord) > maximum_hand_notes or len(fingers) != len(set(fingers)):
            _issue(
                issues,
                "keys.hand_collision",
                f"The {hand} hand has an impossible simultaneous fingering.",
                track_id=track.id,
                note_ids=[event.id for event in chord],
            )
        pitches = [event.pitch for event in chord]
        if pitches and max(pitches) - min(pitches) > maximum_span:
            _issue(
                issues,
                "keys.hand_span",
                f"The {hand} hand span exceeds one octave.",
                track_id=track.id,
                note_ids=[event.id for event in chord],
            )


def _validate_generic(track, issues: list[ValidationIssue]) -> None:
    for measure in track.measures:
        for event in measure.events:
            if event.realization.kind != "generic":
                _issue(
                    issues,
                    "generic.realization_kind",
                    "Generic pitched event has the wrong realization kind.",
                    track_id=track.id,
                    note_ids=[event.id],
                )


def _validate_notation(song: SongIR, issues: list[ValidationIssue]) -> None:
    ids: set[str] = set()
    track_ids: set[str] = set()
    performance_ids = [event.note_id for event in song.performance.events]
    performance_id_set = set(performance_ids)
    for note_id, count in sorted(Counter(performance_ids).items()):
        if count < 2:
            continue
        _issue(
            issues,
            "performance.duplicate_event",
            f"Performance event {note_id!r} is duplicated.",
            note_ids=[note_id],
        )
    for track in song.score.tracks:
        if track.id in track_ids:
            _issue(
                issues,
                "score.duplicate_track_id",
                f"Duplicate score track ID {track.id!r}.",
                track_id=track.id,
            )
        track_ids.add(track.id)
        measure_numbers: set[int] = set()
        for measure in track.measures:
            if measure.number in measure_numbers:
                _issue(
                    issues,
                    "score.duplicate_measure",
                    f"Measure {measure.number} occurs more than once in the track.",
                    track_id=track.id,
                )
            measure_numbers.add(measure.number)
            if measure.duration_beats <= 0 or measure.numerator <= 0 or measure.denominator <= 0:
                _issue(
                    issues,
                    "score.invalid_measure",
                    "Measure duration and time-signature values must be positive.",
                    track_id=track.id,
                )
            measure_end = measure.start_beat + measure.duration_beats
            for event in measure.events:
                if event.id in ids:
                    _issue(
                        issues,
                        "score.duplicate_note_id",
                        f"Duplicate note ID {event.id!r}.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                ids.add(event.id)
                if not 0 <= event.pitch <= 127:
                    _issue(
                        issues,
                        "score.pitch_range",
                        "MIDI pitch must be in the range 0..127.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if event.score.duration_beats <= 0:
                    _issue(
                        issues,
                        "score.non_positive_duration",
                        "Score duration must be positive.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if not measure.start_beat <= event.score.start_beat < measure_end:
                    _issue(
                        issues,
                        "score.measure_bounds",
                        "Event onset is outside its containing measure.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if event.score.measure_number != measure.number:
                    _issue(
                        issues,
                        "score.measure_number",
                        "Event measure number does not match its container.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if event.score.voice not in (1, 2):
                    _issue(
                        issues,
                        "score.voice_range",
                        "Only score voices 1 and 2 are currently supported.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if event.score.start_beat + event.score.duration_beats > measure_end + 1e-6:
                    _issue(
                        issues,
                        "score.measure_overflow",
                        "Event duration extends beyond its containing measure.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                expected_beat = event.score.start_beat - measure.start_beat
                if abs(expected_beat - event.score.beat_in_measure) > 1e-6:
                    _issue(
                        issues,
                        "score.beat_in_measure",
                        "beat_in_measure is inconsistent with the absolute onset.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )
                if event.id not in performance_id_set:
                    _issue(
                        issues,
                        "performance.event_missing",
                        "Every score event requires a performance event.",
                        track_id=track.id,
                        note_ids=[event.id],
                    )

    for event in song.performance.events:
        if event.note_id not in ids:
            _issue(
                issues,
                "performance.orphan_event",
                "Performance event does not reference a score event.",
                note_ids=[event.note_id],
            )
        if event.duration_beats <= 0:
            _issue(
                issues,
                "performance.non_positive_duration",
                "Performance duration must be positive.",
                note_ids=[event.note_id],
            )
        if not 1 <= event.velocity <= 127:
            _issue(
                issues,
                "performance.velocity_range",
                "Performance velocity must be in the range 1..127.",
                note_ids=[event.note_id],
            )


def _validate_drums(track, issues: list[ValidationIssue]) -> None:
    for measure in track.measures:
        for event in measure.events:
            if event.realization.kind != "drums":
                _issue(
                    issues,
                    "drums.realization_kind",
                    "Drum event does not have a drum realization.",
                    track_id=track.id,
                    note_ids=[event.id],
                )
            if not event.realization.piece:
                _issue(
                    issues,
                    "drums.piece_missing",
                    "Every drum event requires a resolved kit piece.",
                    track_id=track.id,
                    note_ids=[event.id],
                )


def _validate_techniques(song: SongIR, issues: list[ValidationIssue]) -> None:
    events = {
        event.id: event
        for track in song.score.tracks
        for measure in track.measures
        for event in measure.events
    }
    technique_ids: set[str] = set()
    for technique in song.score.techniques:
        if technique.id in technique_ids:
            _issue(issues, "technique.duplicate_id", f"Duplicate technique ID {technique.id!r}.")
        technique_ids.add(technique.id)
        missing = [note_id for note_id in technique.note_ids if note_id not in events]
        if missing:
            _issue(
                issues,
                "technique.note_missing",
                "Technique references notes which do not exist.",
                note_ids=missing,
            )
            continue
        if technique.type not in _LINKED_GUITAR_TECHNIQUES:
            continue
        if len(technique.note_ids) != 2:
            _issue(
                issues,
                "technique.link_arity",
                f"{technique.type} requires exactly two notes.",
                note_ids=list(technique.note_ids),
            )
            continue
        source, target = (events[note_id] for note_id in technique.note_ids)
        if source.realization.string != target.realization.string:
            _issue(
                issues,
                "technique.string_mismatch",
                f"{technique.type} must connect notes on the same string.",
                note_ids=list(technique.note_ids),
            )
        if source.score.start_beat >= target.score.start_beat:
            _issue(
                issues,
                "technique.order",
                f"{technique.type} source must precede its target.",
                note_ids=list(technique.note_ids),
            )
        source_fret = source.realization.fret
        target_fret = target.realization.fret
        if source_fret is None or target_fret is None:
            continue
        if technique.type == "hammer_on" and target_fret <= source_fret:
            _issue(
                issues,
                "technique.hammer_direction",
                "Hammer-on target fret must be above its source fret.",
                note_ids=list(technique.note_ids),
            )
        if technique.type == "pull_off" and target_fret >= source_fret:
            _issue(
                issues,
                "technique.pull_direction",
                "Pull-off target fret must be below its source fret.",
                note_ids=list(technique.note_ids),
            )

    known_techniques = {technique.id: technique for technique in song.score.techniques}
    for event in events.values():
        for technique_id in event.technique_ids:
            technique = known_techniques.get(technique_id)
            if technique is None:
                _issue(
                    issues,
                    "technique.reference_missing",
                    "Score event references a technique which does not exist.",
                    note_ids=[event.id],
                )
            elif event.id not in technique.note_ids:
                _issue(
                    issues,
                    "technique.reverse_reference",
                    "Technique and score-event references are inconsistent.",
                    note_ids=[event.id],
                )


def validate_song(song: SongIR, *, raise_on_error: bool = False) -> ValidationLayer:
    """Validate score truth without mutating notes or inventing fallbacks."""

    issues: list[ValidationIssue] = []
    for event in song.analysis.unresolved_events:
        _issue(
            issues,
            "source.unresolved_event",
            event.reason,
            severity="warning",
        )
    _validate_notation(song, issues)
    for track in song.score.tracks:
        if track.family in {"guitar", "bass"}:
            _validate_fretted_track(song, track, issues)
        elif track.family == "drums":
            _validate_drums(track, issues)
        elif track.family == "keys":
            _validate_keys(track, issues)
        elif track.family == "generic":
            _validate_generic(track, issues)
    _validate_techniques(song, issues)
    status = "failed" if any(issue.severity == "error" for issue in issues) else "passed"
    result = ValidationLayer(status=status, issues=issues)
    song.validation = result
    if raise_on_error and result.has_errors:
        raise ScoreValidationError([issue for issue in issues if issue.severity == "error"])
    return result


__all__ = ["ScoreValidationError", "validate_song"]

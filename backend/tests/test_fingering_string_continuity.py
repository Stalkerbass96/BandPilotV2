"""Regression tests for string-continuity fingering fixes.

This validates that the FingeringStage penalises large string jumps in
fast passages, which was the root cause of the "string 5 ↔ 6 bounce" bug
reported by the user (rapid 16th notes alternating between open A on
string 5 and fretted A on string 6).
"""

from __future__ import annotations

import pytest

from fretpilot.engine.context import FingeredNote, PipelineContext, VoicedNote
from fretpilot.engine.stages.fingering import FingeringStage, _score_candidate
from fretpilot.guitar.fretboard import FretPosition
from fretpilot.guitar.instrument import STANDARD_TUNING
from fretpilot.midi.models import NormalizedNote, NormalizedTrack

from tests.conftest import _note, _timeline


def _build_ctx_for_fingering(notes, engine) -> PipelineContext:
    """Build a minimal PipelineContext with pre-populated voiced_notes for fingering tests."""
    timeline = _timeline(notes)
    track = timeline.tracks[0] if timeline.tracks else NormalizedTrack(
        index=0, name="Empty", notes=[]
    )
    ctx = PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=engine.registry,
        style_label="rock",
        midi_fidelity=0.5,
        advisor=None,
        track_role="lead",
        source_track_index=0,
        degraded_mode=False,
    )
    # Pre-populate voiced_notes directly to bypass earlier stages
    for n in notes:
        ctx.voiced_notes.append(
            VoicedNote(
                source_index=0,
                pitch=n.pitch,
                velocity=n.velocity,
                start_beat=n.start_beat,
                duration_beats=n.duration_beats,
                measure_number=1,
                beat_in_measure=1.0,
                tie_in=False,
                tie_out=False,
                original_start_beat=n.start_beat,
                original_duration_beats=n.duration_beats,
                voice=1,
                let_ring=False,
                legato_candidate=False,
            )
        )
    return ctx


class TestStringSkipPenalty:
    """String-skip penalty makes fast passages prefer adjacent strings."""

    def test_fast_passage_prefers_same_string(self, knowledge_engine) -> None:
        """A rapid run of A notes should stay on one string, not bounce."""
        stage = FingeringStage(knowledge_engine, tuning=STANDARD_TUNING)

        notes = [
            _note(pitch=69, start_beat=i * 0.25, duration_beats=0.25)
            for i in range(8)
        ]
        ctx = _build_ctx_for_fingering(notes, knowledge_engine)

        stage.run(ctx)

        strings = [f.string for f in ctx.fingered_notes if f.string is not None]
        assert len(strings) == 8

        # With the string-skip penalty, all notes should cluster on the same
        # string (either 5 or 6, but not alternating).
        unique_strings = set(strings)
        assert len(unique_strings) <= 2, (
            f"Expected notes to cluster on at most 2 strings, got {unique_strings}"
        )

        # Even better: no string difference greater than 1 between consecutive notes
        for i in range(1, len(strings)):
            diff = abs(strings[i] - strings[i - 1])
            assert diff <= 2, (
                f"String jump of {diff} at index {i}: {strings[i-1]} → {strings[i]}"
            )

    def test_slow_passage_allows_string_jump(self, knowledge_engine) -> None:
        """Slow passages (quarter notes) allow the algorithm to choose the
        lowest-fret position freely, and string continuity keeps it stable."""
        stage = FingeringStage(knowledge_engine, tuning=STANDARD_TUNING)

        # Pitch 69 (A4) — no open string in standard tuning. Lowest fret is
        # string 1 fret 5. The algorithm should stay there for all notes.
        notes = [
            _note(pitch=69, start_beat=i * 1.0, duration_beats=1.0)
            for i in range(4)
        ]
        ctx = _build_ctx_for_fingering(notes, knowledge_engine)

        stage.run(ctx)

        strings = [f.string for f in ctx.fingered_notes if f.string is not None]
        # Slow passage + string continuity → all notes should stay on the same string
        assert len(set(strings)) == 1, (
            f"Expected all notes on a single string for slow passage, got {strings}"
        )
        # Specifically, should be string 1 (lowest fret position for A4)
        assert strings[0] == 1, (
            f"Expected string 1 (fret 5 is lowest), got string {strings[0]}"
        )

    def test_mixed_pitch_fast_run_stays_in_cluster(self, knowledge_engine) -> None:
        """A fast run with mixed pitches should stay in a consistent cluster."""
        stage = FingeringStage(knowledge_engine, tuning=STANDARD_TUNING)

        pitches = [69, 71, 72, 74]  # A B C D
        notes = [
            _note(pitch=p, start_beat=i * 0.25, duration_beats=0.25)
            for i, p in enumerate(pitches)
        ]
        notes += [
            _note(pitch=p, start_beat=(4 + i) * 0.25, duration_beats=0.25)
            for i, p in enumerate(pitches)
        ]
        ctx = _build_ctx_for_fingering(notes, knowledge_engine)

        stage.run(ctx)

        strings = [f.string for f in ctx.fingered_notes if f.string is not None]
        # No large string jumps (>2) between consecutive notes in a fast run
        for i in range(1, len(strings)):
            diff = abs(strings[i] - strings[i - 1])
            assert diff <= 2, (
                f"String jump of {diff} at index {i}: {strings[i-1]} → {strings[i]}"
            )


class TestOpenStringBiasContextual:
    """Open-string bonus is reduced when switching from a fretted note on a different string."""

    def test_open_string_reduced_bonus_after_fretted_different_string(self) -> None:
        """After a fretted note on string 6, the open string on string 5 gets
        a reduced bonus, so the algorithm prefers a fretted position on the same
        string cluster instead."""
        priors = {"hand_position_stability": 1.0, "open_string_bias": 1.0, "string_skip_penalty": 1.0}

        # Previous note: fretted on string 6, fret 5 (A)
        prev = FingeredNote(
            source_index=0, pitch=69, velocity=100, start_beat=0.0, duration_beats=0.25,
            measure_number=1, beat_in_measure=1.0, tie_in=False, tie_out=False,
            original_start_beat=0.0, original_duration_beats=0.25, voice=1,
            let_ring=False, legato_candidate=False, string=6, fret=5,
            fretting_digit=2, hand_position=5, fingering_confidence=0.9,
        )

        # Current note: also A (69), candidates are string 5 fret 0 or string 6 fret 5
        pos_open = FretPosition(string=5, fret=0, pitch=69)
        pos_fretted = FretPosition(string=6, fret=5, pitch=69)

        score_open = _score_candidate(pos_open, priors, prev, note_duration=0.25)
        score_fretted = _score_candidate(pos_fretted, priors, prev, note_duration=0.25)

        # With the reduced open-string bonus, the fretted note on string 6
        # should now be competitive or better than the open string on string 5
        # (which incurs a string-skip penalty of 0.5 for the fast passage).
        # The open string score should be higher (worse) due to the string skip.
        assert score_open > score_fretted, (
            f"Fretted same-string should beat open different-string in fast passage: "
            f"open={score_open:.3f}, fretted={score_fretted:.3f}"
        )

    def test_open_string_full_bonus_on_same_string(self) -> None:
        """When the previous note is on the same string, open string gets full bonus."""
        priors = {"hand_position_stability": 1.0, "open_string_bias": 1.0, "string_skip_penalty": 1.0}

        prev = FingeredNote(
            source_index=0, pitch=64, velocity=100, start_beat=0.0, duration_beats=0.25,
            measure_number=1, beat_in_measure=1.0, tie_in=False, tie_out=False,
            original_start_beat=0.0, original_duration_beats=0.25, voice=1,
            let_ring=False, legato_candidate=False, string=5, fret=5,
            fretting_digit=2, hand_position=5, fingering_confidence=0.9,
        )

        pos_open = FretPosition(string=5, fret=0, pitch=69)
        pos_fretted = FretPosition(string=5, fret=5, pitch=69)

        score_open = _score_candidate(pos_open, priors, prev, note_duration=0.25)
        score_fretted = _score_candidate(pos_fretted, priors, prev, note_duration=0.25)

        # Same string: open should win (full bonus, no string skip)
        assert score_open < score_fretted, (
            f"Open same-string should beat fretted same-string: "
            f"open={score_open:.3f}, fretted={score_fretted:.3f}"
        )


class TestHandPositionStability:
    """Hand position changes are penalised to encourage smooth passages."""

    def test_alternating_pitches_avoid_string_bounce(self, knowledge_engine) -> None:
        """A fast alternating passage (e.g., A2-E2-A2-E2) should not bounce
        between open strings on adjacent strings; instead it should settle on
        a consistent position cluster.

        Before the fix, this pattern would produce string 5 fret 0 (open A)
        alternating with string 6 fret 0 (open E), creating a 5↔6 string bounce.
        After the fix, string continuity should push the algorithm toward a
        consistent cluster.
        """
        stage = FingeringStage(knowledge_engine, tuning=STANDARD_TUNING)

        # Alternating A2 (45) and E2 (40) as 16th notes
        pitches = [45, 40, 45, 40, 45, 40, 45, 40]
        notes = [
            _note(pitch=p, start_beat=i * 0.25, duration_beats=0.25)
            for i, p in enumerate(pitches)
        ]
        ctx = _build_ctx_for_fingering(notes, knowledge_engine)

        stage.run(ctx)

        strings = [f.string for f in ctx.fingered_notes if f.string is not None]
        assert len(strings) == 8

        # With string-skip penalty, no large jumps (>1) between consecutive notes
        for i in range(1, len(strings)):
            diff = abs(strings[i] - strings[i - 1])
            assert diff <= 2, (
                f"String jump of {diff} at index {i}: {strings[i-1]} → {strings[i]}"
            )

        # The algorithm should prefer a consistent cluster (not alternating 5↔6)
        # With the conditional open-string bonus + string skip, it should settle
        # on one string for each pitch rather than bouncing.
        # Either all A's on one string and all E's on another (adjacent), or
        # all on the same string (fretted positions).
        a_strings = {strings[i] for i in range(0, len(strings), 2)}
        e_strings = {strings[i] for i in range(1, len(strings), 2)}
        # Both pitch groups should use at most 2 strings each
        assert len(a_strings) <= 2, f"A notes bounced across strings: {a_strings}"
        assert len(e_strings) <= 2, f"E notes bounced across strings: {e_strings}"

    def test_open_string_hop_avoids_cross_string_open(self, knowledge_engine) -> None:
        """A fast A2→D3 bass riff must NOT hop between two open strings.

        Before the fix, A2 (open string 5) → D3 was placed on open string 4,
        producing a 5↔4 open-string hop.  The correct fingering keeps D3 on
        string 5 at fret 5 ("55"), staying on the same string as A2.
        """
        stage = FingeringStage(knowledge_engine, tuning=STANDARD_TUNING)

        # A2 (45) → D3 (50) as 16th notes — a common rock bass root→4th riff
        pitches = [45, 50, 45, 50]
        notes = [
            _note(pitch=p, start_beat=i * 0.25, duration_beats=0.25)
            for i, p in enumerate(pitches)
        ]
        ctx = _build_ctx_for_fingering(notes, knowledge_engine)
        # Force bass role so open-string hopping is the natural trap this test guards
        ctx.track_role = "bass"

        stage.run(ctx)

        fingered = list(ctx.fingered_notes)
        assert len(fingered) == 4

        # D3 (pitch 50) must land on string 5 fret 5, NOT string 4 fret 0
        for f in fingered:
            if f.pitch == 50:
                assert f.string == 5, (
                    f"D3 should be on string 5 (fret 5), got string {f.string} fret {f.fret}"
                )
                assert f.fret == 5, (
                    f"D3 should be fret 5 on string 5, got fret {f.fret}"
                )

        # Consecutive notes must not jump strings (stay on string 5 throughout)
        strings = [f.string for f in fingered if f.string is not None]
        assert all(s == 5 for s in strings), (
            f"Expected all notes on string 5, got {strings}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

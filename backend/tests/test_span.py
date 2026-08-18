"""Regression tests for chord-onset grouping and hand-span logic (S5).

Covers the pure helpers in ``fretpilot.engine.stages.fingering``:
  - ``_group_by_onset``       — simultaneous notes are grouped for chord fingering
  - ``_encode_shape``         — canonical shape key (sorted by string)
  - ``_is_power_chord``       — root+fifth detection
  - ``_score_chord_combo``    — compactness / fret-span / power-chord scoring

These are the unit-level invariants behind "chords are fingered as a unit":
no hand-span beyond physical limits, adjacent strings rewarded, and known
root+fifth shapes preferred when the prior says so.
"""

from __future__ import annotations

import pytest

from fretpilot.engine.context import VoicedNote
from fretpilot.engine.stages.fingering import (
    _MAX_HAND_SPAN,
    _ONSET_TOLERANCE,
    _encode_shape,
    _group_by_onset,
    _is_power_chord,
    _score_chord_combo,
)
from fretpilot.guitar.fretboard import FretPosition


def _note(start_beat: float, pitch: int = 64, **overrides) -> VoicedNote:
    base = dict(
        source_index=0,
        pitch=pitch,
        velocity=90,
        start_beat=start_beat,
        duration_beats=0.5,
        measure_number=1,
        beat_in_measure=start_beat,
        tie_in=False,
        tie_out=False,
        original_start_beat=start_beat,
        original_duration_beats=0.5,
        voice=1,
        let_ring=False,
        legato_candidate=False,
    )
    base.update(overrides)
    return VoicedNote(**base)


def _pos(string: int, fret: int, pitch: int | None = None) -> FretPosition:
    return FretPosition(string=string, fret=fret, pitch=pitch if pitch is not None else 60 + string + fret)


# ─── _group_by_onset ───


class TestGroupByOnset:
    def test_simultaneous_notes_grouped(self) -> None:
        notes = [_note(0.0), _note(0.02), _note(0.04)]
        groups = _group_by_onset(notes)
        assert len(groups) == 1
        assert len(groups[0]) == 3

    def test_tolerance_boundary(self) -> None:
        """Notes just inside/outside the onset tolerance."""
        inside = _note(0.0), _note(_ONSET_TOLERANCE)
        assert len(_group_by_onset(list(inside))) == 1

        outside = _note(0.0), _note(_ONSET_TOLERANCE + 0.01)
        assert len(_group_by_onset(list(outside))) == 2

    def test_order_preserved(self) -> None:
        notes = [_note(0.5), _note(0.0), _note(0.2)]
        groups = _group_by_onset(notes)
        flattened = [n.start_beat for g in groups for n in g]
        assert flattened == sorted(flattened)

    def test_single_notes_are_own_groups(self) -> None:
        notes = [_note(0.0), _note(1.0), _note(2.0)]
        groups = _group_by_onset(notes)
        assert all(len(g) == 1 for g in groups)

    def test_empty_input(self) -> None:
        assert _group_by_onset([]) == []


# ─── _encode_shape ───


class TestEncodeShape:
    def test_canonical_key_sorted_by_string(self) -> None:
        positions = [_pos(4, 2), _pos(2, 0), _pos(6, 1)]
        assert _encode_shape(positions) == "s2f0,s4f2,s6f1"

    def test_duplicate_pairs_preserved_as_entered(self) -> None:
        """The encoder reflects its input; dedup is the caller's job."""
        positions = [_pos(2, 0), _pos(2, 0)]
        assert _encode_shape(positions) == "s2f0,s2f0"


# ─── _is_power_chord ───


class TestIsPowerChord:
    def test_root_fifth_is_power_chord(self) -> None:
        # A2 (MIDI 45) + E3 (MIDI 52): interval = 7 semitones
        assert _is_power_chord([_pos(5, 0, 45), _pos(4, 2, 52)]) is True

    def test_third_is_not_power_chord(self) -> None:
        # A2 (MIDI 45) + C#3 (MIDI 49): interval = 4 semitones
        assert _is_power_chord([_pos(5, 0, 45), _pos(4, 2, 49)]) is False

    def test_single_note_not_power_chord(self) -> None:
        assert _is_power_chord([_pos(5, 0, 45)]) is False

    def test_three_notes_not_power_chord(self) -> None:
        assert _is_power_chord([_pos(5, 0, 45), _pos(4, 2, 52), _pos(3, 2, 57)]) is False


# ─── _score_chord_combo ───


class TestScoreChordCombo:
    def _score(self, positions, priors=None, individual=None) -> float:
        return _score_chord_combo(
            positions,
            priors or {},
            notes=[],
            prev_fingered=None,
            individual_scores=individual if individual is not None else [0.0] * len(positions),
        )

    def test_adjacent_strings_rewarded(self) -> None:
        adjacent = self._score([_pos(3, 2), _pos(4, 2), _pos(5, 2)])
        spread = self._score([_pos(1, 2), _pos(3, 2), _pos(6, 2)])
        # Adjacent strings should score strictly lower (better).
        assert adjacent < spread

    def test_compact_span_rewarded(self) -> None:
        compact = self._score([_pos(3, 2), _pos(4, 4)])
        stretched = self._score([_pos(3, 2), _pos(4, 9)])
        assert compact < stretched

    def test_impossible_span_heavily_penalized(self) -> None:
        ok = self._score([_pos(3, 1), _pos(4, _MAX_HAND_SPAN + 1)])
        impossible = self._score([_pos(3, 1), _pos(4, _MAX_HAND_SPAN + 2)])
        # The impossible combo must be decisively worse, not a tie-break.
        assert impossible - ok >= 9.0

    def test_power_chord_preference_applies(self) -> None:
        fifth = _pos(5, 0, 45), _pos(4, 2, 52)  # A2 + E3
        third = _pos(5, 0, 45), _pos(4, 2, 49)  # A2 + C#3
        priors = {"power_chord_preference": 1.0}
        with_prior = self._score(list(fifth), priors)
        without_prior = self._score(list(fifth), {})
        assert with_prior < without_prior  # bonus only when prior > 0
        # A non-power chord gets no such bonus.
        assert self._score(list(third), priors) == self._score(list(third), {})

    def test_shape_reuse_scales_rewards(self) -> None:
        compact = [_pos(3, 2), _pos(4, 4)]
        high_prior = self._score(compact, {"shape_reuse": 2.0})
        low_prior = self._score(compact, {"shape_reuse": 0.3})
        # Higher shape_reuse → more compactness reward → lower score.
        assert high_prior < low_prior

    def test_single_note_score_is_base_sum_minus_rewards(self) -> None:
        """Degenerate 1-note groups still receive compactness rewards.

        A lone position is trivially "adjacent" (spread 0) and has a zero
        fret span, so the chord scorer applies both bonuses.
        """
        positions = [_pos(3, 2)]
        # 1.5 - 0.15 (adjacent) - 0.2 (span reward at fret=2) = 1.15
        score = self._score(positions, individual=[1.5])
        assert score == pytest.approx(1.15)

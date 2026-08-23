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
    def _score(
        self,
        positions,
        priors=None,
        individual=None,
        chord_shapes=None,
        chord_shape_templates=None,
    ) -> float:
        return _score_chord_combo(
            positions,
            priors or {},
            notes=[],
            prev_fingered=None,
            individual_scores=individual if individual is not None else [0.0] * len(positions),
            chord_shapes=chord_shapes,
            chord_shape_templates=chord_shape_templates,
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

    def test_learned_shape_rewarded_and_open_mix_exempted(self) -> None:
        """An empirically learned shape gets a reward; the open/high-mix
        penalty is waived because this exact shape is a known-good voicing."""
        positions = [_pos(5, 0, 45), _pos(6, 10, 50)]  # s5f0,s6f10
        base = self._score(positions)  # no KB → open-mix penalty applies
        learned = self._score(
            positions,
            chord_shapes={"s5f0,s6f10": 100, "s4f0,s5f0": 200},
        )
        # Difference = +0.3 penalty (base) − (−0.1 − 0.2·100/200) reward (learned)
        assert learned < base
        assert base - learned == pytest.approx(0.3 + 0.2)

    def test_learned_shape_reward_scales_with_frequency(self) -> None:
        """More frequent shapes in the corpus get a stronger reward."""
        positions = [_pos(5, 0, 45), _pos(6, 10, 50)]
        low = self._score(
            positions,
            chord_shapes={"s5f0,s6f10": 10, "s4f0,s5f0": 100},
        )
        high = self._score(
            positions,
            chord_shapes={"s5f0,s6f10": 100, "s4f0,s5f0": 100},
        )
        # Reward delta: (0.1 + 0.2·1.0) − (0.1 + 0.2·0.1) = 0.18
        assert low - high == pytest.approx(0.18)

    def test_transposed_learned_template_gets_bonus(self) -> None:
        positions = [_pos(5, 5), _pos(6, 3)]

        without_template = self._score(positions)
        with_template = self._score(
            positions,
            chord_shape_templates={"s5+2,s6+0": 100},
        )

        assert with_template < without_template

    def test_unmatched_open_high_mix_still_penalized(self) -> None:
        """A cross-string open+high mix whose shape was *not* learned stays
        penalized even when other learned shapes are present."""
        positions = [_pos(5, 0, 45), _pos(6, 10, 50)]
        no_kb = self._score(positions)
        with_kb = self._score(positions, chord_shapes={"s4f0,s5f0": 100})
        assert with_kb == no_kb  # penalty identical, no reward for this key

    def test_open_position_chord_not_penalized(self) -> None:
        """All-open or low-position chords (max fret < 5) never hit the
        open/high-mix penalty."""
        open_pos = [_pos(4, 0, 50), _pos(5, 0, 45)]
        low_pos = [_pos(3, 2, 57), _pos(4, 0, 50)]
        for positions in (open_pos, low_pos):
            assert max(p.fret for p in positions) < 5
            assert self._score(positions) <= 0.0  # only bonuses, no penalty

"""S5: Fingering assignment stage.

Maps each note's pitch to candidate string/fret positions on the fretboard,
then scores candidates using KB2 priors to select the optimal fingering.
Hand position is tracked sequentially for stability.
"""

from __future__ import annotations

from fretpilot.engine.context import FingeredNote, PipelineContext, VoicedNote
from fretpilot.guitar.fretboard import FretPosition, candidate_positions
from fretpilot.guitar.instrument import STANDARD_TUNING, GuitarTuning
from fretpilot.knowledge.engine import KnowledgeEngine


def _digit_for_fret(fret: int, hand_position: int) -> int | None:
    """Estimate the fretting finger (1=index ... 4=pinky) for a fret."""
    if fret == 0:
        return 0  # open string
    offset = fret - hand_position
    if 0 <= offset <= 3:
        return offset + 1
    return None


def _score_candidate(
    pos,
    priors: dict[str, float],
    prev_fingered: FingeredNote | None,
    note_duration: float,
) -> float:
    """Score a candidate position (lower = better)."""
    score = 0.0
    stability = priors.get("hand_position_stability", 1.0)
    open_bias = priors.get("open_string_bias", 1.0)
    string_skip_penalty = priors.get("string_skip_penalty", 1.0)

    is_open = pos.fret == 0

    # --- Open-string bonus (conditional, and now deliberately weak) ---
    # Open strings are a *minor* convenience (no fretting), but they are
    # tonally inconsistent (always ring, can't be muted) and, critically, they
    # cause the hand to hop between strings when a fretted note on the SAME
    # string would keep the phrase in one position.  A large bonus (the old
    # -0.5) made open strings dominate and produced exactly the "5↔6 / 5↔4
    # open-string hop" the user rejected.  We keep only a small nudge so an
    # isolated open string still wins on pure convenience, but string
    # continuity (via the string-skip penalty below) now dominates.
    if is_open:
        same_string = (
            prev_fingered is not None
            and prev_fingered.string is not None
            and prev_fingered.string == pos.string
        )
        if prev_fingered is None or same_string:
            score -= 0.15 * open_bias
        # else: crossing strings → no bonus; the fretted same-string candidate wins.

    # --- Hand position stability ---
    # Only penalise shifts when the previous note was fretted.  An open string
    # does not anchor the hand to any fret (nothing is fretted), so a subsequent
    # fretted note on the same string should not be treated as a big "shift from
    # the nut".  This stops open strings from over-penalising the fretted
    # same-string alternative (e.g. A2 open → D3 fret 5 on string 5).
    hand_pos = (
        max(1, pos.fret)
        if not is_open
        else (prev_fingered.hand_position if prev_fingered else 1)
    )
    prev_was_fretted = (
        prev_fingered is not None
        and prev_fingered.fret is not None
        and prev_fingered.fret > 0
    )
    if prev_was_fretted and prev_fingered.hand_position is not None:
        shift = abs(hand_pos - prev_fingered.hand_position)
        score += shift * 0.3 * stability

    # --- String continuity (adjacent-string preference) ---
    # For fast passages, large string jumps are penalised heavily.  This is the
    # key fix for the "string 5 ↔ 6 bounce" problem where the algorithm alternates
    # between open A (string 5 fret 0) and fretted notes on string 6.
    if prev_fingered is not None and prev_fingered.string is not None:
        string_diff = abs(pos.string - prev_fingered.string)
        # Fast = 8th note or shorter (duration < 0.5 beat in 4/4)
        is_fast = note_duration < 0.5
        base_skip_penalty = 0.3 * string_skip_penalty
        if is_fast:
            # Double penalty for fast passages — you physically cannot jump
            # strings quickly without compromising timing.
            base_skip_penalty *= 2.0
        score += string_diff * base_skip_penalty

    # --- Fret continuity (same-fret / adjacent-fret preference) ---
    # In fast passages, keeping the same fret or moving by 1-2 frets is preferred.
    # This helps group notes into a consistent hand-position cluster.
    if prev_fingered is not None and prev_fingered.fret is not None:
        fret_diff = abs(pos.fret - prev_fingered.fret)
        if note_duration < 0.5:
            score += fret_diff * 0.05 * stability

    # --- Prefer lower frets (less finger stretch) ---
    score += pos.fret * 0.05

    # --- Prefer middle strings (2-5) slightly over extremes ---
    if pos.string in (1, 6):
        score += 0.1

    return score


def _select_fingering(
    note: VoicedNote,
    priors: dict[str, float],
    tuning: GuitarTuning,
    max_fret: int,
    prev_fingered: FingeredNote | None,
) -> FingeredNote:
    """Select the best fingering for a single note."""
    candidates = candidate_positions(note.pitch, tuning=tuning, max_fret=max_fret)
    if not candidates:
        return _unplayable_note(note, prev_fingered.hand_position if prev_fingered else None)

    scored = [
        (pos, _score_candidate(pos, priors, prev_fingered, note.duration_beats))
        for pos in candidates
    ]
    scored.sort(key=lambda item: item[1])
    best_pos, best_score = scored[0]
    hand_position = (
        max(1, best_pos.fret)
        if best_pos.fret > 0
        else (prev_fingered.hand_position if prev_fingered else 1)
    )
    digit = _digit_for_fret(best_pos.fret, hand_position)
    confidence = max(0.0, min(1.0, 1.0 - best_score * 0.2))

    return _build_fingered_note(note, best_pos, digit, hand_position, confidence)


def _unplayable_note(note: VoicedNote, prev_hp: int | None) -> FingeredNote:
    """Build a FingeredNote for a pitch with no playable position.

    超范围音符（吉他弹不出来的音高）强制归入 voice 2，与正常音符（voice 1）
    分离。这样用户可在 Guitar Pro 中按声部筛选，快速定位并批量删除这些
    脏 MIDI 里的"垃圾"音符。IR 里仍保持 string/fret=None（真相），占位
    fingering 只在 GP5 导出层做映射（呈现）。
    """
    return _build_fingered_note(note, None, None, prev_hp, 0.0, voice=2)


def _build_fingered_note(
    note: VoicedNote,
    pos: FretPosition | None,
    digit: int | None,
    hand_position: int | None,
    confidence: float,
    voice: int | None = None,
) -> FingeredNote:
    """Construct a FingeredNote from a VoicedNote and chosen position.

    ``voice`` 默认继承 VoicedNote 的声部；传入非 None 时覆盖（用于把
    超范围音符强制压到 voice 2）。
    """
    return FingeredNote(
        source_index=note.source_index,
        pitch=note.pitch,
        velocity=note.velocity,
        start_beat=note.start_beat,
        duration_beats=note.duration_beats,
        measure_number=note.measure_number,
        beat_in_measure=note.beat_in_measure,
        tie_in=note.tie_in,
        tie_out=note.tie_out,
        original_start_beat=note.original_start_beat,
        original_duration_beats=note.original_duration_beats,
        voice=voice if voice is not None else note.voice,
        let_ring=note.let_ring,
        legato_candidate=note.legato_candidate,
        string=pos.string if pos else None,
        fret=pos.fret if pos else None,
        fretting_digit=digit,
        hand_position=hand_position,
        fingering_confidence=confidence,
        stream=note.stream,
    )


class FingeringStage:
    """S5: Assign string/fret/hand-position to each note."""

    name = "fingering"

    def __init__(
        self,
        engine: KnowledgeEngine,
        tuning: GuitarTuning = STANDARD_TUNING,
    ) -> None:
        self._engine = engine
        self._tuning = tuning
        self._max_fret = tuning.fret_count

    def run(self, ctx: PipelineContext) -> PipelineContext:
        # Use context tuning if available; otherwise fall back to the default
        # (STANDARD_TUNING) for backward compatibility.
        if ctx.tuning is not None:
            instrument_tuning = ctx.tuning.to_instrument_tuning()
            max_fret = instrument_tuning.fret_count
        else:
            instrument_tuning = self._tuning
            max_fret = self._max_fret

        priors = self._engine.get_fingering_priors(ctx.style_label, ctx.track_role)

        # Hand-position continuity is tracked *per stream* so that a low riff
        # does not pull the lead melody's hand away from its phrase position.
        # When no separation is present every note is "lead", which makes this
        # loop identical to the single-track path (preserving the prior
        # byte-for-byte ``prev_fingered`` continuity).
        by_stream: dict[str, list[VoicedNote]] = {}
        for note in ctx.voiced_notes:
            by_stream.setdefault(note.stream, []).append(note)

        for stream in ("lead", "rhythm"):
            prev_fingered: FingeredNote | None = None
            for note in sorted(by_stream.get(stream, []), key=lambda n: n.start_beat):
                fingered = _select_fingering(
                    note, priors, instrument_tuning, max_fret, prev_fingered
                )
                prev_fingered = fingered
                ctx.fingered_notes.append(fingered)

        ctx.record_stage(self.name)
        return ctx


__all__ = ["FingeringStage"]

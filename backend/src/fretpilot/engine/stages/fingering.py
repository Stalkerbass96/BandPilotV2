"""S5: Fingering assignment stage.

Maps each note's pitch to candidate string/fret positions on the fretboard,
then scores candidates using KB2 priors to select the optimal fingering.
Hand position is tracked sequentially for stability.

Chord-onset grouping: simultaneous notes (same start_beat within tolerance)
are fingered together as a unit — no two notes share a string, the hand span
stays within physical limits, and compact / known chord shapes are preferred
via the ``shape_reuse`` and ``power_chord_preference`` priors.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from fretpilot.engine.context import FingeredNote, PipelineContext, VoicedNote
from fretpilot.guitar.fretboard import FretPosition, candidate_positions
from fretpilot.guitar.instrument import STANDARD_TUNING, GuitarTuning
from fretpilot.knowledge.engine import KnowledgeEngine

# Notes within this many beats of each other are treated as a chord.
_ONSET_TOLERANCE = 0.05  # beats

# Maximum fret span a single hand can cover (index to pinky).
_MAX_HAND_SPAN = 4  # frets

# A chord that mixes an open string with frets at or above this position is
# treated as a non-human "cross-string open/high" mix (e.g. s5f0,s6f10) and
# penalized — unless the exact shape was empirically learned as common.
_OPEN_MIX_FRET_MIN = 5  # frets
_OPEN_MIX_PENALTY = 0.3
_PHRASE_OPTION_LIMIT = 24
_PHRASE_BEAM_WIDTH = 32


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


# ─── Chord-onset grouping ───


def _group_by_onset(
    notes: list[VoicedNote],
    tolerance: float = _ONSET_TOLERANCE,
) -> list[list[VoicedNote]]:
    """Group notes whose start_beat falls within *tolerance* of each other.

    Groups preserve time order.  Single-note groups are returned as
    single-element lists so the caller can treat them uniformly.
    """
    if not notes:
        return []
    sorted_notes = sorted(notes, key=lambda n: n.start_beat)
    groups: list[list[VoicedNote]] = [[sorted_notes[0]]]
    for note in sorted_notes[1:]:
        if note.start_beat - groups[-1][0].start_beat <= tolerance:
            groups[-1].append(note)
        else:
            groups.append([note])
    return groups


def _encode_shape(positions: list[FretPosition]) -> str:
    """Encode a chord shape as ``s1f0,s2f2,s3f2`` (sorted by string)."""
    ordered = sorted(positions, key=lambda p: p.string)
    return ",".join(f"s{p.string}f{p.fret}" for p in ordered)


def _encode_shape_template(positions: list[FretPosition]) -> str:
    """Encode a chord by string and fret offsets from its lowest fret."""

    ordered = sorted(positions, key=lambda position: position.string)
    anchor = min(position.fret for position in ordered)
    return ",".join(
        f"s{position.string}+{position.fret - anchor}" for position in ordered
    )


def _is_power_chord(positions: list[FretPosition]) -> bool:
    """True if *positions* form a root+fifth (perfect-fifth interval)."""
    if len(positions) != 2:
        return False
    interval = abs(positions[1].pitch - positions[0].pitch)
    return interval == 7  # 7 semitones = perfect fifth


def _chord_combo_adjustment(
    positions: list[FretPosition],
    priors: dict[str, float],
    chord_shapes: dict[str, int] | None = None,
    chord_shape_templates: dict[str, int] | None = None,
) -> float:
    """Chord-level score adjustment (negative = bonus, positive = penalty).

    Combines:
    - **shape_reuse**: prefer compact shapes (adjacent strings, small fret span)
    - **power_chord_preference**: prefer root+fifth for 2-note groups
    - **chord_shapes** (empirically learned): reward candidate shapes that
      match the style's top-K learned shapes, proportional to frequency
    - **open/high mix**: penalize a chord that mixes an open string with frets
      >= ``_OPEN_MIX_FRET_MIN`` (the "cross-string 5 and 0" anti-pattern)
      unless that exact shape was learned as common
    """
    delta = 0.0

    # --- Compactness / shape_reuse ---
    shape_reuse = priors.get("shape_reuse", 1.0)

    # Adjacent-string bonus: all strings within len-1 range
    strings = sorted(p.string for p in positions)
    string_spread = strings[-1] - strings[0]
    if string_spread == len(strings) - 1:
        # Perfectly adjacent — reward
        delta -= 0.15 * shape_reuse

    # Fret-span penalty: large spans are physically hard
    frets = [p.fret for p in positions if p.fret > 0]
    if frets:
        span = max(frets) - min(frets)
        max_hand_span = int(priors.get("max_fret_span", _MAX_HAND_SPAN))
        if span > max_hand_span:
            # Physically impossible — huge penalty
            delta += 10.0
        else:
            # Reward compact spans (scaled by shape_reuse)
            delta -= (1.0 / (1.0 + span)) * 0.2 * shape_reuse

    # --- Power chord preference ---
    power_pref = priors.get("power_chord_preference", 0.0)
    if power_pref > 0 and _is_power_chord(positions):
        delta -= 0.3 * power_pref

    # --- Empirically learned chord shapes ---
    shape_key = _encode_shape(positions)
    if chord_shapes:
        count = chord_shapes.get(shape_key)
        if count:
            # Reward matches proportionally to empirical frequency (0.1–0.3).
            max_count = max(chord_shapes.values()) or 1
            delta -= 0.1 + 0.2 * (count / max_count)

    template_key = _encode_shape_template(positions)
    if chord_shape_templates:
        template_count = chord_shape_templates.get(template_key)
        if template_count:
            max_template_count = max(chord_shape_templates.values()) or 1
            delta -= 0.1 + 0.2 * (template_count / max_template_count)

    # --- Open string mixed into a high position (un-human cross-string) ---
    all_frets = [p.fret for p in positions]
    if any(f == 0 for f in all_frets) and max(all_frets) >= _OPEN_MIX_FRET_MIN:
        # Learned-common shapes are exempt; everything else is a suspect mix.
        learned_exact = chord_shapes and shape_key in chord_shapes
        learned_template = (
            chord_shape_templates and template_key in chord_shape_templates
        )
        if not (learned_exact or learned_template):
            delta += _OPEN_MIX_PENALTY

    return delta


def _score_chord_combo(
    positions: list[FretPosition],
    priors: dict[str, float],
    notes: list[VoicedNote],
    prev_fingered: FingeredNote | None,
    individual_scores: list[float],
    chord_shapes: dict[str, int] | None = None,
    chord_shape_templates: dict[str, int] | None = None,
) -> float:
    """Score a full chord-position combination (lower = better).

    Combines the per-note scores with chord-level bonuses (see
    ``_chord_combo_adjustment``).
    """
    total = sum(individual_scores)
    total += _chord_combo_adjustment(
        positions, priors, chord_shapes, chord_shape_templates
    )
    return total


def _build_chord_fingered_notes(
    notes: list[VoicedNote],
    positions: list[FretPosition],
    total_score: float,
    prev_fingered: FingeredNote | None,
) -> list[FingeredNote]:
    """Build FingeredNote list from a chord group + chosen positions."""
    frets = [p.fret for p in positions if p.fret > 0]
    if frets:
        hand_position = max(1, min(frets))
    else:
        hand_position = prev_fingered.hand_position if prev_fingered else 1

    confidence = max(0.0, min(1.0, 1.0 - abs(total_score) * 0.1))

    result = []
    for note, pos in zip(notes, positions):
        digit = _digit_for_fret(pos.fret, hand_position)
        result.append(
            _build_fingered_note(note, pos, digit, hand_position, confidence)
        )
    return result


@dataclass(frozen=True, slots=True)
class _GroupOption:
    positions: tuple[FretPosition, ...]
    local_cost: float
    hand_position: int
    anchor_string: float
    has_fretted_note: bool


def _group_options(
    notes: list[VoicedNote],
    priors: dict[str, float],
    tuning: GuitarTuning,
    max_fret: int,
    chord_shapes: dict[str, int] | None,
    chord_shape_templates: dict[str, int] | None = None,
) -> list[_GroupOption]:
    """Generate legal fingering candidates for one onset group."""

    all_candidates: list[list[FretPosition]] = []
    for note in notes:
        candidates = candidate_positions(note.pitch, tuning=tuning, max_fret=max_fret)
        if not candidates:
            return []
        ranked = sorted(
            candidates,
            key=lambda position: _score_candidate(
                position, priors, None, note.duration_beats
            ),
        )[:6]
        all_candidates.append(ranked)

    options: list[_GroupOption] = []
    for combo in itertools.product(*all_candidates):
        if len({position.string for position in combo}) != len(combo):
            continue
        frets = [position.fret for position in combo if position.fret > 0]
        max_hand_span = int(priors.get("max_fret_span", _MAX_HAND_SPAN))
        if frets and max(frets) - min(frets) > max_hand_span:
            continue
        individual = [
            _score_candidate(position, priors, None, note.duration_beats)
            for position, note in zip(combo, notes)
        ]
        local_cost = _score_chord_combo(
            list(combo),
            priors,
            notes,
            None,
            individual,
            chord_shapes,
            chord_shape_templates,
        )
        hand_position = max(1, min(frets)) if frets else 1
        anchor_string = sum(position.string for position in combo) / len(combo)
        options.append(
            _GroupOption(
                positions=tuple(combo),
                local_cost=local_cost,
                hand_position=hand_position,
                anchor_string=anchor_string,
                has_fretted_note=bool(frets),
            )
        )

    options.sort(key=lambda option: option.local_cost)
    return options[:_PHRASE_OPTION_LIMIT]


def _transition_cost(
    previous: _GroupOption,
    current: _GroupOption,
    notes: list[VoicedNote],
    priors: dict[str, float],
) -> float:
    stability = priors.get("hand_position_stability", 1.0)
    string_penalty = priors.get("string_skip_penalty", 1.0)
    position_shift = (
        abs(current.hand_position - previous.hand_position)
        if current.has_fretted_note and previous.has_fretted_note
        else 0
    )
    string_shift = abs(current.anchor_string - previous.anchor_string)
    fastest_duration = min(note.duration_beats for note in notes)
    speed_multiplier = 1.8 if fastest_duration < 0.5 else 1.0
    cost = (
        position_shift * 0.32 * stability
        + string_shift * 0.3 * string_penalty * speed_multiplier
    )
    max_shift = priors.get("max_position_shift", 7.0)
    allowed_shift = max(3.0, max_shift / speed_multiplier)
    if position_shift > allowed_shift:
        cost += (position_shift - allowed_shift) * 2.0
    return cost


def _optimize_phrase(
    groups: list[list[VoicedNote]],
    priors: dict[str, float],
    tuning: GuitarTuning,
    max_fret: int,
    chord_shapes: dict[str, int] | None,
    chord_shape_templates: dict[str, int] | None = None,
) -> list[FingeredNote] | None:
    """Choose a globally coherent fingering path with bounded beam search."""

    if not groups:
        return []
    options_by_group = [
        _group_options(
            group, priors, tuning, max_fret, chord_shapes, chord_shape_templates
        )
        for group in groups
    ]
    if any(not options for options in options_by_group):
        return None

    return _optimize_legal_phrase(groups, options_by_group, priors)


def _optimize_legal_phrase(
    groups: list[list[VoicedNote]],
    options_by_group: list[list[_GroupOption]],
    priors: dict[str, float],
) -> list[FingeredNote]:
    """Optimize a phrase whose onset groups already have legal options."""

    isolated_note = len(groups) == 1 and len(groups[0]) == 1
    beam: list[tuple[float, tuple[_GroupOption, ...]]] = []
    for option in options_by_group[0]:
        cost = option.local_cost
        # An isolated note has no phrase-continuity trade-off. Prefer the
        # physically economical open-string realization when one exists.
        if isolated_note and option.positions[0].fret == 0:
            cost -= 0.35 * priors.get("open_string_bias", 1.0)
        beam.append((cost, (option,)))
    beam.sort(key=lambda item: item[0])
    beam = beam[:_PHRASE_BEAM_WIDTH]

    for group_index, options in enumerate(options_by_group[1:], start=1):
        candidates: list[tuple[float, tuple[_GroupOption, ...]]] = []
        for total_cost, path in beam:
            previous = path[-1]
            for option in options:
                cost = total_cost + option.local_cost + _transition_cost(
                    previous, option, groups[group_index], priors
                )
                candidates.append((cost, (*path, option)))
        candidates.sort(key=lambda item: item[0])
        beam = candidates[:_PHRASE_BEAM_WIDTH]

    if not beam:
        return []
    _cost, best_path = beam[0]
    result: list[FingeredNote] = []
    previous_note: FingeredNote | None = None
    for notes, option in zip(groups, best_path):
        fingered = _build_chord_fingered_notes(
            notes,
            list(option.positions),
            option.local_cost,
            previous_note,
        )
        result.extend(fingered)
        previous_note = fingered[-1]
    return result


def _optimize_with_local_fallback(
    groups: list[list[VoicedNote]],
    priors: dict[str, float],
    tuning: GuitarTuning,
    max_fret: int,
    chord_shapes: dict[str, int] | None,
    chord_shape_templates: dict[str, int] | None = None,
) -> tuple[list[FingeredNote], int]:
    """Optimize legal phrase runs without poisoning them with one bad chord.

    A single onset can be impossible under the active tuning and hand-span
    policy.  Previously that made the *whole stream* fall back to independent
    per-note assignment, creating same-string collisions in otherwise legal
    chords.  Legal runs now retain joint beam-search fingering.  Notes in an
    impossible onset remain explicit unplayable events so validation reports
    the actual problem instead of receiving fabricated positions.
    """

    result: list[FingeredNote] = []
    legal_groups: list[list[VoicedNote]] = []
    legal_options: list[list[_GroupOption]] = []
    impossible_group_count = 0

    def flush_legal_run() -> None:
        if not legal_groups:
            return
        result.extend(_optimize_legal_phrase(legal_groups, legal_options, priors))
        legal_groups.clear()
        legal_options.clear()

    for group in groups:
        options = _group_options(
            group, priors, tuning, max_fret, chord_shapes, chord_shape_templates
        )
        if options:
            legal_groups.append(group)
            legal_options.append(options)
            continue

        flush_legal_run()
        impossible_group_count += 1
        previous_hand_position = result[-1].hand_position if result else None
        result.extend(
            _unplayable_note(note, previous_hand_position)
            for note in group
        )

    flush_legal_run()
    return result, impossible_group_count


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
        # Empirically learned top-K chord shapes (style-specific; merged
        # ensemble for unknown/unmatched styles) drive the shape-reward and
        # open/high-mix penalty terms in chord scoring.
        chord_shapes = self._engine.get_fingering_chord_shapes(
            ctx.style_label, ctx.track_role
        )
        chord_shape_templates = self._engine.get_fingering_chord_shape_templates(
            ctx.style_label, ctx.track_role
        )

        # Hand-position continuity is tracked *per stream* so that a low riff
        # does not pull the lead melody's hand away from its phrase position.
        by_stream: dict[str, list[VoicedNote]] = {}
        for note in ctx.voiced_notes:
            by_stream.setdefault(note.stream, []).append(note)

        for stream in ("lead", "rhythm"):
            stream_notes = sorted(
                by_stream.get(stream, []), key=lambda n: n.start_beat
            )
            groups = _group_by_onset(stream_notes)
            optimized, impossible_groups = _optimize_with_local_fallback(
                groups,
                priors,
                instrument_tuning,
                max_fret,
                chord_shapes,
                chord_shape_templates,
            )
            ctx.fingered_notes.extend(optimized)
            if impossible_groups:
                ctx.warnings.append(
                    f"{impossible_groups} {stream} onset group(s) have no legal "
                    "unique-string fingering under the active tuning and hand-span "
                    "policy; only those groups were marked unplayable"
                )

        # Apply note_overlap prior: truncate ringing notes for staccato styles.
        self._apply_note_overlap(ctx.fingered_notes, priors)

        ctx.record_stage(self.name)
        return ctx

    @staticmethod
    def _apply_note_overlap(
        fingered: list[FingeredNote], priors: dict[str, float]
    ) -> None:
        """Truncate note durations based on the ``note_overlap`` prior.

        Low ``note_overlap`` (staccato style) → notes are cut short so they
        don't ring into the next note on the same string.  High values leave
        durations intact (legato / let-ring styles).
        """
        overlap = priors.get("note_overlap", 1.0)
        if overlap >= 0.9:
            return  # style naturally sustains — no truncation

        # Group by string, sort by start_beat, truncate overlaps.
        by_string: dict[int, list[FingeredNote]] = {}
        for note in fingered:
            if note.string is not None:
                by_string.setdefault(note.string, []).append(note)

        truncate_factor = 1.0 - overlap  # 0.0 = full ring, 1.0 = full cut
        for string_notes in by_string.values():
            string_notes.sort(key=lambda n: n.start_beat)
            for i in range(len(string_notes) - 1):
                curr = string_notes[i]
                nxt = string_notes[i + 1]
                gap = nxt.start_beat - curr.start_beat
                if gap <= 0:
                    continue
                # If the current note would ring past the next note's onset
                if curr.duration_beats > gap:
                    # Truncate: leave a small gap proportional to (1 - overlap)
                    new_duration = gap * (1.0 - truncate_factor * 0.3)
                    if new_duration < curr.duration_beats:
                        curr.duration_beats = new_duration


__all__ = ["FingeringStage"]

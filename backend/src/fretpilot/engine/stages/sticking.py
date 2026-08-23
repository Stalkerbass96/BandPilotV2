"""S6: Sticking suggestion stage.

Suggests R/L hand sticking for each drum hit. This is the drum equivalent
of the guitar fingering stage (S5 in FretPilot).

Sticking rules:
  - **Single strokes**: Alternating R-L-R-L for consecutive hits on the same
    piece or across pieces played by one hand.
  - **Double strokes**: RRLL pattern when two consecutive hits land on the
    same piece at very close spacing (roll-like).
  - **Flams**: Both hands ("both") when two hits on the same piece occur
    nearly simultaneously (within a flam threshold).
  - **Kick/pedal**: Always "right" (foot) — hands don't play kick.
  - **Hi-hat (closed/open)**: Alternating or right-hand-led depending on
    context; left foot plays pedal hi-hat.

KB priors (``drum_kb2_sticking``) modulate the thresholds and handedness:
  - ``flam_rate``: raises the flam detection threshold when the style is
    flam-heavy (metal/funk).
  - ``double_stroke_rate``: widens the double-stroke window when the style
    rolls heavily.
  - ``right_hand_bias`` / ``hand_switch_pattern``: bias the initial hand and
    the alternation pattern when the style is right-hand-led.
"""

from __future__ import annotations

from collections import defaultdict

from fretpilot.engine.drum_context import (
    DrumPipelineContext,
    StickedNote,
    VelocityNote,
)

# ─── Baseline thresholds (beats) ───

_FLAM_THRESHOLD_BEATS = 0.03  # <30 ticks at 120bpm → nearly simultaneous
_DOUBLE_STROKE_THRESHOLD_BEATS = 0.06  # <60 ticks → double stroke
_DOUBLE_STROKE_GAP_BEATS = 0.125  # 32nd note spacing for double detection

# Pieces that are always played with a specific hand/foot.
_FIXED_STICKING: dict[str, str] = {
    "kick": "right",  # right foot
    "hihat_pedal": "right",  # right foot (or left foot, but single limb)
}


def _lookup_sticking_priors(ctx: DrumPipelineContext) -> dict:
    """Fetch drum KB2 sticking priors for the context's style.

    Falls back to an empty dict when the registry has no matching entry
    (degraded mode or style not in KB) — the stage then uses baselines.
    """
    if ctx.degraded_mode or ctx.knowledge is None:
        return {}
    try:
        return ctx.knowledge.query_payload(
            domain="drum_kb2_sticking",
            scope={"style": [ctx.style_label]},
        )
    except Exception:  # noqa: BLE001 — priors are best-effort
        return {}


def _group_by_measure(
    notes: list[VelocityNote],
) -> dict[int, list[VelocityNote]]:
    """Group velocity notes by measure number, preserving order."""
    groups: dict[int, list[VelocityNote]] = defaultdict(list)
    for note in notes:
        groups[note.pattern.mapped.measure_number].append(note)
    return groups


def _suggest_sticking_for_measure(
    notes: list[VelocityNote],
    priors: dict,
) -> list[tuple[str, str]]:
    """Suggest sticking for a sequence of notes in one measure.

    Args:
        notes: VelocityNotes in a single measure, ordered by start_beat.
        priors: drum_kb2_sticking payload (may be empty for defaults).

    Returns:
        List of (sticking, stroke_type) tuples, one per note.
    """
    # KB-modulated thresholds and hand bias.
    flam_threshold = _FLAM_THRESHOLD_BEATS
    double_threshold = _DOUBLE_STROKE_THRESHOLD_BEATS
    if priors:
        flam_rate = priors.get("flam_rate") or 0.0
        double_rate = priors.get("double_stroke_rate") or 0.0
        # Styles with heavy rolls/flams get slightly wider detection windows.
        flam_threshold += flam_rate * 0.01
        double_threshold += (double_rate * 0.02) + (flam_rate * 0.01)

    pattern = (priors.get("hand_switch_pattern") or "RLRL").upper()
    right_hand_bias = priors.get("right_hand_bias") or 1.0

    results: list[tuple[str, str]] = []
    last_hand: str = ""  # "R" or "L" — tracks alternation
    for i, note in enumerate(notes):
        piece = note.pattern.mapped.piece
        start = note.pattern.mapped.start_beat

        # Fixed sticking for kick, pedal hi-hat, etc.
        if piece in _FIXED_STICKING:
            results.append((_FIXED_STICKING[piece], "single"))
            continue

        # Check for flam: nearly simultaneous hit on same piece.
        if i > 0:
            prev = notes[i - 1]
            prev_piece = prev.pattern.mapped.piece
            prev_start = prev.pattern.mapped.start_beat
            gap = start - prev_start

            if prev_piece == piece and gap <= flam_threshold:
                # Flam: both hands. Overwrite the previous result too.
                if results:
                    prev_sticking, _ = results[-1]
                    results[-1] = (prev_sticking, "flam")
                results.append(("both", "flam"))
                last_hand = ""
                continue

            # Double stroke: same piece, close spacing.
            if (
                prev_piece == piece
                and gap <= double_threshold
                and gap > flam_threshold
            ):
                # Use same hand as previous hit for double stroke.
                prev_sticking, _ = results[-1] if results else ("R", "")
                sticking = prev_sticking if prev_sticking in ("R", "L") else "R"
                results.append((sticking, "double"))
                continue

        # Single stroke: alternate hands, guided by KB bias/pattern.
        if not last_hand:
            if right_hand_bias >= 1.2:
                hand = "R"
            elif right_hand_bias <= 0.8:
                hand = "L"
            else:
                hand = "R" if pattern.startswith("R") else "L"
        else:
            # Follow the KB pattern when it prescribes R→L / L→R swaps;
            # otherwise default to plain alternation.
            if pattern.startswith("R") and last_hand == "L":
                hand = "R"
            elif pattern.startswith("L") and last_hand == "R":
                hand = "L"
            else:
                hand = "L" if last_hand == "R" else "R"
        results.append((hand, "single"))
        last_hand = hand

    return results


class StickingStage:
    """S6: Suggest R/L hand sticking for each drum hit.

    Reads ``ctx.velocity_notes`` (output of S5 Velocity) and produces
    ``ctx.sticked_notes`` with sticking and stroke type assignments.

    KB priors from ``drum_kb2_sticking`` (scoped by the track's style label)
    modulate the detection thresholds and hand bias when available.
    """

    name = "sticking"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        if not ctx.velocity_notes:
            ctx.record_stage(self.name)
            return ctx

        priors = _lookup_sticking_priors(ctx)
        by_measure = _group_by_measure(ctx.velocity_notes)

        # Process measures in order, maintaining sticking across measures.
        all_sticked: list[StickedNote] = []
        for measure_number in sorted(by_measure):
            measure_notes = by_measure[measure_number]
            # Sort by start beat to ensure temporal order.
            measure_notes.sort(
                key=lambda n: n.pattern.mapped.start_beat
            )
            sticking_results = _suggest_sticking_for_measure(measure_notes, priors)

            for note, (sticking, stroke_type) in zip(
                measure_notes, sticking_results
            ):
                all_sticked.append(
                    StickedNote(
                        velocity=note,
                        sticking=sticking,
                        stroke_type=stroke_type,
                    )
                )

        ctx.sticked_notes = all_sticked
        ctx.record_stage(self.name)
        return ctx


__all__ = ["StickingStage"]

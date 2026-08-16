"""S6: Articulation inference stage.

Infers playing techniques (palm_mute, let_ring, staccato, hammer_on,
pull_off, slide) based on the style label, KB2 priors, and note context.
All decisions are deterministic — no LLM involvement.
"""

from __future__ import annotations

from fretpilot.engine.context import ArticulationDecision, FingeredNote, PipelineContext
from fretpilot.knowledge.engine import KnowledgeEngine

_SHORT_NOTE_THRESHOLD = 0.25  # beats — notes shorter than this are "short"


def _infer_style_articulations(
    note: FingeredNote,
    priors: dict[str, float],
    style_label: str,
) -> list[ArticulationDecision]:
    """Infer style-dependent articulations for a note."""
    decisions: list[ArticulationDecision] = []
    is_short = note.duration_beats <= _SHORT_NOTE_THRESHOLD

    if style_label in ("metal", "rock") and is_short and priors.get("palm_mute", 0) > 1.0:
        decisions.append(
            ArticulationDecision(
                note_index=note.source_index,
                type="palm_mute",
                confidence=min(1.0, priors["palm_mute"] * 0.4),
                reason=f"short note in {style_label} context",
            )
        )

    if style_label == "funk" and is_short and priors.get("staccato", 0) > 1.0:
        decisions.append(
            ArticulationDecision(
                note_index=note.source_index,
                type="staccato",
                confidence=min(1.0, priors["staccato"] * 0.4),
                reason=f"short note in funk context",
            )
        )

    if note.let_ring:
        decisions.append(
            ArticulationDecision(
                note_index=note.source_index,
                type="let_ring",
                confidence=0.8,
                reason="written duration shortened; source timing preserves ring",
            )
        )

    return decisions


def _infer_legato_articulation(
    note: FingeredNote,
    all_notes: list[FingeredNote],
) -> ArticulationDecision | None:
    """Infer hammer_on/pull_off for legato candidates on the same string."""
    if not note.legato_candidate or note.string is None:
        return None

    # Find the preceding note on the same string.
    same_string = [
        n for n in all_notes
        if n.string == note.string and n.source_index != note.source_index
    ]
    same_string.sort(key=lambda n: n.start_beat)
    prev = None
    for n in same_string:
        if n.start_beat < note.start_beat:
            prev = n
        else:
            break

    if prev is None or prev.fret is None or note.fret is None:
        return None

    if note.fret > prev.fret:
        technique = "hammer_on"
    elif note.fret < prev.fret:
        technique = "pull_off"
    else:
        return None

    return ArticulationDecision(
        note_index=note.source_index,
        type=technique,
        confidence=0.85,
        reason=f"legato {technique} on string {note.string}",
        source_note_id=f"n-{prev.source_index + 1:05d}",
    )


class ArticulationStage:
    """S6: Infer articulations from style priors and note context."""

    name = "articulation"

    def __init__(self, engine: KnowledgeEngine) -> None:
        self._engine = engine

    def run(self, ctx: PipelineContext) -> PipelineContext:
        priors = self._engine.get_fingering_priors(ctx.style_label, ctx.track_role)
        sorted_notes = sorted(ctx.fingered_notes, key=lambda n: n.start_beat)

        # Legato (hammer_on / pull_off) is stream-scoped: the preceding note on
        # the same string must belong to the same stream, otherwise the low
        # riff would forge legato links into the high melody.  Style
        # articulations (palm_mute / staccato / let_ring) are per-note and
        # stream-agnostic.
        by_stream: dict[str, list[FingeredNote]] = {}
        for note in sorted_notes:
            by_stream.setdefault(note.stream, []).append(note)

        for note in sorted_notes:
            decisions = _infer_style_articulations(note, priors, ctx.style_label)
            legato = _infer_legato_articulation(note, by_stream[note.stream])
            if legato is not None:
                decisions.append(legato)
            ctx.articulation_decisions.extend(decisions)

        ctx.record_stage(self.name)
        return ctx


__all__ = ["ArticulationStage"]

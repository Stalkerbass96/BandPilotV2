"""S3: Drum map stage.

Maps MIDI pitches to drum pieces via the GM drum map and detects the kit
type from the pitches used. This is a deterministic operation — no LLM
involvement.
"""

from __future__ import annotations

from fretpilot.drum.drumkit import (
    detect_kit,
    map_pitch_to_piece,
)
from fretpilot.engine.drum_context import DrumPipelineContext, MappedNote


class DrumMapStage:
    """S3: Map MIDI pitches to drum pieces and detect kit type.

    Reads ``ctx.split_notes`` (output of S2 MeasureSplit) and produces
    ``ctx.mapped_notes`` with each note's drum piece and category resolved.
    Also sets ``ctx.kit`` to the detected DrumKit.
    """

    name = "drum_map"

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext:
        if not ctx.split_notes:
            ctx.record_stage(self.name)
            return ctx

        # Detect kit from all pitches present.
        all_pitches = [n.pitch for n in ctx.split_notes]
        kit = detect_kit(all_pitches)
        ctx.kit = kit

        # Build a category lookup from the kit.
        category_lookup: dict[str, str] = {
            piece.name: piece.category for piece in kit.pieces
        }

        for note in ctx.split_notes:
            piece_name = map_pitch_to_piece(note.pitch)
            category = category_lookup.get(piece_name, "unknown")

            ctx.mapped_notes.append(
                MappedNote(
                    source_index=note.source_index,
                    pitch=note.pitch,
                    velocity=note.velocity,
                    start_beat=note.start_beat,
                    duration_beats=note.duration_beats,
                    measure_number=note.measure_number,
                    beat_in_measure=note.beat_in_measure,
                    piece=piece_name,
                    piece_category=category,
                    original_start_beat=note.original_start_beat,
                    original_duration_beats=note.original_duration_beats,
                )
            )

            if piece_name == "unknown":
                ctx.warnings.append(
                    f"Pitch {note.pitch} at beat {note.start_beat:.4f} "
                    f"not in GM drum map; mapped as 'unknown'."
                )

        ctx.record_stage(self.name)
        return ctx


__all__ = ["DrumMapStage"]

"""Note aligner — matches ground truth notes with reconstructed IR notes.

Alignment strategy:
    1. Group both sides by ``(measure_number, pitch)``
    2. Within each group, greedy nearest-neighbour matching on ``beat_in_measure``
    3. Beat tolerance = 0.25 (16th note); unmatched notes are skipped
    4. ``alignment_confidence = 1.0 - (beat_diff / tolerance)``
"""

from __future__ import annotations

import logging
from collections import defaultdict

from fretpilot.elearning.models import AlignedNotePair, GroundTruthNote, GroundTruthTab
from fretpilot.ir.models import GuitarNoteEvent, GuitarProjectIR

logger = logging.getLogger("fretpilot.elearning.note_aligner")

BEAT_TOLERANCE = 0.25  # 16th note


class NoteAligner:
    """P0-4: Align ground truth and reconstructed notes."""

    def align(
        self,
        gt_tab: GroundTruthTab,
        ir: GuitarProjectIR,
    ) -> list[AlignedNotePair]:
        """Align ground truth notes with IR notes.

        Returns a list of ``AlignedNotePair`` for matched notes.
        Unmatched notes on either side are not included.
        """
        ir_notes = self._extract_ir_notes(ir)
        gt_by_key = self._group_by_key(gt_tab.notes)
        ir_by_key = self._group_by_key(ir_notes)

        pairs: list[AlignedNotePair] = []
        all_keys = set(gt_by_key.keys()) | set(ir_by_key.keys())

        for key in all_keys:
            gt_group = gt_by_key.get(key, [])
            ir_group = ir_by_key.get(key, [])
            pairs.extend(self._align_group(gt_group, ir_group))

        logger.debug(
            "Aligned %d/%d GT notes with %d IR notes → %d pairs",
            len(pairs),
            len(gt_tab.notes),
            len(ir_notes),
            len(pairs),
        )
        return pairs

    def _extract_ir_notes(self, ir: GuitarProjectIR) -> list[GuitarNoteEvent]:
        """Flatten all IR note events from all tracks/measures."""
        events: list[GuitarNoteEvent] = []
        for track in ir.tracks:
            for measure in track.measures:
                events.extend(measure.events)
        return events

    def _group_by_key(self, notes: list) -> dict[tuple[int, int], list]:
        """Group notes by ``(measure_number, pitch)``."""
        groups: dict[tuple[int, int], list] = defaultdict(list)
        for note in notes:
            measure = getattr(note, "measure_number", None) or getattr(
                getattr(note, "score", None), "measure_number", 0
            )
            pitch = getattr(note, "pitch", 0)
            groups[(measure, pitch)].append(note)
        return groups

    def _align_group(
        self,
        gt_notes: list[GroundTruthNote],
        ir_notes: list[GuitarNoteEvent],
    ) -> list[AlignedNotePair]:
        """Greedy nearest-neighbour matching within a (measure, pitch) group."""
        pairs: list[AlignedNotePair] = []
        used_ir: set[int] = set()

        for gt in gt_notes:
            best_idx = -1
            best_diff = float("inf")

            for i, ir in enumerate(ir_notes):
                if i in used_ir:
                    continue
                ir_beat = ir.score.beat_in_measure
                diff = abs(gt.beat_in_measure - ir_beat)
                if diff < best_diff:
                    best_diff = diff
                    best_idx = i

            if best_idx >= 0 and best_diff <= BEAT_TOLERANCE:
                ir = ir_notes[best_idx]
                used_ir.add(best_idx)
                pairs.append(AlignedNotePair(
                    gt_note=gt,
                    ir_string=ir.fingering.string,
                    ir_fret=ir.fingering.fret,
                    ir_hand_position=ir.fingering.hand_position,
                    alignment_confidence=1.0 - (best_diff / BEAT_TOLERANCE),
                    beat_delta=best_diff,
                    ir_note_id=ir.id,
                ))

        return pairs


__all__ = ["NoteAligner"]

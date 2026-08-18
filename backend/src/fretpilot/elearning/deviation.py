"""Deviation calculator — computes evaluation metrics from aligned note pairs.

Produces 5 core metrics + 4 auxiliary metrics as defined in the PRD:
    - String Match Rate
    - Fret Match Rate
    - Position Deviation
    - Chord Shape Match
    - Overall Fingering Accuracy
    - Pitch Accuracy (validation)
    - Note Count Match
    - Measure Alignment Rate
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fretpilot.elearning.models import (
    AlignedNotePair,
    EvaluationMetrics,
    EvaluationReport,
    GroundTruthTab,
)
from fretpilot.ir.models import GuitarProjectIR

logger = logging.getLogger("fretpilot.elearning.deviation")


class DeviationCalculator:
    """P0-5: Compute deviation metrics from aligned note pairs."""

    def calculate(
        self,
        pairs: list[AlignedNotePair],
        gt_tab: GroundTruthTab,
        ir: GuitarProjectIR,
        warnings: list[str] | None = None,
    ) -> EvaluationReport:
        """Compute the full evaluation report."""
        warnings = warnings or []
        gt_count = len(gt_tab.notes)
        ir_count = self._count_ir_notes(ir)

        metrics = self._compute_metrics(pairs, gt_count, ir_count)
        per_note = self._build_per_note(pairs)
        per_measure = self._build_per_measure(pairs)

        return EvaluationReport(
            file_path=gt_tab.file_path,
            style_label=gt_tab.style_label,
            metrics=metrics,
            per_note=per_note,
            per_measure=per_measure,
            warnings=warnings,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _compute_metrics(
        self,
        pairs: list[AlignedNotePair],
        gt_count: int,
        ir_count: int,
    ) -> EvaluationMetrics:
        """Calculate all metrics from aligned pairs."""
        if not pairs:
            return EvaluationMetrics.empty()

        total = len(pairs)
        string_match = 0
        fret_match = 0
        both_match = 0
        pitch_match = 0
        position_deviations: list[float] = []

        for pair in pairs:
            gt = pair.gt_note
            ir_str = pair.ir_string
            ir_frt = pair.ir_fret
            ir_hp = pair.ir_hand_position

            # Pitch should always match (alignment key includes pitch)
            pitch_match += 1

            s_match = ir_str is not None and gt.string == ir_str
            f_match = ir_frt is not None and gt.fret == ir_frt

            if s_match:
                string_match += 1
            if f_match:
                fret_match += 1
            if s_match and f_match:
                both_match += 1

            if ir_hp is not None:
                position_deviations.append(abs(gt.hand_position - ir_hp))

        # Chord shape match: group by (measure, beat) onset
        chord_match = self._compute_chord_match(pairs)

        # Measure alignment rate
        gt_measures = set(p.gt_note.measure_number for p in pairs)
        total_measures = max(gt_measures, default=0)
        measure_align_rate = len(gt_measures) / total_measures if total_measures > 0 else 0.0

        note_count_match = ir_count / gt_count if gt_count > 0 else 0.0

        return EvaluationMetrics(
            string_match_rate=string_match / total,
            fret_match_rate=fret_match / total,
            position_deviation=sum(position_deviations) / len(position_deviations) if position_deviations else 0.0,
            chord_shape_match=chord_match,
            overall_fingering_accuracy=both_match / total,
            pitch_accuracy=pitch_match / total,
            note_count_match=note_count_match,
            measure_alignment_rate=measure_align_rate,
            total_aligned=total,
            total_gt_notes=gt_count,
            total_ir_notes=ir_count,
            total_unmatched=gt_count - total,
        )

    def _compute_chord_match(self, pairs: list[AlignedNotePair]) -> float:
        """Compute chord shape match rate.

        Groups aligned pairs by (measure, beat) onset.  A chord is "matched"
        only when ALL notes in the chord have matching (string, fret).
        """
        chords: dict[tuple[int, float], list[AlignedNotePair]] = defaultdict(list)
        for pair in pairs:
            key = (pair.gt_note.measure_number, pair.gt_note.beat_in_measure)
            chords[key].append(pair)

        if not chords:
            return 0.0

        matched = 0
        total = len(chords)
        for chord_pairs in chords.values():
            all_match = all(
                p.gt_note.string == p.ir_string and p.gt_note.fret == p.ir_fret
                for p in chord_pairs
            )
            if all_match:
                matched += 1
        return matched / total

    def _count_ir_notes(self, ir: GuitarProjectIR) -> int:
        """Count total notes in the IR."""
        return sum(len(m.events) for t in ir.tracks for m in t.measures)

    def _build_per_note(self, pairs: list[AlignedNotePair]) -> list[dict[str, Any]]:
        """Build per-note deviation details."""
        result: list[dict[str, Any]] = []
        for pair in pairs:
            gt = pair.gt_note
            result.append({
                "measure": gt.measure_number,
                "beat": round(gt.beat_in_measure, 3),
                "pitch": gt.pitch,
                "gt_string": gt.string,
                "gt_fret": gt.fret,
                "gt_hand_position": gt.hand_position,
                "ir_string": pair.ir_string,
                "ir_fret": pair.ir_fret,
                "ir_hand_position": pair.ir_hand_position,
                "string_match": gt.string == pair.ir_string if pair.ir_string is not None else False,
                "fret_match": gt.fret == pair.ir_fret if pair.ir_fret is not None else False,
                "alignment_confidence": round(pair.alignment_confidence, 3),
                "ir_note_id": pair.ir_note_id,
            })
        return result

    def _build_per_measure(self, pairs: list[AlignedNotePair]) -> list[dict[str, Any]]:
        """Build per-measure summary."""
        measures: dict[int, list[AlignedNotePair]] = defaultdict(list)
        for pair in pairs:
            measures[pair.gt_note.measure_number].append(pair)

        result: list[dict[str, Any]] = []
        for m_num in sorted(measures.keys()):
            m_pairs = measures[m_num]
            total = len(m_pairs)
            s_match = sum(1 for p in m_pairs if p.gt_note.string == p.ir_string)
            f_match = sum(1 for p in m_pairs if p.gt_note.fret == p.ir_fret)
            result.append({
                "measure": m_num,
                "note_count": total,
                "string_match_rate": round(s_match / total, 3) if total else 0.0,
                "fret_match_rate": round(f_match / total, 3) if total else 0.0,
            })
        return result


__all__ = ["DeviationCalculator"]

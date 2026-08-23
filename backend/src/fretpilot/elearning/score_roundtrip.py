"""Professional GP score round-trip comparison.

The comparator measures the actual exported GP5 parse-back against the source
score.  It deliberately stays independent from the repair IR so exporter loss
cannot be hidden by a good pre-export result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from fretpilot.elearning.models import GroundTruthNote, GroundTruthTab

ONSET_TOLERANCE_BEATS = 0.25
EXACT_RHYTHM_TOLERANCE_BEATS = 1 / 64


@dataclass(frozen=True, slots=True)
class ScoreNotePair:
    source: GroundTruthNote
    generated: GroundTruthNote
    onset_delta: float


@dataclass(slots=True)
class ScoreRoundTripMetrics:
    note_recall: float
    note_precision: float
    onset_exact_rate: float
    duration_exact_rate: float
    onset_mae_beats: float
    duration_mae_beats: float
    string_match_rate: float
    fret_match_rate: float
    exact_fingering_rate: float
    chord_shape_match_rate: float
    technique_precision: float
    technique_recall: float
    technique_f1: float
    professional_score_score: float
    source_notes: int
    generated_notes: int
    aligned_notes: int
    missing_notes: int
    extra_notes: int
    source_techniques: int
    generated_techniques: int
    aligned_techniques: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScoreRoundTripReport:
    source_file: str
    generated_file: str
    style_label: str
    source_track_name: str
    generated_track_name: str
    metrics: ScoreRoundTripMetrics
    instrument_family: str = "guitar"
    evaluation_dimensions: list[str] = field(
        default_factory=lambda: ["notes", "rhythm", "fingering", "techniques"]
    )
    mismatch_counts: dict[str, int] = field(default_factory=dict)
    per_measure: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "generated_file": self.generated_file,
            "style_label": self.style_label,
            "source_track_name": self.source_track_name,
            "generated_track_name": self.generated_track_name,
            "instrument_family": self.instrument_family,
            "evaluation_dimensions": list(self.evaluation_dimensions),
            "metrics": self.metrics.to_dict(),
            "mismatch_counts": dict(self.mismatch_counts),
            "per_measure": list(self.per_measure),
            "warnings": list(self.warnings),
        }


def _group_notes(notes: list[GroundTruthNote]) -> dict[int, list[GroundTruthNote]]:
    grouped: dict[int, list[GroundTruthNote]] = defaultdict(list)
    for note in notes:
        grouped[note.pitch].append(note)
    for group in grouped.values():
        group.sort(key=lambda note: (note.absolute_start_beat, note.duration_beats))
    return grouped


def align_score_notes(
    source: GroundTruthTab,
    generated: GroundTruthTab,
) -> list[ScoreNotePair]:
    """Align equal-pitch notes by nearest absolute onset within tolerance."""
    source_groups = _group_notes(source.notes)
    generated_groups = _group_notes(generated.notes)
    result: list[ScoreNotePair] = []
    for pitch, source_notes in source_groups.items():
        candidates = generated_groups.get(pitch, [])
        used: set[int] = set()
        for source_note in source_notes:
            best_index = -1
            best_delta = float("inf")
            for index, candidate in enumerate(candidates):
                if index in used:
                    continue
                delta = abs(source_note.absolute_start_beat - candidate.absolute_start_beat)
                if delta < best_delta:
                    best_index, best_delta = index, delta
            if best_index >= 0 and best_delta <= ONSET_TOLERANCE_BEATS:
                used.add(best_index)
                result.append(
                    ScoreNotePair(
                        source=source_note,
                        generated=candidates[best_index],
                        onset_delta=best_delta,
                    )
                )
    return result


def _technique_signatures(tab: GroundTruthTab) -> Counter[tuple]:
    notes = {note.note_id: note for note in tab.notes}
    signatures: Counter[tuple] = Counter()
    for technique in tab.techniques:
        related = tuple(
            sorted(
                (
                    round(notes[note_id].absolute_start_beat, 3),
                    notes[note_id].pitch,
                )
                for note_id in technique.note_ids
                if note_id in notes
            )
        )
        signatures[(technique.type, related)] += 1
    return signatures


def _technique_metrics(
    source: GroundTruthTab,
    generated: GroundTruthTab,
) -> tuple[float, float, float, int, int, int, int, int]:
    source_signatures = _technique_signatures(source)
    generated_signatures = _technique_signatures(generated)
    matched = sum((source_signatures & generated_signatures).values())
    source_count = sum(source_signatures.values())
    generated_count = sum(generated_signatures.values())
    precision = matched / generated_count if generated_count else (1.0 if not source_count else 0.0)
    recall = matched / source_count if source_count else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return (
        precision,
        recall,
        f1,
        source_count - matched,
        generated_count - matched,
        source_count,
        generated_count,
        matched,
    )


def _chord_match_rate(source: GroundTruthTab, pairs: list[ScoreNotePair]) -> float:
    pair_by_source = {pair.source.note_id: pair for pair in pairs}
    groups: dict[float, list[GroundTruthNote]] = defaultdict(list)
    for note in source.notes:
        groups[round(note.absolute_start_beat, 6)].append(note)
    chords = [notes for notes in groups.values() if len(notes) >= 2]
    if not chords:
        return 1.0
    matched = 0
    for chord in chords:
        chord_pairs = [pair_by_source.get(note.note_id) for note in chord]
        if all(
            pair is not None
            and pair.source.string == pair.generated.string
            and pair.source.fret == pair.generated.fret
            for pair in chord_pairs
        ):
            matched += 1
    return matched / len(chords)


def _per_measure(source: GroundTruthTab, pairs: list[ScoreNotePair]) -> list[dict[str, Any]]:
    source_counts = Counter(note.measure_number for note in source.notes)
    aligned: dict[int, list[ScoreNotePair]] = defaultdict(list)
    for pair in pairs:
        aligned[pair.source.measure_number].append(pair)
    result: list[dict[str, Any]] = []
    for measure in sorted(source_counts):
        measure_pairs = aligned.get(measure, [])
        exact = sum(
            pair.source.string == pair.generated.string
            and pair.source.fret == pair.generated.fret
            for pair in measure_pairs
        )
        rhythm = sum(
            pair.onset_delta <= EXACT_RHYTHM_TOLERANCE_BEATS
            and abs(pair.source.duration_beats - pair.generated.duration_beats)
            <= EXACT_RHYTHM_TOLERANCE_BEATS
            for pair in measure_pairs
        )
        result.append(
            {
                "measure": measure,
                "source_notes": source_counts[measure],
                "aligned_notes": len(measure_pairs),
                "note_recall": len(measure_pairs) / source_counts[measure],
                "exact_fingering_rate": exact / len(measure_pairs) if measure_pairs else 0.0,
                "exact_rhythm_rate": rhythm / len(measure_pairs) if measure_pairs else 0.0,
            }
        )
    return result


class ProfessionalScoreComparator:
    """Compare a source professional score with an exported parse-back."""

    def compare(
        self,
        source: GroundTruthTab,
        generated: GroundTruthTab,
        *,
        generated_file: str,
        warnings: list[str] | None = None,
        instrument_family: str = "guitar",
        evaluate_fingering: bool = True,
    ) -> ScoreRoundTripReport:
        pairs = align_score_notes(source, generated)
        source_count, generated_count, aligned_count = (
            len(source.notes),
            len(generated.notes),
            len(pairs),
        )
        onset_exact = sum(pair.onset_delta <= EXACT_RHYTHM_TOLERANCE_BEATS for pair in pairs)
        duration_exact = sum(
            abs(pair.source.duration_beats - pair.generated.duration_beats)
            <= EXACT_RHYTHM_TOLERANCE_BEATS
            for pair in pairs
        )
        string_matches = (
            sum(pair.source.string == pair.generated.string for pair in pairs)
            if evaluate_fingering
            else aligned_count
        )
        fret_matches = (
            sum(pair.source.fret == pair.generated.fret for pair in pairs)
            if evaluate_fingering
            else aligned_count
        )
        exact_fingering = (
            sum(
                pair.source.string == pair.generated.string
                and pair.source.fret == pair.generated.fret
                for pair in pairs
            )
            if evaluate_fingering
            else aligned_count
        )
        (
            technique_precision,
            technique_recall,
            technique_f1,
            missing_techniques,
            extra_techniques,
            source_techniques,
            generated_techniques,
            aligned_techniques,
        ) = _technique_metrics(source, generated)
        chord_match = _chord_match_rate(source, pairs) if evaluate_fingering else 1.0
        note_recall = aligned_count / source_count if source_count else 1.0
        note_precision = aligned_count / generated_count if generated_count else (1.0 if not source_count else 0.0)
        onset_rate = onset_exact / aligned_count if aligned_count else 0.0
        duration_rate = duration_exact / aligned_count if aligned_count else 0.0
        fingering_rate = exact_fingering / aligned_count if aligned_count else 0.0
        components = [
            (note_recall, 0.25),
            (note_precision, 0.10),
            (onset_rate, 0.10),
            (duration_rate, 0.10),
            (technique_f1, 0.10),
        ]
        if evaluate_fingering:
            components.extend(((fingering_rate, 0.25), (chord_match, 0.10)))
        active_weight = sum(weight for _value, weight in components)
        score = sum(value * weight for value, weight in components) / active_weight
        metrics = ScoreRoundTripMetrics(
            note_recall=note_recall,
            note_precision=note_precision,
            onset_exact_rate=onset_rate,
            duration_exact_rate=duration_rate,
            onset_mae_beats=(sum(pair.onset_delta for pair in pairs) / aligned_count if aligned_count else 0.0),
            duration_mae_beats=(
                sum(abs(pair.source.duration_beats - pair.generated.duration_beats) for pair in pairs)
                / aligned_count
                if aligned_count
                else 0.0
            ),
            string_match_rate=string_matches / aligned_count if aligned_count else 0.0,
            fret_match_rate=fret_matches / aligned_count if aligned_count else 0.0,
            exact_fingering_rate=fingering_rate,
            chord_shape_match_rate=chord_match,
            technique_precision=technique_precision,
            technique_recall=technique_recall,
            technique_f1=technique_f1,
            professional_score_score=score,
            source_notes=source_count,
            generated_notes=generated_count,
            aligned_notes=aligned_count,
            missing_notes=max(0, source_count - aligned_count),
            extra_notes=max(0, generated_count - aligned_count),
            source_techniques=source_techniques,
            generated_techniques=generated_techniques,
            aligned_techniques=aligned_techniques,
        )
        mismatch_counts = {
            "missing_notes": metrics.missing_notes,
            "extra_notes": metrics.extra_notes,
            "onset_mismatches": aligned_count - onset_exact,
            "duration_mismatches": aligned_count - duration_exact,
            "string_mismatches": aligned_count - string_matches if evaluate_fingering else 0,
            "fret_mismatches": aligned_count - fret_matches if evaluate_fingering else 0,
            "missing_techniques": missing_techniques,
            "extra_techniques": extra_techniques,
        }
        return ScoreRoundTripReport(
            source_file=source.file_path,
            generated_file=generated_file,
            style_label=source.style_label,
            source_track_name=source.track_name,
            generated_track_name=generated.track_name,
            instrument_family=instrument_family,
            evaluation_dimensions=(
                ["notes", "rhythm", "fingering", "techniques"]
                if evaluate_fingering
                else ["notes", "rhythm", "techniques"]
            ),
            metrics=metrics,
            mismatch_counts=mismatch_counts,
            per_measure=_per_measure(source, pairs),
            warnings=list(warnings or []),
        )


__all__ = [
    "EXACT_RHYTHM_TOLERANCE_BEATS",
    "ONSET_TOLERANCE_BEATS",
    "ProfessionalScoreComparator",
    "ScoreNotePair",
    "ScoreRoundTripMetrics",
    "ScoreRoundTripReport",
    "align_score_notes",
]

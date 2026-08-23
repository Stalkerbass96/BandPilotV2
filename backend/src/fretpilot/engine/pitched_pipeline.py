"""Deterministic repair pipelines for bass, keys, and generic instruments."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import floor

from fretpilot.ir.models import (
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
    Transformation,
)
from fretpilot.ir.pitched_models import (
    PitchedMeasure,
    PitchedNoteEvent,
    PitchedProjectIR,
    PitchedRealization,
    PitchedTrackIR,
)
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.knowledge.registry import KnowledgeRegistry
from fretpilot.midi.models import NormalizedNote, NormalizedTimeline, NormalizedTrack

STANDARD_BASS_4 = (28, 33, 38, 43)  # E1 A1 D2 G2, low to high
STANDARD_BASS_5 = (23, 28, 33, 38, 43)  # B0 E1 A1 D2 G2
_EPSILON = 1e-8


@dataclass(frozen=True, slots=True)
class _Measure:
    number: int
    start: float
    end: float
    numerator: int
    denominator: int


@dataclass(slots=True)
class _Fragment:
    source_index: int
    note: NormalizedNote
    start: float
    duration: float
    measure: _Measure
    tie_in: bool
    tie_out: bool
    confidence: float
    realization: PitchedRealization
    unresolved_reason: str | None = None


def _round_grid(value: float, step: float) -> float:
    return max(0, int(floor(value / step + 0.5))) * step


def _measure_map(timeline: NormalizedTimeline, end_beat: float) -> list[_Measure]:
    signatures = sorted(timeline.time_signature_events, key=lambda event: event.beat)
    if not signatures:
        raise ValueError("Timeline must contain a time signature.")
    result: list[_Measure] = []
    cursor = 0.0
    sig_index = 0
    while cursor < end_beat - _EPSILON or not result:
        while sig_index + 1 < len(signatures) and signatures[sig_index + 1].beat <= cursor:
            sig_index += 1
        signature = signatures[sig_index]
        length = signature.numerator * 4.0 / signature.denominator
        natural_end = cursor + length
        if sig_index + 1 < len(signatures):
            change = signatures[sig_index + 1].beat
            natural_end = change if cursor < change < natural_end else natural_end
        result.append(
            _Measure(
                number=len(result) + 1,
                start=cursor,
                end=natural_end,
                numerator=signature.numerator,
                denominator=signature.denominator,
            )
        )
        cursor = natural_end
    return result


def _containing_measure(measures: list[_Measure], beat: float) -> _Measure:
    return next(
        (measure for measure in measures if measure.start <= beat < measure.end - _EPSILON),
        measures[-1],
    )


def _bass_candidates(pitch: int, tuning: tuple[int, ...], fret_count: int) -> list[tuple[int, int]]:
    candidates: list[tuple[int, int]] = []
    for low_index, open_pitch in enumerate(tuning):
        fret = pitch - open_pitch
        if 0 <= fret <= fret_count:
            string = len(tuning) - low_index
            candidates.append((string, fret))
    return candidates


def _bass_group_choices(
    fragments: list[_Fragment],
    tuning: tuple[int, ...],
    fret_count: int,
    maximum_span: int,
    fixed_positions: dict[int, tuple[int, int]] | None = None,
) -> list[tuple[tuple[int, int], ...]]:
    fixed_positions = fixed_positions or {}
    candidates = [
        [fixed_positions[fragment.source_index]]
        if fragment.source_index in fixed_positions
        else _bass_candidates(fragment.note.pitch, tuning, fret_count)
        for fragment in fragments
    ]
    if any(not item for item in candidates):
        return []
    choices: list[tuple[tuple[int, int], ...]] = []
    for choice in product(*candidates):
        strings = [item[0] for item in choice]
        frets = [item[1] for item in choice if item[1] > 0]
        if len(strings) != len(set(strings)):
            continue
        if frets and max(frets) - min(frets) > maximum_span:
            continue
        choices.append(choice)
    return choices


def _realize_bass(
    fragments: list[_Fragment],
    tuning: tuple[int, ...],
    fret_count: int,
    priors: dict[str, object],
) -> None:
    """Assign phrase-continuous bass positions with chord feasibility constraints."""

    by_onset: dict[float, list[_Fragment]] = {}
    for fragment in fragments:
        by_onset.setdefault(round(fragment.start, 8), []).append(fragment)

    previous_position: float | None = None
    previous_string: float | None = None
    source_positions: dict[int, tuple[int, int]] = {}
    for _onset, group in sorted(by_onset.items()):
        # Tied fragments must keep the physical position selected at note onset.
        choices = _bass_group_choices(
            group,
            tuning,
            fret_count,
            int(priors.get("maximum_chord_fret_span", 4)),
            source_positions,
        )
        if not choices:
            for fragment in group:
                fragment.unresolved_reason = (
                    "bass pitch/chord has no playable unique-string realization"
                )
            continue

        def cost(choice: tuple[tuple[int, int], ...]) -> float:
            fretted = [fret for _string, fret in choice if fret > 0]
            position = sum(fretted) / len(fretted) if fretted else 0.0
            mean_string = sum(string for string, _fret in choice) / len(choice)
            shift = abs(position - previous_position) if previous_position is not None else 0.0
            string_move = (
                abs(mean_string - previous_string) if previous_string is not None else 0.0
            )
            chord_open_penalty = float(priors.get("chord_open_string_penalty", 0.16))
            open_penalty = sum(
                chord_open_penalty
                for _string, fret in choice
                if fret == 0 and len(group) > 1
            )
            return (
                shift * float(priors.get("hand_shift_weight", 0.72))
                + string_move * float(priors.get("string_movement_weight", 0.18))
                + position * float(priors.get("fret_height_weight", 0.025))
                + open_penalty
            )

        selected = min(choices, key=cost)
        fretted = [fret for _string, fret in selected if fret > 0]
        previous_position = sum(fretted) / len(fretted) if fretted else 0.0
        previous_string = sum(string for string, _fret in selected) / len(selected)
        for fragment, (string, fret) in zip(group, selected, strict=True):
            hand_position = max(1, fret - 1) if fret else 1
            digit = 0 if fret == 0 else min(4, max(1, fret - hand_position + 1))
            fragment.realization = PitchedRealization(
                kind="bass",
                string=string,
                fret=fret,
                fretting_digit=digit,
                hand_position=hand_position,
            )
            source_positions[fragment.source_index] = (string, fret)


def _realize_keys(
    fragments: list[_Fragment], split_pitch: int, priors: dict[str, object]
) -> None:
    """Assign playable hand/finger layouts for simultaneous keyboard notes."""

    by_onset: dict[float, list[_Fragment]] = {}
    for fragment in fragments:
        by_onset.setdefault(round(fragment.start, 8), []).append(fragment)
    source_realizations: dict[int, tuple[str, int]] = {}
    for _onset, group in sorted(by_onset.items()):
        new_notes = [fragment for fragment in group if fragment.source_index not in source_realizations]
        ordered = sorted(new_notes, key=lambda fragment: fragment.note.pitch)
        maximum_hand_notes = int(priors.get("maximum_hand_notes", 5))
        maximum_span = int(priors.get("maximum_hand_span_semitones", 12))
        maximum_total = maximum_hand_notes * 2
        if len(ordered) > maximum_total:
            for fragment in ordered[maximum_total:]:
                fragment.unresolved_reason = (
                    f"keyboard chord exceeds {maximum_total} simultaneously playable notes"
                )
            ordered = ordered[:maximum_total]

        partitions: list[tuple[float, list[_Fragment], list[_Fragment]]] = []
        for split in range(
            max(0, len(ordered) - maximum_hand_notes),
            min(maximum_hand_notes, len(ordered)) + 1,
        ):
            left_candidate, right_candidate = ordered[:split], ordered[split:]
            left_span = (
                left_candidate[-1].note.pitch - left_candidate[0].note.pitch
                if len(left_candidate) > 1
                else 0
            )
            right_span = (
                right_candidate[-1].note.pitch - right_candidate[0].note.pitch
                if len(right_candidate) > 1
                else 0
            )
            if left_span > maximum_span or right_span > maximum_span:
                continue
            boundary_cost = sum(
                max(0, fragment.note.pitch - split_pitch) for fragment in left_candidate
            ) + sum(
                max(0, split_pitch - fragment.note.pitch) for fragment in right_candidate
            )
            balance_cost = abs(len(left_candidate) - len(right_candidate)) * float(
                priors.get("hand_balance_weight", 0.25)
            )
            partitions.append(
                (boundary_cost + balance_cost, left_candidate, right_candidate)
            )
        if partitions:
            _cost, left, right = min(partitions, key=lambda item: item[0])
        else:
            left = ordered[:maximum_hand_notes]
            right = ordered[maximum_hand_notes:maximum_total]
            for fragment in ordered:
                fragment.unresolved_reason = "keyboard chord exceeds a playable hand span"

        for hand, notes in (("left", left), ("right", right)):
            notes.sort(key=lambda fragment: fragment.note.pitch)
            fingers = (
                list(range(5, 5 - len(notes), -1))
                if hand == "left"
                else list(range(1, len(notes) + 1))
            )
            if len(notes) == 1:
                fingers = [3]
            for fragment, finger in zip(notes, fingers, strict=True):
                fragment.realization = PitchedRealization(kind="keys", hand=hand, finger=finger)
                source_realizations[fragment.source_index] = (hand, finger)

        for fragment in group:
            saved = source_realizations.get(fragment.source_index)
            if saved and fragment.unresolved_reason is None:
                fragment.realization = PitchedRealization(
                    kind="keys", hand=saved[0], finger=saved[1]
                )


class PitchedRepairPipeline:
    """Four-stage pipeline: quantize, split, realize, assemble."""

    stages = ("quantize", "measure_split", "realize", "assemble")

    def __init__(self, family: str) -> None:
        if family not in {"bass", "keys", "generic"}:
            raise ValueError(f"Unsupported pitched family: {family}")
        self.family = family

    def execute(
        self,
        *,
        track: NormalizedTrack,
        timeline: NormalizedTimeline,
        registry: KnowledgeRegistry,
        settings: dict[str, object],
    ) -> PitchedProjectIR:
        style = str(settings.get("style_label", "unknown"))
        fidelity = float(settings.get("midi_fidelity", 0.5))
        step = KnowledgeEngine(registry).select_grid(style, fidelity).step_beats
        changes: list[Transformation] = []
        quantized: list[tuple[int, NormalizedNote, float, float, float]] = []
        for index, note in enumerate(track.notes):
            start = _round_grid(note.start_beat, step)
            duration = max(step, _round_grid(note.duration_beats, step))
            confidence = max(
                0.0,
                min(1.0, 1.0 - (abs(start - note.start_beat) + abs(duration - note.duration_beats)) / (2 * step)),
            )
            if abs(start - note.start_beat) > _EPSILON or abs(duration - note.duration_beats) > _EPSILON:
                changes.append(
                    Transformation(
                        id=f"chg-{len(changes) + 1:05d}",
                        stage="pitched_quantize",
                        source_note_index=index,
                        before={"start_beat": note.start_beat, "duration_beats": note.duration_beats},
                        after={"start_beat": start, "duration_beats": duration},
                        confidence=confidence,
                        reason=f"snap_to_{step:g}_beat_grid",
                    )
                )
            quantized.append((index, note, start, duration, confidence))

        end_beat = max((start + duration for _i, _n, start, duration, _c in quantized), default=0.0)
        measures = _measure_map(timeline, end_beat)
        fragments: list[_Fragment] = []
        for index, note, start, duration, confidence in quantized:
            cursor = start
            end = start + duration
            parts: list[tuple[_Measure, float, float]] = []
            while cursor < end - _EPSILON:
                measure = _containing_measure(measures, cursor)
                part_end = min(end, measure.end)
                parts.append((measure, cursor, part_end - cursor))
                cursor = part_end
            for part_index, (measure, part_start, part_duration) in enumerate(parts):
                fragments.append(
                    _Fragment(
                        source_index=index,
                        note=note,
                        start=part_start,
                        duration=part_duration,
                        measure=measure,
                        tie_in=part_index > 0,
                        tie_out=part_index < len(parts) - 1,
                        confidence=confidence,
                        realization=PitchedRealization(kind=self.family),
                    )
                )

        instrument: dict[str, object]
        role = self.family
        if self.family == "bass":
            bass_priors = registry.query_payload(domain="bass_kb2_performance")
            requested = settings.get("bass_tuning")
            tuning = tuple(int(value) for value in requested) if isinstance(requested, (list, tuple)) else STANDARD_BASS_4
            if len(tuning) not in {4, 5, 6} or tuple(sorted(tuning)) != tuning:
                raise ValueError("Bass tuning must contain 4–6 ascending open-string MIDI pitches.")
            fret_count = int(
                settings.get(
                    "bass_fret_count", bass_priors.get("default_fret_count", 24)
                )
            )
            _realize_bass(fragments, tuning, fret_count, bass_priors)
            instrument = {"tuning": list(tuning), "fret_count": fret_count, "program": track.program or 33}
        elif self.family == "keys":
            keys_priors = registry.query_payload(domain="keys_kb2_performance")
            split_pitch = int(
                settings.get(
                    "keys_split_pitch", keys_priors.get("default_split_pitch", 60)
                )
            )
            _realize_keys(fragments, split_pitch, keys_priors)
            instrument = {
                "program": track.program or 0,
                "split_pitch": split_pitch,
                "maximum_hand_notes": int(keys_priors.get("maximum_hand_notes", 5)),
                "maximum_hand_span_semitones": int(
                    keys_priors.get("maximum_hand_span_semitones", 12)
                ),
            }
        else:
            instrument = {"program": track.program or 0, "instrument_name": track.instrument_name or "Generic"}

        events_by_measure: dict[int, list[PitchedNoteEvent]] = {measure.number: [] for measure in measures}
        source_fragments: dict[int, int] = {}
        for fragment in fragments:
            sequence = source_fragments.get(fragment.source_index, 0) + 1
            source_fragments[fragment.source_index] = sequence
            event_id = f"n-{fragment.source_index + 1:05d}-{sequence}"
            voice = 2 if fragment.realization.hand == "left" else 1
            events_by_measure[fragment.measure.number].append(
                PitchedNoteEvent(
                    id=event_id,
                    source_note_index=fragment.source_index,
                    pitch=fragment.note.pitch,
                    score=ScoreTiming(
                        start_beat=fragment.start,
                        duration_beats=fragment.duration,
                        measure_number=fragment.measure.number,
                        beat_in_measure=fragment.start - fragment.measure.start,
                        voice=voice,
                        tie_in=fragment.tie_in,
                        tie_out=fragment.tie_out,
                    ),
                    performance=PerformanceTiming(
                        source_start_beat=fragment.note.start_beat,
                        source_duration_beats=fragment.note.duration_beats,
                        velocity=max(1, min(127, fragment.note.velocity)),
                    ),
                    realization=fragment.realization,
                    confidence=NoteConfidence(
                        rhythm=fragment.confidence,
                        fingering=0.0 if fragment.unresolved_reason else 0.82,
                    ),
                    unresolved_reason=fragment.unresolved_reason,
                )
            )

        ir_measures = [
            PitchedMeasure(
                number=measure.number,
                start_beat=measure.start,
                duration_beats=measure.end - measure.start,
                numerator=measure.numerator,
                denominator=measure.denominator,
                events=sorted(events_by_measure[measure.number], key=lambda event: (event.score.start_beat, event.pitch)),
            )
            for measure in measures
        ]
        knowledge_domains = {
            "bass": "bass_kb2_performance",
            "keys": "keys_kb2_performance",
        }
        used_entries = (
            registry.query(domain=knowledge_domains[self.family])
            if self.family in knowledge_domains
            else []
        )
        knowledge = IRKnowledgeReference(
            snapshot_version=registry.snapshot_version,
            kb_versions=registry.kb_versions,
            entry_ids=[entry.knowledge_id for entry in used_entries],
        )
        return PitchedProjectIR(
            title=str(settings.get("title", timeline.source or "Untitled")),
            source=timeline.source,
            family=self.family,
            tempo_map=[IRTempoEvent(beat=event.beat, bpm=event.bpm) for event in timeline.tempo_events],
            time_signatures=[
                IRTimeSignatureEvent(
                    beat=event.beat,
                    numerator=event.numerator,
                    denominator=event.denominator,
                )
                for event in timeline.time_signature_events
            ],
            tracks=[
                PitchedTrackIR(
                    id=f"{self.family}-{track.index}",
                    name=track.name or self.family.title(),
                    source_track_index=track.index,
                    family=self.family,
                    role=role,
                    instrument=instrument,
                    measures=ir_measures,
                )
            ],
            knowledge=knowledge,
            style_label=style,
            changes=changes,
            warnings=[
                f"{sum(event.unresolved_reason is not None for event in (e for m in ir_measures for e in m.events))} source event(s) could not be physically realized."
            ] if any(event.unresolved_reason for measure in ir_measures for event in measure.events) else [],
        )


__all__ = ["PitchedRepairPipeline", "STANDARD_BASS_4", "STANDARD_BASS_5"]

"""Licence-safe GuitarSet importer and KB2 aggregate builder.

The official GuitarSet JAMS annotations contain one ``note_midi`` stream per
string. This module intentionally reads JSON directly so building knowledge
does not add a runtime dependency on the legacy JAMS 0.3 package.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

_OPEN_PITCHES = (40, 45, 50, 55, 59, 64)  # low E to high E
_NAME_RE = re.compile(
    r"^(?P<performer>\d{2})_(?P<style>BN|Funk|Jazz|Rock|SS).*_(?P<role>comp|solo)$"
)
_STYLE_NAMES = {
    "BN": "bossa_nova",
    "Funk": "funk",
    "Jazz": "jazz",
    "Rock": "rock",
    "SS": "singer_songwriter",
}
_ROLE_NAMES = {"comp": "rhythm", "solo": "lead"}
_CHORD_TOP_K = 12


@dataclass(frozen=True, slots=True)
class GuitarSetNote:
    onset: float
    duration: float
    pitch: int
    string: int
    fret: int


@dataclass(frozen=True, slots=True)
class GuitarSetExcerpt:
    source_key: str
    performer: str
    style: str
    role: str
    tempo_bpm: float
    notes: tuple[GuitarSetNote, ...]


def _annotation_data(document: dict[str, Any], namespace: str) -> Iterable[dict[str, Any]]:
    for annotation in document.get("annotations", []):
        if annotation.get("namespace") == namespace:
            yield annotation


def load_excerpt(path: str | Path) -> GuitarSetExcerpt:
    """Load one GuitarSet JAMS annotation with validated string/fret data."""

    source = Path(path)
    match = _NAME_RE.match(source.stem)
    if match is None:
        raise ValueError(f"Unrecognised GuitarSet filename: {source.name}")
    document = json.loads(source.read_text(encoding="utf-8"))

    tempo_annotations = list(_annotation_data(document, "tempo"))
    tempo = 120.0
    if tempo_annotations and tempo_annotations[0].get("data"):
        tempo = float(tempo_annotations[0]["data"][0]["value"])

    notes: list[GuitarSetNote] = []
    for annotation in _annotation_data(document, "note_midi"):
        metadata = annotation.get("annotation_metadata", {})
        source_string = int(metadata.get("data_source", -1))
        if source_string not in range(6):
            raise ValueError(f"Invalid GuitarSet string index in {source.name}")
        open_pitch = _OPEN_PITCHES[source_string]
        string_number = 6 - source_string
        for event in annotation.get("data", []):
            pitch = int(round(float(event["value"])))
            fret = pitch - open_pitch
            if not 0 <= fret <= 24:
                raise ValueError(f"Implausible fret {fret} in {source.name} string {string_number}")
            notes.append(
                GuitarSetNote(
                    onset=float(event["time"]),
                    duration=float(event["duration"]),
                    pitch=pitch,
                    string=string_number,
                    fret=fret,
                )
            )

    return GuitarSetExcerpt(
        source_key=source.name,
        performer=match.group("performer"),
        style=_STYLE_NAMES[match.group("style")],
        role=_ROLE_NAMES[match.group("role")],
        tempo_bpm=tempo,
        notes=tuple(sorted(notes, key=lambda note: (note.onset, note.string))),
    )


def split_name(performer: str) -> str:
    """Frozen performer-disjoint split used by all GuitarSet builds."""

    if performer in {"00", "01", "02", "03"}:
        return "train"
    if performer == "04":
        return "validation"
    if performer == "05":
        return "test"
    raise ValueError(f"Unexpected GuitarSet performer: {performer}")


def _onset_groups(
    notes: tuple[GuitarSetNote, ...], tolerance_seconds: float = 0.08
) -> list[list[GuitarSetNote]]:
    groups: list[list[GuitarSetNote]] = []
    for note in notes:
        if not groups or note.onset - groups[-1][0].onset > tolerance_seconds:
            groups.append([note])
        else:
            groups[-1].append(note)
    return groups


def absolute_shape(notes: Iterable[GuitarSetNote]) -> str:
    pairs = sorted({(note.string, note.fret) for note in notes})
    return ",".join(f"s{string}f{fret}" for string, fret in pairs)


def relative_shape(notes: Iterable[GuitarSetNote]) -> str:
    """Return a transposition-invariant string/fret-offset chord template."""

    pairs = sorted({(note.string, note.fret) for note in notes})
    anchor = min(fret for _, fret in pairs)
    return ",".join(f"s{string}+{fret - anchor}" for string, fret in pairs)


def aggregate_excerpts(excerpts: Iterable[GuitarSetExcerpt]) -> dict[str, Any]:
    """Aggregate observations without creating cross-file transitions/chords."""

    material = list(excerpts)
    total_notes = sum(len(excerpt.notes) for excerpt in material)
    if total_notes == 0:
        raise ValueError("Cannot aggregate an empty GuitarSet group")

    open_notes = short_notes = chord_onsets = onset_count = 0
    stable_transitions = large_shifts = transition_count = 0
    gate_ratios: list[float] = []
    absolute_shapes: Counter[str] = Counter()
    relative_shapes: Counter[str] = Counter()

    for excerpt in material:
        notes = excerpt.notes
        open_notes += sum(note.fret == 0 for note in notes)
        beat_seconds = 60.0 / excerpt.tempo_bpm
        short_notes += sum(note.duration / beat_seconds < 0.25 for note in notes)
        groups = _onset_groups(notes)
        onset_count += len(groups)
        for group in groups:
            distinct = {(note.string, note.fret) for note in group}
            if len(distinct) >= 2:
                chord_onsets += 1
                absolute_shapes[absolute_shape(group)] += 1
                relative_shapes[relative_shape(group)] += 1

        anchors: list[tuple[float, float, float, float]] = []
        for group in groups:
            fretted = [note.fret for note in group if note.fret > 0]
            hand_anchor = float(min(fretted)) if fretted else 0.0
            string_anchor = mean(note.string for note in group)
            anchors.append(
                (
                    group[0].onset,
                    max(note.duration for note in group),
                    hand_anchor,
                    string_anchor,
                )
            )
        for previous, current in zip(anchors, anchors[1:]):
            transition_count += 1
            fret_delta = abs(current[2] - previous[2])
            string_delta = abs(current[3] - previous[3])
            stable_transitions += fret_delta <= 4 and string_delta <= 2
            large_shifts += fret_delta > 7
            gap = current[0] - previous[0]
            if gap > 0:
                gate_ratios.append(min(1.5, previous[1] / gap))

    def rate(value: int, denominator: int) -> float:
        return round(value / denominator, 6) if denominator else 0.0

    return {
        "files": len(material),
        "notes": total_notes,
        "open_string_rate": rate(open_notes, total_notes),
        "short_note_rate": rate(short_notes, total_notes),
        "chord_onset_rate": rate(chord_onsets, onset_count),
        "stable_transition_rate": rate(stable_transitions, transition_count),
        "large_shift_rate": rate(large_shifts, transition_count),
        "mean_gate_ratio": round(mean(gate_ratios), 6) if gate_ratios else 0.0,
        "chord_shapes": dict(absolute_shapes.most_common(_CHORD_TOP_K)),
        "chord_shape_templates": dict(relative_shapes.most_common(_CHORD_TOP_K)),
    }


def _clamp(value: float, low: float = 0.3, high: float = 2.0) -> float:
    return round(max(low, min(high, value)), 6)


def observations_to_priors(observed: dict[str, Any]) -> dict[str, Any]:
    """Map transparent, versioned observed rates to conservative weights."""

    return {
        "shape_reuse": _clamp(0.8 + observed["chord_onset_rate"] * 1.0),
        "hand_position_stability": _clamp(0.7 + observed["stable_transition_rate"] * 0.9),
        "note_overlap": _clamp(0.6 + observed["mean_gate_ratio"] * 0.55),
        "open_string_bias": _clamp(0.7 + observed["open_string_rate"] * 5.0),
        "staccato": _clamp(0.6 + observed["short_note_rate"] * 3.5),
        "string_skip_penalty": _clamp(0.8 + observed["stable_transition_rate"] * 0.5),
        "chord_shapes": observed["chord_shapes"],
        "chord_shape_templates": observed["chord_shape_templates"],
        "observed_rates": {
            key: value
            for key, value in observed.items()
            if key not in {"chord_shapes", "chord_shape_templates"}
        },
        "derivation": {
            "formula_version": "guitarset-priors-v1",
            "onset_tolerance_seconds": 0.08,
            "fret_rounding": "nearest_midi_then_subtract_open_pitch",
        },
    }


def _rates_only(observed: dict[str, Any]) -> dict[str, int | float]:
    return {
        key: value
        for key, value in observed.items()
        if key not in {"chord_shapes", "chord_shape_templates"}
    }


def _split_drift(train: dict[str, Any], held_out: dict[str, Any]) -> dict[str, float]:
    rate_keys = (
        "open_string_rate",
        "short_note_rate",
        "chord_onset_rate",
        "stable_transition_rate",
        "large_shift_rate",
        "mean_gate_ratio",
    )
    deltas = [abs(float(train[key]) - float(held_out[key])) for key in rate_keys]
    return {
        "mean_absolute_rate_delta": round(mean(deltas), 6),
        "max_absolute_rate_delta": round(max(deltas), 6),
    }


def evaluate_fingering_ab(
    entries: list[dict[str, Any]],
    excerpts: Iterable[GuitarSetExcerpt],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Run safe-default vs candidate fingering A/B on held-out performers."""

    # Lazy imports keep aggregate-only inspection independent of the repair
    # pipeline, while the build command still evaluates the real runtime stage.
    from fretpilot.engine.context import PipelineContext, VoicedNote
    from fretpilot.engine.stages.fingering import FingeringStage
    from fretpilot.knowledge.engine import KnowledgeEngine
    from fretpilot.knowledge.models import KnowledgeEntry, KnowledgeSnapshot
    from fretpilot.knowledge.registry import KnowledgeRegistry
    from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack

    material = list(excerpts)
    typed_entries = tuple(KnowledgeEntry.from_dict(entry) for entry in entries)
    safe_default = next(
        entry for entry in typed_entries if entry.knowledge_id == "kb2-guitar-safe-defaults-v1"
    )
    baseline_registry = KnowledgeRegistry(
        KnowledgeSnapshot("guitarset-baseline", "2", "approved", (safe_default,))
    )
    candidate_registry = KnowledgeRegistry(
        KnowledgeSnapshot("guitarset-candidate", "2", "approved", typed_entries)
    )
    engines = {
        "baseline": KnowledgeEngine(baseline_registry),
        "candidate": KnowledgeEngine(candidate_registry),
    }
    counts: dict[tuple[str, str, str, str], int] = defaultdict(int)

    for excerpt in material:
        split = split_name(excerpt.performer)
        if split not in {"validation", "test"}:
            continue
        beat_seconds = 60.0 / excerpt.tempo_bpm
        voiced: list[VoicedNote] = []
        truth: dict[int, tuple[int, int]] = {}
        for index, note in enumerate(excerpt.notes):
            start_beat = note.onset / beat_seconds
            duration_beats = note.duration / beat_seconds
            voiced.append(
                VoicedNote(
                    source_index=index,
                    pitch=note.pitch,
                    velocity=80,
                    start_beat=start_beat,
                    duration_beats=duration_beats,
                    measure_number=int(start_beat // 4) + 1,
                    beat_in_measure=start_beat % 4,
                    tie_in=False,
                    tie_out=False,
                    original_start_beat=start_beat,
                    original_duration_beats=duration_beats,
                    voice=1,
                    let_ring=False,
                    legato_candidate=False,
                    stream=excerpt.role,
                )
            )
            truth[index] = (note.string, note.fret)

        track = NormalizedTrack(0, "guitar")
        timeline = NormalizedTimeline(excerpt.source_key, 1, 480, [], [], [track])
        for label, engine in engines.items():
            context = PipelineContext(
                timeline=timeline,
                track=track,
                knowledge=engine.registry,
                style_label=excerpt.style,
                midi_fidelity=0.75,
                advisor=None,
                track_role=excerpt.role,
            )
            context.voiced_notes = list(voiced)
            FingeringStage(engine).run(context)
            exact = sum(
                (note.string, note.fret) == truth[note.source_index]
                for note in context.fingered_notes
            )
            counts[(excerpt.style, excerpt.role, split, f"{label}_exact")] += exact
            if label == "baseline":
                counts[(excerpt.style, excerpt.role, split, "total")] += len(truth)

    result: dict[tuple[str, str], dict[str, Any]] = {}
    for style, role in sorted({(excerpt.style, excerpt.role) for excerpt in material}):
        split_metrics: dict[str, Any] = {}
        for split in ("validation", "test"):
            total = counts[(style, role, split, "total")]
            baseline_exact = counts[(style, role, split, "baseline_exact")]
            candidate_exact = counts[(style, role, split, "candidate_exact")]
            baseline_rate = baseline_exact / total if total else 0.0
            candidate_rate = candidate_exact / total if total else 0.0
            split_metrics[split] = {
                "notes": total,
                "baseline_exact_rate": round(baseline_rate, 6),
                "candidate_exact_rate": round(candidate_rate, 6),
                "delta": round(candidate_rate - baseline_rate, 6),
            }
        result[(style, role)] = split_metrics
    return result


def build_kb2_asset(annotation_dir: str | Path) -> dict[str, Any]:
    """Build a complete, provenance-safe KB2 asset from 360 annotations."""

    excerpts = [load_excerpt(path) for path in sorted(Path(annotation_dir).glob("*.jams"))]
    if len(excerpts) != 360:
        raise ValueError(f"Expected 360 GuitarSet annotations, found {len(excerpts)}")

    grouped: dict[tuple[str, str, str], list[GuitarSetExcerpt]] = defaultdict(list)
    for excerpt in excerpts:
        grouped[(split_name(excerpt.performer), excerpt.style, excerpt.role)].append(excerpt)

    entries: list[dict[str, Any]] = [
        {
            "knowledge_id": "kb2-guitar-safe-defaults-v1",
            "domain": "kb2_performance",
            "kind": "fingering_priors",
            "schema_version": "2",
            "knowledge_version": "2026.08.23-guitarset-v1",
            "status": "approved",
            "payload": {
                "shape_reuse": 1.0,
                "hand_position_stability": 1.25,
                "note_overlap": 1.0,
                "open_string_bias": 1.0,
                "staccato": 1.0,
                "string_skip_penalty": 1.15,
                "max_fret_span": 4.0,
                "max_position_shift": 7.0,
                "articulation_policy": {
                    "mode": "conservative_evidence_first",
                    "legato_max_interval_semitones": 5,
                    "legato_max_gap_beats": 0.25,
                    "bend_requires_pitch_curve": True,
                    "slide_requires_explicit_or_contextual_evidence": True,
                    "never_infer": ["harmonic", "tapping", "trill"],
                },
            },
            "scope": {},
            "provenance": {
                "source_type": "hand_authored",
                "source_ids": [
                    "bandpilot-internal-policy-v1",
                    "path-difference-learning-2004",
                    "guitar-biomechanics-2002",
                ],
                "authored_by": "BandPilot knowledge governance",
                "notes": "Conservative fallback. Empirical style-role entries layer on top.",
            },
            "evaluation": {
                "status": "approved",
                "confidence": 0.8,
                "tested_against": ["bandpilot-internal-policy-v1"],
                "metrics": {},
            },
        },
        {
            "knowledge_id": "kb2-metal-safe-policy-v1",
            "domain": "kb2_performance",
            "kind": "fingering_priors",
            "schema_version": "2",
            "knowledge_version": "2026.08.23-guitarset-v1",
            "status": "approved",
            "payload": {
                "shape_reuse": 1.45,
                "hand_position_stability": 1.4,
                "palm_mute": 1.55,
                "staccato": 1.3,
                "open_string_bias": 0.8,
                "power_chord_preference": 1.5,
                "chord_shapes": {"s5f2,s6f0": 100, "s4f2,s5f0": 100, "s4f2,s5f2,s6f0": 80},
                "chord_shape_templates": {"s5+2,s6+0": 100, "s4+2,s5+0": 100, "s4+2,s5+2,s6+0": 80},
            },
            "scope": {"style": ["metal"]},
            "provenance": {
                "source_type": "hand_authored",
                "source_ids": ["bandpilot-internal-policy-v1", "rich-guitar-tablature-2024"],
                "authored_by": "BandPilot knowledge governance",
                "notes": "Conservative metal policy pending a rights-clear labelled metal corpus.",
            },
            "evaluation": {
                "status": "approved",
                "confidence": 0.65,
                "tested_against": ["bandpilot-internal-policy-v1"],
                "metrics": {},
            },
        },
    ]

    aliases = {
        "singer_songwriter": ["singer_songwriter", "acoustic", "pop"],
    }
    for style in sorted({excerpt.style for excerpt in excerpts}):
        for role in ("lead", "rhythm"):
            train = aggregate_excerpts(grouped[("train", style, role)])
            validation = aggregate_excerpts(grouped[("validation", style, role)])
            test = aggregate_excerpts(grouped[("test", style, role)])
            validation_drift = _split_drift(train, validation)
            confidence = round(
                max(
                    0.6,
                    min(
                        0.95,
                        0.95 - validation_drift["mean_absolute_rate_delta"] * 1.5,
                    ),
                ),
                3,
            )
            entries.append(
                {
                    "knowledge_id": f"kb2-guitarset-{style}-{role}-v1",
                    "domain": "kb2_performance",
                    "kind": "fingering_priors",
                    "schema_version": "2",
                    "knowledge_version": "2026.08.23-guitarset-v1",
                    "status": "approved",
                    "payload": observations_to_priors(train),
                    "scope": {"style": aliases.get(style, [style]), "role": [role]},
                    "provenance": {
                        "source_type": "empirical",
                        "source_ids": ["guitarset-zenodo-3371780"],
                        "authored_by": "fretpilot.elearning.guitarset",
                        "notes": "Aggregate-only derivation from performer-disjoint training split (00-03).",
                    },
                    "evaluation": {
                        "status": "approved",
                        "confidence": confidence,
                        "tested_against": [
                            "guitarset-performer-04-validation",
                            "guitarset-performer-05-test",
                        ],
                        "metrics": {
                            "validation_observed_rates": _rates_only(validation),
                            "validation_drift": validation_drift,
                            "test_observed_rates": _rates_only(test),
                            "test_drift": _split_drift(train, test),
                        },
                    },
                }
            )

    fingering_ab = evaluate_fingering_ab(entries, excerpts)
    for entry in entries:
        if entry["provenance"]["source_type"] != "empirical":
            continue
        style = entry["scope"]["style"][0]
        role = entry["scope"]["role"][0]
        metrics = fingering_ab[(style, role)]
        passed = all(metrics[split]["delta"] >= 0.0 for split in ("validation", "test"))
        entry["evaluation"]["metrics"]["fingering_ab"] = metrics
        entry["evaluation"]["metrics"]["promotion_gate"] = {
            "rule": "non_negative_exact_fingering_delta_on_validation_and_test",
            "passed": passed,
        }
        entry["status"] = "approved" if passed else "candidate"
        entry["evaluation"]["status"] = "approved" if passed else "evaluated"

    return {
        "snapshot_version": "2026.08.23-guitarset-v1",
        "schema_version": "2",
        "status": "approved",
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    """Rebuild the KB2 asset from an already verified annotation directory."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotation_dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    asset = build_kb2_asset(args.annotation_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(asset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


__all__ = [
    "GuitarSetExcerpt",
    "GuitarSetNote",
    "absolute_shape",
    "aggregate_excerpts",
    "build_kb2_asset",
    "evaluate_fingering_ab",
    "load_excerpt",
    "observations_to_priors",
    "relative_shape",
    "split_name",
]


if __name__ == "__main__":  # pragma: no cover - exercised as a build tool
    raise SystemExit(main())

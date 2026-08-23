"""Track router — dispatches tracks to sub-module pipelines.

Routes guitar tracks to the existing FretPilot pipeline and drum tracks to
the DrumRepairPipeline. Tracks with unhandled families (bass, keys, unknown)
are passed through unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.ir.models import GuitarProjectIR, Transformation
from fretpilot.ir.pitched_models import PitchedProjectIR
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.orchestrator.detector import InstrumentFamily

if TYPE_CHECKING:
    from fretpilot.engine.drum_pipeline import DrumRepairPipeline
    from fretpilot.engine.pipeline import RepairPipeline

logger = logging.getLogger("fretpilot.orchestrator.router")


@dataclass(slots=True)
class RouteResult:
    """Result of routing a single track to a sub-module pipeline.

    Attributes:
        track_index: Index of the routed track in the timeline.
        family: Instrument family that determined the route.
        module: Name of the sub-module that processed the track
            ("fretpilot", "stickpilot", or "passthrough").
        guitar_ir: Guitar IR if routed to FretPilot, else None.
        drum_ir: Drum IR if routed to StickPilot, else None.
        changes: Transformation list produced by the pipeline.
        stages_completed: Number of pipeline stages completed.
        note_count: Number of notes in the processed track.
        warnings: Non-fatal warnings from the pipeline.
        drum_report: Extra drum-specific report data (if applicable).
        skipped: True if the track was passed through unchanged.
        failed: True if the selected pipeline raised an error.
    """

    track_index: int
    family: InstrumentFamily
    module: str
    guitar_ir: GuitarProjectIR | None = None
    drum_ir: DrumProjectIR | None = None
    pitched_ir: PitchedProjectIR | None = None
    changes: list[Transformation] = field(default_factory=list)
    stages_completed: int = 0
    note_count: int = 0
    warnings: list[str] = field(default_factory=list)
    drum_report: dict[str, Any] = field(default_factory=dict)
    separation: Any | None = None
    skipped: bool = False
    failed: bool = False
    error: str | None = None


def route_guitar(
    track: NormalizedTrack,
    timeline: NormalizedTimeline,
    guitar_pipeline: RepairPipeline,
    knowledge: Any,
    settings: dict[str, Any],
) -> RouteResult:
    """Route a guitar track to the FretPilot pipeline."""
    from fretpilot.engine.context import PipelineContext

    midi_fidelity = settings.get("midi_fidelity", 0.5)
    style_label = settings.get("style_label", "unknown")
    track_role = settings.get("guitar_role", "unknown")
    tuning = settings.get("tuning", None)
    advisor = settings.get("advisor", None)
    degraded_mode = settings.get("degraded_mode", False)
    rewrite_decisions = settings.get("rewrite_decisions", [])
    initial_transformations = settings.get("initial_transformations", [])

    ctx = PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=knowledge,
        style_label=style_label,
        midi_fidelity=midi_fidelity,
        advisor=advisor,
        track_role=track_role,
        source_track_index=track.index,
        degraded_mode=degraded_mode,
        tuning=tuning,
        track_id=settings.get("track_id", f"guitar-{track.index}"),
        rewrite_decisions=list(rewrite_decisions),
    )
    ctx.transformations.extend(initial_transformations)

    ir = guitar_pipeline.execute(ctx)
    stages_completed = sum(1 for v in ctx.stage_progress.values() if v)

    return RouteResult(
        track_index=track.index,
        family=InstrumentFamily.GUITAR,
        module="fretpilot",
        guitar_ir=ir,
        changes=list(ctx.transformations),
        stages_completed=stages_completed,
        note_count=len(track.notes),
        warnings=list(ctx.warnings),
        separation=ctx.separation,
    )


def route_drums(
    track: NormalizedTrack,
    timeline: NormalizedTimeline,
    drum_pipeline: DrumRepairPipeline,
    knowledge: Any,
    settings: dict[str, Any],
) -> RouteResult:
    """Route a drum track to the StickPilot pipeline."""
    from fretpilot.engine.drum_context import DrumPipelineContext

    midi_fidelity = settings.get("midi_fidelity", 0.5)
    style_label = settings.get("style_label", "unknown")

    ctx = DrumPipelineContext(
        timeline=timeline,
        track=track,
        knowledge=knowledge,
        style_label=style_label,
        midi_fidelity=midi_fidelity,
        track_id=settings.get("track_id", f"drum-{track.index}"),
        source_track_index=track.index,
    )

    ir = drum_pipeline.execute(ctx)
    stages_completed = sum(1 for v in ctx.stage_progress.values() if v)

    # Build drum-specific report.
    drum_report: dict[str, Any] = {
        "kit_type": "",
        "style_detected": ctx.detected_style,
        "patterns": [],
        "sticking_suggested": stages_completed >= 6,
        "velocity_normalized": stages_completed >= 5,
        "piece_stats": [],
    }
    if ir.tracks:
        drum_track = ir.tracks[0]
        drum_report["kit_type"] = drum_track.kit
        drum_report["style_detected"] = drum_track.style
        drum_report["patterns"] = [m.pattern for m in drum_track.measures]
        piece_velocities: dict[str, list[int]] = {}
        for measure in drum_track.measures:
            for event in measure.events:
                piece_velocities.setdefault(event.piece, []).append(
                    event.performance.velocity
                )
        drum_report["piece_stats"] = [
            {
                "name": piece,
                "hit_count": len(velocities),
                "avg_velocity": round(sum(velocities) / len(velocities), 1),
            }
            for piece, velocities in sorted(piece_velocities.items())
        ]

    return RouteResult(
        track_index=track.index,
        family=InstrumentFamily.DRUMS,
        module="stickpilot",
        drum_ir=ir,
        changes=list(ctx.transformations),
        stages_completed=stages_completed,
        note_count=len(track.notes),
        warnings=list(ctx.warnings),
        drum_report=drum_report,
    )


def route_passthrough(
    track: NormalizedTrack,
    family: InstrumentFamily,
) -> RouteResult:
    """Pass a track through unchanged (unhandled family)."""
    return RouteResult(
        track_index=track.index,
        family=family,
        module="passthrough",
        stages_completed=0,
        note_count=len(track.notes),
        warnings=[
            f"No repair pipeline for instrument family '{family.value}'; "
            "the source track is retained as passthrough metadata but omitted from notation exports"
        ],
        skipped=True,
    )


def route_pitched(
    track: NormalizedTrack,
    timeline: NormalizedTimeline,
    family: InstrumentFamily,
    pipeline: Any,
    knowledge: Any,
    settings: dict[str, Any],
) -> RouteResult:
    """Route bass, keys, or generic tracks to a dedicated pitched plugin."""
    ir = pipeline.execute(
        track=track,
        timeline=timeline,
        registry=knowledge,
        settings=settings,
    )
    return RouteResult(
        track_index=track.index,
        family=family,
        module={
            InstrumentFamily.BASS: "basspilot",
            InstrumentFamily.KEYS: "keyspilot",
            InstrumentFamily.UNKNOWN: "genericpilot",
        }[family],
        pitched_ir=ir,
        changes=list(ir.changes),
        stages_completed=len(pipeline.stages),
        note_count=len(track.notes),
        warnings=list(ir.warnings),
    )


def route_track(
    track: NormalizedTrack,
    family: InstrumentFamily,
    knowledge: Any,
    settings: dict[str, Any],
    timeline: NormalizedTimeline,
    guitar_pipeline: RepairPipeline | None = None,
    drum_pipeline: DrumRepairPipeline | None = None,
) -> RouteResult:
    """Route a track to the appropriate sub-module pipeline.

    Args:
        track: The physical MIDI track to process.
        family: Detected instrument family for this track.
        knowledge: Knowledge registry (from the pipeline).
        settings: Dict of pipeline settings (midi_fidelity, style_label, ...).
        timeline: The full normalized MIDI timeline.
        guitar_pipeline: FretPilot pipeline instance (required for guitar).
        drum_pipeline: StickPilot pipeline instance (required for drums).

    Returns:
        A ``RouteResult`` containing the IR and transformation list.

    Raises:
        RuntimeError: If a required pipeline is not provided.
    """
    if family == InstrumentFamily.GUITAR:
        if guitar_pipeline is None:
            raise RuntimeError("Guitar pipeline required but not provided")
        return route_guitar(track, timeline, guitar_pipeline, knowledge, settings)

    if family == InstrumentFamily.DRUMS:
        if drum_pipeline is None:
            raise RuntimeError("Drum pipeline required but not provided")
        return route_drums(track, timeline, drum_pipeline, knowledge, settings)

    # Bass, keys, unknown — passthrough.
    return route_passthrough(track, family)


__all__ = [
    "RouteResult",
    "route_drums",
    "route_guitar",
    "route_passthrough",
    "route_pitched",
    "route_track",
]

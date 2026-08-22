"""BandPilot orchestrator — the main entry point for mixed-instrument MIDI repair.

Workflow:
  1. Detect instrument families for all tracks.
  2. Route each track to the appropriate sub-module pipeline.
  3. Collect results (guitar IRs, drum IRs, passthrough tracks).
  4. Merge all IRs into a unified structure for GP5 export.

Backward compatibility: if no drums (or other non-guitar tracks) are detected,
the orchestrator behaves exactly like the existing guitar-only pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.ir.models import GuitarProjectIR, Transformation
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack

from fretpilot.orchestrator.detector import (
    InstrumentFamily,
    TrackFamilyClassification,
    classify_track_family,
)
from fretpilot.orchestrator.merge import merge_irs
from fretpilot.orchestrator.router import RouteResult, route_track

if TYPE_CHECKING:
    from fretpilot.engine.pipeline import RepairPipeline
    from fretpilot.engine.drum_pipeline import DrumRepairPipeline

logger = logging.getLogger("fretpilot.orchestrator.bandpilot")


@dataclass(slots=True)
class TrackRepairReport:
    """Per-track repair report for the API response.

    Attributes:
        track_index: Index of the track in the timeline.
        track_name: Human-readable track name.
        family: Instrument family string.
        module: Sub-module that processed the track.
        stages_completed: Number of pipeline stages completed.
        note_count: Number of notes in the track.
        change_count: Number of transformations applied.
        drum_report: Extra drum-specific data (if applicable).
        skipped: True if the track was passed through unchanged.
    """

    track_index: int
    track_name: str
    family: str
    module: str
    stages_completed: int
    note_count: int
    change_count: int
    drum_report: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON responses."""
        from dataclasses import asdict
        return asdict(self)


@dataclass(slots=True)
class BandPilotResult:
    """Aggregated result of a BandPilot orchestration run.

    Attributes:
        title: Project title.
        style_label: Detected style label.
        degraded_mode: Whether any pipeline ran in degraded mode.
        classifications: Per-track family classifications.
        route_results: Per-track routing results.
        track_reports: Per-track repair reports (for API response).
        guitar_irs: All guitar IRs produced.
        drum_irs: All drum IRs produced.
        merged_ir: Unified merged IR dict (ready for GP5 export).
        total_changes: Total transformation count across all tracks.
        warnings: All warnings collected during the run.
        has_drums: Whether any drum tracks were detected.
        has_guitar: Whether any guitar tracks were detected.
    """

    title: str
    style_label: str
    degraded_mode: bool
    classifications: list[TrackFamilyClassification] = field(default_factory=list)
    route_results: list[RouteResult] = field(default_factory=list)
    track_reports: list[TrackRepairReport] = field(default_factory=list)
    guitar_irs: list[GuitarProjectIR] = field(default_factory=list)
    drum_irs: list[DrumProjectIR] = field(default_factory=list)
    merged_ir: dict[str, Any] = field(default_factory=dict)
    total_changes: int = 0
    warnings: list[str] = field(default_factory=list)
    has_drums: bool = False
    has_guitar: bool = False

    @property
    def primary_guitar_ir(self) -> GuitarProjectIR | None:
        """Return the first guitar IR, if any (backward-compat helper)."""
        return self.guitar_irs[0] if self.guitar_irs else None

    @property
    def primary_drum_ir(self) -> DrumProjectIR | None:
        """Return the first drum IR, if any."""
        return self.drum_irs[0] if self.drum_irs else None


class BandPilotOrchestrator:
    """Main BandPilot orchestrator — auto-detect, route, merge.

    Usage::

        orchestrator = BandPilotOrchestrator(
            guitar_pipeline=create_pipeline(),
            drum_pipeline=create_drum_pipeline(),
        )
        result = orchestrator.run(timeline, settings)

    Backward compatibility: when no drums are detected, the result contains
    only guitar IRs and ``merged_ir`` wraps the single guitar IR, matching
    the behavior of the existing guitar-only repair endpoint.
    """

    def __init__(
        self,
        guitar_pipeline: RepairPipeline,
        drum_pipeline: DrumRepairPipeline,
    ) -> None:
        """Initialize the orchestrator with sub-module pipelines.

        Args:
            guitar_pipeline: FretPilot repair pipeline instance.
            drum_pipeline: StickPilot drum repair pipeline instance.
        """
        self._guitar_pipeline = guitar_pipeline
        self._drum_pipeline = drum_pipeline

    @property
    def registry(self) -> Any:
        """Expose the guitar pipeline's knowledge registry (shared)."""
        return self._guitar_pipeline.registry

    def run(
        self,
        timeline: NormalizedTimeline,
        settings: dict[str, Any] | None = None,
    ) -> BandPilotResult:
        """Run the full BandPilot orchestration on a timeline.

        Steps:
          1. Classify each track's instrument family.
          2. Route each track to its sub-module pipeline.
          3. Collect guitar IRs, drum IRs, and passthrough tracks.
          4. Merge all IRs into a unified structure.

        Args:
            timeline: The full normalized MIDI timeline.
            settings: Optional dict of pipeline settings. Supported keys:
                ``midi_fidelity`` (float), ``style_label`` (str),
                ``tuning`` (GuitarTuning), ``advisor`` (RewriteAdvisor),
                ``degraded_mode`` (bool), ``title`` (str).

        Returns:
            A ``BandPilotResult`` with per-track reports and merged IR.
        """
        settings = settings or {}
        title = settings.get("title", timeline.source or "Untitled")
        knowledge = self._guitar_pipeline.registry

        # ── Step 1: Detect families for all tracks ──
        classifications: list[TrackFamilyClassification] = []
        for track in timeline.tracks:
            if not track.notes:
                continue
            cls = classify_track_family(track)
            classifications.append(cls)

        has_guitar = any(c.family == InstrumentFamily.GUITAR for c in classifications)
        has_drums = any(c.family == InstrumentFamily.DRUMS for c in classifications)

        logger.info(
            "BandPilot: detected %d tracks — guitar=%s, drums=%s",
            len(classifications), has_guitar, has_drums,
        )

        # ── Step 2: Route each track to its sub-module ──
        route_results: list[RouteResult] = []
        guitar_irs: list[GuitarProjectIR] = []
        drum_irs: list[DrumProjectIR] = []
        warnings: list[str] = []
        degraded_mode = False

        cls_by_index = {c.track_index: c for c in classifications}

        for track in timeline.tracks:
            if not track.notes:
                continue
            cls = cls_by_index.get(track.index)
            if cls is None:
                continue

            try:
                result = route_track(
                    track=track,
                    family=cls.family,
                    knowledge=knowledge,
                    settings=settings,
                    timeline=timeline,
                    guitar_pipeline=self._guitar_pipeline,
                    drum_pipeline=self._drum_pipeline,
                )
            except Exception:
                logger.exception(
                    "BandPilot: error routing track %d (family=%s)",
                    track.index, cls.family.value,
                )
                # Gracefully handle errors — passthrough on failure.
                result = RouteResult(
                    track_index=track.index,
                    family=cls.family,
                    module="passthrough",
                    note_count=len(track.notes),
                    warnings=[f"Pipeline error on track {track.index} — passed through"],
                    skipped=True,
                )

            route_results.append(result)
            warnings.extend(result.warnings)

            if result.guitar_ir is not None:
                guitar_irs.append(result.guitar_ir)
                if result.guitar_ir.degraded_mode:
                    degraded_mode = True
            if result.drum_ir is not None:
                drum_irs.append(result.drum_ir)

        # ── Step 3: Build per-track repair reports ──
        track_reports: list[TrackRepairReport] = []
        for cls, rr in zip(classifications, route_results, strict=False):
            # Match by track_index since zip may misalign if some tracks
            # were skipped. Use the route result's own track_index.
            pass

        # Rebuild reports by matching classifications to route results.
        rr_by_index = {r.track_index: r for r in route_results}
        for cls in classifications:
            rr = rr_by_index.get(cls.track_index)
            if rr is None:
                continue
            track_reports.append(TrackRepairReport(
                track_index=cls.track_index,
                track_name=cls.track_name,
                family=cls.family.value,
                module=rr.module,
                stages_completed=rr.stages_completed,
                note_count=rr.note_count,
                change_count=len(rr.changes),
                drum_report=rr.drum_report,
                skipped=rr.skipped,
            ))

        # ── Step 4: Merge all IRs ──
        merged_ir = merge_irs(guitar_irs, drum_irs, title)

        total_changes = sum(len(r.changes) for r in route_results)

        # Determine style label from settings or merged IR.
        style_label = settings.get("style_label", merged_ir.get("style_label", "unknown"))

        return BandPilotResult(
            title=title,
            style_label=style_label,
            degraded_mode=degraded_mode,
            classifications=classifications,
            route_results=route_results,
            track_reports=track_reports,
            guitar_irs=guitar_irs,
            drum_irs=drum_irs,
            merged_ir=merged_ir,
            total_changes=total_changes,
            warnings=warnings,
            has_drums=has_drums,
            has_guitar=has_guitar,
        )


__all__ = ["BandPilotOrchestrator", "BandPilotResult", "TrackRepairReport"]

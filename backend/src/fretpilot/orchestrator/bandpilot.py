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
from fretpilot.ir.models import GuitarProjectIR
from fretpilot.ir.pitched_models import PitchedProjectIR
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.orchestrator.detector import (
    InstrumentFamily,
    TrackFamilyClassification,
    classify_track_family,
)
from fretpilot.orchestrator.merge import merge_irs
from fretpilot.orchestrator.plugins import InstrumentPluginRegistry, PluginRequest
from fretpilot.orchestrator.router import RouteResult

if TYPE_CHECKING:
    from fretpilot.engine.drum_pipeline import DrumRepairPipeline
    from fretpilot.engine.pipeline import RepairPipeline

logger = logging.getLogger("fretpilot.orchestrator.bandpilot")


def _classify_tracks(
    timeline: NormalizedTimeline,
    overrides: dict[int, InstrumentFamily | str] | None = None,
) -> list[TrackFamilyClassification]:
    """Classify each note-bearing physical track exactly once."""
    overrides = overrides or {}
    return [
        classify_track_family(track, overrides.get(track.index))
        for track in timeline.tracks
        if track.notes
    ]


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
    failed: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

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
    pitched_irs: list[PitchedProjectIR] = field(default_factory=list)
    merged_ir: dict[str, Any] = field(default_factory=dict)
    total_changes: int = 0
    warnings: list[str] = field(default_factory=list)
    has_drums: bool = False
    has_guitar: bool = False

    @property
    def successful_track_count(self) -> int:
        return sum(not result.skipped and not result.failed for result in self.route_results)

    @property
    def failed_track_count(self) -> int:
        return sum(result.failed for result in self.route_results)

    @property
    def skipped_track_count(self) -> int:
        return sum(result.skipped for result in self.route_results)

    @property
    def status(self) -> str:
        """Return the truthful aggregate outcome for persistence and API use."""
        if self.successful_track_count == 0:
            return "failed"
        if self.failed_track_count or self.skipped_track_count:
            return "partial"
        return "repaired"

    @property
    def primary_guitar_ir(self) -> GuitarProjectIR | None:
        """Return the first guitar IR, if any (backward-compat helper)."""
        return self.guitar_irs[0] if self.guitar_irs else None

    @property
    def primary_drum_ir(self) -> DrumProjectIR | None:
        """Return the first drum IR, if any."""
        return self.drum_irs[0] if self.drum_irs else None


def _build_track_reports(
    classifications: list[TrackFamilyClassification],
    route_results: list[RouteResult],
) -> list[TrackRepairReport]:
    """Join classifications and route results by stable source track index."""
    results_by_index = {result.track_index: result for result in route_results}
    reports: list[TrackRepairReport] = []
    for classification in classifications:
        result = results_by_index.get(classification.track_index)
        if result is None:
            continue
        reports.append(
            TrackRepairReport(
                track_index=classification.track_index,
                track_name=classification.track_name,
                family=classification.family.value,
                module=result.module,
                stages_completed=result.stages_completed,
                note_count=result.note_count,
                change_count=len(result.changes),
                drum_report=result.drum_report,
                skipped=result.skipped,
                failed=result.failed,
                error=result.error,
                warnings=list(result.warnings),
            )
        )
    return reports


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
        plugin_registry: InstrumentPluginRegistry | None = None,
    ) -> None:
        """Initialize the orchestrator with sub-module pipelines.

        Args:
            guitar_pipeline: FretPilot repair pipeline instance.
            drum_pipeline: StickPilot drum repair pipeline instance.
        """
        self._guitar_pipeline = guitar_pipeline
        self._drum_pipeline = drum_pipeline
        self._plugins = plugin_registry or InstrumentPluginRegistry.default(
            guitar_pipeline, drum_pipeline
        )

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
        classifications = _classify_tracks(timeline, settings.get("family_overrides"))

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
        pitched_irs: list[PitchedProjectIR] = []
        warnings: list[str] = []
        degraded_mode = False

        cls_by_index = {c.track_index: c for c in classifications}
        track_overrides: dict[int, NormalizedTrack] = settings.get("track_overrides", {})
        track_settings: dict[int, dict[str, Any]] = settings.get("track_settings", {})

        for track in timeline.tracks:
            if not track.notes:
                continue
            cls = cls_by_index.get(track.index)
            if cls is None:
                continue

            try:
                routed_track = track_overrides.get(track.index, track)
                effective_settings = {**settings, **track_settings.get(track.index, {})}
                result = self._plugins.route(
                    cls.family,
                    PluginRequest(
                        track=routed_track,
                        timeline=timeline,
                        knowledge=knowledge,
                        settings=effective_settings,
                    ),
                )
            except Exception:
                logger.exception(
                    "BandPilot: error routing track %d (family=%s)",
                    track.index, cls.family.value,
                )
                error = f"Pipeline failed for track {track.index} ({cls.family.value})"
                result = RouteResult(
                    track_index=track.index,
                    family=cls.family,
                    module={
                        InstrumentFamily.GUITAR: "fretpilot",
                        InstrumentFamily.DRUMS: "stickpilot",
                        InstrumentFamily.BASS: "basspilot",
                        InstrumentFamily.KEYS: "keyspilot",
                        InstrumentFamily.UNKNOWN: "genericpilot",
                    }[cls.family],
                    note_count=len(track.notes),
                    warnings=[error],
                    failed=True,
                    error=error,
                )

            route_results.append(result)
            warnings.extend(result.warnings)

            if result.guitar_ir is not None:
                guitar_irs.append(result.guitar_ir)
                if result.guitar_ir.degraded_mode:
                    degraded_mode = True
            if result.drum_ir is not None:
                drum_irs.append(result.drum_ir)
            if result.pitched_ir is not None:
                pitched_irs.append(result.pitched_ir)

        # ── Step 3: Build per-track repair reports ──
        track_reports = _build_track_reports(classifications, route_results)

        # ── Step 4: Merge all IRs ──
        merged_ir = merge_irs(guitar_irs, drum_irs, title)
        merged_ir["passthrough_tracks"] = [
            {
                "track_index": report.track_index,
                "track_name": report.track_name,
                "family": report.family,
                "note_count": report.note_count,
            }
            for report in track_reports
            if report.skipped
        ]
        merged_ir["failed_tracks"] = [
            {
                "track_index": report.track_index,
                "track_name": report.track_name,
                "family": report.family,
                "error": report.error,
            }
            for report in track_reports
            if report.failed
        ]

        total_changes = sum(len(r.changes) for r in route_results)

        # Determine style label from settings or merged IR.
        requested_style = settings.get("style_label")
        style_label = (
            requested_style
            if requested_style and requested_style != "unknown"
            else merged_ir.get("style_label", "unknown")
        )

        return BandPilotResult(
            title=title,
            style_label=style_label,
            degraded_mode=degraded_mode,
            classifications=classifications,
            route_results=route_results,
            track_reports=track_reports,
            guitar_irs=guitar_irs,
            drum_irs=drum_irs,
            pitched_irs=pitched_irs,
            merged_ir=merged_ir,
            total_changes=total_changes,
            warnings=warnings,
            has_drums=has_drums,
            has_guitar=has_guitar,
        )


__all__ = ["BandPilotOrchestrator", "BandPilotResult", "TrackRepairReport"]

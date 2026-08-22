"""BandPilot orchestration layer — auto-detect, route, and merge.

Public API:
  - ``InstrumentFamily``: enum of detectable instrument families.
  - ``TrackFamilyClassification``: per-track family classification result.
  - ``classify_track_family``: classify a single track's instrument family.
  - ``RouteResult``: result of routing a track to a sub-module pipeline.
  - ``route_track``: route a track to the appropriate sub-module.
  - ``merge_irs``: merge multiple instrument IRs into a unified structure.
  - ``BandPilotOrchestrator``: main entry point for BandPilot orchestration.
  - ``BandPilotResult``: aggregated result of a BandPilot run.
"""

from __future__ import annotations

from fretpilot.orchestrator.bandpilot import BandPilotOrchestrator, BandPilotResult
from fretpilot.orchestrator.detector import (
    InstrumentFamily,
    TrackFamilyClassification,
    classify_track_family,
)
from fretpilot.orchestrator.merge import merge_irs
from fretpilot.orchestrator.router import RouteResult, route_track

__all__ = [
    "InstrumentFamily",
    "TrackFamilyClassification",
    "classify_track_family",
    "RouteResult",
    "route_track",
    "merge_irs",
    "BandPilotOrchestrator",
    "BandPilotResult",
]

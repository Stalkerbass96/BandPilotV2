"""Track detection and guitar identification."""

from fretpilot.detection.classifier import classify_timeline
from fretpilot.detection.models import GuitarDetectionReport, TrackClassification
from fretpilot.detection.separation import (
    SeparationNote,
    SeparationReport,
    SeparationSegment,
    assign_stream,
    detect_separation,
)
from fretpilot.detection.streams import LogicalStream, resolve_streams, stream_from_track

__all__ = [
    "TrackClassification",
    "GuitarDetectionReport",
    "LogicalStream",
    "resolve_streams",
    "stream_from_track",
    "classify_timeline",
    "SeparationNote",
    "SeparationSegment",
    "SeparationReport",
    "detect_separation",
    "assign_stream",
]

"""Detection result models — guitar track identification output."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TrackClassification:
    """Classification result for a single physical track.

    Auto-detected results are user-editable data: :meth:`apply_override` lets
    the caller overwrite the family/role, after which ``is_guitar``,
    ``instrument_family`` and ``guitar_role`` reflect the override and
    ``confidence`` is pinned to 1.0.
    """

    track_index: int
    track_name: str
    instrument_family: str  # guitar / bass / piano / ...
    program: int | None
    is_guitar: bool
    guitar_role: str  # lead / rhythm / bass / unknown
    confidence: float
    reason: str
    user_override: bool = False
    overridden_family: str = ""
    overridden_role: str = ""

    def apply_override(self, family: str, role: str = "") -> "TrackClassification":
        """Apply a user override, re-deriving derived fields from ``family``.

        ``family`` should be an instrument family (e.g. "guitar", "bass").
        ``role`` optionally sets the guitar role ("lead"/"rhythm"); when empty
        it defaults to "bass" for the bass family and "unknown" otherwise.
        """
        self.user_override = True
        self.overridden_family = family
        self.overridden_role = role
        self.instrument_family = family
        self.is_guitar = family == "guitar"
        self.guitar_role = role or ("bass" if family == "bass" else "unknown")
        self.confidence = 1.0
        self.reason = f"User override: family={family}, role={role or '-'}"
        return self


@dataclass(slots=True)
class GuitarDetectionReport:
    """Aggregated detection report across all tracks in a timeline."""

    classifications: list[TrackClassification] = field(default_factory=list)
    primary_guitar_track_index: int | None = None
    total_guitar_tracks: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def primary_classification(self) -> TrackClassification | None:
        """Return the classification for the primary guitar track, if any."""
        if self.primary_guitar_track_index is None:
            return None
        for cls in self.classifications:
            if cls.track_index == self.primary_guitar_track_index:
                return cls
        return None

    @property
    def guitar_classifications(self) -> list[TrackClassification]:
        """Return only the guitar-track classifications."""
        return [c for c in self.classifications if c.is_guitar]


__all__ = ["TrackClassification", "GuitarDetectionReport"]

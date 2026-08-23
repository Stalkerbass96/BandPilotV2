"""Instrument plugin registry for BandPilot orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fretpilot.engine.drum_pipeline import DrumRepairPipeline
from fretpilot.engine.pipeline import RepairPipeline
from fretpilot.engine.pitched_pipeline import PitchedRepairPipeline
from fretpilot.midi.models import NormalizedTimeline, NormalizedTrack
from fretpilot.orchestrator.detector import InstrumentFamily
from fretpilot.orchestrator.router import (
    RouteResult,
    route_drums,
    route_guitar,
    route_passthrough,
    route_pitched,
)


@dataclass(slots=True)
class PluginRequest:
    track: NormalizedTrack
    timeline: NormalizedTimeline
    knowledge: Any
    settings: dict[str, Any]


class InstrumentPlugin(Protocol):
    family: InstrumentFamily
    module: str

    def repair(self, request: PluginRequest) -> RouteResult:
        """Produce a typed route result without changing source ownership."""


class GuitarPlugin:
    family = InstrumentFamily.GUITAR
    module = "fretpilot"

    def __init__(self, pipeline: RepairPipeline) -> None:
        self._pipeline = pipeline

    def repair(self, request: PluginRequest) -> RouteResult:
        return route_guitar(
            request.track,
            request.timeline,
            self._pipeline,
            request.knowledge,
            request.settings,
        )


class DrumPlugin:
    family = InstrumentFamily.DRUMS
    module = "stickpilot"

    def __init__(self, pipeline: DrumRepairPipeline) -> None:
        self._pipeline = pipeline

    def repair(self, request: PluginRequest) -> RouteResult:
        return route_drums(
            request.track,
            request.timeline,
            self._pipeline,
            request.knowledge,
            request.settings,
        )


class PitchedInstrumentPlugin:
    """Base implementation shared by truthful family-specific plugins."""

    module = "pitchedpilot"

    def __init__(self, family: InstrumentFamily) -> None:
        self.family = family
        self._pipeline = PitchedRepairPipeline(
            "generic" if family == InstrumentFamily.UNKNOWN else family.value
        )

    def repair(self, request: PluginRequest) -> RouteResult:
        return route_pitched(
            request.track,
            request.timeline,
            self.family,
            self._pipeline,
            request.knowledge,
            request.settings,
        )


class BassPlugin(PitchedInstrumentPlugin):
    module = "basspilot"

    def __init__(self) -> None:
        super().__init__(InstrumentFamily.BASS)


class KeysPlugin(PitchedInstrumentPlugin):
    module = "keyspilot"

    def __init__(self) -> None:
        super().__init__(InstrumentFamily.KEYS)


class GenericPlugin(PitchedInstrumentPlugin):
    module = "genericpilot"

    def __init__(self) -> None:
        super().__init__(InstrumentFamily.UNKNOWN)


class InstrumentPluginRegistry:
    """Explicit family-to-plugin mapping with truthful passthrough fallback."""

    def __init__(self, plugins: list[InstrumentPlugin]) -> None:
        self._plugins: dict[InstrumentFamily, InstrumentPlugin] = {}
        for plugin in plugins:
            if plugin.family in self._plugins:
                raise ValueError(f"Duplicate instrument plugin: {plugin.family.value}")
            self._plugins[plugin.family] = plugin

    @classmethod
    def default(
        cls,
        guitar_pipeline: RepairPipeline,
        drum_pipeline: DrumRepairPipeline,
    ) -> InstrumentPluginRegistry:
        return cls(
            [
                GuitarPlugin(guitar_pipeline),
                DrumPlugin(drum_pipeline),
                BassPlugin(),
                KeysPlugin(),
                GenericPlugin(),
            ]
        )

    @property
    def supported_families(self) -> frozenset[InstrumentFamily]:
        return frozenset(self._plugins)

    def route(self, family: InstrumentFamily, request: PluginRequest) -> RouteResult:
        plugin = self._plugins.get(family)
        if plugin is None:
            return route_passthrough(request.track, family)
        return plugin.repair(request)


__all__ = [
    "BassPlugin",
    "DrumPlugin",
    "GenericPlugin",
    "GuitarPlugin",
    "InstrumentPlugin",
    "InstrumentPluginRegistry",
    "KeysPlugin",
    "PitchedInstrumentPlugin",
    "PluginRequest",
]

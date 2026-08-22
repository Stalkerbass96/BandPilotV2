"""Drum repair pipeline orchestrator.

Executes the 8 drum stages in order, passing the DrumPipelineContext between
them. Stages S1 (Quantize) and S2 (MeasureSplit) reuse the existing guitar
pipeline stages since they operate on generic MIDI timing. Stages S3–S8 are
drum-specific.

Pipeline:
  S1 Quantize → S2 MeasureSplit → S3 DrumMap → S4 PatternDetect →
  S5 Velocity → S6 Sticking → S7 DrumNotation → S8 DrumAssemble
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from fretpilot.engine.drum_context import DrumPipelineContext
from fretpilot.engine.stages.drum_assemble import DrumAssembleStage
from fretpilot.engine.stages.drum_map import DrumMapStage
from fretpilot.engine.stages.drum_notation import DrumNotationStage
from fretpilot.engine.stages.measure_split import MeasureSplitStage
from fretpilot.engine.stages.pattern_detect import PatternDetectStage
from fretpilot.engine.stages.quantize import QuantizeStage
from fretpilot.engine.stages.sticking import StickingStage
from fretpilot.engine.stages.velocity import VelocityStage
from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.knowledge.registry import KnowledgeRegistry

logger = logging.getLogger("fretpilot.engine.drum_pipeline")


@runtime_checkable
class DrumPipelineStage(Protocol):
    """Protocol every drum pipeline stage must satisfy."""

    name: str

    def run(self, ctx: DrumPipelineContext) -> DrumPipelineContext: ...


class DrumRepairPipeline:
    """Orchestrates the 8-stage drum repair pipeline.

    Stages S1–S2 reuse the guitar QuantizeStage and MeasureSplitStage
    (generic MIDI timing). Stages S3–S8 are drum-specific. The assemble
    stage is special: after run(), its build_ir() produces the DrumProjectIR.
    """

    def __init__(self, engine: KnowledgeEngine) -> None:
        self._engine = engine
        self._assemble = DrumAssembleStage()
        self.stages: list[DrumPipelineStage] = [
            QuantizeStage(engine),       # S1 — reused from guitar
            MeasureSplitStage(),         # S2 — reused from guitar
            DrumMapStage(),              # S3 — drum-specific
            PatternDetectStage(),        # S4 — drum-specific
            VelocityStage(),             # S5 — drum-specific
            StickingStage(),             # S6 — drum-specific
            DrumNotationStage(),         # S7 — drum-specific
            self._assemble,              # S8 — drum-specific
        ]

    @property
    def registry(self) -> KnowledgeRegistry:
        """Expose the knowledge registry used by this pipeline."""
        return self._engine.registry

    def execute(self, ctx: DrumPipelineContext) -> DrumProjectIR:
        """Run all 8 stages in order and return the assembled DrumProjectIR.

        Args:
            ctx: The drum pipeline context initialized with the drum track
                and timeline.

        Returns:
            The assembled DrumProjectIR.
        """
        for stage in self.stages:
            logger.debug("Running drum stage: %s", stage.name)
            stage.run(ctx)
        return self._assemble.build_ir(ctx)


def create_drum_pipeline(knowledge_dir: str | None = None) -> DrumRepairPipeline:
    """Factory: build a drum pipeline with a KnowledgeRegistry from assets.

    Args:
        knowledge_dir: Path to the knowledge assets directory. If None,
            uses the default from application settings.

    Returns:
        A DrumRepairPipeline ready to execute.
    """
    if knowledge_dir:
        registry = KnowledgeRegistry.from_assets_dir(knowledge_dir)
    else:
        from fretpilot.config import get_settings

        registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
    engine = KnowledgeEngine(registry)
    return DrumRepairPipeline(engine)


__all__ = [
    "DrumPipelineStage",
    "DrumRepairPipeline",
    "create_drum_pipeline",
]

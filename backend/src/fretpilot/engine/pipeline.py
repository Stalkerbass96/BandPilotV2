"""Repair pipeline orchestrator.

Executes the 7 stages in order, passing the PipelineContext between them.
Each stage is an independent, testable unit. The orchestrator only sequences
and delegates — it contains no repair logic itself.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from fretpilot.engine.context import PipelineContext
from fretpilot.ir.models import GuitarProjectIR
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.knowledge.registry import KnowledgeRegistry

logger = logging.getLogger("fretpilot.engine.pipeline")


@runtime_checkable
class PipelineStage(Protocol):
    """Protocol every pipeline stage must satisfy."""

    name: str

    def run(self, ctx: PipelineContext) -> PipelineContext: ...


class RepairPipeline:
    """Orchestrates the 7-stage repair pipeline.

    Stages are constructed with a KnowledgeEngine so they can query KB assets.
    The assemble stage is special: after run(), its build_ir() produces the IR.
    """

    def __init__(self, engine: KnowledgeEngine) -> None:
        from fretpilot.engine.stages import (
            ArticulationStage,
            AssembleStage,
            FingeringStage,
            MeasureSplitStage,
            QuantizeStage,
            StreamSeparationStage,
            TieStage,
            VoiceStage,
        )

        self._engine = engine
        self._assemble = AssembleStage()
        self.stages: list[PipelineStage] = [
            QuantizeStage(engine),
            MeasureSplitStage(),
            TieStage(),
            VoiceStage(),
            StreamSeparationStage(engine),
            FingeringStage(engine),
            ArticulationStage(engine),
            self._assemble,
        ]

    @property
    def registry(self) -> KnowledgeRegistry:
        """Expose the knowledge registry used by this pipeline."""
        return self._engine.registry

    def execute(self, ctx: PipelineContext) -> GuitarProjectIR:
        """Run all stages in order and return the assembled IR."""
        for stage in self.stages:
            logger.debug("Running stage: %s", stage.name)
            stage.run(ctx)
        return self._assemble.build_ir(ctx)


def create_pipeline(knowledge_dir: str | None = None) -> RepairPipeline:
    """Factory: build a pipeline with a KnowledgeRegistry from assets."""
    if knowledge_dir:
        registry = KnowledgeRegistry.from_assets_dir(knowledge_dir)
    else:
        from fretpilot.config import get_settings

        registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
    engine = KnowledgeEngine(registry)
    return RepairPipeline(engine)


__all__ = ["PipelineStage", "RepairPipeline", "create_pipeline"]

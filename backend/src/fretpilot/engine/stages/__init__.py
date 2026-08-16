"""Pipeline stages package."""

from fretpilot.engine.stages.articulation import ArticulationStage
from fretpilot.engine.stages.assemble import AssembleStage
from fretpilot.engine.stages.fingering import FingeringStage
from fretpilot.engine.stages.measure_split import MeasureSplitStage
from fretpilot.engine.stages.quantize import QuantizeStage
from fretpilot.engine.stages.separation import StreamSeparationStage
from fretpilot.engine.stages.tie import TieStage
from fretpilot.engine.stages.voice import VoiceStage

__all__ = [
    "QuantizeStage",
    "MeasureSplitStage",
    "TieStage",
    "VoiceStage",
    "StreamSeparationStage",
    "FingeringStage",
    "ArticulationStage",
    "AssembleStage",
]

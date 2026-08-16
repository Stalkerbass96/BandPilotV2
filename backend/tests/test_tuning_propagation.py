"""End-to-end tuning propagation tests.

Verifies that a user-selected tuning (e.g. Drop A 7-string) is correctly
propagated through the entire pipeline:

1. ``knowledge.tunings.GuitarTuning.to_instrument_tuning()`` produces a
   ``guitar.instrument.GuitarTuning`` with matching string pitches and the
   correct string-numbering convention (1=highest, N=lowest).

2. The fingering stage uses ``ctx.tuning`` (when set) instead of always
   falling back to ``STANDARD_TUNING`` — notes that are unplayable on a
   6-string become playable on a 7-string Drop A tuning.

3. The assembled IR's ``tuning`` and ``fret_count`` fields reflect the
   selected tuning, not the hardcoded standard 6-string values.

4. Backward compatibility: when ``ctx.tuning`` is ``None``, the pipeline
   falls back to ``STANDARD_TUNING`` exactly as before.
"""

from __future__ import annotations

import pytest

from fretpilot.engine.context import PipelineContext
from fretpilot.engine.stages import (
    ArticulationStage,
    AssembleStage,
    FingeringStage,
    MeasureSplitStage,
    QuantizeStage,
    TieStage,
    VoiceStage,
)
from fretpilot.guitar.fretboard import candidate_positions
from fretpilot.guitar.instrument import STANDARD_TUNING, GuitarTuning as InstrumentTuning
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.knowledge.tunings import GuitarTuning, TuningRegistry
from fretpilot.midi.models import NormalizedTrack

from tests.conftest import _note, _timeline, _MockAdvisor


# ─── Helpers ───


def _build_ctx(
    notes=None,
    engine: KnowledgeEngine | None = None,
    style_label: str = "metal",
    fidelity: float = 0.5,
    tuning: GuitarTuning | None = None,
) -> PipelineContext:
    """Build a minimal PipelineContext for stage testing, with optional tuning."""
    if notes is None:
        notes = [
            _note(pitch=64, start_beat=0.0, duration_beats=0.5),
            _note(pitch=67, start_beat=0.5, duration_beats=0.5),
            _note(pitch=60, start_beat=1.0, duration_beats=1.0),
        ]
    timeline = _timeline(notes)
    if engine is None:
        from fretpilot.knowledge.registry import KnowledgeRegistry
        from fretpilot.config import get_settings

        registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
        engine = KnowledgeEngine(registry)

    track = (
        timeline.tracks[0]
        if timeline.tracks
        else NormalizedTrack(index=0, name="Empty", notes=[])
    )

    return PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=engine.registry,
        style_label=style_label,
        midi_fidelity=fidelity,
        advisor=_MockAdvisor(),
        track_role="lead",
        source_track_index=0,
        degraded_mode=False,
        tuning=tuning,
    )


def _run_full_pipeline(ctx: PipelineContext, engine: KnowledgeEngine):
    """Run all 7 stages and return the assembled IR."""
    QuantizeStage(engine).run(ctx)
    MeasureSplitStage().run(ctx)
    TieStage().run(ctx)
    VoiceStage().run(ctx)
    FingeringStage(engine).run(ctx)
    ArticulationStage(engine).run(ctx)
    assemble = AssembleStage()
    assemble.run(ctx)
    return assemble.build_ir(ctx)


def _default_registry() -> TuningRegistry:
    """Load the default tuning registry (12 tunings)."""
    return TuningRegistry.default()


# ─── Unit tests: to_instrument_tuning() adapter ───


class TestToInstrumentTuning:
    """Verify knowledge.tunings.GuitarTuning.to_instrument_tuning() conversion."""

    def test_standard_6_string_conversion(self) -> None:
        """Standard 6-string should convert to matching instrument tuning."""
        registry = _default_registry()
        standard_6 = registry.get("standard_6")
        assert standard_6 is not None

        inst = standard_6.to_instrument_tuning()

        assert isinstance(inst, InstrumentTuning)
        assert inst.string_count == 6
        assert inst.fret_count == 24
        # open_pitches returns low → high, matching string_pitches.
        assert inst.open_pitches == standard_6.string_pitches
        # String 1 = highest (E4=64), string 6 = lowest (E2=40).
        assert inst.pitch_for_string(1) == 64
        assert inst.pitch_for_string(6) == 40

    def test_drop_a_7_string_conversion(self) -> None:
        """Drop A 7-string should convert with correct string numbering."""
        registry = _default_registry()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None
        assert drop_a_7.string_pitches == [33, 40, 45, 50, 55, 59, 64]

        inst = drop_a_7.to_instrument_tuning()

        assert inst.string_count == 7
        assert inst.fret_count == 24
        # open_pitches low → high matches string_pitches.
        assert inst.open_pitches == [33, 40, 45, 50, 55, 59, 64]
        # String 1 = highest (E4=64), string 7 = lowest (A1=33).
        assert inst.pitch_for_string(1) == 64
        assert inst.pitch_for_string(7) == 33

    def test_standard_8_string_conversion(self) -> None:
        """Standard 8-string should convert with 8 strings."""
        registry = _default_registry()
        standard_8 = registry.get("standard_8")
        assert standard_8 is not None

        inst = standard_8.to_instrument_tuning()

        assert inst.string_count == 8
        assert inst.pitch_for_string(1) == 64   # E4
        assert inst.pitch_for_string(8) == 30   # F#1

    def test_custom_fret_count(self) -> None:
        """The fret_count parameter should be respected."""
        registry = _default_registry()
        standard_6 = registry.get("standard_6")
        assert standard_6 is not None

        inst = standard_6.to_instrument_tuning(fret_count=22)
        assert inst.fret_count == 22

    def test_open_strings_matches_standard_tuning_constant(self) -> None:
        """Converted standard_6 open_strings must match guitar.instrument.STANDARD_TUNING."""
        registry = _default_registry()
        standard_6 = registry.get("standard_6")
        assert standard_6 is not None

        inst = standard_6.to_instrument_tuning()

        # The open_strings tuple should be identical to the hardcoded constant.
        assert inst.open_strings == STANDARD_TUNING.open_strings

    def test_candidate_positions_with_drop_a_7(self) -> None:
        """Pitch 33 (A1) should be playable on Drop A 7-string but not standard 6-string."""
        registry = _default_registry()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        inst = drop_a_7.to_instrument_tuning()

        # Pitch 33 = open string 7 on Drop A.
        positions = candidate_positions(33, tuning=inst, max_fret=24)
        assert len(positions) >= 1
        assert any(p.string == 7 and p.fret == 0 for p in positions)

        # With standard 6-string tuning, pitch 33 is unplayable.
        std_positions = candidate_positions(33, tuning=STANDARD_TUNING, max_fret=24)
        assert len(std_positions) == 0


# ─── Integration tests: pipeline with non-standard tuning ───


class TestPipelineTuningPropagation:
    """Verify tuning propagates through the full pipeline to the IR."""

    def test_ir_tuning_matches_drop_a_7(self, engine: KnowledgeEngine) -> None:
        """IR tuning field should reflect Drop A 7-string, not standard 6-string."""
        registry = _default_registry()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        notes = [
            _note(pitch=64, start_beat=0.0, duration_beats=0.5),
            _note(pitch=60, start_beat=0.5, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=drop_a_7)
        ir = _run_full_pipeline(ctx, engine)

        assert ir.tracks[0].tuning == drop_a_7.string_pitches
        assert ir.tracks[0].fret_count == 24
        # Must NOT be the standard 6-string pitches.
        assert ir.tracks[0].tuning != STANDARD_TUNING.open_pitches

    def test_ir_tuning_defaults_to_standard_when_none(self, engine: KnowledgeEngine) -> None:
        """When ctx.tuning is None, IR should use standard 6-string tuning."""
        notes = [
            _note(pitch=64, start_beat=0.0, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=None)
        ir = _run_full_pipeline(ctx, engine)

        assert ir.tracks[0].tuning == STANDARD_TUNING.open_pitches
        assert ir.tracks[0].fret_count == STANDARD_TUNING.fret_count

    def test_low_pitch_playable_with_drop_a_7(self, engine: KnowledgeEngine) -> None:
        """Pitch 33 should get a fingering with Drop A 7-string (unplayable on standard)."""
        registry = _default_registry()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        notes = [
            _note(pitch=33, start_beat=0.0, duration_beats=1.0),  # A1 — only on 7-string
            _note(pitch=64, start_beat=1.0, duration_beats=0.5),  # E4 — on any tuning
        ]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=drop_a_7)
        _run_full_pipeline(ctx, engine)

        # The A1 note (pitch 33) should have a valid string/fret assignment.
        low_note = next(n for n in ctx.fingered_notes if n.pitch == 33)
        assert low_note.string is not None
        assert low_note.fret is not None
        assert low_note.string == 7   # open string 7
        assert low_note.fret == 0

    def test_low_pitch_unplayable_with_standard(self, engine: KnowledgeEngine) -> None:
        """Pitch 33 should be unplayable (string/fret=None, voice=2) with standard tuning."""
        notes = [
            _note(pitch=33, start_beat=0.0, duration_beats=1.0),  # A1 — below range
            _note(pitch=64, start_beat=1.0, duration_beats=0.5),  # E4 — playable
        ]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=None)
        _run_full_pipeline(ctx, engine)

        low_note = next(n for n in ctx.fingered_notes if n.pitch == 33)
        assert low_note.string is None
        assert low_note.fret is None
        assert low_note.voice == 2  # unplayable notes go to voice 2

    def test_fingering_differs_between_tunings(self, engine: KnowledgeEngine) -> None:
        """Same notes should produce different fingering with Drop A vs standard."""
        registry = _default_registry()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        notes = [
            _note(pitch=33, start_beat=0.0, duration_beats=1.0),
            _note(pitch=40, start_beat=1.0, duration_beats=0.5),
        ]

        # With Drop A 7-string: pitch 33 is playable (string 7, fret 0).
        ctx_drop_a = _build_ctx(notes=notes, engine=engine, tuning=drop_a_7)
        _run_full_pipeline(ctx_drop_a, engine)

        # With standard 6-string: pitch 33 is unplayable.
        ctx_std = _build_ctx(notes=notes, engine=engine, tuning=None)
        _run_full_pipeline(ctx_std, engine)

        drop_a_low = next(n for n in ctx_drop_a.fingered_notes if n.pitch == 33)
        std_low = next(n for n in ctx_std.fingered_notes if n.pitch == 33)

        assert drop_a_low.string is not None  # playable on Drop A
        assert std_low.string is None          # unplayable on standard

    def test_drop_d_6_string_ir_tuning(self, engine: KnowledgeEngine) -> None:
        """Drop D 6-string should produce IR with correct pitches (38 instead of 40 on low E)."""
        registry = _default_registry()
        drop_d = registry.get("drop_d_6")
        assert drop_d is not None
        assert drop_d.string_pitches == [38, 45, 50, 55, 59, 64]

        notes = [_note(pitch=38, start_beat=0.0, duration_beats=0.5)]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=drop_d)
        ir = _run_full_pipeline(ctx, engine)

        assert ir.tracks[0].tuning == [38, 45, 50, 55, 59, 64]
        # Pitch 38 = open string 6 on Drop D.
        note = next(n for n in ctx.fingered_notes if n.pitch == 38)
        assert note.string == 6
        assert note.fret == 0

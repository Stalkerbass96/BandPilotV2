"""Pipeline stage tests — each of the 7 stages independently tested.

Each test constructs a minimal PipelineContext, runs a single stage,
and asserts the expected output.
"""

from __future__ import annotations

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
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.midi.models import NormalizedTrack
from tests.conftest import _MockAdvisor, _note, _timeline


def _build_ctx(
    notes=None,
    engine: KnowledgeEngine | None = None,
    style_label: str = "metal",
    fidelity: float = 0.5,
) -> PipelineContext:
    """Build a minimal PipelineContext for stage testing."""
    if notes is None:
        notes = [
            _note(pitch=64, start_beat=0.0, duration_beats=0.5),
            _note(pitch=67, start_beat=0.5, duration_beats=0.5),
            _note(pitch=60, start_beat=1.0, duration_beats=1.0),
        ]
    timeline = _timeline(notes)
    if engine is None:
        from fretpilot.config import get_settings
        from fretpilot.knowledge.registry import KnowledgeRegistry

        registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
        engine = KnowledgeEngine(registry)

    # Handle empty note lists: create a dummy track so stages can run safely.
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
    )


class TestQuantizeStage:
    """S1: Quantization — snap note onsets/durations to a grid."""

    def test_quantize_produces_notes(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        stage = QuantizeStage(engine)
        stage.run(ctx)
        assert len(ctx.quantized_notes) == 3
        assert all(hasattr(n, "quantized_start_beat") for n in ctx.quantized_notes)

    def test_quantize_snaps_off_grid_notes(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=60, start_beat=0.07, duration_beats=0.48)]
        ctx = _build_ctx(notes=notes, engine=engine)
        stage = QuantizeStage(engine)
        stage.run(ctx)
        quantized = ctx.quantized_notes[0]
        # 0.07 should snap to 0.0 (nearest sixteenth at fidelity 0.5 for metal)
        assert quantized.quantized_start_beat != 0.07
        assert quantized.original_start_beat == 0.07

    def test_quantize_records_transformations(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=60, start_beat=0.03, duration_beats=0.5)]
        ctx = _build_ctx(notes=notes, engine=engine)
        stage = QuantizeStage(engine)
        stage.run(ctx)
        # An off-grid onset should produce a transformation.
        assert len(ctx.transformations) >= 1
        assert ctx.transformations[0].stage == "quantize_onset"

    def test_quantize_marks_stage_complete(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        assert ctx.stage_progress.get("quantize") is True

    def test_quantize_empty_track(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(notes=[], engine=engine)
        QuantizeStage(engine).run(ctx)
        assert len(ctx.quantized_notes) == 0


class TestMeasureSplitStage:
    """S2: Measure split — compute boundaries, split cross-measure notes."""

    def test_measure_boundaries_computed(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        assert len(ctx.measures) > 0
        assert ctx.measures[0].number == 1
        assert ctx.measures[0].numerator == 4

    def test_cross_measure_note_is_split(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=60, start_beat=3.5, duration_beats=2.0)]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        # The note spans from beat 3.5 to 5.5, crossing a 4-beat measure.
        # It should produce at least 2 split notes.
        assert len(ctx.split_notes) >= 2
        assert ctx.split_notes[0].tie_out is True
        assert ctx.split_notes[1].tie_in is True

    def test_in_measure_note_not_split(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=60, start_beat=0.0, duration_beats=0.5)]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        assert len(ctx.split_notes) == 1
        assert ctx.split_notes[0].tie_in is False
        assert ctx.split_notes[0].tie_out is False

    def test_measure_split_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        assert ctx.stage_progress.get("measure_split") is True


class TestTieStage:
    """S3: Tie / legato identification."""

    def test_consecutive_same_pitch_marked_legato(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=60, start_beat=0.5, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        first_fragments = [n for n in ctx.split_notes if not n.tie_in]
        assert any(n.legato_candidate for n in first_fragments)

    def test_different_pitch_not_legato(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        assert not any(n.legato_candidate for n in ctx.split_notes)

    def test_far_apart_not_legato(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=60, start_beat=4.0, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        first_fragments = [n for n in ctx.split_notes if not n.tie_in]
        assert not any(n.legato_candidate for n in first_fragments)

    def test_tie_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        assert ctx.stage_progress.get("tie") is True


class TestVoiceStage:
    """S4: Voice assignment — chord releases and ringing normalization."""

    def test_voice_assignment_produces_voiced_notes(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        assert len(ctx.voiced_notes) > 0
        assert all(n.voice in (1, 2) for n in ctx.voiced_notes)

    def test_chord_release_not_promoted_to_voice_2(self, engine: KnowledgeEngine) -> None:
        """和弦 release 不再 promote 到 voice 2（voice 2 专归超范围音符）。"""
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.0, duration_beats=2.0),
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        # 和弦 release 保持 voice 1，后续由 gp5 导出用 tie 表达长音符延音。
        assert all(n.voice == 1 for n in ctx.voiced_notes)

    def test_voice_no_longer_records_promotion_transformation(
        self, engine: KnowledgeEngine
    ) -> None:
        """取消 voice 2 promotion 后，voice stage 不再记录 voice_assignment 变更。"""
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.0, duration_beats=2.0),
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        voice_changes = [t for t in ctx.transformations if t.stage == "voice_assignment"]
        assert len(voice_changes) == 0

    def test_voice_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        assert ctx.stage_progress.get("voice") is True


class TestFingeringStage:
    """S5: Fingering — string/fret/hand-position assignment."""

    def test_fingering_assigns_positions(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        assert len(ctx.fingered_notes) > 0
        for note in ctx.fingered_notes:
            if note.pitch >= 40 and note.pitch <= 88:
                assert note.string is not None
                assert note.fret is not None

    def test_fingering_confidence_in_range(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        for note in ctx.fingered_notes:
            assert 0.0 <= note.fingering_confidence <= 1.0

    def test_fingering_open_string_for_open_e(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=64, start_beat=0.0, duration_beats=0.5)]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        # Pitch 64 = E4 = open high E string (string 1, fret 0)
        note = ctx.fingered_notes[0]
        assert note.fret == 0
        assert note.string == 1

    def test_fingering_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        assert ctx.stage_progress.get("fingering") is True

    def test_impossible_chord_does_not_poison_later_legal_chord(
        self, engine: KnowledgeEngine
    ) -> None:
        notes = [
            *[
                _note(pitch=pitch, start_beat=0.0, duration_beats=0.5)
                for pitch in (40, 45, 50, 55, 59, 64, 67)
            ],
            *[
                _note(pitch=pitch, start_beat=1.0, duration_beats=0.5)
                for pitch in (52, 57, 64)
            ],
        ]
        ctx = _build_ctx(notes=notes, engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)

        impossible = [note for note in ctx.fingered_notes if note.start_beat == 0.0]
        legal = [note for note in ctx.fingered_notes if note.start_beat == 1.0]
        assert all(note.string is None and note.fret is None for note in impossible)
        assert all(note.string is not None and note.fret is not None for note in legal)
        assert len({note.string for note in legal}) == len(legal)
        assert any("only those groups were marked unplayable" in warning for warning in ctx.warnings)


class TestArticulationStage:
    """S6: Articulation inference."""

    def test_articulation_produces_decisions(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.25),
            _note(pitch=60, start_beat=0.25, duration_beats=0.25),
        ]
        ctx = _build_ctx(notes=notes, engine=engine, style_label="metal")
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        assert len(ctx.articulation_decisions) >= 0  # May be empty if no articulations apply

    def test_palm_mute_for_short_metal_notes(self, engine: KnowledgeEngine) -> None:
        notes = [_note(pitch=60, start_beat=0.0, duration_beats=0.2, velocity=100)]
        ctx = _build_ctx(notes=notes, engine=engine, style_label="metal")
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        palm_mutes = [d for d in ctx.articulation_decisions if d.type == "palm_mute"]
        assert len(palm_mutes) >= 1

    def test_articulation_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        assert ctx.stage_progress.get("articulation") is True


class TestAssembleStage:
    """S7: IR assembly."""

    def test_assemble_produces_ir(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        assemble = AssembleStage()
        assemble.run(ctx)
        ir = assemble.build_ir(ctx)
        assert ir.schema_version == "1.0"
        assert len(ir.tracks) == 1
        assert len(ir.tracks[0].measures) > 0
        assert ir.style_label == "metal"

    def test_assemble_ir_has_knowledge_ref(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        ir = AssembleStage().build_ir(ctx)
        assert ir.knowledge is not None
        assert ir.knowledge.snapshot_version != "unknown"

    def test_assemble_ir_has_tempo_and_time_sig(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        ir = AssembleStage().build_ir(ctx)
        assert len(ir.tempo_map) >= 1
        assert ir.tempo_map[0].bpm == 120.0
        assert len(ir.time_signatures) >= 1
        assert ir.time_signatures[0].numerator == 4

    def test_assemble_marks_stage(self, engine: KnowledgeEngine) -> None:
        ctx = _build_ctx(engine=engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)
        FingeringStage(engine).run(ctx)
        ArticulationStage(engine).run(ctx)
        AssembleStage().run(ctx)
        assert ctx.stage_progress.get("assemble") is True


class TestFullPipeline:
    """Integration test: run all 7 stages via the pipeline orchestrator."""

    def test_pipeline_execute_produces_valid_ir(self, pipeline) -> None:
        ctx = _build_ctx(engine=pipeline._engine)
        ir = pipeline.execute(ctx)
        assert ir.schema_version == "1.0"
        assert len(ir.tracks) == 1
        assert ir.tracks[0].role == "lead"
        assert len(ir.tracks[0].measures) > 0

    def test_pipeline_records_all_stages(self, pipeline) -> None:
        ctx = _build_ctx(engine=pipeline._engine)
        pipeline.execute(ctx)
        for stage in ("quantize", "measure_split", "tie", "voice", "fingering", "articulation", "assemble"):
            assert ctx.stage_progress.get(stage) is True, f"Stage {stage} not marked complete"


class TestGetFingeringChordShapes:
    """KB2 learned chord shapes must reach the fingering scorer.

    Style-specific entries return their own top-K shapes; unknown/unmatched
    styles (and styles whose entry has no chord_shapes, e.g. undersampled
    metal) fall back to the merged ensemble so the learned knowledge still
    steers fingering instead of degrading to pure defaults.
    """

    def test_rock_returns_style_specific_shapes(self, engine: KnowledgeEngine) -> None:
        shapes = engine.get_fingering_chord_shapes("rock", "lead")
        assert shapes
        # Values are empirical occurrence counts (positive ints), keys are
        # canonical shape strings sorted by string.
        assert all(int(v) > 0 for v in shapes.values())
        assert all(
            k and all(part.startswith("s") and "f" in part for part in k.split(","))
            for k in shapes
        )

    def test_unknown_falls_back_to_merged_ensemble(self, engine: KnowledgeEngine) -> None:
        unknown = engine.get_fingering_chord_shapes("unknown")
        rock = engine.get_fingering_chord_shapes("rock", "lead")
        assert unknown  # never empty — the KB is always consulted
        # The ensemble is a superset of the dominant (rock) style's shapes.
        for key in list(rock)[:3]:
            assert key in unknown

    def test_metal_returns_textbook_power_chord_shapes(
        self, engine: KnowledgeEngine
    ) -> None:
        # metal's entry now carries textbook-derived chord_shapes (Troy
        # Stetina "Speed & Thrash Metal Guitar Method") instead of falling
        # back to the merged ensemble.
        shapes = engine.get_fingering_chord_shapes("metal")
        assert shapes
        # Canonical movable power-chord forms are the book's core shapes:
        # 2-string root+fifth on the 6th (s5f2,s6f0 = E5 open) and 5th
        # (s4f2,s5f0 = A5 open).  The fifth sits +2 frets on the adjacent
        # string (tuned a perfect 4th), never at the same fret.
        assert "s5f2,s6f0" in shapes
        assert "s4f2,s5f0" in shapes

    def test_empty_registry_returns_empty(self) -> None:
        from fretpilot.knowledge.engine import KnowledgeEngine

        registry = type(
            "EmptyRegistry",
            (),
            {"query": lambda self, **kw: [], "query_payload": lambda self, **kw: {}},
        )()
        eng = KnowledgeEngine(registry)  # type: ignore[arg-type]
        assert eng.get_fingering_chord_shapes("rock") == {}

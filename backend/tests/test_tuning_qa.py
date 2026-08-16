"""QA edge-case tests for tuning propagation.

These tests complement ``test_tuning_propagation.py`` with targeted edge cases
that the original 12 tests do not cover:

1. Drop D makes a low D2 (pitch 38) playable on the open 6th string where
   standard tuning cannot reach it at all.
2. An 8-string tuning extends the playable range below E2 (pitch 33 / A1).
3. Backward compatibility: ``ctx.tuning is None`` falls back to standard
   6-string tuning in both the fingering stage and the assembled IR.
4. The GP5 exporter declares the correct string *count* for a 7-string
   tuning (not the hardcoded 6).
5. The GP5 exporter declares the correct string *pitches* for Drop D
   ([38, 45, 50, 55, 59, 64], not standard [40, ...]).
6. Full pipeline on the Tokyo Midnight dirty sample with Drop A 7-string:
   the IR tuning matches and fewer notes go out of range than with the
   standard 6-string tuning.
"""

from __future__ import annotations

from pathlib import Path

import guitarpro as gp
import pytest

from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.engine.stages import (
    ArticulationStage,
    AssembleStage,
    FingeringStage,
    MeasureSplitStage,
    QuantizeStage,
    TieStage,
    VoiceStage,
)
from fretpilot.exporters.gp5 import GP5Exporter
from fretpilot.guitar.fretboard import candidate_positions
from fretpilot.guitar.instrument import STANDARD_TUNING
from fretpilot.ir.models import (
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRFingering,
    IRTempoEvent,
    IRTimeSignatureEvent,
    PerformanceTiming,
    ScoreTiming,
)
from fretpilot.knowledge.tunings import TuningRegistry
from fretpilot.midi.models import NormalizedTrack
from fretpilot.midi.parser import load_midi

from tests.conftest import _MockAdvisor, _note, _timeline

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


# --- Shared helpers ---------------------------------------------------------


def _build_ctx(notes, engine, tuning=None):
    """Build a minimal PipelineContext with an optional knowledge tuning."""
    timeline = _timeline(notes)
    track = (
        timeline.tracks[0]
        if timeline.tracks
        else NormalizedTrack(index=0, name="Empty", notes=[])
    )
    return PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=engine.registry,
        style_label="metal",
        midi_fidelity=0.5,
        advisor=_MockAdvisor(),
        track_role="lead",
        source_track_index=0,
        degraded_mode=False,
        tuning=tuning,
    )


def _run_full_pipeline(ctx, engine):
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


def _make_event(idx, pitch, start, duration, voice, string, fret):
    """Build a single GuitarNoteEvent for GP5 export tests."""
    return GuitarNoteEvent(
        id=f"n-{idx + 1:05d}",
        source_note_index=idx,
        pitch=pitch,
        score=ScoreTiming(
            start_beat=start,
            duration_beats=duration,
            measure_number=1,
            beat_in_measure=start,
            voice=voice,
        ),
        performance=PerformanceTiming(
            source_start_beat=start,
            source_duration_beats=duration,
            velocity=80,
        ),
        fingering=IRFingering(string=string, fret=fret),
    )


def _make_ir_with_tuning(events, tuning_pitches, fret_count=24):
    """Build a one-track, one-measure IR with a custom tuning."""
    measure = GuitarMeasure(
        number=1,
        start_beat=0.0,
        duration_beats=4.0,
        numerator=4,
        denominator=4,
        events=events,
    )
    track = GuitarTrackIR(
        id="guitar-1",
        name="Test",
        source_track_index=0,
        role="lead",
        tuning=list(tuning_pitches),
        fret_count=fret_count,
        measures=[measure],
    )
    return GuitarProjectIR(
        title="TuningQA",
        source="test.mid",
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)],
        tracks=[track],
    )


def _export_and_parse(ir, tmp_path, name="out.gp5"):
    """Export IR to GP5 and parse it back, returning ``(result, song)``."""
    out = tmp_path / name
    result = GP5Exporter().export(ir, out)
    with open(out, "rb") as f:
        song = gp.parse(f)
    return result, song


def _string_pitches_low_to_high(song):
    """Return the parsed track's open-string pitches sorted low -> high."""
    return sorted(s.value for s in song.tracks[0].strings)


def _tokyo_cleaned_track(timeline):
    """parse -> detect -> cleanup -> build a NormalizedTrack from primary stream."""
    from fretpilot.detection import classify_timeline, resolve_streams
    from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams

    report = classify_timeline(timeline)
    assert report.primary_guitar_track_index is not None
    streams = resolve_streams(timeline)
    tuning = auto_detect_tuning(streams)
    clean_result = cleanup_streams(streams, timeline=timeline, tuning=tuning)
    assert clean_result.streams, "cleanup should retain at least one stream"
    primary_stream = max(clean_result.streams, key=lambda s: s.note_count)
    cleaned_track = NormalizedTrack(
        index=report.primary_guitar_track_index or 0,
        name=primary_stream.track_name,
        notes=list(primary_stream.notes),
        instrument_name=primary_stream.instrument_name,
        program=primary_stream.program,
    )
    role = (
        report.primary_classification.guitar_role
        if report.primary_classification
        else "unknown"
    )
    return cleaned_track, role


def _count_unplayable(ir):
    """Count IR note events whose fingering is unplayable (string/fret None)."""
    return sum(
        1
        for track in ir.tracks
        for measure in track.measures
        for event in measure.events
        if not event.fingering.playable
    )


# --- 1. Drop D fingering divergence ----------------------------------------


class TestDropDFingeringDivergence:
    """Drop D makes D2 (pitch 38) playable where standard cannot reach it."""

    def test_d2_open_on_drop_d_string6(self) -> None:
        """Pitch 38 (D2) is playable on string 6 fret 0 with Drop D."""
        registry = TuningRegistry.default()
        drop_d = registry.get("drop_d_6")
        assert drop_d is not None

        inst = drop_d.to_instrument_tuning()
        positions = candidate_positions(38, tuning=inst, max_fret=24)
        assert any(p.string == 6 and p.fret == 0 for p in positions)

    def test_d2_unplayable_on_standard(self) -> None:
        """Pitch 38 (D2) is unplayable on standard 6-string (below low E2=40)."""
        positions = candidate_positions(38, tuning=STANDARD_TUNING, max_fret=24)
        assert positions == []

    def test_drop_d_vs_standard_pipeline_fingering(self, engine) -> None:
        """Same D2 note: playable (string 6, fret 0) on Drop D, dropped on standard."""
        registry = TuningRegistry.default()
        drop_d = registry.get("drop_d_6")
        assert drop_d is not None

        notes = [_note(pitch=38, start_beat=0.0, duration_beats=1.0)]

        ctx_drop_d = _build_ctx(notes=notes, engine=engine, tuning=drop_d)
        _run_full_pipeline(ctx_drop_d, engine)
        drop_d_note = next(n for n in ctx_drop_d.fingered_notes if n.pitch == 38)
        assert drop_d_note.string == 6
        assert drop_d_note.fret == 0
        assert drop_d_note.voice == 1

        ctx_std = _build_ctx(notes=notes, engine=engine, tuning=None)
        _run_full_pipeline(ctx_std, engine)
        std_note = next(n for n in ctx_std.fingered_notes if n.pitch == 38)
        assert std_note.string is None
        assert std_note.fret is None
        assert std_note.voice == 2


# --- 2. 8-string extended range -------------------------------------------


class TestEightStringExtendedRange:
    """An 8-string tuning plays pitches below E2 that a 6-string cannot."""

    def test_a1_playable_on_standard_8(self) -> None:
        """Pitch 33 (A1) is playable on standard 8-string (string 8, fret 3)."""
        registry = TuningRegistry.default()
        standard_8 = registry.get("standard_8")
        assert standard_8 is not None

        inst = standard_8.to_instrument_tuning()
        positions = candidate_positions(33, tuning=inst, max_fret=24)
        assert positions, "A1 should be playable on an 8-string"
        assert any(p.string == 8 and p.fret == 3 for p in positions)

    def test_a1_unplayable_on_standard_6(self) -> None:
        """Pitch 33 (A1) is unplayable on standard 6-string."""
        positions = candidate_positions(33, tuning=STANDARD_TUNING, max_fret=24)
        assert positions == []

    def test_standard_8_pipeline_plays_a1(self, engine) -> None:
        """Pitch 33 gets a real fingering with standard_8 (unplayable on 6)."""
        registry = TuningRegistry.default()
        standard_8 = registry.get("standard_8")
        assert standard_8 is not None

        notes = [
            _note(pitch=33, start_beat=0.0, duration_beats=1.0),
            _note(pitch=64, start_beat=1.0, duration_beats=0.5),
        ]

        ctx_8 = _build_ctx(notes=notes, engine=engine, tuning=standard_8)
        _run_full_pipeline(ctx_8, engine)
        a1 = next(n for n in ctx_8.fingered_notes if n.pitch == 33)
        assert a1.string is not None
        assert a1.fret is not None
        assert a1.voice == 1

        ctx_6 = _build_ctx(notes=notes, engine=engine, tuning=None)
        _run_full_pipeline(ctx_6, engine)
        a1_std = next(n for n in ctx_6.fingered_notes if n.pitch == 33)
        assert a1_std.string is None
        assert a1_std.fret is None
        assert a1_std.voice == 2


# --- 3. Backward compatibility: tuning=None --------------------------------


class TestBackwardCompatNoneTuning:
    """ctx.tuning is None -> standard 6-string in fingering and IR."""

    def test_none_tuning_uses_standard_ir(self, engine) -> None:
        """IR tuning defaults to standard 6-string when ctx.tuning is None."""
        notes = [_note(pitch=64, start_beat=0.0, duration_beats=0.5)]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=None)
        ir = _run_full_pipeline(ctx, engine)

        assert ir.tracks[0].tuning == STANDARD_TUNING.open_pitches
        assert ir.tracks[0].fret_count == STANDARD_TUNING.fret_count

    def test_none_tuning_unplayable_below_e2(self, engine) -> None:
        """With tuning=None, a sub-E2 pitch is unplayable (standard behaviour)."""
        notes = [
            _note(pitch=38, start_beat=0.0, duration_beats=1.0),
            _note(pitch=64, start_beat=1.0, duration_beats=0.5),
        ]
        ctx = _build_ctx(notes=notes, engine=engine, tuning=None)
        _run_full_pipeline(ctx, engine)

        low = next(n for n in ctx.fingered_notes if n.pitch == 38)
        assert low.string is None
        assert low.fret is None
        assert low.voice == 2


# --- 4 & 5. GP5 export string count and pitches ----------------------------


class TestGP5ExportTuningStrings:
    """The GP5 exporter writes the IR's tuning, not a hardcoded 6-string."""

    def test_gp5_seven_strings_for_drop_a_7(self, tmp_path: Path) -> None:
        """A 7-string IR exports a .gp5 with 7 strings (not 6)."""
        drop_a_7_pitches = [33, 40, 45, 50, 55, 59, 64]
        events = [_make_event(0, 64, 0.0, 1.0, voice=1, string=1, fret=0)]
        ir = _make_ir_with_tuning(events, drop_a_7_pitches)

        _, song = _export_and_parse(ir, tmp_path, "seven.gp5")

        assert len(song.tracks[0].strings) == 7
        pitches = _string_pitches_low_to_high(song)
        assert pitches == drop_a_7_pitches
        # Bonus: the fret count is also propagated.
        assert song.tracks[0].fretCount == 24

    def test_gp5_drop_d_pitches(self, tmp_path: Path) -> None:
        """Drop D exports string pitches [38, 45, 50, 55, 59, 64], not standard."""
        drop_d_pitches = [38, 45, 50, 55, 59, 64]
        standard_pitches = [40, 45, 50, 55, 59, 64]
        events = [_make_event(0, 38, 0.0, 1.0, voice=1, string=6, fret=0)]
        ir = _make_ir_with_tuning(events, drop_d_pitches)

        _, song = _export_and_parse(ir, tmp_path, "dropd.gp5")

        pitches = _string_pitches_low_to_high(song)
        assert pitches == drop_d_pitches
        assert pitches != standard_pitches
        # The lowest string (number 6) must carry pitch 38 (D2), not 40 (E2).
        lowest = min(song.tracks[0].strings, key=lambda s: s.value)
        assert lowest.value == 38
        assert lowest.number == 6


# --- 6. Full pipeline on Tokyo Midnight with Drop A 7-string ----------------


class TestTokyoMidnightDropA7Pipeline:
    """Tokyo Midnight with Drop A 7-string: IR matches, fewer out-of-range."""

    def test_drop_a_7_ir_tuning_matches(self) -> None:
        """IR tuning reflects Drop A 7-string, not standard 6-string."""
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _tokyo_cleaned_track(timeline)

        registry = TuningRegistry.default()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        pipeline = create_pipeline()
        ctx = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label="unknown",
            midi_fidelity=0.5,
            advisor=None,
            track_role=role,
            source_track_index=cleaned_track.index,
            degraded_mode=True,
            tuning=drop_a_7,
        )
        ir = pipeline.execute(ctx)

        assert ir.tracks[0].tuning == drop_a_7.string_pitches
        assert ir.tracks[0].tuning != STANDARD_TUNING.open_pitches

    def test_drop_a_7_fewer_out_of_range_than_standard(self) -> None:
        """Drop A 7-string yields fewer unplayable notes than standard 6-string."""
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _tokyo_cleaned_track(timeline)

        # Precondition: the sample must contain pitches only a 7-string can play
        # (33-39), otherwise the comparison would be meaningless.
        all_pitches = [n.pitch for n in cleaned_track.notes]
        extended_range = [p for p in all_pitches if 33 <= p <= 39]
        assert extended_range, (
            "precondition: sample must contain pitches playable only on 7-string"
        )

        registry = TuningRegistry.default()
        drop_a_7 = registry.get("drop_a_7")
        assert drop_a_7 is not None

        pipeline = create_pipeline()

        ctx_drop_a = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label="unknown",
            midi_fidelity=0.5,
            advisor=None,
            track_role=role,
            source_track_index=cleaned_track.index,
            degraded_mode=True,
            tuning=drop_a_7,
        )
        ir_drop_a = pipeline.execute(ctx_drop_a)
        drop_a_unplayable = _count_unplayable(ir_drop_a)

        ctx_std = PipelineContext(
            timeline=timeline,
            track=cleaned_track,
            knowledge=pipeline.registry,
            style_label="unknown",
            midi_fidelity=0.5,
            advisor=None,
            track_role=role,
            source_track_index=cleaned_track.index,
            degraded_mode=True,
            tuning=None,
        )
        ir_std = pipeline.execute(ctx_std)
        std_unplayable = _count_unplayable(ir_std)

        # Both contain some out-of-range notes (pitch 31 & 89 are out of reach
        # even for Drop A 7-string).
        assert drop_a_unplayable > 0
        assert std_unplayable > 0
        # Drop A 7-string strictly fewer: pitches 33-39 become playable.
        assert drop_a_unplayable < std_unplayable

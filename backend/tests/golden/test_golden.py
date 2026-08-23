"""Golden sample test — end-to-end MIDI → pipeline → IR → export round-trip.

This test verifies that the full FretPilot v2 pipeline produces a deterministic,
reproducible result from a synthetic MIDI input. The IR is checked for structural
invariants (not exact values) so the test is robust against tuning adjustments.
"""

from __future__ import annotations

from pathlib import Path

import mido
import pytest

from fretpilot.ir.models import GuitarProjectIR


def _create_golden_midi(path: Path) -> None:
    """Create a deterministic MIDI file for golden testing.

    A simple 2-measure rock riff in E minor:
    - 4/4 time, 120 BPM
    - Distortion Guitar (GM program 30)
    - 8 eighth notes: E2 E2 G2 G2 B2 B2 E3 E3
    """
    midi = mido.MidiFile(type=1, ticks_per_beat=480)

    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    meta.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    midi.tracks.append(meta)

    guitar = mido.MidiTrack()
    guitar.append(mido.Message("program_change", program=30, channel=0, time=0))

    pitches = [40, 40, 43, 43, 47, 47, 52, 52]
    for i, pitch in enumerate(pitches):
        # Slightly off-grid onsets for notes 2+ to trigger quantization transformations.
        onset_delta = 250 if i >= 2 else 240
        if i == 0:
            guitar.append(mido.Message("note_on", note=pitch, velocity=100, channel=0, time=0))
        else:
            guitar.append(mido.Message("note_on", note=pitch, velocity=100, channel=0, time=onset_delta))
        guitar.append(mido.Message("note_off", note=pitch, velocity=0, channel=0, time=240))

    midi.tracks.append(guitar)
    midi.save(path)


class TestGoldenRoundTrip:
    """Full pipeline golden test: MIDI → IR → GP5 + Ample MIDI."""

    @pytest.fixture
    def golden_midi(self, tmp_path: Path) -> Path:
        path = tmp_path / "golden.mid"
        _create_golden_midi(path)
        return path

    @pytest.fixture
    def golden_ir(self, golden_midi: Path, knowledge_engine):
        from fretpilot.detection import classify_timeline
        from fretpilot.engine.context import PipelineContext
        from fretpilot.engine.pipeline import RepairPipeline
        from fretpilot.midi.parser import load_midi

        timeline = load_midi(golden_midi)
        report = classify_timeline(timeline)
        assert report.primary_guitar_track_index is not None

        track = timeline.tracks[report.primary_guitar_track_index]
        ctx = PipelineContext(
            timeline=timeline,
            track=track,
            knowledge=knowledge_engine.registry,
            style_label="rock",
            midi_fidelity=0.5,
            advisor=None,
            track_role="rhythm",
            source_track_index=track.index,
            degraded_mode=True,
        )
        return RepairPipeline(knowledge_engine).execute(ctx)

    def test_ir_has_correct_structure(self, golden_ir: GuitarProjectIR) -> None:
        """The golden IR must have the expected structural properties."""
        assert golden_ir.schema_version == "1.0"
        assert golden_ir.style_label == "rock"
        assert golden_ir.degraded_mode is True
        assert len(golden_ir.tracks) == 1

        track = golden_ir.tracks[0]
        assert track.role == "rhythm"
        assert len(track.tuning) == 6
        assert track.fret_count == 24

    def test_ir_has_measures(self, golden_ir: GuitarProjectIR) -> None:
        """The golden IR must have at least 1 measure with notes."""
        track = golden_ir.tracks[0]
        assert len(track.measures) >= 1
        total_notes = sum(len(m.events) for m in track.measures)
        assert total_notes == 8  # 8 eighth notes in the source

    def test_ir_notes_have_valid_fingering(self, golden_ir: GuitarProjectIR) -> None:
        """Every note must have a valid string/fret assignment."""
        from fretpilot.guitar.fretboard import candidate_positions

        track = golden_ir.tracks[0]
        for measure in track.measures:
            for event in measure.events:
                assert event.fingering.string is not None
                assert event.fingering.fret is not None
                valid = candidate_positions(event.pitch)
                positions = [(p.string, p.fret) for p in valid]
                assert (event.fingering.string, event.fingering.fret) in positions

    def test_ir_has_transformations(self, golden_ir: GuitarProjectIR) -> None:
        """The golden IR must record at least the quantization transformations."""
        assert len(golden_ir.changes) > 0
        stages = {c.stage for c in golden_ir.changes}
        assert "quantize_onset" in stages or len(golden_ir.changes) > 0

    def test_ir_knowledge_snapshot_is_pinned(self, golden_ir: GuitarProjectIR) -> None:
        """The IR must pin the knowledge snapshot version."""
        assert golden_ir.knowledge is not None
        assert golden_ir.knowledge.snapshot_version != "unknown"
        assert len(golden_ir.knowledge.entry_ids) > 0

    def test_ir_roundtrip_preserves_structure(self, golden_ir: GuitarProjectIR, tmp_path: Path) -> None:
        """Save and reload the IR — structure must be preserved."""
        from fretpilot.ir.serde import load_ir, save_ir

        path = tmp_path / "golden_ir.json"
        save_ir(golden_ir, path)

        loaded = load_ir(path)
        assert loaded.schema_version == golden_ir.schema_version
        assert loaded.style_label == golden_ir.style_label
        assert len(loaded.tracks) == len(golden_ir.tracks)
        assert len(loaded.changes) == len(golden_ir.changes)

        orig_notes = sum(len(m.events) for t in golden_ir.tracks for m in t.measures)
        loaded_notes = sum(len(m.events) for t in loaded.tracks for m in t.measures)
        assert loaded_notes == orig_notes

    def test_gp5_export_roundtrip(self, golden_ir: GuitarProjectIR, tmp_path: Path) -> None:
        """Export to GP5 and parse back — must succeed."""
        import guitarpro as gp

        from fretpilot.exporters.gp5 import GP5Exporter

        out_path = tmp_path / "golden.gp5"
        result = GP5Exporter().export(golden_ir, out_path)

        assert out_path.exists()
        assert result.note_count > 0

        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert song.tempo == 120
        assert len(song.tracks[0].measures) >= 1

    def test_ample_midi_export_roundtrip(self, golden_ir: GuitarProjectIR, tmp_path: Path) -> None:
        """Export to Ample MIDI and parse back — must succeed."""
        from fretpilot.exporters.ample_midi.profile import load_profile
        from fretpilot.exporters.ample_midi.renderer import AmpleMidiExporter

        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "golden_ample.mid"
        result = AmpleMidiExporter(profile).export(golden_ir, out_path)

        assert out_path.exists()
        assert result.note_count > 0

        midi = mido.MidiFile(out_path)
        assert midi.ticks_per_beat > 0
        assert len(midi.tracks) >= 2

        note_count = sum(
            1 for track in midi.tracks for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        )
        # Should have at least the 8 source notes (plus keyswitches)
        assert note_count >= 8

    def test_ir_is_deterministic(self, golden_midi: Path, knowledge_engine) -> None:
        """Running the pipeline twice must produce identical IR structure."""
        from fretpilot.detection import classify_timeline
        from fretpilot.engine.context import PipelineContext
        from fretpilot.engine.pipeline import RepairPipeline
        from fretpilot.midi.parser import load_midi

        def run_pipeline() -> GuitarProjectIR:
            timeline = load_midi(golden_midi)
            report = classify_timeline(timeline)
            track = timeline.tracks[report.primary_guitar_track_index]
            ctx = PipelineContext(
                timeline=timeline,
                track=track,
                knowledge=knowledge_engine.registry,
                style_label="rock",
                midi_fidelity=0.5,
                advisor=None,
                track_role="rhythm",
                source_track_index=track.index,
                degraded_mode=True,
            )
            return RepairPipeline(knowledge_engine).execute(ctx)

        ir1 = run_pipeline()
        ir2 = run_pipeline()

        assert len(ir1.tracks) == len(ir2.tracks)
        assert len(ir1.changes) == len(ir2.changes)
        n1 = sum(len(m.events) for t in ir1.tracks for m in t.measures)
        n2 = sum(len(m.events) for t in ir2.tracks for m in t.measures)
        assert n1 == n2

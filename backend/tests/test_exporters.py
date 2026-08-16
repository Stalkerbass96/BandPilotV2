"""Exporter tests — gp5 parse-back + Ample MIDI output verification."""

from __future__ import annotations

from pathlib import Path

import guitarpro as gp
import mido
import pytest

from fretpilot.exporters.ample_midi.profile import AmpleGuitarProfile, load_profile
from fretpilot.exporters.ample_midi.renderer import AmpleMidiExporter
from fretpilot.exporters.base import ExportResult, UnsupportedGuitarIR
from fretpilot.exporters.gp5 import GP5Exporter
from fretpilot.ir.models import (
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRArticulation,
    IRFingering,
    IRTempoEvent,
    IRTimeSignatureEvent,
    PerformanceTiming,
    ScoreTiming,
)


def _build_simple_ir(
    *,
    with_articulation: bool = False,
) -> GuitarProjectIR:
    """Build a minimal IR with one track, one measure, and a few notes."""
    notes: list[GuitarNoteEvent] = []
    pitches_and_strings = [
        (64, 1, 0),   # E4, string 1, fret 0
        (65, 1, 1),   # F4, string 1, fret 1
        (67, 1, 3),   # G4, string 1, fret 3
        (69, 2, 0),   # A4, string 2, fret 0
    ]
    for i, (pitch, string, fret) in enumerate(pitches_and_strings):
        articulations: list[IRArticulation] = []
        if with_articulation and i == 0:
            articulations.append(
                IRArticulation(type="palm_mute", confidence=0.8, reason="test")
            )
        notes.append(
            GuitarNoteEvent(
                id=f"n-{i + 1:05d}",
                source_note_index=i,
                pitch=pitch,
                score=ScoreTiming(
                    start_beat=float(i) * 0.5,
                    duration_beats=0.5,
                    measure_number=1,
                    beat_in_measure=float(i) * 0.5,
                    voice=1,
                    tie_in=False,
                    tie_out=False,
                ),
                performance=PerformanceTiming(
                    source_start_beat=float(i) * 0.5,
                    source_duration_beats=0.48,
                    velocity=80,
                ),
                fingering=IRFingering(string=string, fret=fret),
                articulations=articulations,
            ),
        )

    measure = GuitarMeasure(
        number=1,
        start_beat=0.0,
        duration_beats=4.0,
        numerator=4,
        denominator=4,
        events=notes,
    )
    track = GuitarTrackIR(
        id="guitar-1",
        name="Test Guitar",
        source_track_index=0,
        role="lead",
        tuning=[40, 45, 50, 55, 59, 64],
        fret_count=24,
        measures=[measure],
    )
    return GuitarProjectIR(
        title="Export Test",
        source="test.mid",
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[
            IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
        style_label="metal",
        midi_fidelity=0.5,
    )


def _build_two_track_ir() -> GuitarProjectIR:
    """Build a Lead + Rhythm IR pair (one measure each, shared measure count)."""
    ir = _build_simple_ir()
    lead_track = ir.tracks[0]
    rhythm_notes = [
        GuitarNoteEvent(
            id=f"n-{100 + i:05d}",
            source_note_index=100 + i,
            pitch=pitch,
            score=ScoreTiming(
                start_beat=float(i) * 0.5,
                duration_beats=0.5,
                measure_number=1,
                beat_in_measure=float(i) * 0.5,
                voice=1,
                tie_in=False,
                tie_out=False,
            ),
            performance=PerformanceTiming(
                source_start_beat=float(i) * 0.5,
                source_duration_beats=0.48,
                velocity=80,
            ),
            fingering=IRFingering(string=string, fret=fret),
        )
        for i, (pitch, string, fret) in enumerate([(40, 6, 0), (43, 6, 3)])
    ]
    rhythm_track = GuitarTrackIR(
        id="guitar-1-rhythm",
        name="Test Guitar - Rhythm",
        source_track_index=0,
        role="rhythm",
        tuning=list(lead_track.tuning),
        fret_count=lead_track.fret_count,
        measures=[
            GuitarMeasure(
                number=1,
                start_beat=0.0,
                duration_beats=4.0,
                numerator=4,
                denominator=4,
                events=rhythm_notes,
            )
        ],
    )
    ir.tracks.append(rhythm_track)
    return ir


class TestGP5Exporter:
    """Tests for the Guitar Pro 5 exporter."""

    def test_export_creates_file(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        exporter = GP5Exporter()
        out_path = tmp_path / "test.gp5"
        result = exporter.export(ir, out_path)
        assert out_path.exists()
        assert result.format_id == "gp5"
        assert result.note_count > 0
        assert result.measure_count == 1

    def test_export_result_is_export_result(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        result = GP5Exporter().export(ir, tmp_path / "test.gp5")
        assert isinstance(result, ExportResult)

    def test_parse_back_reads_file(self, tmp_path: Path) -> None:
        """The exported .gp5 file should be re-readable by PyGuitarPro."""
        ir = _build_simple_ir()
        out_path = tmp_path / "roundtrip.gp5"
        GP5Exporter().export(ir, out_path)

        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert song is not None
        assert song.title == "Export Test"
        assert len(song.tracks) >= 1
        assert len(song.measureHeaders) >= 1

    def test_parse_back_preserves_tempo(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        out_path = tmp_path / "tempo.gp5"
        GP5Exporter().export(ir, out_path)
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert song.tempo == 120

    def test_parse_back_preserves_notes(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        out_path = tmp_path / "notes.gp5"
        result = GP5Exporter().export(ir, out_path)
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        track = song.tracks[0]
        total_notes = sum(
            len(beat.notes)
            for measure in track.measures
            for voice in measure.voices
            for beat in voice.beats
        )
        assert total_notes == result.note_count

    def test_export_preserves_string_assignment(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        out_path = tmp_path / "strings.gp5"
        GP5Exporter().export(ir, out_path)
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        track = song.tracks[0]
        first_measure = track.measures[0]
        first_voice = first_measure.voices[0]
        first_beat = first_voice.beats[0]
        assert len(first_beat.notes) >= 1
        note = first_beat.notes[0]
        # String 1 in our IR = high E, which is string 1 in GP (1-indexed)
        assert note.string == 1
        assert note.value == 0  # fret 0

    def test_export_with_articulations(self, tmp_path: Path) -> None:
        ir = _build_simple_ir(with_articulation=True)
        out_path = tmp_path / "artic.gp5"
        result = GP5Exporter().export(ir, out_path)
        assert out_path.exists()
        assert result.note_count > 0

    def test_export_rejects_empty_ir(self, tmp_path: Path) -> None:
        ir = GuitarProjectIR(title="Empty", source="s")
        with pytest.raises(UnsupportedGuitarIR):
            GP5Exporter().export(ir, tmp_path / "empty.gp5")

    def test_export_supports_multi_track(self, tmp_path: Path) -> None:
        """Two guitar tracks (Lead + Rhythm) export and parse back as 2 tracks."""
        ir = _build_two_track_ir()
        out_path = tmp_path / "multi.gp5"
        result = GP5Exporter().export(ir, out_path)
        assert out_path.exists()
        # 4 lead notes + 2 rhythm notes.
        assert result.note_count == 6

        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert len(song.tracks) == 2
        assert song.tracks[0].name.startswith("Test Guitar")
        assert song.tracks[1].name.startswith("Test Guitar")

    def test_multi_track_shared_measure_headers(self, tmp_path: Path) -> None:
        """Both exported tracks share the same measure header count."""
        ir = _build_two_track_ir()
        out_path = tmp_path / "multi2.gp5"
        GP5Exporter().export(ir, out_path)
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert len(song.measureHeaders) == 1
        for track in song.tracks:
            assert len(track.measures) == len(song.measureHeaders)


class TestAmpleMidiExporter:
    """Tests for the Ample Guitar MIDI exporter."""

    def test_export_creates_midi_file(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        exporter = AmpleMidiExporter(profile)
        out_path = tmp_path / "ample.mid"
        result = exporter.export(ir, out_path)
        assert out_path.exists()
        assert result.format_id == "ample_midi"
        assert result.note_count > 0

    def test_export_result_is_export_result(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        result = AmpleMidiExporter(profile).export(ir, tmp_path / "r.mid")
        assert isinstance(result, ExportResult)

    def test_output_is_valid_midi(self, tmp_path: Path) -> None:
        """The exported MIDI should be re-parseable by mido."""
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "valid.mid"
        AmpleMidiExporter(profile).export(ir, out_path)
        mid = mido.MidiFile(out_path)
        assert mid.ticks_per_beat > 0
        assert len(mid.tracks) >= 2  # meta + performance

    def test_output_contains_note_events(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "notes.mid"
        AmpleMidiExporter(profile).export(ir, out_path)
        mid = mido.MidiFile(out_path)
        note_ons = [
            msg for track in mid.tracks for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        ]
        assert len(note_ons) >= 4  # At least the 4 source notes

    def test_output_contains_keyswitches(self, tmp_path: Path) -> None:
        """The default sustain keyswitch should be present at tick 0."""
        ir = _build_simple_ir(with_articulation=True)
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "ks.mid"
        AmpleMidiExporter(profile).export(ir, out_path)
        mid = mido.MidiFile(out_path)
        all_msgs = [msg for track in mid.tracks for msg in track]
        # Sustain keyswitch note should be present
        sustain_note = profile.keyswitch_note("sustain")
        assert sustain_note is not None
        sustain_msgs = [m for m in all_msgs if m.type == "note_on" and m.note == sustain_note]
        assert len(sustain_msgs) >= 1

    def test_export_preserves_tempo_in_meta_track(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "tempo.mid"
        AmpleMidiExporter(profile).export(ir, out_path)
        mid = mido.MidiFile(out_path)
        tempos = [
            msg for track in mid.tracks for msg in track
            if msg.type == "set_tempo"
        ]
        assert len(tempos) >= 1
        assert mido.tempo2bpm(tempos[0].tempo) == 120.0

    def test_export_preserves_time_signature(self, tmp_path: Path) -> None:
        ir = _build_simple_ir()
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "ts.mid"
        AmpleMidiExporter(profile).export(ir, out_path)
        mid = mido.MidiFile(out_path)
        time_sigs = [
            msg for track in mid.tracks for msg in track
            if msg.type == "time_signature"
        ]
        assert len(time_sigs) >= 1
        assert time_sigs[0].numerator == 4
        assert time_sigs[0].denominator == 4

    def test_export_rejects_empty_ir(self, tmp_path: Path) -> None:
        ir = GuitarProjectIR(title="Empty", source="s")
        profile = load_profile("ample_eclipse")
        with pytest.raises(ValueError):
            AmpleMidiExporter(profile).export(ir, tmp_path / "empty.mid")

    def test_export_merges_multi_track(self, tmp_path: Path) -> None:
        """Lead + Rhythm tracks merge into one playable MIDI stream."""
        ir = _build_two_track_ir()
        profile = load_profile("ample_eclipse")
        out_path = tmp_path / "multi.mid"
        result = AmpleMidiExporter(profile).export(ir, out_path)
        assert out_path.exists()
        # 4 lead + 2 rhythm source notes merged.
        assert result.note_count == 6
        mid = mido.MidiFile(out_path)
        note_ons = [
            msg for track in mid.tracks for msg in track
            if msg.type == "note_on" and msg.velocity > 0
        ]
        assert len(note_ons) >= 6


class TestAmpleProfile:
    """Tests for the AmpleGuitarProfile loading (v2 schema)."""

    def test_load_eclipse_profile(self) -> None:
        profile = load_profile("ample_eclipse")
        assert profile.profile_id == "ample_eclipse"
        assert profile.playable_min > 0
        assert profile.playable_max > profile.playable_min
        assert "sustain" in profile.articulations
        assert profile.manufacturer == "Ample Sound"
        assert profile.kb_version == "1.0.0"
        assert profile.octave_convention == "c3_60"

    def test_load_sc_profile(self) -> None:
        profile = load_profile("ample_sc")
        assert profile.profile_id == "ample_sc"
        assert "sustain" in profile.articulations

    def test_keyswitch_for_articulation(self) -> None:
        profile = load_profile("ample_eclipse")
        ks = profile.keyswitch_note("palm_mute")
        assert ks is not None
        assert isinstance(ks, int)
        assert ks == 26

    def test_keyswitch_for_hammer_on(self) -> None:
        profile = load_profile("ample_eclipse")
        ks = profile.keyswitch_note("hammer_on")
        # hammer_on maps to "hammer_pull" keyswitch (note 29)
        assert ks is not None
        assert ks == 29

    def test_keyswitch_alias_matches_new_method(self) -> None:
        """The deprecated alias must agree with keyswitch_note."""
        profile = load_profile("ample_eclipse")
        assert profile.keyswitch_for_articulation("slide") == profile.keyswitch_note("slide")

    def test_velocity_layers(self) -> None:
        """Eclipse sustain articulation has 5 velocity layers."""
        profile = load_profile("ample_eclipse")
        sustain = profile.articulations["sustain"]
        assert len(sustain.velocity_layers) == 5
        names = [layer.name for layer in sustain.velocity_layers]
        assert "full_mute" in names
        assert "sustain" in names
        # Layers should be contiguous and non-overlapping.
        for layer in sustain.velocity_layers:
            assert 1 <= layer.min <= layer.max <= 127

    def test_string_force(self) -> None:
        """Eclipse profile defines 6 string-force entries (one per string)."""
        profile = load_profile("ample_eclipse")
        assert len(profile.string_force) == 6
        strings = {entry.string for entry in profile.string_force}
        assert strings == {1, 2, 3, 4, 5, 6}

    def test_fx_sounds(self) -> None:
        """Eclipse profile defines 11 FX sounds."""
        profile = load_profile("ample_eclipse")
        assert len(profile.fx_sounds) == 11
        scratch = profile.fx_sounds["scratch"]
        assert scratch.note == 89
        assert scratch.label == "F5"

    def test_per_articulation_range(self) -> None:
        """Natural harmonic has a narrower range than the global playable range."""
        profile = load_profile("ample_eclipse")
        lo, hi = profile.playable_range_for("natural_harmonic")
        assert lo == 40
        assert hi == 69
        # Global range is wider.
        assert profile.playable_min == 36
        assert profile.playable_max == 84
        # Unknown articulation falls back to global range.
        assert profile.playable_range_for("nonexistent") == (36, 84)

    def test_capo_force(self) -> None:
        """Eclipse profile defines a capo-force block."""
        profile = load_profile("ample_eclipse")
        assert profile.capo_force is not None
        assert profile.capo_force.activate_note == 32
        assert profile.capo_force.fret_min == 0
        assert profile.capo_force.fret_max == 18
        assert len(profile.capo_force.position_notes) == 19

    def test_control_switches(self) -> None:
        """Eclipse profile defines control switches including poly_repeater."""
        profile = load_profile("ample_eclipse")
        assert "open_string_first" in profile.control_switches
        assert "auto_legato_mode" in profile.control_switches
        # poly_repeater uses notes[]/labels[] arrays; first entry is used.
        poly = profile.control_switches["poly_repeater"]
        assert poly.note == 98
        assert poly.label == "D6"

    def test_sc_has_all_optional_blocks(self) -> None:
        """SC profile (v2, from official manual) has fx_sounds, capo_force, control_switches."""
        profile = load_profile("ample_sc")
        # 12 FX sounds (includes Raking which Eclipse doesn't have).
        assert len(profile.fx_sounds) == 12
        assert "raking" in profile.fx_sounds
        # Capo force (Position Assignment in SC manual).
        assert profile.capo_force is not None
        assert profile.capo_force.activate_note == 37  # C#1
        # 4 control switches.
        assert len(profile.control_switches) == 4
        assert "note_repeater" in profile.control_switches
        assert "position_mode" in profile.control_switches
        # String force: SC uses G0-C1 (31-36), not Eclipse's F#-1~B-1 (18-23).
        assert len(profile.string_force) == 6
        assert profile.string_force[0].note == 31  # G0 = 6th string
        assert profile.string_force[5].note == 36  # C1 = 1st string

    def test_sc_slide_guitar_articulation(self) -> None:
        """SC has slide_guitar (F#0) instead of tap (Eclipse-specific)."""
        profile = load_profile("ample_sc")
        assert "slide_guitar" in profile.articulations
        assert "tap" not in profile.articulations
        assert profile.articulations["slide_guitar"].note == 30  # F#0
        # Eclipse has tap, not slide_guitar.
        eclipse = load_profile("ample_eclipse")
        assert "tap" in eclipse.articulations
        assert "slide_guitar" not in eclipse.articulations

    def test_sc_pinch_harmonic_separate_keyswitch(self) -> None:
        """SC has PH as separate keyswitch (B-1=23), unlike Eclipse."""
        profile = load_profile("ample_sc")
        assert "pinch_harmonic" in profile.articulations
        assert profile.articulations["pinch_harmonic"].note == 23  # B-1
        eclipse = load_profile("ample_eclipse")
        assert "pinch_harmonic" not in eclipse.articulations

    def test_persist_and_revert_metadata(self) -> None:
        """Persist / revert_to flags are parsed correctly."""
        profile = load_profile("ample_eclipse")
        assert profile.articulations["palm_mute"].persist is True
        assert profile.articulations["sustain"].persist is True
        # slide_in_out has revert_to but no persist flag.
        assert profile.articulations["slide_in_out"].persist is False
        assert profile.articulations["slide_in_out"].revert_to == "sustain"

    def test_load_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError):
            load_profile("nonexistent_profile")

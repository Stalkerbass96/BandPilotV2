"""Professional drum notation and learning regressions."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from fretpilot.drum.drumkit import map_pitch_to_piece
from fretpilot.elearning.drum_models import DrumGroundTruthNote, DrumGroundTruthTab
from fretpilot.elearning.drum_stats_extractor import DrumStatsExtractor
from fretpilot.engine.drum_context import DrumPipelineContext
from fretpilot.engine.stages.measure_split import MeasureSplitStage
from fretpilot.engine.stages.quantize import QuantizeStage
from fretpilot.exporters.musicxml import MusicXMLSongExporter
from fretpilot.ir.models import IRTempoEvent, IRTimeSignatureEvent, ScoreTiming
from fretpilot.ir.song import (
    AnalysisLayer,
    InstrumentRealization,
    InstrumentTrackIR,
    PerformanceEventIR,
    PerformanceLayer,
    ReproducibilityPins,
    ScoreEventIR,
    ScoreLayer,
    ScoreMeasureIR,
    SongIR,
    SourceLayer,
    SourceNoteReference,
    ValidationLayer,
)
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.validation import validate_song
from tests.conftest import _note, _timeline


def _event(
    note_id: str,
    pitch: int,
    piece: str,
    onset: float,
    duration: float,
    voice: int,
) -> ScoreEventIR:
    return ScoreEventIR(
        id=note_id,
        pitch=pitch,
        score=ScoreTiming(onset, duration, 1, onset, voice=voice),
        source=SourceNoteReference(0, pitch),
        realization=InstrumentRealization(kind="drums", piece=piece),
    )


def _song() -> SongIR:
    events = [
        _event("snare", 38, "snare", 0.0, 0.5, 1),
        _event("kick", 36, "kick", 0.0, 1.0, 2),
        _event("hihat", 42, "hihat_closed", 0.5, 1.0, 1),
    ]
    return SongIR(
        title="Drum notation",
        source=SourceLayer("drums.mid", "", 1, 480, 3, 4.0),
        analysis=AnalysisLayer(),
        score=ScoreLayer(
            tempo_map=[IRTempoEvent(0.0, 120.0)],
            time_signatures=[IRTimeSignatureEvent(0.0, 4, 4)],
            tracks=[
                InstrumentTrackIR(
                    id="drums",
                    name="Drums",
                    family="drums",
                    role="drums",
                    source_track_indices=[0],
                    instrument={"kit": "standard_5pc"},
                    measures=[ScoreMeasureIR(1, 0.0, 4.0, 4, 4, events)],
                )
            ],
        ),
        performance=PerformanceLayer(
            events=[PerformanceEventIR(event.id, event.score.start_beat, 3.0, 90) for event in events]
        ),
        validation=ValidationLayer(),
        pins=ReproducibilityPins("test", "test"),
    )


def test_musicxml_uses_five_line_staff_standard_noteheads_and_stems(tmp_path) -> None:
    destination = tmp_path / "drums.musicxml"
    MusicXMLSongExporter().export(_song(), destination)
    root = ET.parse(destination).getroot()

    assert root.findtext(".//staff-details/staff-lines") == "5"
    assert root.findtext(".//clef/sign") == "percussion"

    notes = root.findall(".//note[unpitched]")
    by_position = {
        (
            note.findtext("unpitched/display-step"),
            note.findtext("unpitched/display-octave"),
        ): note
        for note in notes
    }
    kick = by_position[("F", "3")]
    snare = by_position[("C", "5")]
    hihat = by_position[("G", "5")]
    assert kick.findtext("voice") == "2"
    assert kick.findtext("stem") == "down"
    assert snare.findtext("voice") == "1"
    assert snare.findtext("stem") == "up"
    assert hihat.findtext("notehead") == "x"
    # 0.0 -> 0.5 in voice 1, so the old three-beat sampler gate is closed.
    assert snare.findtext("duration") == "240"


def test_validation_blocks_nonstandard_voice_and_overlapping_drum_rhythm() -> None:
    song = _song()
    events = song.score.tracks[0].measures[0].events
    events[0].score.duration_beats = 1.0  # crosses the hi-hat at beat 0.5
    events[1].score.voice = 1  # kick must be in the lower/foot voice

    result = validate_song(song)
    codes = {issue.code for issue in result.issues}

    assert result.status == "failed"
    assert "drums.voice_policy" in codes
    assert "drums.voice_overlap" in codes


def test_gm_map_is_deterministic_for_standard_kit_range() -> None:
    expected = {
        35: "kick",
        36: "kick",
        37: "side_stick",
        38: "snare",
        39: "hand_clap",
        40: "snare",
        41: "tom_floor",
        42: "hihat_closed",
        43: "tom_floor",
        44: "hihat_pedal",
        45: "tom_low",
        46: "hihat_open",
        47: "tom_mid",
        48: "tom_mid",
        49: "crash",
        50: "tom_high",
        51: "ride",
        52: "china",
        53: "ride_bell",
        54: "tambourine",
        55: "splash",
        56: "cowbell",
        57: "crash_2",
        58: "vibraslap",
        59: "ride_2",
    }
    assert {pitch: map_pitch_to_piece(pitch) for pitch in expected} == expected


def test_drum_learning_extracts_written_duration_and_voice_evidence() -> None:
    notes = [
        DrumGroundTruthNote(1, 0.0, 38, "snare", 90, 0.5, 1, False),
        DrumGroundTruthNote(1, 0.0, 36, "kick", 100, 1.0, 2, False),
        DrumGroundTruthNote(1, 0.5, 42, "hihat_closed", 80, 0.5, 1, False),
        DrumGroundTruthNote(1, 1.0, 36, "kick", 100, 2.0, 1, False),
    ]
    tab = DrumGroundTruthTab(
        "reference.gp5", "Reference", "rock", 120.0, (4, 4), "Drums", notes
    )
    stats = DrumStatsExtractor().extract([tab])["rock"]

    assert stats.duration_distribution == {
        "0.500000": 0.5,
        "1.000000": 0.25,
        "2.000000": 0.25,
    }
    assert stats.quarter_or_shorter_rate == 0.75
    assert stats.voice_two_rate == 0.25
    assert stats.foot_voice_two_rate == 0.5


def test_drum_quantization_uses_onsets_and_never_splits_sampler_gates(
    engine: KnowledgeEngine,
) -> None:
    notes = [
        _note(38, 3.75, 2.0),
        _note(42, 4.0, 2.0),
        _note(38, 4.25, 2.0),
    ]
    timeline = _timeline(notes)
    ctx = DrumPipelineContext(
        timeline=timeline,
        track=timeline.tracks[0],
        knowledge=engine.registry,
        style_label="rock",
        midi_fidelity=0.5,
    )

    QuantizeStage(engine).run(ctx)
    MeasureSplitStage().run(ctx)

    assert [note.quantized_start_beat for note in ctx.quantized_notes] == [
        3.75,
        4.0,
        4.25,
    ]
    assert len(ctx.split_notes) == len(notes)
    assert [note.measure_number for note in ctx.split_notes] == [1, 2, 2]
    assert all(not note.tie_in and not note.tie_out for note in ctx.split_notes)

"""IR Schema serialization / deserialization round-trip tests.

Verifies that ``ir_from_dict(ir_to_dict(ir)) == ir`` for a representative
IR with tracks, measures, notes, articulations, and transformations.
"""

from __future__ import annotations

import json

from fretpilot.ir.models import (
    SCHEMA_VERSION,
    GuitarMeasure,
    GuitarNoteEvent,
    GuitarProjectIR,
    GuitarTrackIR,
    IRArticulation,
    IRFingering,
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    NoteConfidence,
    PerformanceTiming,
    ScoreTiming,
    Transformation,
)
from fretpilot.ir.serde import ir_from_dict, ir_to_dict, load_ir, save_ir


def _build_sample_ir() -> GuitarProjectIR:
    """Build a fully-populated IR for round-trip testing."""
    note = GuitarNoteEvent(
        id="n-00001",
        source_note_index=0,
        pitch=64,
        score=ScoreTiming(
            start_beat=0.0,
            duration_beats=0.5,
            measure_number=1,
            beat_in_measure=0.0,
            voice=1,
            tie_in=False,
            tie_out=False,
        ),
        performance=PerformanceTiming(
            source_start_beat=0.0,
            source_duration_beats=0.48,
            velocity=95,
        ),
        fingering=IRFingering(
            string=1,
            fret=0,
            fretting_digit=0,
            hand_position=1,
        ),
        articulations=[
            IRArticulation(
                type="palm_mute",
                confidence=0.8,
                reason="short note in metal context",
                source_note_id=None,
                parameters={"intensity": 0.7},
            ),
        ],
        confidence=NoteConfidence(rhythm=0.95, fingering=0.9, articulation=0.8),
        source_note_origin="midi",
    )
    measure = GuitarMeasure(
        number=1,
        start_beat=0.0,
        duration_beats=4.0,
        numerator=4,
        denominator=4,
        events=[note],
    )
    track = GuitarTrackIR(
        id="guitar-1",
        name="Lead Guitar",
        source_track_index=0,
        role="lead",
        tuning=[40, 45, 50, 55, 59, 64],
        fret_count=24,
        measures=[measure],
    )
    knowledge = IRKnowledgeReference(
        snapshot_version="2026.08.2",
        kb_versions={"kb1_arrangement": "1.0", "kb2_performance": "1.0"},
        entry_ids=["kb1-metal-001", "kb2-metal-lead"],
    )
    change = Transformation(
        id="chg-00001",
        stage="quantize_onset",
        source_note_index=0,
        before={"start_beat": 0.03},
        after={"start_beat": 0.0},
        confidence=0.85,
        reason="snap_to_sixteenth_grid",
        knowledge_ref="kb1-metal-001",
    )
    return GuitarProjectIR(
        title="Test Song",
        source="/tmp/test.mid",
        schema_version=SCHEMA_VERSION,
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[
            IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
        knowledge=knowledge,
        style_label="metal",
        midi_fidelity=0.6,
        degraded_mode=False,
        changes=[change],
        warnings=["Selected grid: sixteenth (step=0.25)"],
    )


class TestIRSchemaVersion:
    """Tests for the schema version constant."""

    def test_schema_version_is_1_0(self) -> None:
        assert SCHEMA_VERSION == "1.0"

    def test_ir_has_default_schema_version(self) -> None:
        ir = GuitarProjectIR(title="T", source="s")
        assert ir.schema_version == "1.0"


class TestIRRoundTrip:
    """Tests for IR serialization / deserialization consistency."""

    def test_to_dict_produces_valid_json(self) -> None:
        ir = _build_sample_ir()
        data = ir.to_dict()
        serialized = json.dumps(data, ensure_ascii=False)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert parsed["schema_version"] == "1.0"

    def test_roundtrip_preserves_all_fields(self) -> None:
        ir = _build_sample_ir()
        restored = ir_from_dict(ir_to_dict(ir))
        assert restored.title == ir.title
        assert restored.source == ir.source
        assert restored.schema_version == ir.schema_version
        assert restored.style_label == ir.style_label
        assert restored.midi_fidelity == ir.midi_fidelity
        assert restored.degraded_mode == ir.degraded_mode
        assert restored.warnings == ir.warnings

    def test_roundtrip_preserves_tracks_and_notes(self) -> None:
        ir = _build_sample_ir()
        restored = ir_from_dict(ir_to_dict(ir))
        assert len(restored.tracks) == 1
        track = restored.tracks[0]
        assert track.id == "guitar-1"
        assert track.role == "lead"
        assert track.tuning == [40, 45, 50, 55, 59, 64]
        assert len(track.measures) == 1
        measure = track.measures[0]
        assert measure.number == 1
        assert len(measure.events) == 1
        note = measure.events[0]
        assert note.id == "n-00001"
        assert note.pitch == 64
        assert note.score.start_beat == 0.0
        assert note.performance.velocity == 95
        assert note.fingering.string == 1
        assert note.fingering.fret == 0
        assert len(note.articulations) == 1
        assert note.articulations[0].type == "palm_mute"

    def test_roundtrip_preserves_knowledge_ref(self) -> None:
        ir = _build_sample_ir()
        restored = ir_from_dict(ir_to_dict(ir))
        assert restored.knowledge is not None
        assert restored.knowledge.snapshot_version == "2026.08.2"
        assert "kb1_arrangement" in restored.knowledge.kb_versions

    def test_roundtrip_preserves_transformations(self) -> None:
        ir = _build_sample_ir()
        restored = ir_from_dict(ir_to_dict(ir))
        assert len(restored.changes) == 1
        change = restored.changes[0]
        assert change.id == "chg-00001"
        assert change.stage == "quantize_onset"
        assert change.before == {"start_beat": 0.03}
        assert change.after == {"start_beat": 0.0}
        assert change.knowledge_ref == "kb1-metal-001"

    def test_roundtrip_preserves_tempo_and_time_sigs(self) -> None:
        ir = _build_sample_ir()
        restored = ir_from_dict(ir_to_dict(ir))
        assert len(restored.tempo_map) == 1
        assert restored.tempo_map[0].bpm == 120.0
        assert len(restored.time_signatures) == 1
        assert restored.time_signatures[0].numerator == 4

    def test_save_load_file_roundtrip(self, tmp_path) -> None:
        ir = _build_sample_ir()
        path = tmp_path / "ir.json"
        save_ir(ir, path)
        assert path.exists()
        loaded = load_ir(path)
        assert loaded.title == ir.title
        assert len(loaded.tracks) == 1
        assert loaded.tracks[0].measures[0].events[0].id == "n-00001"

    def test_load_rejects_wrong_schema_version(self) -> None:
        data = {"title": "T", "source": "s", "schema_version": "2.0"}
        try:
            ir_from_dict(data)
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "2.0" in str(exc)

    def test_empty_ir_roundtrip(self) -> None:
        ir = GuitarProjectIR(title="Empty", source="none")
        restored = ir_from_dict(ir_to_dict(ir))
        assert restored.title == "Empty"
        assert restored.tracks == []
        assert restored.changes == []

    def test_ir_with_none_knowledge_roundtrip(self) -> None:
        ir = GuitarProjectIR(title="T", source="s", knowledge=None)
        restored = ir_from_dict(ir_to_dict(ir))
        assert restored.knowledge is None

    def test_ir_with_none_fingering_roundtrip(self) -> None:
        """Notes with unplayable pitches have string=None, fret=None."""
        note = GuitarNoteEvent(
            id="n-00001",
            source_note_index=0,
            pitch=100,
            score=ScoreTiming(0.0, 0.5, 1, 0.0),
            performance=PerformanceTiming(0.0, 0.5, 80),
            fingering=IRFingering(string=None, fret=None),
        )
        measure = GuitarMeasure(1, 0.0, 4.0, 4, 4, [note])
        track = GuitarTrackIR("t1", "T", 0, "lead", [40, 45, 50, 55, 59, 64], 24, [measure])
        ir = GuitarProjectIR(title="T", source="s", tracks=[track])
        restored = ir_from_dict(ir_to_dict(ir))
        restored_note = restored.tracks[0].measures[0].events[0]
        assert restored_note.fingering.string is None
        assert restored_note.fingering.fret is None
        assert restored_note.fingering.playable is False

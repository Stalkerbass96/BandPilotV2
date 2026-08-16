"""Test IR Schema 1.0 — round-trip serialization, version validation, and slot enforcement."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass

import pytest

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


SLOTTED_CLASSES = [
    IRTempoEvent,
    IRTimeSignatureEvent,
    ScoreTiming,
    PerformanceTiming,
    IRFingering,
    IRArticulation,
    NoteConfidence,
    GuitarNoteEvent,
    GuitarMeasure,
    GuitarTrackIR,
    IRKnowledgeReference,
    Transformation,
    GuitarProjectIR,
]


class TestSchemaVersion:
    """SCHEMA_VERSION must be frozen at '1.0'."""

    def test_schema_version_is_1_0(self) -> None:
        assert SCHEMA_VERSION == "1.0"

    def test_ir_defaults_to_current_version(self) -> None:
        ir = GuitarProjectIR(title="Test", source="test.mid")
        assert ir.schema_version == SCHEMA_VERSION


class TestSlotsEnforcement:
    """All IR dataclasses must use slots=True."""

    @pytest.mark.parametrize("cls", SLOTTED_CLASSES)
    def test_class_has_slots(self, cls) -> None:
        assert is_dataclass(cls), f"{cls.__name__} is not a dataclass"
        # slots=True creates __slots__ on the class
        assert hasattr(cls, "__slots__"), f"{cls.__name__} missing __slots__"
        # Verify __slots__ is not empty
        assert len(cls.__slots__) > 0, f"{cls.__name__} has empty __slots__"

    def test_ir_project_cannot_add_arbitrary_attr(self) -> None:
        """A slotted dataclass instance must reject unknown attributes."""
        ir = GuitarProjectIR(title="Test", source="test.mid")
        with pytest.raises(AttributeError):
            ir.nonexistent_field = 42  # type: ignore[attr-defined]


class TestRoundTrip:
    """ir_from_dict(ir_to_dict(ir)) must produce an equal IR."""

    def test_roundtrip_minimal_ir(self) -> None:
        ir = GuitarProjectIR(
            title="Test Song",
            source="/tmp/test.mid",
            tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
            time_signatures=[IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)],
            tracks=[],
            style_label="rock",
            midi_fidelity=0.5,
        )
        recovered = ir_from_dict(ir_to_dict(ir))
        assert recovered.title == ir.title
        assert recovered.source == ir.source
        assert recovered.schema_version == ir.schema_version
        assert recovered.style_label == ir.style_label
        assert recovered.midi_fidelity == ir.midi_fidelity

    def test_roundtrip_full_ir(self, repaired_ir: GuitarProjectIR) -> None:
        """Round-trip a fully repaired IR with notes, measures, and transformations."""
        as_dict = ir_to_dict(repaired_ir)
        recovered = ir_from_dict(as_dict)

        assert recovered.title == repaired_ir.title
        assert recovered.schema_version == repaired_ir.schema_version
        assert len(recovered.tracks) == len(repaired_ir.tracks)
        assert len(recovered.changes) == len(repaired_ir.changes)

        if repaired_ir.tracks:
            orig_track = repaired_ir.tracks[0]
            rec_track = recovered.tracks[0]
            assert rec_track.name == orig_track.name
            assert rec_track.role == orig_track.role
            assert rec_track.tuning == orig_track.tuning
            assert len(rec_track.measures) == len(orig_track.measures)

            if orig_track.measures:
                orig_m = orig_track.measures[0]
                rec_m = rec_track.measures[0]
                assert rec_m.number == orig_m.number
                assert len(rec_m.events) == len(orig_m.events)

    def test_roundtrip_preserves_knowledge_ref(self) -> None:
        ir = GuitarProjectIR(
            title="Test",
            source="test.mid",
            knowledge=IRKnowledgeReference(
                snapshot_version="2026.08.2",
                kb_versions={"kb1": "1.0", "kb2": "1.0"},
                entry_ids=["kb1-001", "kb2-001"],
            ),
        )
        recovered = ir_from_dict(ir_to_dict(ir))
        assert recovered.knowledge is not None
        assert recovered.knowledge.snapshot_version == "2026.08.2"
        assert recovered.knowledge.kb_versions == {"kb1": "1.0", "kb2": "1.0"}
        assert recovered.knowledge.entry_ids == ["kb1-001", "kb2-001"]

    def test_roundtrip_preserves_transformations(self) -> None:
        ir = GuitarProjectIR(
            title="Test",
            source="test.mid",
            changes=[
                Transformation(
                    id="chg-00001",
                    stage="quantize_onset",
                    source_note_index=0,
                    before={"start_beat": 0.13},
                    after={"start_beat": 0.25},
                    confidence=0.85,
                    reason="snap_to_eighth_grid",
                    knowledge_ref="kb1-001",
                ),
            ],
        )
        recovered = ir_from_dict(ir_to_dict(ir))
        assert len(recovered.changes) == 1
        ch = recovered.changes[0]
        assert ch.id == "chg-00001"
        assert ch.stage == "quantize_onset"
        assert ch.confidence == 0.85
        assert ch.knowledge_ref == "kb1-001"

    def test_roundtrip_preserves_articulations(self) -> None:
        ir = GuitarProjectIR(
            title="Test",
            source="test.mid",
            tracks=[
                GuitarTrackIR(
                    id="guitar-1",
                    name="Guitar",
                    source_track_index=0,
                    role="lead",
                    tuning=[40, 45, 50, 55, 59, 64],
                    fret_count=24,
                    measures=[
                        GuitarMeasure(
                            number=1,
                            start_beat=0.0,
                            duration_beats=4.0,
                            numerator=4,
                            denominator=4,
                            events=[
                                GuitarNoteEvent(
                                    id="n-00001",
                                    source_note_index=0,
                                    pitch=48,
                                    score=ScoreTiming(
                                        start_beat=0.0,
                                        duration_beats=1.0,
                                        measure_number=1,
                                        beat_in_measure=0.0,
                                    ),
                                    performance=PerformanceTiming(
                                        source_start_beat=0.0,
                                        source_duration_beats=1.0,
                                        velocity=100,
                                    ),
                                    fingering=IRFingering(string=6, fret=8),
                                    articulations=[
                                        IRArticulation(
                                            type="palm_mute",
                                            confidence=0.9,
                                            reason="short note in metal context",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        recovered = ir_from_dict(ir_to_dict(ir))
        event = recovered.tracks[0].measures[0].events[0]
        assert len(event.articulations) == 1
        art = event.articulations[0]
        assert art.type == "palm_mute"
        assert art.confidence == 0.9


class TestVersionValidation:
    """ir_from_dict must reject unsupported schema versions."""

    def test_rejects_v0(self) -> None:
        with pytest.raises(ValueError, match="Unsupported IR schema version"):
            ir_from_dict({"title": "x", "source": "y", "schema_version": "0.1"})

    def test_rejects_v2(self) -> None:
        with pytest.raises(ValueError, match="Unsupported IR schema version"):
            ir_from_dict({"title": "x", "source": "y", "schema_version": "2.0"})

    def test_accepts_v1_1(self) -> None:
        """Future 1.x versions should be accepted (forward-compatible)."""
        ir = ir_from_dict({"title": "x", "source": "y", "schema_version": "1.1"})
        assert ir.schema_version == "1.1"


class TestFilePersistence:
    """save_ir / load_ir must round-trip through JSON files."""

    def test_save_and_load(self, tmp_path, repaired_ir: GuitarProjectIR) -> None:
        path = tmp_path / "ir.json"
        save_ir(repaired_ir, path)
        assert path.exists()

        loaded = load_ir(path)
        assert loaded.title == repaired_ir.title
        assert loaded.schema_version == repaired_ir.schema_version
        assert len(loaded.tracks) == len(repaired_ir.tracks)

    def test_saved_json_is_valid_json(self, tmp_path, repaired_ir: GuitarProjectIR) -> None:
        path = tmp_path / "ir.json"
        save_ir(repaired_ir, path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert raw["schema_version"] == SCHEMA_VERSION

"""Canonical SongIR, professional-score validation, and artifact contracts."""

from __future__ import annotations

import json

import pytest

from fretpilot.ai.advisor import ShadowRewriteAdvisor
from fretpilot.artifacts import file_sha256
from fretpilot.exporters.registry import SongExporterRegistry
from fretpilot.ir.song import TechniqueIR
from fretpilot.ir.song_adapter import _techniques_for_event
from fretpilot.ir.song_serde import load_song_ir, save_song_ir, song_ir_from_dict
from fretpilot.knowledge.tunings import TuningRegistry
from fretpilot.midi.parser import load_midi
from fretpilot.services.repair import RepairService
from fretpilot.validation import ScoreValidationError, validate_song
from tests.conftest import _make_midi_file


def _repair(tmp_path, notes=None):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = _make_midi_file(project_dir / "source.mid", notes=notes)
    timeline = load_midi(source)
    service = RepairService(ShadowRewriteAdvisor(None))
    run = service.run(
        timeline,
        title="SongIR Contract",
        midi_fidelity=0.5,
        source_path=source,
        source_filename="source.mid",
    )
    return service, run, project_dir


def test_song_ir_round_trip_and_artifact_manifest(tmp_path) -> None:
    service, run, project_dir = _repair(tmp_path)
    assert run.song is not None
    assert run.song.schema_version == "2.0"
    assert run.song.validation.status == "passed"

    parsed = song_ir_from_dict(run.song.to_dict())
    assert parsed.to_dict() == run.song.to_dict()
    save_song_ir(parsed, project_dir / "manual_song_ir.json")
    assert load_song_ir(project_dir / "manual_song_ir.json").to_dict() == parsed.to_dict()

    service.persist(run, project_dir, "SongIR Contract")
    manifest = json.loads(
        (project_dir / "artifact_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_sha256"] == file_sha256(project_dir / "source.mid")
    assert manifest["song_schema_version"] == "2.0"
    assert manifest["validation_status"] == "passed"
    captured = {item["name"]: item["sha256"] for item in manifest["artifacts"]}
    assert captured["song_ir.json"] == file_sha256(project_dir / "song_ir.json")


def test_unplayable_source_note_is_explicit_notation_exclusion(tmp_path) -> None:
    notes = [
        (20, 0, 240, 80),
        (64, 480, 240, 80),
    ]
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source = _make_midi_file(project_dir / "source.mid", notes=notes)
    service = RepairService(ShadowRewriteAdvisor(None))
    tuning = TuningRegistry.default().get("standard_6")
    assert tuning is not None
    run = service.run(
        load_midi(source),
        title="Dirty source",
        midi_fidelity=0.5,
        tuning_override=tuning,
        source_path=source,
    )
    assert run.song is not None
    assert run.song.validation.status == "passed"
    assert len(run.song.analysis.unresolved_events) == 1
    unresolved = run.song.analysis.unresolved_events[0]
    assert unresolved.pitch == 20
    score_pitches = [
        event.pitch
        for track in run.song.score.tracks
        for measure in track.measures
        for event in measure.events
    ]
    assert score_pitches == [64]
    assert any(
        issue.code == "source.unresolved_event"
        and issue.severity == "warning"
        for issue in run.song.validation.issues
    )


def test_export_registry_rejects_invalid_fingering_without_repair(tmp_path) -> None:
    _service, run, _project_dir = _repair(tmp_path)
    assert run.song is not None
    event = next(
        event
        for track in run.song.score.tracks
        if track.family == "guitar"
        for measure in track.measures
        for event in measure.events
    )
    assert event.realization.fret is not None
    event.realization.fret += 1

    validation = validate_song(run.song)
    assert validation.status == "failed"
    assert any(issue.code == "guitar.pitch_mismatch" for issue in validation.issues)
    with pytest.raises(ScoreValidationError):
        SongExporterRegistry.default().export("gp5", run.song, tmp_path / "invalid.gp5")
    assert not (tmp_path / "invalid.gp5").exists()


def test_linked_technique_requires_consistent_relation(tmp_path) -> None:
    _service, run, _project_dir = _repair(tmp_path)
    assert run.song is not None
    events = [
        event
        for track in run.song.score.tracks
        if track.family == "guitar"
        for measure in track.measures
        for event in measure.events
    ]
    assert len(events) >= 2
    technique = TechniqueIR(
        id="tech:bad-slide",
        type="slide",
        note_ids=[events[1].id, events[0].id],
        confidence=1.0,
        reason="test invalid relation",
    )
    run.song.score.techniques.append(technique)
    events[0].technique_ids.append(technique.id)
    events[1].technique_ids.append(technique.id)
    validation = validate_song(run.song)
    assert validation.status == "failed"
    assert any(issue.code == "technique.order" for issue in validation.issues)


def test_linked_technique_projects_only_on_destination_event(tmp_path) -> None:
    _service, run, _project_dir = _repair(tmp_path)
    assert run.song is not None
    events = [
        event
        for track in run.song.score.tracks
        if track.family == "guitar"
        for measure in track.measures
        for event in measure.events
    ]
    source, target = events[:2]
    technique = TechniqueIR(
        id="tech:slide",
        type="slide",
        note_ids=[source.id, target.id],
        confidence=1.0,
        reason="test relation projection",
    )
    run.song.score.techniques.append(technique)
    source.technique_ids.append(technique.id)
    target.technique_ids.append(technique.id)

    assert _techniques_for_event(run.song, source.technique_ids, source.id) == []
    projected = _techniques_for_event(run.song, target.technique_ids, target.id)
    assert len(projected) == 1
    assert projected[0].type == "slide"
    assert projected[0].source_note_id == source.id.rsplit(":", 1)[-1]


def test_song_ir_rejects_unknown_major_schema() -> None:
    with pytest.raises(ValueError, match="Unsupported SongIR"):
        song_ir_from_dict({"schema_version": "3.0"})

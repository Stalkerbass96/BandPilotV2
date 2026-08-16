"""Multivoice separation + tuning override integration tests.

覆盖本次增量两个功能：

1. **multivoice 分离超范围音符** —— 超范围音符（pitch < 40 或 > 88）在
   IR 里强制归入 voice 2（string/fret=None 保留真相），正常音符留在 voice 1；
   GP5 导出用占位 fingering + tie 机制，让 voice 2 的音符可见可删、同 onset
   不同 duration 的和弦 release 不再抛异常。
2. **定弦用户覆盖** —— repair 传 ``tuning_id`` 覆盖自动检测，``GET /tunings``
   暴露 12 套定弦给前端选择器。
"""

from __future__ import annotations

from pathlib import Path

import guitarpro as gp
import pytest
from fastapi.testclient import TestClient

from fretpilot.detection import classify_timeline, resolve_streams
from fretpilot.engine.cleanup import auto_detect_tuning, cleanup_streams
from fretpilot.engine.context import PipelineContext
from fretpilot.engine.pipeline import create_pipeline
from fretpilot.engine.stages import (
    FingeringStage,
    MeasureSplitStage,
    QuantizeStage,
    TieStage,
    VoiceStage,
)
from fretpilot.exporters.gp5 import GP5Exporter
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
from fretpilot.knowledge.engine import KnowledgeEngine
from fretpilot.midi.models import NormalizedTrack
from fretpilot.midi.parser import load_midi

from tests.conftest import _make_midi_file, _note, _timeline

_FIXTURE = Path(__file__).parent / "fixtures" / "tokyo_midnight.mid"


# ─── 共享辅助 ────────────────────────────────────────────────────────────────


def _build_ctx(notes, engine: KnowledgeEngine) -> PipelineContext:
    """Build a minimal PipelineContext for stage-level tests."""
    timeline = _timeline(notes)
    track = timeline.tracks[0] if timeline.tracks else NormalizedTrack(
        index=0, name="Empty", notes=[]
    )
    return PipelineContext(
        timeline=timeline,
        track=track,
        knowledge=engine.registry,
        style_label="metal",
        midi_fidelity=0.5,
        advisor=None,
        track_role="lead",
        source_track_index=0,
        degraded_mode=False,
    )


def _run_fingering(notes, engine: KnowledgeEngine) -> PipelineContext:
    """Run quantize → measure_split → tie → voice → fingering."""
    ctx = _build_ctx(notes, engine)
    QuantizeStage(engine).run(ctx)
    MeasureSplitStage().run(ctx)
    TieStage().run(ctx)
    VoiceStage().run(ctx)
    FingeringStage(engine).run(ctx)
    return ctx


def _make_event(
    idx: int,
    pitch: int,
    start: float,
    duration: float,
    voice: int,
    string: int | None,
    fret: int | None,
) -> GuitarNoteEvent:
    """Build a single GuitarNoteEvent for gp5 export tests."""
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
            source_start_beat=start, source_duration_beats=duration, velocity=80
        ),
        fingering=IRFingering(string=string, fret=fret),
    )


def _make_ir(events: list[GuitarNoteEvent]) -> GuitarProjectIR:
    """Build a one-track, one-measure IR wrapping ``events``."""
    measure = GuitarMeasure(
        number=1, start_beat=0.0, duration_beats=4.0, numerator=4, denominator=4,
        events=events,
    )
    track = GuitarTrackIR(
        id="guitar-1",
        name="Test",
        source_track_index=0,
        role="lead",
        tuning=[40, 45, 50, 55, 59, 64],
        fret_count=24,
        measures=[measure],
    )
    return GuitarProjectIR(
        title="Multivoice",
        source="test.mid",
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)],
        tracks=[track],
    )


def _tokyo_cleaned_track(timeline) -> tuple[NormalizedTrack, str]:
    """parse → detect → cleanup → 从 cleaned stream 构建 NormalizedTrack。"""
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


# ─── 功能 1a/1b：IR 声部分离 ────────────────────────────────────────────────


class TestMultivoiceSeparation:
    """超范围音符 → voice 2；正常音符 / 和弦 release 留在 voice 1。"""

    def test_out_of_range_notes_go_to_voice2(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=30, start_beat=0.0, duration_beats=0.5),
            _note(pitch=38, start_beat=0.5, duration_beats=0.5),
            _note(pitch=89, start_beat=1.0, duration_beats=0.5),
            _note(pitch=100, start_beat=1.5, duration_beats=0.5),
        ]
        ctx = _run_fingering(notes, engine)

        out_of_range = [
            n for n in ctx.fingered_notes if n.pitch < 40 or n.pitch > 88
        ]
        assert len(out_of_range) == 4
        assert all(n.voice == 2 for n in out_of_range)
        # IR 里 unplayable 音符保持 string/fret=None（真相）。
        assert all(n.string is None and n.fret is None for n in out_of_range)

    def test_normal_notes_stay_voice1(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.5, duration_beats=0.5),
            _note(pitch=67, start_beat=1.0, duration_beats=0.5),
            _note(pitch=72, start_beat=1.5, duration_beats=0.5),
        ]
        ctx = _run_fingering(notes, engine)

        assert ctx.fingered_notes
        assert all(n.voice == 1 for n in ctx.fingered_notes)
        assert all(n.string is not None and n.fret is not None for n in ctx.fingered_notes)

    def test_chord_release_not_promoted_to_voice2(self, engine: KnowledgeEngine) -> None:
        notes = [
            _note(pitch=60, start_beat=0.0, duration_beats=0.5),
            _note(pitch=64, start_beat=0.0, duration_beats=2.0),
        ]
        ctx = _run_fingering(notes, engine)

        # 和弦 release 保持 voice 1，不再 promote 到 voice 2。
        assert all(n.voice == 1 for n in ctx.fingered_notes)


class TestRingingNormalization:
    """同 onset 和弦 + 长音符越过下一 onset：voice stage 应截断长音符。

    回归 bug：旧实现按「排序后紧邻的下一个音符」截断，同 onset 和弦时
    ``available = 0`` 被跳过，长音符越过下一 onset 也不截断，导致 GP5 导出
    小节 tick 溢出、文件损坏。
    """

    def test_long_chord_note_clipped_to_next_onset(
        self, engine: KnowledgeEngine
    ) -> None:
        notes = [
            _note(pitch=45, start_beat=0.0, duration_beats=0.25),
            _note(pitch=49, start_beat=0.0, duration_beats=0.5),
            _note(pitch=52, start_beat=0.0, duration_beats=0.25),
            _note(pitch=57, start_beat=0.25, duration_beats=0.25),
        ]
        ctx = _build_ctx(notes, engine)
        QuantizeStage(engine).run(ctx)
        MeasureSplitStage().run(ctx)
        TieStage().run(ctx)
        VoiceStage().run(ctx)

        long_notes = [n for n in ctx.voiced_notes if n.pitch == 49]
        assert len(long_notes) == 1
        # 长音符被截断到下一不同 onset（0.25），并标记 let_ring。
        assert long_notes[0].duration_beats == pytest.approx(0.25)
        assert long_notes[0].let_ring is True


# ─── 功能 1c/1d：GP5 导出 ───────────────────────────────────────────────────


class TestGP5MultivoiceExport:
    """GP5 导出：超范围占位 fingering + 同 onset 不同 duration 用 tie。"""

    def test_gp5_export_handles_out_of_range(self, tmp_path: Path) -> None:
        events = [
            _make_event(0, 38, 0.0, 0.5, voice=2, string=None, fret=None),
            _make_event(1, 89, 0.5, 0.5, voice=2, string=None, fret=None),
        ]
        ir = _make_ir(events)
        out_path = tmp_path / "oor.gp5"

        result = GP5Exporter().export(ir, out_path)
        assert out_path.exists()
        assert result.note_count >= 2

        with open(out_path, "rb") as f:
            song = gp.parse(f)
        measure = song.tracks[0].measures[0]
        voice2_notes = [n for b in measure.voices[1].beats for n in b.notes]
        assert voice2_notes, "out-of-range notes should appear in voice 2"
        # 低音超范围 → string 6（low E）；高音超范围 → string 1（high E）且 fret 超 24。
        assert any(n.string == 6 for n in voice2_notes)
        assert any(n.string == 1 and n.value > 24 for n in voice2_notes)

    def test_gp5_export_chord_unequal_duration_tie(self, tmp_path: Path) -> None:
        events = [
            _make_event(0, 60, 0.0, 0.5, voice=1, string=4, fret=10),
            _make_event(1, 64, 0.0, 2.0, voice=1, string=1, fret=0),
        ]
        ir = _make_ir(events)
        out_path = tmp_path / "chord.gp5"

        result = GP5Exporter().export(ir, out_path)
        assert result.note_count >= 3

        with open(out_path, "rb") as f:
            song = gp.parse(f)
        notes = [
            n
            for m in song.tracks[0].measures
            for v in m.voices
            for b in v.beats
            for n in b.notes
        ]
        assert any(n.type == gp.NoteType.tie for n in notes), (
            "chord release should be expressed with a tie"
        )

    def test_gp5_export_measure_overflow_guarded(self, tmp_path: Path) -> None:
        """IR 异常（长音符越过小节结束）时，tie 延长被截断，文件仍可回读。"""
        events = [
            _make_event(0, 60, 0.0, 0.5, voice=1, string=4, fret=10),
            _make_event(1, 64, 0.0, 4.5, voice=1, string=1, fret=0),
        ]
        ir = _make_ir(events)
        out_path = tmp_path / "overflow.gp5"

        result = GP5Exporter().export(ir, out_path)
        # 触发了防御性截断告警。
        assert any(
            "truncated" in w.lower() or "measure overflow" in w.lower()
            for w in result.warnings
        )
        # 文件仍可被 guitarpro 回读（未损坏）。
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        assert song is not None
        assert len(song.tracks[0].measures) >= 1


# ─── 功能 2：定弦用户覆盖 API ───────────────────────────────────────────────


class TestTuningOverrideAPI:
    """repair 传 tuning_id 覆盖自动检测；GET /tunings 返回 12 套定弦。"""

    def test_tuning_override_api(
        self, client: TestClient, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_midi_file(tmp_path / "tuning_override.mid")
        with open(midi_path, "rb") as f:
            create_res = client.post(
                "/api/projects",
                files={"file": ("tuning_override.mid", f, "audio/midi")},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
        project_id = create_res.json()["data"]["id"]

        # 非法 tuning_id → 400。
        bad = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5, "tuning_id": "nonexistent"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert bad.status_code == 400

        # 合法 tuning_id → cleanup 使用指定定弦（覆盖自动检测）。
        res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5, "tuning_id": "drop_d_6"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        cleanup = res.json()["data"]["cleanup"]
        assert cleanup is not None
        assert cleanup["tuning_id"] == "drop_d_6"

    def test_tunings_list_api(self, client: TestClient, auth_token: str) -> None:
        res = client.get(
            "/api/tunings", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert res.status_code == 200
        items = res.json()["data"]["items"]
        assert len(items) == 12
        assert all(
            {"id", "name", "display_name", "string_count", "min_pitch", "max_pitch"}
            <= set(t.keys())
            for t in items
        )
        ids = {t["id"] for t in items}
        assert "standard_6" in ids
        assert "standard_8" in ids


# ─── 功能 1e：Tokyo Midnight 完整跑通 ──────────────────────────────────────


class TestTokyoMidnightMultivoice:
    """真实脏样本：voice 2 全 unplayable，voice 1 全 playable，导出不抛异常。"""

    def test_tokyo_midnight_full_multivoice(self, tmp_path: Path) -> None:
        timeline = load_midi(_FIXTURE)
        cleaned_track, role = _tokyo_cleaned_track(timeline)

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
        )
        ir = pipeline.execute(ctx)

        events = [e for t in ir.tracks for m in t.measures for e in m.events]
        voice1 = [e for e in events if e.score.voice == 1]
        voice2 = [e for e in events if e.score.voice == 2]

        assert voice2, "Tokyo Midnight 应包含超范围音符（voice 2）"
        assert all(not e.fingering.playable for e in voice2)
        assert all(e.fingering.playable for e in voice1)

        # GP5 导出不应抛异常。
        out_path = tmp_path / "tokyo.gp5"
        result = GP5Exporter().export(ir, out_path)
        assert out_path.exists()
        assert result.note_count > 0

        # 回读校验：导出文件必须能被 guitarpro 重新解析（回归：小节溢出损坏）。
        # 声部分离后可能产出多轨（Lead + Rhythm），须统计所有轨的音符。
        with open(out_path, "rb") as f:
            song = gp.parse(f)
        parsed_notes = sum(
            len(b.notes)
            for track in song.tracks
            for m in track.measures
            for v in m.voices
            for b in v.beats
        )
        assert parsed_notes == result.note_count

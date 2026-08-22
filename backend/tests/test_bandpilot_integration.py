"""BandPilot integration tests — mixed MIDI → multi-track .gp5 export.

Covers the full end-to-end contract:

1. **API flow**: upload a mixed MIDI (guitar + drums) → family detection →
   repair (both FretPilot and StickPilot pipelines) → `ir_merged.json`
   written with the documented ``{"guitar": {...}|null, "drum": {...}|null}``
   layout → gp5 export → parse back with PyGuitarPro and verify a
   non-percussion guitar track + a percussion drum track sharing measure
   headers.

2. **Unit flow**: ``load_merged_irs`` → ``export_bandpilot`` for the
   guitar-only, drum-only, and combined cases — including tracks whose IRs
   span different measure counts (the shorter track must be padded with
   rest-only measures so all tracks share one measure count).

Regression coverage: the guitar IR must never pick up a drum stream
(previously the drum track won the max-note-count stream selection, so the
"guitar" IR held drum notes and the exported .gp5 had two "Drums" tracks).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import guitarpro as gp
import mido
import pytest

from fretpilot.exporters.gp5 import export_bandpilot
from fretpilot.ir.drum_models import (
    DrumHitLocation,
    DrumMeasure,
    DrumNoteEvent,
    DrumProjectIR,
    DrumTrackIR,
)
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
from fretpilot.ir.serde import load_merged_irs

_TPB = 480

# GM drum pitches used by the synthetic drum track.
_DRUM_PITCHES = {36, 38, 42}

# Guitar riff: E3–E4 range, safely inside standard 6-string tuning.
_GUITAR_NOTES = [
    (52, 90), (55, 90), (59, 90), (52, 90),
    (57, 90), (60, 90), (55, 90), (59, 90),
]


def _make_mixed_midi(
    path: Path,
    *,
    guitar_notes: list[tuple[int, int]] | None = None,
    drum_notes: list[tuple[int, int]] | None = None,
) -> Path:
    """Write a type-1 MIDI with a guitar track and a GM-percussion drum track."""
    guitar_notes = guitar_notes if guitar_notes is not None else _GUITAR_NOTES
    drum_notes = drum_notes if drum_notes is not None else (
        [(36, 100), (38, 90), (42, 70)] * 5 + [(36, 100)]
    )

    midi = mido.MidiFile(type=1, ticks_per_beat=_TPB)
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    meta.append(
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
    )
    midi.tracks.append(meta)

    def _build_track(
        name: str, program: int, channel: int, notes: list[tuple[int, int]]
    ) -> mido.MidiTrack:
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=name, time=0))
        track.append(
            mido.Message("program_change", program=program, channel=channel, time=0)
        )
        events: list[tuple[int, int, str, int, int]] = []
        for i, (pitch, vel) in enumerate(notes):
            start = i * _TPB
            duration = _TPB // 2
            events.append((start, 0, "note_on", pitch, vel))
            events.append((start + duration, 1, "note_off", pitch, 0))
        events.sort(key=lambda e: (e[0], e[1]))
        last_tick = 0
        for tick, _priority, msg_type, pitch, vel in events:
            delta = max(0, tick - last_tick)
            track.append(
                mido.Message(msg_type, note=pitch, velocity=vel, channel=channel, time=delta)
            )
            last_tick = tick
        return track

    midi.tracks.append(_build_track("Guitar", 30, 0, guitar_notes))
    midi.tracks.append(_build_track("Drums", 0, 9, drum_notes))
    midi.save(path)
    return path


def _create_project(
    client, auth_token: str, midi_path: Path
) -> int:
    """Upload a MIDI and return the created project id."""
    with open(midi_path, "rb") as f:
        res = client.post(
            "/api/projects",
            files={"file": (midi_path.name, f, "audio/midi")},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
    assert res.status_code == 200, res.text
    return res.json()["data"]["id"]


def _notes_of(song: gp.Song) -> list[list[gp.Note]]:
    """Return per-track note lists (flattened across measures/voices/beats)."""
    return [
        [
            n
            for m in track.measures
            for v in m.voices
            for b in v.beats
            for n in b.notes
        ]
        for track in song.tracks
    ]


# ─── IR builders for the unit-level export tests ───


def _build_guitar_ir(*, measure_count: int = 1) -> GuitarProjectIR:
    """Build a minimal guitar IR with ``measure_count`` measures of 4 notes."""
    measures: list[GuitarMeasure] = []
    for m in range(1, measure_count + 1):
        events = [
            GuitarNoteEvent(
                id=f"n-{m:02d}{i:03d}",
                source_note_index=(m - 1) * 4 + i,
                pitch=52 + i,
                score=ScoreTiming(
                    start_beat=float(m - 1) * 4.0 + float(i),
                    duration_beats=0.5,
                    measure_number=m,
                    beat_in_measure=float(i),
                    voice=1,
                    tie_in=False,
                    tie_out=False,
                ),
                performance=PerformanceTiming(
                    source_start_beat=float(m - 1) * 4.0 + float(i),
                    source_duration_beats=0.48,
                    velocity=90,
                ),
                fingering=IRFingering(string=3, fret=i),
                articulations=[],
            )
            for i in range(4)
        ]
        measures.append(
            GuitarMeasure(
                number=m,
                start_beat=float(m - 1) * 4.0,
                duration_beats=4.0,
                numerator=4,
                denominator=4,
                events=events,
            )
        )
    track = GuitarTrackIR(
        id="guitar-1",
        name="Guitar",
        source_track_index=1,
        role="rhythm",
        tuning=[40, 45, 50, 55, 59, 64],
        fret_count=24,
        measures=measures,
    )
    return GuitarProjectIR(
        title="BandPilot Unit",
        source="unit.mid",
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[
            IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
        style_label="rock",
        midi_fidelity=0.5,
    )


def _build_drum_ir(*, measure_count: int = 1) -> DrumProjectIR:
    """Build a minimal drum IR with ``measure_count`` measures of kick hits."""
    measures: list[DrumMeasure] = []
    for m in range(1, measure_count + 1):
        events = [
            DrumNoteEvent(
                id=f"d-{m:02d}{i:03d}",
                source_note_index=(m - 1) * 4 + i,
                pitch=36,
                piece="kick",
                score=ScoreTiming(
                    start_beat=float(m - 1) * 4.0 + float(i),
                    duration_beats=0.5,
                    measure_number=m,
                    beat_in_measure=float(i),
                    voice=1,
                    tie_in=False,
                    tie_out=False,
                ),
                performance=PerformanceTiming(
                    source_start_beat=float(m - 1) * 4.0 + float(i),
                    source_duration_beats=0.45,
                    velocity=100,
                ),
                location=DrumHitLocation(piece="kick", sticking="R", technique="normal"),
            )
            for i in range(4)
        ]
        measures.append(
            DrumMeasure(
                number=m,
                start_beat=float(m - 1) * 4.0,
                duration_beats=4.0,
                numerator=4,
                denominator=4,
                pattern="beat",
                events=events,
            )
        )
    track = DrumTrackIR(
        id="drum-1",
        name="Drums",
        source_track_index=2,
        kit="standard_5pc",
        style="rock",
        measures=measures,
    )
    return DrumProjectIR(
        title="BandPilot Unit",
        source="unit.mid",
        tempo_map=[IRTempoEvent(beat=0.0, bpm=120.0)],
        time_signatures=[
            IRTimeSignatureEvent(beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
        style_label="rock",
    )


def _write_merged_ir(
    project_dir: Path, guitar_ir: GuitarProjectIR | None, drum_ir: DrumProjectIR | None
) -> Path:
    """Write an ``ir_merged.json`` in the documented contract and return its path."""
    path = project_dir / "ir_merged.json"
    path.write_text(
        json.dumps(
            {
                "guitar": guitar_ir.to_dict() if guitar_ir is not None else None,
                "drum": drum_ir.to_dict() if drum_ir is not None else None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


# ─── API end-to-end tests ───


class TestMixedMidiApiFlow:
    """Upload → detect → repair → export → parse-back for a mixed MIDI."""

    def test_family_detection(self, client, auth_token: str, tmp_path: Path) -> None:
        midi_path = _make_mixed_midi(tmp_path / "mixed.mid")
        project_id = _create_project(client, auth_token, midi_path)

        res = client.get(
            f"/api/projects/{project_id}/tracks",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200
        tracks = res.json()["data"]["tracks"]
        by_name = {t["name"]: t for t in tracks}
        assert set(by_name) == {"Guitar", "Drums"}
        assert by_name["Guitar"]["family"] == "guitar"
        assert by_name["Guitar"]["is_drum"] is False
        assert by_name["Drums"]["family"] == "drums"
        assert by_name["Drums"]["is_drum"] is True

    def test_repair_export_parse_back(
        self, client, auth_token: str, tmp_path: Path
    ) -> None:
        midi_path = _make_mixed_midi(tmp_path / "mixed.mid")
        project_id = _create_project(client, auth_token, midi_path)

        res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["status"] == "repaired"
        assert data["has_drums"] is True
        assert data["note_count"] == len(_GUITAR_NOTES) + 16  # 8 guitar + 16 drums

        # Both pipelines must have run their full 8-stage loops.
        modules = {t["module"] for t in data["tracks_repaired"]}
        assert modules == {"fretpilot", "stickpilot"}
        for t in data["tracks_repaired"]:
            assert t["stages_completed"] == 8

        # Export and parse back.
        res = client.post(
            f"/api/projects/{project_id}/export",
            json={"format": "gp5"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["note_count"] == 24

        url = res.json()["data"]["download_url"]
        res = client.get(url, headers={"Authorization": f"Bearer {auth_token}"})
        assert res.status_code == 200
        song = gp.parse(io.BytesIO(res.content))

        assert len(song.tracks) == 2
        guitar_track = song.tracks[0]
        drum_track = song.tracks[1]
        assert guitar_track.name == "Guitar"
        assert guitar_track.isPercussionTrack is False
        assert drum_track.name == "Drums"
        assert drum_track.isPercussionTrack is True

        # Shared measure structure: both tracks and the headers must agree.
        assert len(guitar_track.measures) == len(drum_track.measures)
        assert len(guitar_track.measures) == len(song.measureHeaders)

        # Guitar notes live on the non-percussion track (fret values ≠ GM drum
        # pitches); GM drum pitches live only on the percussion track.
        guitar_notes, drum_notes = _notes_of(song)
        assert guitar_notes, "expected guitar notes on the non-percussion track"
        assert drum_notes, "expected drum notes on the percussion track"
        guitar_pitches = {n.value for n in guitar_notes}
        drum_pitches = {n.value for n in drum_notes}
        assert guitar_pitches.isdisjoint(_DRUM_PITCHES)
        assert drum_pitches <= _DRUM_PITCHES

        assert song.tempo == 120
        for header in song.measureHeaders:
            assert header.timeSignature.numerator == 4
            assert header.timeSignature.denominator.value == 4

    def test_ir_merged_contract(
        self, client, auth_token: str, tmp_path: Path
    ) -> None:
        """Regression: the guitar IR must hold guitar content, not a drum stream.

        Previously the drum track (more notes) won the max-note-count stream
        selection inside cleanup, so ``ir_merged.json``'s "guitar" slot held a
        track named "Drums" with GM pitches, and the exported .gp5 had two
        "Drums" tracks. This test pins the corrected behaviour.
        """
        midi_path = _make_mixed_midi(tmp_path / "mixed.mid")
        project_id = _create_project(client, auth_token, midi_path)
        res = client.post(
            f"/api/projects/{project_id}/repair",
            json={"midi_fidelity": 0.5},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert res.status_code == 200

        # Locate the project storage dir under the test job root (user id is
        # not hard-coded — find the dir by project id).
        from fretpilot.config import get_settings

        merged_path = next(
            p
            for p in get_settings().job_root_path.glob(
                f"*/{project_id}/ir_merged.json"
            )
        )
        assert merged_path.exists()

        raw = json.loads(merged_path.read_text(encoding="utf-8"))
        assert set(raw) == {"guitar", "drum"}
        assert raw["guitar"] is not None
        assert raw["drum"] is not None

        guitar_ir, drum_ir = load_merged_irs(merged_path)
        assert guitar_ir is not None and drum_ir is not None
        assert guitar_ir.tracks[0].name == "Guitar"
        assert drum_ir.tracks[0].name == "Drums"

        guitar_pitches = {
            e.pitch
            for t in guitar_ir.tracks
            for m in t.measures
            for e in m.events
        }
        assert guitar_pitches.isdisjoint(_DRUM_PITCHES), (
            "guitar IR must not contain GM drum pitches"
        )
        drum_pitches = {
            e.pitch
            for t in drum_ir.tracks
            for m in t.measures
            for e in m.events
        }
        assert drum_pitches <= _DRUM_PITCHES


# ─── Unit-level export tests (load_merged_irs → export_bandpilot) ───


class TestBandpilotExportUnit:
    """Direct ``load_merged_irs`` + ``export_bandpilot`` round-trips."""

    def test_guitar_only_merged(self, tmp_path: Path) -> None:
        guitar_ir = _build_guitar_ir()
        merged = _write_merged_ir(tmp_path, guitar_ir, None)
        g, d = load_merged_irs(merged)
        assert d is None

        out = tmp_path / "guitar_only.gp5"
        result = export_bandpilot(g, None, out)
        assert result.note_count == 4

        song = gp.parse(str(out))
        assert len(song.tracks) == 1
        assert song.tracks[0].isPercussionTrack is False
        assert song.tracks[0].name == "Guitar"

    def test_drum_only_merged(self, tmp_path: Path) -> None:
        drum_ir = _build_drum_ir()
        merged = _write_merged_ir(tmp_path, None, drum_ir)
        g, d = load_merged_irs(merged)
        assert g is None

        out = tmp_path / "drum_only.gp5"
        result = export_bandpilot(None, d, out)
        assert result.note_count == 4

        song = gp.parse(str(out))
        assert len(song.tracks) == 1
        assert song.tracks[0].isPercussionTrack is True
        assert song.tracks[0].name == "Drums"

    def test_both_ir_shared_measure_count(self, tmp_path: Path) -> None:
        """Guitar IR spans fewer measures than drum IR → guitar tail is rests."""
        guitar_ir = _build_guitar_ir(measure_count=1)
        drum_ir = _build_drum_ir(measure_count=2)
        merged = _write_merged_ir(tmp_path, guitar_ir, drum_ir)
        g, d = load_merged_irs(merged)

        out = tmp_path / "both.gp5"
        result = export_bandpilot(g, d, out)
        assert result.measure_count == 2

        song = gp.parse(str(out))
        assert len(song.tracks) == 2
        assert len(song.measureHeaders) == 2
        assert song.tracks[0].name == "Guitar"
        assert song.tracks[0].isPercussionTrack is False
        assert song.tracks[1].name == "Drums"
        assert song.tracks[1].isPercussionTrack is True

        guitar_notes, drum_notes = _notes_of(song)
        assert len(guitar_notes) == 4          # only measure 1 has guitar notes
        assert len(drum_notes) == 8            # drums span both measures

        # The guitar track's trailing (padded) measure must be rest-only.
        guitar_measure_2 = song.tracks[0].measures[1]
        padded_beats = [
            b for v in guitar_measure_2.voices for b in v.beats
        ]
        assert padded_beats, "padded measure must contain rest beats"
        assert all(b.notes == [] for b in padded_beats)

    def test_load_merged_irs_rejects_missing_keys(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"guitar": None}), encoding="utf-8")
        with pytest.raises(ValueError, match="guitar"):
            load_merged_irs(bad)

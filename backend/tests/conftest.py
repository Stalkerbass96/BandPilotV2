"""Pytest configuration and shared fixtures for FretPilot v2 tests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import mido
import pytest

# Set test environment variables BEFORE importing fretpilot modules.
_TMP_DIR = tempfile.mkdtemp(prefix="fretpilot_test_")
os.environ.setdefault("FRETPILOR_DEBUG", "true")
os.environ.setdefault(
    "FRETPILOR_JWT_SECRET", "test-secret-key-with-at-least-32-bytes"
)
# Provide a stable Fernet master key so BYOK encrypt/decrypt round-trips work
# deterministically across the whole test session (an empty key would make
# ``get_key_vault`` generate a *new* random key on every call, breaking decryption).
try:
    from cryptography.fernet import Fernet

    os.environ.setdefault("FRETPILOR_MASTER_KEY", Fernet.generate_key().decode())
except Exception:  # pragma: no cover - cryptography is a hard dependency
    os.environ.setdefault("FRETPILOR_MASTER_KEY", "")
os.environ.setdefault("FRETPILOR_DATABASE_URL", f"sqlite:///{_TMP_DIR}/test.db")
os.environ.setdefault("FRETPILOR_JOB_ROOT", f"{_TMP_DIR}/job_root")
os.environ.setdefault("FRETPILOR_KNOWLEDGE_ROOT", f"{_TMP_DIR}/knowledge_store")
os.environ.setdefault("FRETPILOR_ADMIN_EMAILS", "test@fretpilot.dev")

# Ticks-per-beat used by the synthetic MIDI helpers below.
_TPB = 480


# ─── Shared helper builders (importable as ``from tests.conftest import ...``) ───


def _note(
    pitch: int,
    start_beat: float,
    duration_beats: float,
    program: int = 30,
    channel: int = 0,
    velocity: int = 80,
):
    """Build a :class:`NormalizedNote` with beat-based timing and derived ticks."""
    from fretpilot.midi.models import NormalizedNote

    return NormalizedNote(
        track_index=0,
        track_name="Guitar",
        channel=channel,
        pitch=pitch,
        velocity=velocity,
        start_tick=int(round(start_beat * _TPB)),
        duration_ticks=int(round(duration_beats * _TPB)),
        start_beat=start_beat,
        duration_beats=duration_beats,
        program=program,
    )


def _timeline(notes):
    """Build a :class:`NormalizedTimeline` with a single guitar track holding ``notes``."""
    from fretpilot.midi.gm import program_family, program_name
    from fretpilot.midi.models import (
        NormalizedTimeline,
        NormalizedTrack,
        ProgramEvent,
        TempoEvent,
        TimeSignatureEvent,
    )

    program = notes[0].program if notes else None
    track = NormalizedTrack(
        index=0,
        name="Guitar",
        notes=list(notes),
        program=program,
        instrument_name="Guitar",
    )
    program_events: list[ProgramEvent] = []
    if program is not None:
        program_events.append(
            ProgramEvent(
                track_index=0,
                channel=0,
                tick=0,
                beat=0.0,
                program=program,
                program_name=program_name(program),
                family=program_family(program),
            )
        )
    return NormalizedTimeline(
        source="test.mid",
        midi_type=1,
        ticks_per_beat=_TPB,
        tempo_events=[TempoEvent(tick=0, beat=0.0, bpm=120.0)],
        time_signature_events=[
            TimeSignatureEvent(tick=0, beat=0.0, numerator=4, denominator=4)
        ],
        tracks=[track],
        program_events=program_events,
    )


class _MockAdvisor:
    """A no-op :class:`RewriteAdvisor` mock — never makes real LLM calls."""

    def __init__(self) -> None:
        from fretpilot.ai.models import AIProviderIdentity

        self.identity = AIProviderIdentity(provider="mock", model="mock-model")

    def infer_style(self, features) -> str:
        return "metal"

    def propose_rewrite(self, request):
        from fretpilot.ai.models import RewriteResponse

        return RewriteResponse()


def _make_midi_file(
    path: Path,
    notes=None,
    program: int = 30,
    tpb: int = _TPB,
    bpm: int = 120,
) -> Path:
    """Write a minimal type-1 MIDI file and return its path.

    ``notes`` is an optional list of ``(pitch, start_tick, duration_tick, velocity)``
    tuples. When omitted, a one-octave C-major scale (8 notes, 1 beat apart,
    half-beat duration, velocity 80) is generated — matching the expectations of
    :mod:`tests.test_midi_parser`.
    """
    if notes is None:
        pitches = [60, 62, 64, 65, 67, 69, 71, 72]
        notes = [(p, i * tpb, tpb // 2, 80) for i, p in enumerate(pitches)]

    midi = mido.MidiFile(type=1, ticks_per_beat=tpb)

    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    meta.append(
        mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
    )
    midi.tracks.append(meta)

    track = mido.MidiTrack()
    track.append(
        mido.Message("program_change", program=program, channel=0, time=0)
    )

    # Build absolute-tick events then convert to delta times.
    events = []
    for pitch, start, dur, vel in notes:
        events.append((start, 0, "note_on", pitch, vel))
        events.append((start + dur, 1, "note_off", pitch, 0))
    events.sort(key=lambda e: (e[0], e[1]))

    last_tick = 0
    for tick, _priority, msg_type, pitch, vel in events:
        delta = max(0, tick - last_tick)
        track.append(
            mido.Message(msg_type, note=pitch, velocity=vel, channel=0, time=delta)
        )
        last_tick = tick

    midi.tracks.append(track)
    midi.save(path)
    return path


# ─── Session-scoped fixtures ───


@pytest.fixture(scope="session")
def assets_dir() -> Path:
    """Return the path to bundled knowledge assets."""
    from fretpilot.config import get_settings

    return get_settings().assets_dir


@pytest.fixture(scope="session")
def registry(assets_dir: Path):
    """Return a KnowledgeRegistry loaded from the bundled assets."""
    from fretpilot.knowledge.registry import KnowledgeRegistry

    return KnowledgeRegistry.from_assets_dir(assets_dir)


@pytest.fixture(scope="session")
def knowledge_engine(registry):
    """Return a KnowledgeEngine backed by the bundled registry."""
    from fretpilot.knowledge.engine import KnowledgeEngine

    return KnowledgeEngine(registry)


# ─── MIDI / pipeline fixtures (built from a real synthetic MIDI) ───


@pytest.fixture
def tmp_midi_path(tmp_path: Path) -> Path:
    """Create a minimal MIDI file with a short guitar-like melody and return its path."""
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    meta_track = mido.MidiTrack()
    meta_track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))
    meta_track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    midi.tracks.append(meta_track)

    note_track = mido.MidiTrack()
    note_track.append(mido.Message("program_change", program=30, channel=0, time=0))  # Distortion Guitar

    # Simple E minor riff: E2, G2, B2 each lasting 1 beat
    notes = [
        (40, 0, 480),   # E2 at beat 0, 1 beat
        (43, 480, 480), # G2 at beat 1, 1 beat
        (47, 960, 480), # B2 at beat 2, 1 beat
        (40, 1440, 480),# E2 at beat 3, 1 beat
    ]
    for pitch, start_offset, duration in notes:
        note_track.append(mido.Message("note_on", note=pitch, velocity=100, channel=0, time=start_offset if pitch == 40 and start_offset == 0 else 0))
        note_track.append(mido.Message("note_off", note=pitch, velocity=0, channel=0, time=duration))

    midi.tracks.append(note_track)

    path = tmp_path / "test_guitar.mid"
    midi.save(path)
    return path


@pytest.fixture
def normalized_timeline(tmp_midi_path: Path):
    """Return a NormalizedTimeline parsed from the test MIDI."""
    from fretpilot.midi.parser import load_midi

    return load_midi(tmp_midi_path)


@pytest.fixture
def guitar_track(normalized_timeline):
    """Return the primary guitar track from the test timeline."""
    from fretpilot.detection import classify_timeline

    report = classify_timeline(normalized_timeline)
    assert report.primary_guitar_track_index is not None, "Expected a guitar track in test MIDI"
    return normalized_timeline.tracks[report.primary_guitar_track_index]


@pytest.fixture
def pipeline_context(normalized_timeline, guitar_track, registry):
    """Return a PipelineContext ready for pipeline execution."""
    from fretpilot.engine.context import PipelineContext

    return PipelineContext(
        timeline=normalized_timeline,
        track=guitar_track,
        knowledge=registry,
        style_label="rock",
        midi_fidelity=0.5,
        advisor=None,
        track_role="rhythm",
        source_track_index=guitar_track.index,
        degraded_mode=True,
    )


@pytest.fixture
def repaired_ir(pipeline_context, knowledge_engine):
    """Run the full pipeline and return the assembled GuitarProjectIR."""
    from fretpilot.engine.pipeline import RepairPipeline

    pipeline = RepairPipeline(knowledge_engine)
    return pipeline.execute(pipeline_context)


# ─── Fixtures for the pipeline-stage unit tests ───


@pytest.fixture
def engine(knowledge_engine):
    """Alias of ``knowledge_engine`` for tests that inject it as ``engine``."""
    return knowledge_engine


@pytest.fixture
def pipeline(knowledge_engine):
    """Return a :class:`RepairPipeline` wired to the bundled knowledge engine."""
    from fretpilot.engine.pipeline import RepairPipeline

    return RepairPipeline(knowledge_engine)


@pytest.fixture
def midi_file(tmp_path: Path) -> Path:
    """Return a path to a C-major-scale MIDI file for parser tests."""
    path = tmp_path / "test_c_major.mid"
    _make_midi_file(path)
    return path


# ─── Fixtures for the API integration tests ───


@pytest.fixture
def client():
    """Return a FastAPI ``TestClient`` backed by an isolated, clean SQLite DB."""
    from fastapi.testclient import TestClient

    from fretpilot.app import create_app
    from fretpilot.config import get_settings, reset_settings_cache
    from fretpilot.db.models import Base
    from fretpilot.db.session import get_engine

    reset_settings_cache()
    settings = get_settings()
    app = create_app(settings)

    with TestClient(app) as c:
        # The lifespan has initialised the DB engine by now; wipe all tables so
        # every test starts from a clean slate (independent, idempotent tests).
        engine_obj = get_engine()
        Base.metadata.drop_all(bind=engine_obj)
        Base.metadata.create_all(bind=engine_obj)

        # Also wipe the file-system job root — SQLite reuses rowids after
        # DROP/CREATE, so project paths (job_root/<uid>/<pid>) collide between
        # tests.  Stale IR/export files would cause false positives.
        import shutil
        job_root = Path(settings.job_root)
        if job_root.exists():
            shutil.rmtree(job_root)
        job_root.mkdir(parents=True, exist_ok=True)

        yield c


@pytest.fixture
def auth_token(client) -> str:
    """Create a verified user and return a JWT for ``test@fretpilot.dev``."""
    from fretpilot.api.security import create_access_token, hash_password
    from fretpilot.db.models import User
    from fretpilot.db.session import session_scope

    with session_scope() as db:
        user = User(
            email="test@fretpilot.dev",
            password_hash=hash_password("password123"),
        )
        db.add(user)
        db.flush()  # populate user.id without committing yet
        token = create_access_token(user.id)
    return token

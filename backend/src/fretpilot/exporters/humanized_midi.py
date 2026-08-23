"""Deterministic, profile-driven humanized MIDI export from canonical SongIR."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

import mido

from fretpilot.config import get_settings
from fretpilot.exporters.base import ExportResult
from fretpilot.ir.song import PerformanceEventIR, SongIR
from fretpilot.knowledge.registry import KnowledgeRegistry
from fretpilot.validation import validate_song

TICKS_PER_BEAT = 960


@dataclass(frozen=True, slots=True)
class HumanizationProfile:
    profile_id: str
    timing_jitter_beats: float
    velocity_jitter: int
    downbeat_accent: int
    backbeat_accent: int
    gate_ratio: float
    source_deviation_limit: float
    seed: str


NATURAL_BAND_PROFILE = HumanizationProfile(
    profile_id="natural-band-v1",
    timing_jitter_beats=0.012,
    velocity_jitter=3,
    downbeat_accent=5,
    backbeat_accent=2,
    gate_ratio=0.96,
    source_deviation_limit=0.04,
    seed="bandpilot-natural-band-v1",
)


def load_humanization_profile(profile_id: str = "natural-band-v1") -> HumanizationProfile:
    """Load a versioned, approved humanization profile from the knowledge base."""
    registry = KnowledgeRegistry.from_assets_dir(get_settings().assets_dir)
    payload = registry.query_payload(
        domain="performance_profiles", scope={"profile": [profile_id]}
    )
    if not payload:
        raise KeyError(f"Unknown humanization profile: {profile_id}")
    return HumanizationProfile(
        profile_id=str(payload["profile_id"]),
        timing_jitter_beats=float(payload["timing_jitter_beats"]),
        velocity_jitter=int(payload["velocity_jitter"]),
        downbeat_accent=int(payload["downbeat_accent"]),
        backbeat_accent=int(payload["backbeat_accent"]),
        gate_ratio=float(payload["gate_ratio"]),
        source_deviation_limit=float(payload["source_deviation_limit"]),
        seed=str(payload["seed"]),
    )


def _unit(seed: str, key: str) -> float:
    raw = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(raw[:8], "big") / (2**64 - 1)


def humanize_performance(
    song: SongIR,
    profile: HumanizationProfile | None = None,
) -> list[PerformanceEventIR]:
    """Return a new performance layer; never mutate canonical score truth."""
    profile = profile or load_humanization_profile()
    score_events = {
        event.id: event
        for track in song.score.tracks
        for measure in track.measures
        for event in measure.events
    }
    result: list[PerformanceEventIR] = []
    for performance in song.performance.events:
        score = score_events.get(performance.note_id)
        if score is None:
            continue
        source_offset = performance.start_beat - score.score.start_beat
        source_offset = max(
            -profile.source_deviation_limit,
            min(profile.source_deviation_limit, source_offset),
        )
        chord_key = f"{score.source.source_track_index}:{score.score.start_beat:.6f}"
        jitter = (_unit(profile.seed, chord_key) * 2 - 1) * profile.timing_jitter_beats
        start = max(0.0, score.score.start_beat + source_offset + jitter)
        gate_source = min(performance.duration_beats, score.score.duration_beats * 1.15)
        duration = max(0.03, gate_source * profile.gate_ratio)
        beat_index = int(round(score.score.start_beat))
        accent = profile.downbeat_accent if beat_index % 4 == 0 else 0
        if beat_index % 4 in {1, 3}:
            accent += profile.backbeat_accent
        velocity_jitter = int(
            round((_unit(profile.seed, performance.note_id) * 2 - 1) * profile.velocity_jitter)
        )
        result.append(
            replace(
                performance,
                start_beat=start,
                duration_beats=duration,
                velocity=max(1, min(127, performance.velocity + accent + velocity_jitter)),
            )
        )
    return result


def _tick(beat: float) -> int:
    return max(0, int(round(beat * TICKS_PER_BEAT)))


def _channel_map(song: SongIR) -> dict[str, int]:
    result: dict[str, int] = {}
    channel = 0
    for track in song.score.tracks:
        if track.family == "drums":
            result[track.id] = 9
            continue
        while channel == 9:
            channel += 1
        result[track.id] = channel % 16
        channel += 1
    return result


def _conductor(song: SongIR) -> mido.MidiTrack:
    events: list[tuple[int, int, mido.MetaMessage]] = []
    for tempo in song.score.tempo_map:
        events.append(
            (
                _tick(tempo.beat),
                0,
                mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo.bpm), time=0),
            )
        )
    for signature in song.score.time_signatures:
        events.append(
            (
                _tick(signature.beat),
                1,
                mido.MetaMessage(
                    "time_signature",
                    numerator=signature.numerator,
                    denominator=signature.denominator,
                    time=0,
                ),
            )
        )
    if not events:
        events.append((0, 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0)))
    track = mido.MidiTrack([mido.MetaMessage("track_name", name="BandPilot Conductor", time=0)])
    previous = 0
    for tick, _priority, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = tick - previous
        track.append(message)
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return track


class HumanizedMidiSongExporter:
    format_id = "humanized_midi"

    def __init__(self, profile: HumanizationProfile | None = None) -> None:
        self.profile = profile

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        validate_song(song, raise_on_error=True)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_BEAT)
        midi.tracks.append(_conductor(song))
        profile = self.profile or load_humanization_profile()
        performance = {event.note_id: event for event in humanize_performance(song, profile)}
        channels = _channel_map(song)
        note_count = 0
        for score_track in song.score.tracks:
            channel = channels[score_track.id]
            track = mido.MidiTrack()
            track.append(mido.MetaMessage("track_name", name=score_track.name[:127], time=0))
            if score_track.family != "drums":
                program = max(0, min(127, int(score_track.instrument.get("program", 0))))
                track.append(mido.Message("program_change", program=program, channel=channel, time=0))
            timed: list[tuple[int, int, mido.Message]] = []
            for measure in score_track.measures:
                for event in measure.events:
                    # A split note is one sounding performance event; tie continuations
                    # are notation-only and must not retrigger MIDI.
                    if event.score.tie_in:
                        continue
                    rendered = performance[event.id]
                    start = _tick(rendered.start_beat)
                    end = max(start + 1, _tick(rendered.start_beat + rendered.duration_beats))
                    timed.append(
                        (start, 1, mido.Message("note_on", note=event.pitch, velocity=rendered.velocity, channel=channel, time=0))
                    )
                    timed.append(
                        (end, 0, mido.Message("note_off", note=event.pitch, velocity=0, channel=channel, time=0))
                    )
                    note_count += 1
            previous = 0
            for tick, _priority, message in sorted(timed, key=lambda item: (item[0], item[1])):
                message.time = tick - previous
                track.append(message)
                previous = tick
            track.append(mido.MetaMessage("end_of_track", time=0))
            midi.tracks.append(track)
        midi.save(destination)
        return ExportResult(
            format_id=self.format_id,
            path=str(destination),
            measure_count=max((len(track.measures) for track in song.score.tracks), default=0),
            note_count=note_count,
            warnings=[f"Humanization profile: {profile.profile_id}"],
        )


__all__ = [
    "HumanizationProfile",
    "HumanizedMidiSongExporter",
    "NATURAL_BAND_PROFILE",
    "TICKS_PER_BEAT",
    "humanize_performance",
    "load_humanization_profile",
]

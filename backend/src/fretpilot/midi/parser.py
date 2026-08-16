"""SMF (Standard MIDI File) parsing and normalization.

Reads a MIDI file with ``mido`` and produces a :class:`NormalizedTimeline`
that preserves physical tracks, channels, program changes, source ticks,
and derived beat values. No quantization or repair happens here.

Functions are kept small (≤80 lines) to avoid the god-function anti-pattern.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from pathlib import Path

import mido
from mido.midifiles import meta as midi_meta

from fretpilot.midi.gm import program_family, program_name
from fretpilot.midi.models import (
    Diagnostic,
    NormalizedNote,
    NormalizedTimeline,
    NormalizedTrack,
    ProgramEvent,
    TempoEvent,
    TimeSignatureEvent,
)

logger = logging.getLogger("fretpilot.midi.parser")

DEFAULT_TEMPO_US_PER_BEAT = 500_000  # MIDI default: 120 BPM
DEFAULT_TIME_SIGNATURE = (4, 4)

# A lock serializes the temporary mido-decode patch used by the tolerant loader
# so concurrent ``load_midi`` calls on a threaded server never interleave.
_MIDI_LOAD_LOCK = threading.Lock()
# Fallback key name used when an out-of-range key signature is encountered.
_FALLBACK_KEY_SIGNATURE = "C"


def _beat(tick: int, ticks_per_beat: int) -> float:
    """Convert an absolute tick to a beat position."""
    return tick / ticks_per_beat


def _extract_track_metadata(track: mido.MidiTrack) -> tuple[str, str | None]:
    """Return (track_name, instrument_name) from the first metadata messages."""
    track_name = ""
    instrument_name: str | None = None
    for message in track:
        if message.type == "track_name" and message.name.strip():
            track_name = message.name.strip()
        elif message.type == "instrument_name" and message.name.strip():
            instrument_name = message.name.strip()
        if track_name and instrument_name:
            break
    return track_name or "", instrument_name


def _finalize_note(
    open_notes: dict,
    channel: int,
    pitch: int,
    close_tick: int,
    track_index: int,
    track_name: str,
    ticks_per_beat: int,
    notes: list[NormalizedNote],
    diagnostics: list[Diagnostic],
) -> None:
    """Pop the oldest open note for (channel, pitch) and append a NormalizedNote."""
    key = (channel, pitch)
    pending = open_notes.get(key)
    if not pending:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="unmatched_note_off",
                message=f"Note-off for MIDI note {pitch} has no matching note-on.",
                track_index=track_index,
                tick=close_tick,
            )
        )
        return

    start_tick, velocity, program = pending.popleft()
    duration_ticks = max(0, close_tick - start_tick)
    notes.append(
        NormalizedNote(
            track_index=track_index,
            track_name=track_name,
            channel=channel,
            pitch=pitch,
            velocity=velocity,
            start_tick=start_tick,
            duration_ticks=duration_ticks,
            start_beat=_beat(start_tick, ticks_per_beat),
            duration_beats=_beat(duration_ticks, ticks_per_beat),
            program=program,
        )
    )


def _collect_note_events(
    track: mido.MidiTrack,
    track_index: int,
    track_name: str,
    ticks_per_beat: int,
    diagnostics: list[Diagnostic],
) -> tuple[list[NormalizedNote], list[ProgramEvent], int | None]:
    """Walk a single track, producing normalized notes and program events."""
    absolute_tick = 0
    current_program: dict[int, int] = {}
    open_notes: dict[tuple[int, int], deque[tuple[int, int, int | None]]] = (
        defaultdict(deque)
    )
    notes: list[NormalizedNote] = []
    program_events: list[ProgramEvent] = []
    dominant_program: int | None = None

    for message in track:
        absolute_tick += int(message.time)

        if message.is_meta:
            continue

        if message.type == "program_change":
            program = int(message.program)
            channel = int(message.channel)
            current_program[channel] = program
            dominant_program = program
            program_events.append(
                ProgramEvent(
                    track_index=track_index,
                    channel=channel,
                    tick=absolute_tick,
                    beat=_beat(absolute_tick, ticks_per_beat),
                    program=program,
                    program_name=program_name(program),
                    family=program_family(program),
                )
            )
            continue

        if message.type == "note_on" and message.velocity > 0:
            channel = int(message.channel)
            open_notes[(channel, int(message.note))].append(
                (absolute_tick, int(message.velocity), current_program.get(channel))
            )
            continue

        is_note_end = message.type == "note_off" or (
            message.type == "note_on" and message.velocity == 0
        )
        if not is_note_end:
            continue

        _finalize_note(
            open_notes,
            channel=int(message.channel),
            pitch=int(message.note),
            close_tick=absolute_tick,
            track_index=track_index,
            track_name=track_name,
            ticks_per_beat=ticks_per_beat,
            notes=notes,
            diagnostics=diagnostics,
        )

    _report_unclosed_notes(open_notes, track_index, diagnostics)
    notes.sort(key=lambda n: (n.start_tick, n.pitch, n.channel))
    return notes, program_events, dominant_program


def _report_unclosed_notes(
    open_notes: dict,
    track_index: int,
    diagnostics: list[Diagnostic],
) -> None:
    """Emit diagnostics for notes that were never closed."""
    for (channel, pitch), pending in open_notes.items():
        for start_tick, _velocity, _program in pending:
            diagnostics.append(
                Diagnostic(
                    level="warning",
                    code="unclosed_note",
                    message=(
                        f"MIDI note {pitch} on channel {channel} has no matching note-off."
                    ),
                    track_index=track_index,
                    tick=start_tick,
                )
            )


def _ensure_initial_tempo(
    tempo_events: list[TempoEvent], diagnostics: list[Diagnostic]
) -> None:
    """Insert a default 120 BPM tempo at beat 0 if none exists."""
    if tempo_events and tempo_events[0].tick <= 0:
        return
    tempo_events.insert(
        0,
        TempoEvent(
            tick=0,
            beat=0.0,
            bpm=round(float(mido.tempo2bpm(DEFAULT_TEMPO_US_PER_BEAT)), 6),
        ),
    )
    diagnostics.append(
        Diagnostic(level="info", code="default_tempo",
                   message="No tempo at beat 0; MIDI default 120 BPM is used.", tick=0)
    )


def _ensure_initial_time_signature(
    time_signature_events: list[TimeSignatureEvent],
    diagnostics: list[Diagnostic],
) -> None:
    """Insert a default 4/4 time signature at beat 0 if none exists."""
    if time_signature_events and time_signature_events[0].tick <= 0:
        return
    numerator, denominator = DEFAULT_TIME_SIGNATURE
    time_signature_events.insert(
        0, TimeSignatureEvent(tick=0, beat=0.0, numerator=numerator, denominator=denominator)
    )
    diagnostics.append(
        Diagnostic(level="info", code="default_time_signature",
                   message="No time signature at beat 0; 4/4 is assumed.", tick=0)
    )


def _collect_global_meta(
    midi: mido.MidiFile,
    ticks_per_beat: int,
    tempo_events: list[TempoEvent],
    time_signature_events: list[TimeSignatureEvent],
) -> None:
    """Gather tempo and time-signature events from all tracks (SMF type 1)."""
    for track in midi.tracks:
        abs_tick = 0
        for message in track:
            abs_tick += int(message.time)
            if message.type == "set_tempo":
                tempo_events.append(
                    TempoEvent(
                        tick=abs_tick,
                        beat=_beat(abs_tick, ticks_per_beat),
                        bpm=round(float(mido.tempo2bpm(message.tempo)), 6),
                    )
                )
            elif message.type == "time_signature":
                time_signature_events.append(
                    TimeSignatureEvent(
                        tick=abs_tick,
                        beat=_beat(abs_tick, ticks_per_beat),
                        numerator=int(message.numerator),
                        denominator=int(message.denominator),
                    )
                )


def _process_track(
    track: mido.MidiTrack,
    track_index: int,
    ticks_per_beat: int,
    diagnostics: list[Diagnostic],
) -> tuple[NormalizedTrack, list[ProgramEvent]]:
    """Process one MIDI track into a NormalizedTrack plus program events."""
    track_name, instrument_name = _extract_track_metadata(track)
    if not track_name:
        track_name = f"Track {track_index + 1}"

    notes, program_events, dominant_program = _collect_note_events(
        track, track_index, track_name, ticks_per_beat, diagnostics
    )
    normalized = NormalizedTrack(
        index=track_index,
        name=track_name,
        notes=notes,
        instrument_name=instrument_name,
        program=dominant_program,
    )
    return normalized, program_events


def _record_load_diagnostics(
    invalid_keys: list[tuple[int, int]],
    malformed_tempo_lengths: list[int],
    diagnostics: list[Diagnostic],
) -> None:
    """Translate tolerant-parse findings into ``Diagnostic`` warnings."""
    for key, mode in invalid_keys:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="invalid_key_signature",
                message=(
                    f"Invalid key signature ({key} accidentals, mode {mode}) "
                    f"falls outside the legal -7..+7 range; treated as {_FALLBACK_KEY_SIGNATURE}."
                ),
            )
        )
    for length in malformed_tempo_lengths:
        diagnostics.append(
            Diagnostic(
                level="warning",
                code="malformed_tempo",
                message=(
                    f"Malformed set_tempo payload ({length} bytes, expected 3); "
                    "default 120 BPM is used."
                ),
            )
        )


def _load_midi_file_tolerant(
    source: Path, diagnostics: list[Diagnostic]
) -> mido.MidiFile:
    """Load a MIDI file while tolerating invalid key signatures and tempos.

    Suno exports systematically emit ``key_signature`` meta events with 18
    sharps (legal range is -7..+7), which makes ``mido.MidiFile`` raise
    ``KeySignatureError``. It can also emit ``set_tempo`` payloads shorter than
    3 bytes. This function temporarily patches mido's strict decoders so a
    single bad meta event is downgraded to a warning instead of aborting the
    entire file (and dropping all 2269 notes).
    """
    original_key_decode = midi_meta._key_signature_decode
    original_tempo_decode = midi_meta.MetaSpec_set_tempo.decode
    invalid_keys: list[tuple[int, int]] = []
    malformed_tempo_lengths: list[int] = []

    class _TolerantKeySignatureDecode(dict):
        """A key-signature table that records (and tolerates) unknown keys."""

        def __missing__(self, key: tuple[int, int]) -> str:
            invalid_keys.append(key)
            return _FALLBACK_KEY_SIGNATURE

    def _tolerant_tempo_decode(self, message: mido.MetaMessage, data: bytes) -> None:
        """Decode a tempo event, defaulting short payloads to 120 BPM."""
        if len(data) < 3:
            malformed_tempo_lengths.append(len(data))
            message.tempo = DEFAULT_TEMPO_US_PER_BEAT
            return
        original_tempo_decode(self, message, data)

    with _MIDI_LOAD_LOCK:
        midi_meta._key_signature_decode = _TolerantKeySignatureDecode(
            original_key_decode
        )
        midi_meta.MetaSpec_set_tempo.decode = _tolerant_tempo_decode
        try:
            midi = mido.MidiFile(source)
        finally:
            midi_meta._key_signature_decode = original_key_decode
            midi_meta.MetaSpec_set_tempo.decode = original_tempo_decode

    _record_load_diagnostics(invalid_keys, malformed_tempo_lengths, diagnostics)
    return midi


def load_midi(path: str | Path) -> NormalizedTimeline:
    """Read a Standard MIDI File and return a NormalizedTimeline.

    This stage does not quantize or repair anything. It preserves physical
    tracks, channels, program changes, source ticks, and derived beat values.
    Invalid key signatures and malformed tempo events are tolerated (recorded
    as diagnostics) so that parsing never aborts the whole file.
    """
    source = Path(path)
    diagnostics: list[Diagnostic] = []
    midi = _load_midi_file_tolerant(source, diagnostics)
    ticks_per_beat = midi.ticks_per_beat

    tempo_events: list[TempoEvent] = []
    time_signature_events: list[TimeSignatureEvent] = []
    program_events: list[ProgramEvent] = []
    normalized_tracks: list[NormalizedTrack] = []

    _collect_global_meta(midi, ticks_per_beat, tempo_events, time_signature_events)

    for track_index, track in enumerate(midi.tracks):
        normalized, track_programs = _process_track(
            track, track_index, ticks_per_beat, diagnostics
        )
        normalized_tracks.append(normalized)
        program_events.extend(track_programs)

    tempo_events.sort(key=lambda e: e.tick)
    time_signature_events.sort(key=lambda e: e.tick)
    program_events.sort(key=lambda e: (e.tick, e.track_index, e.channel))

    _ensure_initial_tempo(tempo_events, diagnostics)
    _ensure_initial_time_signature(time_signature_events, diagnostics)

    total_notes = sum(len(t.notes) for t in normalized_tracks)
    logger.debug(
        "Parsed MIDI: source=%s tracks=%d notes=%d", source.name, len(normalized_tracks), total_notes
    )

    return NormalizedTimeline(
        source=NormalizedTimeline.source_name(source),
        midi_type=int(midi.type),
        ticks_per_beat=int(ticks_per_beat),
        tempo_events=tempo_events,
        time_signature_events=time_signature_events,
        tracks=normalized_tracks,
        program_events=program_events,
        diagnostics=diagnostics,
    )


__all__ = ["load_midi"]

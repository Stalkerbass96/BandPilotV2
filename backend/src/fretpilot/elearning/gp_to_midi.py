"""GP Song → MIDI file converter.

PyGuitarPro cannot export MIDI, so this module builds a MIDI file from the
parsed GP data using ``mido``.  The resulting MIDI serves as "dirty" input
for the FretPilot pipeline round-trip evaluation.

Key design choices:
    - ``ticks_per_beat=960`` matches GP's ``quarterTime``
    - Tie notes are skipped (no repeated note_on)
    - Type-1 MIDI: track 0 = meta, track 1 = music
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import mido

from fretpilot.elearning.models import (
    GroundTruthNote,
    GroundTruthTab,
    ProfessionalScoreCorpus,
)

logger = logging.getLogger("fretpilot.elearning.gp_to_midi")

TPB = 960  # ticks per beat, same as gp.Duration.quarterTime
DEFAULT_VELOCITY = 95
GUITAR_PROGRAM = 30  # Overdriven Guitar (GM)

_MIDI_TEXT_REPLACEMENTS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "‹": "<",
        "›": ">",
        "…": "...",
        "～": "~",
    }
)


def _midi_safe_text(value: str) -> str:
    """Normalize SMF text to mido's Latin-1 metadata encoding."""
    normalized = value.translate(_MIDI_TEXT_REPLACEMENTS)
    return normalized.encode("latin1", errors="replace").decode("latin1")


class GPMidiConverter:
    """P0-2: Convert ``GroundTruthTab`` to a MIDI file."""

    def convert(
        self,
        tab: GroundTruthTab,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert ground truth tab to MIDI and save.

        Returns the path to the saved MIDI file.
        """
        if output_path is None:
            fd, tmp = tempfile.mkstemp(suffix=".mid", prefix="elearning_")
            import os
            os.close(fd)
            output_path = Path(tmp)
        else:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)

        midi = mido.MidiFile(ticks_per_beat=TPB, type=1)

        # Track 0: meta events
        meta_track = mido.MidiTrack()
        midi.tracks.append(meta_track)
        meta_track.append(mido.MetaMessage(
            "set_tempo",
            tempo=mido.bpm2tempo(tab.tempo_bpm),
            time=0,
        ))
        num, den = tab.time_signature
        meta_track.append(mido.MetaMessage(
            "time_signature",
            numerator=num,
            denominator=den,
            time=0,
        ))
        meta_track.append(mido.MetaMessage(
            "end_of_track",
            time=0,
        ))

        # Track 1: music
        music_track = mido.MidiTrack()
        midi.tracks.append(music_track)
        music_track.append(mido.Message(
            "program_change",
            program=GUITAR_PROGRAM,
            channel=0,
            time=0,
        ))

        # Build note events from ground truth notes
        events: list[tuple[int, bool, int, int]] = []  # (abs_tick, is_on, pitch, velocity)
        for note in tab.notes:
            if note.is_tie:
                continue
            # GPReader retains the actual absolute beat, including pickup bars
            # and time-signature changes. Reconstructing it from the initial
            # meter loses rhythm before the product even sees the MIDI.
            absolute_beat = note.absolute_start_beat
            if absolute_beat == 0.0 and (
                note.measure_number != 1 or note.beat_in_measure != 0.0
            ):
                # Compatibility for hand-built/legacy GroundTruthNote values
                # created before absolute_start_beat became part of the model.
                numerator, _denominator = tab.time_signature
                absolute_beat = (
                    (note.measure_number - 1) * numerator + note.beat_in_measure
                )
            abs_on_tick = int(round(absolute_beat * TPB))
            abs_off_tick = abs_on_tick + int(round(note.duration_beats * TPB))
            events.append((abs_on_tick, True, note.pitch, note.velocity))
            events.append((abs_off_tick, False, note.pitch, 0))

        # Sort: note_off before note_on at the same tick (stable sort)
        events.sort(key=lambda e: (e[0], 0 if not e[1] else 1))

        # Convert to delta time and write to track
        prev_tick = 0
        for abs_tick, is_on, pitch, velocity in events:
            delta = max(0, abs_tick - prev_tick)
            if is_on:
                music_track.append(mido.Message(
                    "note_on",
                    note=pitch,
                    velocity=velocity,
                    channel=0,
                    time=delta,
                ))
            else:
                music_track.append(mido.Message(
                    "note_off",
                    note=pitch,
                    velocity=0,
                    channel=0,
                    time=delta,
                ))
            prev_tick = abs_tick

        # End of track
        music_track.append(mido.MetaMessage("end_of_track", time=0))

        midi.save(str(output_path))
        logger.debug("MIDI exported: %s (%d notes)", output_path, len(tab.notes))
        return output_path

    def convert_corpus(
        self,
        corpus: ProfessionalScoreCorpus,
        output_path: str | Path | None = None,
    ) -> Path:
        """Convert every GP score track into one faithful type-1 MIDI file."""
        if output_path is None:
            fd, tmp = tempfile.mkstemp(suffix=".mid", prefix="elearning-song-")
            import os

            os.close(fd)
            destination = Path(tmp)
        else:
            destination = Path(output_path)
            destination.parent.mkdir(parents=True, exist_ok=True)

        midi = mido.MidiFile(ticks_per_beat=TPB, type=1)
        midi.tracks.append(self._build_corpus_meta_track(corpus))
        melodic_channel = 0
        for source_track in corpus.tracks:
            if source_track.is_percussion:
                channel = 9
            else:
                while melodic_channel == 9:
                    melodic_channel += 1
                channel = melodic_channel % 16
                if channel == 9:
                    channel = 10
                melodic_channel += 1
            midi.tracks.append(
                self._build_music_track(
                    name=source_track.name,
                    program=source_track.program,
                    notes=source_track.notes,
                    channel=channel,
                )
            )

        midi.save(str(destination))
        logger.debug(
            "Full-score MIDI exported: %s (%d tracks)",
            destination,
            len(corpus.tracks),
        )
        return destination

    @staticmethod
    def _build_corpus_meta_track(corpus: ProfessionalScoreCorpus) -> mido.MidiTrack:
        track = mido.MidiTrack()
        events: list[tuple[int, int, mido.MetaMessage]] = []
        for item in corpus.tempo_map:
            tick = max(0, int(round(float(item["beat"]) * TPB)))
            events.append(
                (
                    tick,
                    0,
                    mido.MetaMessage(
                        "set_tempo", tempo=mido.bpm2tempo(float(item["bpm"])), time=0
                    ),
                )
            )

        previous_signature: tuple[int, int] | None = None
        for item in corpus.time_signature_map:
            signature = (int(item["numerator"]), int(item["denominator"]))
            if signature == previous_signature:
                continue
            previous_signature = signature
            tick = max(0, int(round(float(item["beat"]) * TPB)))
            events.append(
                (
                    tick,
                    1,
                    mido.MetaMessage(
                        "time_signature",
                        numerator=signature[0],
                        denominator=signature[1],
                        time=0,
                    ),
                )
            )

        previous_tick = 0
        for tick, _priority, message in sorted(events, key=lambda event: event[:2]):
            message.time = max(0, tick - previous_tick)
            track.append(message)
            previous_tick = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
        return track

    @staticmethod
    def _build_music_track(
        *,
        name: str,
        program: int,
        notes: list[GroundTruthNote],
        channel: int,
    ) -> mido.MidiTrack:
        track = mido.MidiTrack()
        safe_name = _midi_safe_text(name)[:127]
        track.append(mido.MetaMessage("track_name", name=safe_name, time=0))
        track.append(mido.MetaMessage("instrument_name", name=safe_name, time=0))
        if channel != 9:
            track.append(
                mido.Message(
                    "program_change",
                    program=max(0, min(127, int(program))),
                    channel=channel,
                    time=0,
                )
            )

        events: list[tuple[int, bool, int, int]] = []
        for note in notes:
            if note.is_tie:
                continue
            start = max(0, int(round(note.absolute_start_beat * TPB)))
            end = start + max(1, int(round(note.duration_beats * TPB)))
            events.append((start, True, note.pitch, note.velocity))
            events.append((end, False, note.pitch, 0))
        events.sort(key=lambda event: (event[0], 0 if not event[1] else 1))

        previous_tick = 0
        for tick, is_on, pitch, velocity in events:
            delta = max(0, tick - previous_tick)
            track.append(
                mido.Message(
                    "note_on" if is_on else "note_off",
                    note=max(0, min(127, pitch)),
                    velocity=max(1, min(127, velocity)) if is_on else 0,
                    channel=channel,
                    time=delta,
                )
            )
            previous_tick = tick
        track.append(mido.MetaMessage("end_of_track", time=0))
        return track

    def _measure_to_abs_tick(
        self,
        measure_number: int,
        beat_in_measure: float,
        time_signature: tuple[int, int],
    ) -> int:
        """Compute absolute tick position from measure number and beat.

        Assumes 4/4 (or any time sig where 1 beat = 1 quarter note) and
        that measures are ``numerator`` beats long (for 4/4 = 4 beats).
        """
        numerator, _denominator = time_signature
        beats_per_measure = numerator
        abs_beat = (measure_number - 1) * beats_per_measure + beat_in_measure
        return int(round(abs_beat * TPB))


__all__ = ["GPMidiConverter"]

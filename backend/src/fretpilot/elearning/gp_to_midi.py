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

from fretpilot.elearning.models import GroundTruthTab

logger = logging.getLogger("fretpilot.elearning.gp_to_midi")

TPB = 960  # ticks per beat, same as gp.Duration.quarterTime
DEFAULT_VELOCITY = 95
GUITAR_PROGRAM = 30  # Overdriven Guitar (GM)


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
            on_tick = int(round(note.beat_in_measure * TPB))
            # Compute absolute tick from measure number and beat
            # We need measure start tick — reconstruct from time signature
            # For simplicity, use cumulative beats
            abs_on_tick = self._measure_to_abs_tick(note.measure_number, note.beat_in_measure, tab.time_signature)
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

"""GP3/GP4/GP5 drum reader — extracts ground truth drum data.

Uses PyGuitarPro's ``guitarpro.parse()`` to read GP files and extracts
per-hit GM pitch, mapped drum piece, velocity, and timing information from
the percussion track as ``DrumGroundTruthTab``.

For percussion tracks in GP, ``note.value`` holds the GM percussion pitch
(0–127) and the string tuning is zero, so ``note.realValue == note.value``.
Ghost/accent markings are exposed via ``note.effect.ghostNote`` and
``note.effect.accentuatedNote``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import guitarpro as gp

from fretpilot.drum.drumkit import map_pitch_to_piece
from fretpilot.elearning.drum_models import DrumGroundTruthNote, DrumGroundTruthTab
from fretpilot.elearning.style_mapper import map_directory_to_style, map_filename_to_style

logger = logging.getLogger("fretpilot.elearning.drum_reader")

QUARTER_TICKS = gp.Duration.quarterTime  # 960

# Substring keywords (lower-cased) that hint a track is a drum track.
_DRUM_NAME_HINTS = (
    "drum", "percussion", "perc", "kit", "sticks",
    "鼓", "打击", "架子鼓",
)

# Velocity values assigned when the tab marks ghost/accent but carries no
# explicit dynamics byte (PyGuitarPro defaults velocity to 95).
_GHOST_VELOCITY = 20
_ACCENT_VELOCITY = 115


class DrumReader:
    """Parse GP3/GP4/GP5 files into ``DrumGroundTruthTab``."""

    def parse(
        self,
        path: str | Path,
        style_label: str | None = None,
    ) -> DrumGroundTruthTab:
        """Parse a GP file and return drum ground truth data.

        Parameters
        ----------
        path
            Path to a .gp3/.gp4/.gp5 file.
        style_label
            Optional override; if ``None``, inferred from path.
        """
        path = Path(path)
        song = gp.parse(str(path))

        track = self._select_drum_track(song)
        tempo_bpm = float(song.tempo)
        ts = self._extract_time_signature(song)

        notes = self._extract_notes(track)

        if style_label is None:
            dir_style = map_directory_to_style(str(path.parent))
            style_label = dir_style if dir_style != "unknown" else map_filename_to_style(path.name)

        return DrumGroundTruthTab(
            file_path=str(path),
            title=song.title or path.stem,
            style_label=style_label,
            tempo_bpm=tempo_bpm,
            time_signature=ts,
            track_name=track.name,
            notes=notes,
        )

    def _select_drum_track(self, song: gp.Song) -> gp.Track:
        """Select the primary percussion track.

        Preference order (each tier picks the track with the most notes):
          1. percussion tracks whose name hints drums
          2. any percussion track
          3. any non-percussion track whose name hints drums

        Raises:
            ValueError: If no drum-like track exists in the song.
        """
        tracks = list(song.tracks)
        if not tracks:
            raise ValueError("Song has no tracks.")

        def note_count(t: gp.Track) -> int:
            return sum(
                1
                for m in t.measures
                for v in m.voices
                for b in v.beats
                for _ in b.notes
            )

        def hints_drum(t: gp.Track) -> bool:
            lower = (t.name or "").lower()
            return any(k in lower for k in _DRUM_NAME_HINTS)

        percussion = [t for t in tracks if t.isPercussionTrack]
        if percussion:
            tier1 = [t for t in percussion if hints_drum(t)]
            if tier1:
                return max(tier1, key=note_count)
            return max(percussion, key=note_count)

        # No percussion track — fall back to a named drum track.
        tier3 = [t for t in tracks if hints_drum(t)]
        if tier3:
            return max(tier3, key=note_count)

        raise ValueError("Song has no percussion/drum track.")

    def _extract_time_signature(self, song: gp.Song) -> tuple[int, int]:
        """Extract the initial time signature from the first measure header."""
        if song.measureHeaders:
            ts = song.measureHeaders[0].timeSignature
            return ts.numerator, ts.denominator.value
        return 4, 4

    def _extract_notes(self, track: gp.Track) -> list[DrumGroundTruthNote]:
        """Extract all non-tie drum hits from the track.

        Each hit's GM pitch is ``note.value`` (percussion tracks have zero
        string tuning, so ``realValue`` equals the stored pitch).  Velocity
        comes from the dynamics byte when present; ghost/accent markings
        override it with canonical values otherwise.
        """
        notes: list[DrumGroundTruthNote] = []
        for measure in track.measures:
            measure_start_tick = measure.start
            for voice in measure.voices:
                for beat in voice.beats:
                    beat_start_tick = beat.start
                    beat_in_measure = (beat_start_tick - measure_start_tick) / QUARTER_TICKS
                    duration_beats = beat.duration.time / QUARTER_TICKS
                    for note in beat.notes:
                        if note.type == gp.NoteType.tie:
                            continue
                        pitch = note.value
                        if pitch <= 0:
                            continue
                        velocity = note.velocity
                        if note.effect.ghostNote:
                            velocity = min(velocity, _GHOST_VELOCITY)
                        elif note.effect.accentuatedNote or note.effect.heavyAccentuatedNote:
                            velocity = max(velocity, _ACCENT_VELOCITY)
                        notes.append(DrumGroundTruthNote(
                            measure_number=measure.number,
                            beat_in_measure=beat_in_measure,
                            pitch=pitch,
                            piece=map_pitch_to_piece(pitch),
                            velocity=velocity,
                            duration_beats=duration_beats,
                            is_tie=False,
                        ))
        return notes


__all__ = ["DrumReader"]

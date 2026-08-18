"""GP3/GP4/GP5 file reader — extracts ground truth fingering data.

Uses PyGuitarPro's ``guitarpro.parse()`` to read GP files and extracts
per-note string/fret/pitch/measure/beat information as ``GroundTruthTab``.

String numbering: 1=high E, 6=low E (same convention as FretPilot IR).
"""

from __future__ import annotations

import logging
from pathlib import Path

import guitarpro as gp

from fretpilot.elearning.models import GroundTruthNote, GroundTruthTab
from fretpilot.elearning.style_mapper import map_directory_to_style, map_filename_to_style

logger = logging.getLogger("fretpilot.elearning.gp_reader")

QUARTER_TICKS = gp.Duration.quarterTime  # 960

# Substring keywords (lower-cased) that hint a track is a guitar track.
_GUITAR_NAME_HINTS = (
    "guitar", "gtr", "lead", "rhythm", "solo", "acoustic", "clean",
    "dist", "overdrive", "吉", "电吉", "木吉", "主音", "节奏", "伴奏",
)


class GPReader:
    """P0-1: Parse GP3/GP4/GP5 files into ``GroundTruthTab``."""

    def parse(
        self,
        path: str | Path,
        style_label: str | None = None,
    ) -> GroundTruthTab:
        """Parse a GP file and return ground truth data.

        Parameters
        ----------
        path
            Path to a .gp3/.gp4/.gp5 file.
        style_label
            Optional override; if ``None``, inferred from path.
        """
        path = Path(path)
        song = gp.parse(str(path))

        track = self._select_guitar_track(song)
        tuning_pitches = self._extract_tuning(track)
        tempo_bpm = float(song.tempo)
        ts = self._extract_time_signature(song)

        notes = self._extract_notes(track)
        self._compute_hand_positions(notes)

        if style_label is None:
            dir_style = map_directory_to_style(str(path.parent))
            style_label = dir_style if dir_style != "unknown" else map_filename_to_style(path.name)

        return GroundTruthTab(
            file_path=str(path),
            title=song.title or path.stem,
            style_label=style_label,
            tempo_bpm=tempo_bpm,
            time_signature=ts,
            tuning_pitches=tuning_pitches,
            notes=notes,
            track_name=track.name,
        )

    def _select_guitar_track(self, song: gp.Song) -> gp.Track:
        """Select the primary guitar track.

        Preference order (each tier picks the track with the most notes):
          1. non-percussion tracks with ≥6 strings whose name hints guitar
          2. any non-percussion track with ≥6 strings
          3. any non-percussion track

        Percussion/drum tracks are excluded outright — their 6-string layout
        uses tuning 0 and stores MIDI percussion pitches in the ``value``
        field, which would corrupt fret-based statistics.
        """
        tracks = [t for t in song.tracks if not t.isPercussionTrack]
        if not tracks:
            raise ValueError("Song has no non-percussion tracks.")

        def note_count(t: gp.Track) -> int:
            return sum(
                1
                for m in t.measures
                for v in m.voices
                for b in v.beats
                for _ in b.notes
            )

        def hints_guitar(t: gp.Track) -> bool:
            lower = (t.name or "").lower()
            return any(k in lower for k in _GUITAR_NAME_HINTS)

        tier1 = [t for t in tracks if len(t.strings) >= 6 and hints_guitar(t)]
        if tier1:
            return max(tier1, key=note_count)

        tier2 = [t for t in tracks if len(t.strings) >= 6]
        if tier2:
            return max(tier2, key=note_count)

        return max(tracks, key=note_count)

    def _extract_tuning(self, track: gp.Track) -> list[int]:
        """Extract open-string pitches ordered low → high (string 6 → 1)."""
        # track.strings is ordered by string number: 1=high, 6=low
        # We want low → high for consistency with knowledge.tunings.GuitarTuning
        return [s.value for s in sorted(track.strings, key=lambda s: -s.number)]

    def _extract_time_signature(self, song: gp.Song) -> tuple[int, int]:
        """Extract the initial time signature from the first measure header."""
        if song.measureHeaders:
            ts = song.measureHeaders[0].timeSignature
            return ts.numerator, ts.denominator.value
        return 4, 4

    def _extract_notes(self, track: gp.Track) -> list[GroundTruthNote]:
        """Extract all non-tie notes from the track."""
        notes: list[GroundTruthNote] = []
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
                        notes.append(GroundTruthNote(
                            measure_number=measure.number,
                            beat_in_measure=beat_in_measure,
                            pitch=note.realValue,
                            string=note.string,
                            fret=note.value,
                            hand_position=0,  # filled by _compute_hand_positions
                            duration_beats=duration_beats,
                            is_tie=False,
                            velocity=95,
                        ))
        return notes

    def _compute_hand_positions(self, notes: list[GroundTruthNote]) -> None:
        """Compute hand_position for each note (same convention as FingeringStage).

        - fretted note (fret > 0): hand_position = max(1, fret)
        - open string (fret == 0): hand_position = prev fretted note's hand_position
        - first note if open: hand_position = 1
        """
        prev_hp = 1
        for note in notes:
            if note.fret > 0:
                note.hand_position = max(1, note.fret)
                prev_hp = note.hand_position
            else:
                note.hand_position = prev_hp


__all__ = ["GPReader"]

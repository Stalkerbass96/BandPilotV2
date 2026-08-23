"""GP3/GP4/GP5 file reader — extracts ground truth fingering data.

Uses PyGuitarPro's ``guitarpro.parse()`` to read GP files and extracts
per-note string/fret/pitch/measure/beat information as ``GroundTruthTab``.

String numbering: 1=high E, 6=low E (same convention as FretPilot IR).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import guitarpro as gp

from fretpilot.elearning.models import (
    CorpusProvenance,
    GroundTruthNote,
    GroundTruthTab,
    GroundTruthTechnique,
    GroundTruthTrack,
    ProfessionalScoreCorpus,
)
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
        song = self._parse_song(path)

        track = self._select_guitar_track(song)
        tuning_pitches = self._extract_tuning(track)
        tempo_bpm = float(song.tempo)
        ts = self._extract_time_signature(song)

        extracted_track = self._extract_track(track)
        notes = [note for note in extracted_track.notes if not note.is_tie]
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
            techniques=extracted_track.techniques,
        )

    def parse_corpus(
        self,
        path: str | Path,
        *,
        style_label: str | None = None,
        license_id: str = "unverified",
        permitted_for_training: bool = False,
        quality_tier: str = "unreviewed",
        split: str = "train",
    ) -> ProfessionalScoreCorpus:
        """Parse every GP track into a loss-minimizing learning artifact.

        Rights metadata is deliberately required at the corpus boundary. An
        unverified file may be inspected, but governance code will not allow
        it to influence a promoted knowledge snapshot.
        """

        source_path = Path(path)
        song = self._parse_song(source_path)
        if style_label is None:
            directory_style = map_directory_to_style(str(source_path.parent))
            style_label = (
                directory_style
                if directory_style != "unknown"
                else map_filename_to_style(source_path.name)
            )
        tracks = [self._extract_track(track) for track in song.tracks]
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        tempo_map: list[dict[str, float]] = [{"beat": 0.0, "bpm": float(song.tempo)}]
        time_signature_map = [
            {
                "beat": float((header.start - QUARTER_TICKS) / QUARTER_TICKS),
                "numerator": int(header.timeSignature.numerator),
                "denominator": int(header.timeSignature.denominator.value),
            }
            for header in song.measureHeaders
        ]
        return ProfessionalScoreCorpus(
            file_path=str(source_path),
            title=song.title or source_path.stem,
            artist=song.artist or "",
            style_label=style_label,
            tempo_map=tempo_map,
            time_signature_map=time_signature_map,
            tracks=tracks,
            provenance=CorpusProvenance(
                source_id=source_path.name,
                content_sha256=digest,
                license_id=license_id,
                permitted_for_training=permitted_for_training,
                quality_tier=quality_tier,
                split=split,
            ),
        )

    @staticmethod
    def _parse_song(path: Path) -> gp.Song:
        """Parse legacy GP text with a loss-tolerant charset fallback.

        GP3–GP5 do not declare their 8-bit text charset. PyGuitarPro defaults
        to cp1252, whose undefined bytes make otherwise valid scores fail.
        Latin-1 is a final byte-preserving fallback; notation bytes and timing
        remain unchanged even when old metadata was authored in another local
        code page.
        """

        first_error: Exception | None = None
        for encoding in ("cp1252", "gb18030", "latin1"):
            try:
                song = gp.parse(str(path), encoding=encoding)
                if encoding != "cp1252":
                    logger.warning("Parsed %s using legacy %s fallback", path, encoding)
                return song
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
        raise RuntimeError(f"Unable to parse GP score: {path}")

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
        return [note for note in self._extract_track(track).notes if not note.is_tie]

    def _extract_track(self, track: gp.Track) -> GroundTruthTrack:
        notes: list[GroundTruthNote] = []
        effects_by_note: dict[str, list[str]] = {}
        for measure in track.measures:
            measure_start_tick = measure.start
            for voice_index, voice in enumerate(measure.voices, start=1):
                for beat_index, beat in enumerate(voice.beats, start=1):
                    beat_start_tick = beat.start
                    beat_in_measure = (beat_start_tick - measure_start_tick) / QUARTER_TICKS
                    duration_beats = beat.duration.time / QUARTER_TICKS
                    for note_index, note in enumerate(beat.notes, start=1):
                        note_id = (
                            f"track-{track.number}:m{measure.number}:v{voice_index}:"
                            f"b{beat_index}:n{note_index}"
                        )
                        effects_by_note[note_id] = self._note_effect_types(note)
                        notes.append(
                            GroundTruthNote(
                                measure_number=measure.number,
                                beat_in_measure=beat_in_measure,
                                pitch=note.realValue,
                                string=note.string,
                                fret=note.value,
                                hand_position=0,
                                duration_beats=duration_beats,
                                is_tie=note.type == gp.NoteType.tie,
                                velocity=int(getattr(note, "velocity", 95)),
                                note_id=note_id,
                                voice=voice_index,
                                absolute_start_beat=(beat_start_tick - QUARTER_TICKS)
                                / QUARTER_TICKS,
                            )
                        )

        self._compute_hand_positions(notes)
        techniques = self._build_techniques(notes, effects_by_note)
        return GroundTruthTrack(
            id=f"track-{track.number}",
            name=track.name or f"Track {track.number}",
            program=int(getattr(track.channel, "instrument", 0)),
            is_percussion=bool(track.isPercussionTrack),
            tuning_pitches=self._extract_tuning(track),
            capo=int(getattr(track, "offset", 0)),
            notes=notes,
            techniques=techniques,
        )

    @staticmethod
    def _note_effect_types(note: gp.Note) -> list[str]:
        effect = note.effect
        mapping = (
            ("palm_mute", "palmMute"),
            ("let_ring", "letRing"),
            ("staccato", "staccato"),
            ("vibrato", "vibrato"),
            ("ghost_note", "ghostNote"),
            ("accent", "accentuatedNote"),
            ("heavy_accent", "heavyAccentuatedNote"),
            ("bend", "bend"),
            ("harmonic", "harmonic"),
            ("grace", "grace"),
            ("trill", "trill"),
            ("tremolo_picking", "tremoloPicking"),
        )
        result = [name for name, attribute in mapping if getattr(effect, attribute, None)]
        if getattr(effect, "hammer", False):
            result.append("legato")
        if getattr(effect, "slides", None):
            result.append("slide")
        return result

    @staticmethod
    def _build_techniques(
        notes: list[GroundTruthNote],
        effects_by_note: dict[str, list[str]],
    ) -> list[GroundTruthTechnique]:
        techniques: list[GroundTruthTechnique] = []
        for index, note in enumerate(notes):
            for sequence, technique_type in enumerate(
                effects_by_note.get(note.note_id, []), start=1
            ):
                note_ids = [note.note_id]
                if technique_type in {"legato", "slide"}:
                    target = next(
                        (
                            candidate
                            for candidate in notes[index + 1 :]
                            if candidate.string == note.string
                            and candidate.absolute_start_beat > note.absolute_start_beat
                        ),
                        None,
                    )
                    if target is not None:
                        note_ids.append(target.note_id)
                technique_id = f"tech:{note.note_id}:{sequence}"
                technique = GroundTruthTechnique(
                    id=technique_id,
                    type=technique_type,
                    note_ids=note_ids,
                    measure_number=note.measure_number,
                    start_beat=note.absolute_start_beat,
                    end_beat=(
                        next(
                            (
                                candidate.absolute_start_beat
                                for candidate in notes
                                if candidate.note_id == note_ids[-1]
                            ),
                            note.absolute_start_beat + note.duration_beats,
                        )
                        if len(note_ids) == 2
                        else note.absolute_start_beat + note.duration_beats
                    ),
                )
                techniques.append(technique)
                for related_note in notes:
                    if related_note.note_id in note_ids:
                        related_note.technique_ids.append(technique_id)
        return techniques

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

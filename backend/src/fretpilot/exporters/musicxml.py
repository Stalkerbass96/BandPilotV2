"""Strict SongIR to MusicXML 4.0 score exporter."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from fretpilot.drum.notation import DRUM_DISPLAY, DRUM_NOTEHEAD
from fretpilot.exporters.base import ExportResult
from fretpilot.ir.song import InstrumentTrackIR, ScoreEventIR, SongIR
from fretpilot.validation import validate_song

DIVISIONS = 480
_PITCH_STEPS = ("C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B")
_PITCH_ALTERS = (0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0)
_DYNAMIC_MARKS = {"ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"}


def _ticks(beats: float) -> int:
    return max(1, int(round(beats * DIVISIONS)))


def _pitch(parent: ET.Element, midi_pitch: int) -> None:
    pitch = ET.SubElement(parent, "pitch")
    pitch_class = midi_pitch % 12
    ET.SubElement(pitch, "step").text = _PITCH_STEPS[pitch_class]
    alter = _PITCH_ALTERS[pitch_class]
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(midi_pitch // 12 - 1)


def _type_name(duration_beats: float) -> str:
    values = (
        (4.0, "whole"),
        (2.0, "half"),
        (1.0, "quarter"),
        (0.5, "eighth"),
        (0.25, "16th"),
        (0.125, "32nd"),
        (0.0625, "64th"),
    )
    return min(values, key=lambda item: abs(item[0] - duration_beats))[1]


def _written_duration(duration_beats: float) -> tuple[str, int, tuple[int, int] | None]:
    values = (
        (4.0, "whole"),
        (2.0, "half"),
        (1.0, "quarter"),
        (0.5, "eighth"),
        (0.25, "16th"),
        (0.125, "32nd"),
        (0.0625, "64th"),
    )
    for value, name in values:
        if abs(duration_beats - value) <= 1e-8:
            return name, 0, None
        if abs(duration_beats - value * 1.5) <= 1e-8:
            return name, 1, None
        if abs(duration_beats - value * 2 / 3) <= 1e-8:
            return name, 0, (3, 2)
    return _type_name(duration_beats), 0, None


def _write_duration_notation(note: ET.Element, duration_beats: float) -> None:
    name, dots, tuplet = _written_duration(duration_beats)
    ET.SubElement(note, "type").text = name
    for _ in range(dots):
        ET.SubElement(note, "dot")
    if tuplet is not None:
        time_modification = ET.SubElement(note, "time-modification")
        ET.SubElement(time_modification, "actual-notes").text = str(tuplet[0])
        ET.SubElement(time_modification, "normal-notes").text = str(tuplet[1])


def _notations(note: ET.Element, song: SongIR, event: ScoreEventIR) -> None:
    realization = event.realization
    techniques = {
        technique.id: technique
        for technique in song.score.techniques
        if technique.id in event.technique_ids
    }
    if (
        realization.string is None
        and realization.finger is None
        and not techniques
        and not event.score.tie_in
        and not event.score.tie_out
    ):
        return
    notations = ET.SubElement(note, "notations")
    technical = None
    if realization.string is not None or realization.finger is not None:
        technical = ET.SubElement(notations, "technical")
    if realization.string is not None:
        assert technical is not None
        ET.SubElement(technical, "string").text = str(realization.string)
    if realization.fret is not None:
        assert technical is not None
        ET.SubElement(technical, "fret").text = str(realization.fret)
    if realization.finger is not None:
        assert technical is not None
        ET.SubElement(technical, "fingering").text = str(realization.finger)
    if event.score.tie_in:
        ET.SubElement(notations, "tied", type="stop")
    if event.score.tie_out:
        ET.SubElement(notations, "tied", type="start")
    articulation_types = {
        technique.type
        for technique in techniques.values()
        if technique.type in {"staccato", "accent"}
    }
    if articulation_types:
        articulations = ET.SubElement(notations, "articulations")
        for articulation_type in sorted(articulation_types):
            ET.SubElement(articulations, articulation_type)
    for technique in techniques.values():
        if technique.type == "hammer_on":
            if technical is not None:
                link_type = "start" if technique.note_ids[0] == event.id else "stop"
                ET.SubElement(technical, "hammer-on", type=link_type).text = "H"
        elif technique.type == "pull_off":
            if technical is not None:
                link_type = "start" if technique.note_ids[0] == event.id else "stop"
                ET.SubElement(technical, "pull-off", type=link_type).text = "P"
        elif technique.type == "slide":
            link_type = "start" if technique.note_ids[0] == event.id else "stop"
            ET.SubElement(notations, "slide", type=link_type)
        elif technique.type in {"palm_mute", "let_ring"} and technical is not None:
            ET.SubElement(technical, "other-technical").text = technique.type.replace("_", " ")
        elif technique.type == "bend" and technical is not None:
            bend = ET.SubElement(technical, "bend")
            ET.SubElement(bend, "bend-alter").text = str(
                technique.parameters.get("semitones", 1.0)
            )
        elif technique.type == "harmonic" and technical is not None:
            harmonic = ET.SubElement(technical, "harmonic")
            ET.SubElement(harmonic, "natural")
        elif technique.type == "vibrato":
            ornaments = ET.SubElement(notations, "ornaments")
            ET.SubElement(ornaments, "wavy-line", type="start")


def _note_element(
    parent: ET.Element,
    song: SongIR,
    track: InstrumentTrackIR,
    event: ScoreEventIR,
    *,
    chord: bool,
) -> None:
    note = ET.SubElement(parent, "note")
    if chord:
        ET.SubElement(note, "chord")
    if track.family == "drums":
        display_step, octave = DRUM_DISPLAY.get(
            event.realization.piece or "", ("C", 5)
        )
        unpitched = ET.SubElement(note, "unpitched")
        ET.SubElement(unpitched, "display-step").text = display_step
        ET.SubElement(unpitched, "display-octave").text = str(octave)
        note.set("dynamics", str(next(
            (performance.velocity for performance in song.performance.events if performance.note_id == event.id),
            80,
        )))
    else:
        _pitch(note, event.pitch)
    ET.SubElement(note, "duration").text = str(_ticks(event.score.duration_beats))
    ET.SubElement(note, "voice").text = str(event.score.voice)
    _write_duration_notation(note, event.score.duration_beats)
    if track.family == "drums":
        ET.SubElement(note, "stem").text = (
            "down" if event.score.voice == 2 else "up"
        )
        notehead = DRUM_NOTEHEAD.get(event.realization.piece or "")
        if notehead:
            ET.SubElement(note, "notehead").text = notehead
    if event.score.tie_in:
        ET.SubElement(note, "tie", type="stop")
    if event.score.tie_out:
        ET.SubElement(note, "tie", type="start")
    if track.family == "keys":
        ET.SubElement(note, "staff").text = "2" if event.realization.hand == "left" else "1"
    _notations(note, song, event)


def _rest(parent: ET.Element, duration: float, voice: int) -> None:
    if duration <= 1e-8:
        return
    note = ET.SubElement(parent, "note")
    ET.SubElement(note, "rest")
    ET.SubElement(note, "duration").text = str(_ticks(duration))
    ET.SubElement(note, "voice").text = str(voice)
    _write_duration_notation(note, duration)


def _event_dynamic(song: SongIR, event: ScoreEventIR) -> tuple[str, int] | None:
    performance = next(
        (value for value in song.performance.events if value.note_id == event.id),
        None,
    )
    if performance is None:
        return None
    dynamic = next(
        (
            str(control["value"])
            for control in performance.controls
            if control.get("type") == "dynamic" and control.get("value") in _DYNAMIC_MARKS
        ),
        None,
    )
    return (dynamic, performance.velocity) if dynamic is not None else None


def _dynamic_direction(
    parent: ET.Element,
    dynamic: str,
    velocity: int,
    voice: int,
) -> None:
    direction = ET.SubElement(parent, "direction", placement="below")
    direction_type = ET.SubElement(direction, "direction-type")
    dynamics = ET.SubElement(direction_type, "dynamics")
    ET.SubElement(dynamics, dynamic)
    ET.SubElement(direction, "voice").text = str(voice)
    ET.SubElement(direction, "sound", dynamics=str(round(velocity / 127 * 100)))


def _attributes(parent: ET.Element, track: InstrumentTrackIR, measure) -> None:
    attributes = ET.SubElement(parent, "attributes")
    ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = str(measure.numerator)
    ET.SubElement(time, "beat-type").text = str(measure.denominator)
    if track.family == "keys":
        ET.SubElement(attributes, "staves").text = "2"
        treble = ET.SubElement(attributes, "clef", number="1")
        ET.SubElement(treble, "sign").text = "G"
        ET.SubElement(treble, "line").text = "2"
        bass = ET.SubElement(attributes, "clef", number="2")
        ET.SubElement(bass, "sign").text = "F"
        ET.SubElement(bass, "line").text = "4"
    else:
        clef = ET.SubElement(attributes, "clef")
        sign = "percussion" if track.family == "drums" else ("F" if track.family == "bass" else "G")
        ET.SubElement(clef, "sign").text = sign
        if sign != "percussion":
            ET.SubElement(clef, "line").text = "4" if sign == "F" else "2"
        else:
            staff_details = ET.SubElement(attributes, "staff-details")
            ET.SubElement(staff_details, "staff-lines").text = "5"


def _write_measure(parent: ET.Element, song: SongIR, track: InstrumentTrackIR, measure) -> None:
    xml_measure = ET.SubElement(parent, "measure", number=str(measure.number))
    _attributes(xml_measure, track, measure)
    by_voice: dict[int, list[ScoreEventIR]] = defaultdict(list)
    for event in measure.events:
        by_voice[event.score.voice].append(event)
    voices = sorted(by_voice) or [1]
    for voice_index, voice in enumerate(voices):
        if voice_index:
            backup = ET.SubElement(xml_measure, "backup")
            ET.SubElement(backup, "duration").text = str(_ticks(measure.duration_beats))
        cursor = measure.start_beat
        groups: dict[float, list[ScoreEventIR]] = defaultdict(list)
        for event in by_voice.get(voice, []):
            groups[round(event.score.start_beat, 8)].append(event)
        for onset, events in sorted(groups.items()):
            _rest(xml_measure, onset - cursor, voice)
            ordered = sorted(events, key=lambda item: (-item.score.duration_beats, item.pitch))
            explicit_dynamic = next(
                (
                    value
                    for event in ordered
                    if (value := _event_dynamic(song, event)) is not None
                ),
                None,
            )
            if explicit_dynamic is not None:
                _dynamic_direction(
                    xml_measure,
                    explicit_dynamic[0],
                    explicit_dynamic[1],
                    voice,
                )
            for index, event in enumerate(ordered):
                _note_element(xml_measure, song, track, event, chord=index > 0)
            cursor = max(cursor, onset + max(event.score.duration_beats for event in events))
        _rest(xml_measure, measure.start_beat + measure.duration_beats - cursor, voice)


class MusicXMLSongExporter:
    format_id = "musicxml"

    def export(self, song: SongIR, output_path: Path) -> ExportResult:
        validate_song(song, raise_on_error=True)
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        root = ET.Element("score-partwise", version="4.0")
        work = ET.SubElement(root, "work")
        ET.SubElement(work, "work-title").text = song.title
        identification = ET.SubElement(root, "identification")
        encoding = ET.SubElement(identification, "encoding")
        ET.SubElement(encoding, "software").text = "BandPilot"
        part_list = ET.SubElement(root, "part-list")
        for index, track in enumerate(song.score.tracks, start=1):
            part_id = f"P{index}"
            score_part = ET.SubElement(part_list, "score-part", id=part_id)
            ET.SubElement(score_part, "part-name").text = track.name
            score_instrument = ET.SubElement(score_part, "score-instrument", id=f"{part_id}-I1")
            ET.SubElement(score_instrument, "instrument-name").text = track.name
            midi = ET.SubElement(score_part, "midi-instrument", id=f"{part_id}-I1")
            ET.SubElement(midi, "midi-channel").text = "10" if track.family == "drums" else str(min(index, 9))
            program = int(track.instrument.get("program", 0)) + 1
            ET.SubElement(midi, "midi-program").text = str(max(1, min(128, program)))
        for index, track in enumerate(song.score.tracks, start=1):
            part = ET.SubElement(root, "part", id=f"P{index}")
            for measure in track.measures:
                _write_measure(part, song, track, measure)
        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(destination, encoding="utf-8", xml_declaration=True)
        return ExportResult(
            format_id=self.format_id,
            path=str(destination),
            measure_count=max((len(track.measures) for track in song.score.tracks), default=0),
            note_count=sum(
                len(measure.events)
                for track in song.score.tracks
                for measure in track.measures
            ),
        )


__all__ = ["DIVISIONS", "MusicXMLSongExporter"]

"""Physical-track to logical-stream resolution.

In SMF type-1 files, a single instrument may be split across multiple physical
tracks (e.g. one track per channel). This module groups notes by instrument
identity (program + channel) into logical streams for classification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fretpilot.midi.models import NormalizedNote, NormalizedTimeline, NormalizedTrack


@dataclass(slots=True)
class LogicalStream:
    """A logical instrument stream: notes grouped by program + channel."""

    stream_id: str
    program: int | None
    channel: int | None
    instrument_name: str | None
    track_name: str = ""
    notes: list[NormalizedNote] = field(default_factory=list)
    source_track_indices: list[int] = field(default_factory=list)

    @property
    def note_count(self) -> int:
        return len(self.notes)


def _meaningful_track_name(track: NormalizedTrack) -> str:
    """Return a track's real name, ignoring the auto-generated default label."""
    name = (track.name or "").strip()
    if not name or name == f"Track {track.index + 1}":
        return ""
    return name


def _timeline_title(timeline: NormalizedTimeline) -> str:
    """Return the conductor/title track name (first named track with no notes).

    Suno exports put the stem description (e.g. "Story of Despair (Lead
    Electric Guitar)") on the empty conductor track, while the note-bearing
    tracks stay unnamed. Surfacing that title lets the classifier read the
    strongest instrument signal even though every note's program is 0.
    """
    for track in timeline.tracks:
        if track.notes:
            continue
        name = _meaningful_track_name(track)
        if name:
            return name
    return ""


def resolve_streams(timeline: NormalizedTimeline) -> list[LogicalStream]:
    """Group all timeline notes into logical streams by (program, channel).

    Tracks with no notes are skipped. Notes preserve their source track index.
    A stream's ``track_name`` falls back to the timeline title when the source
    track has no meaningful name of its own.
    """
    streams: dict[tuple[int | None, int | None], LogicalStream] = {}
    title = _timeline_title(timeline)

    for track in timeline.tracks:
        if not track.notes:
            continue
        track_name = _meaningful_track_name(track) or title
        for note in track.notes:
            key = (note.program, note.channel)
            stream = streams.get(key)
            if stream is None:
                stream = LogicalStream(
                    stream_id=f"stream-{len(streams) + 1:03d}",
                    program=note.program,
                    channel=note.channel,
                    instrument_name=track.instrument_name,
                    track_name=track_name,
                )
                streams[key] = stream
            stream.notes.append(note)
            if track.index not in stream.source_track_indices:
                stream.source_track_indices.append(track.index)

    for stream in streams.values():
        stream.notes.sort(key=lambda n: (n.start_tick, n.pitch))

    return list(streams.values())


def stream_from_track(track: NormalizedTrack) -> LogicalStream:
    """Create a single logical stream from a physical track (1:1 mapping)."""
    return LogicalStream(
        stream_id=f"track-{track.index:03d}",
        program=track.program,
        channel=track.notes[0].channel if track.notes else None,
        instrument_name=track.instrument_name,
        track_name=_meaningful_track_name(track),
        notes=list(track.notes),
        source_track_indices=[track.index],
    )


__all__ = ["LogicalStream", "resolve_streams", "stream_from_track"]

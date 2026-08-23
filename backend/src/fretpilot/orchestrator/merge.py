"""IR merger — combines multiple instrument IRs into a unified structure.

Merges GuitarProjectIR and DrumProjectIR instances into a single dict
structure ready for GP5 export. Handles tempo/time-signature alignment so
all tracks share a consistent rhythmic grid.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fretpilot.ir.drum_models import DrumProjectIR
from fretpilot.ir.models import (
    GuitarProjectIR,
    IRKnowledgeReference,
    IRTempoEvent,
    IRTimeSignatureEvent,
    Transformation,
)


def _merge_tempo_maps(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
) -> list[IRTempoEvent]:
    """Merge tempo maps from all IRs.

    Guitar and drum tracks share the same source MIDI, so their tempo maps
    should be identical. We take the first available map and warn if there
    are conflicts (logged by the caller via warnings).
    """
    for ir in guitar_irs:
        if ir.tempo_map:
            return list(ir.tempo_map)
    for ir in drum_irs:
        if ir.tempo_map:
            return list(ir.tempo_map)
    return []


def _merge_time_signatures(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
) -> list[IRTimeSignatureEvent]:
    """Merge time-signature maps from all IRs.

    Same rationale as tempo: all tracks share the source MIDI's time-sig map.
    """
    for ir in guitar_irs:
        if ir.time_signatures:
            return list(ir.time_signatures)
    for ir in drum_irs:
        if ir.time_signatures:
            return list(ir.time_signatures)
    return []


def _merge_changes(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
) -> list[Transformation]:
    """Concatenate transformation records from all IRs.

    IDs are re-prefixed with the module name to avoid collisions:
    guitar changes keep their IDs; drum changes are prefixed with "drum-".
    """
    changes: list[Transformation] = []
    for ir in guitar_irs:
        changes.extend(ir.changes)
    for ir in drum_irs:
        for ch in ir.changes:
            changes.append(
                Transformation(
                    id=f"drum-{ch.id}",
                    stage=ch.stage,
                    source_note_index=ch.source_note_index,
                    before=ch.before,
                    after=ch.after,
                    confidence=ch.confidence,
                    reason=ch.reason,
                    knowledge_ref=ch.knowledge_ref,
                )
            )
    return changes


def _collect_warnings(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
) -> list[str]:
    """Collect warnings from all IRs, prefixed by module."""
    warnings: list[str] = []
    for ir in guitar_irs:
        for w in ir.warnings:
            warnings.append(f"[fretpilot] {w}")
    for ir in drum_irs:
        for w in ir.warnings:
            warnings.append(f"[stickpilot] {w}")
    return warnings


def _merge_knowledge(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
) -> IRKnowledgeReference | None:
    """Merge knowledge references from all IRs.

    Takes the first available knowledge reference (they should all point to
    the same KB snapshot). If guitar and drum IRs have different snapshots,
    we merge the kb_versions dicts.
    """
    merged_versions: dict[str, str] = {}
    merged_entries: list[str] = []
    snapshot_version = ""

    for ir in guitar_irs + drum_irs:
        if ir.knowledge is None:
            continue
        if not snapshot_version:
            snapshot_version = ir.knowledge.snapshot_version
        merged_versions.update(ir.knowledge.kb_versions)
        merged_entries.extend(ir.knowledge.entry_ids)

    if not snapshot_version:
        return None

    return IRKnowledgeReference(
        snapshot_version=snapshot_version,
        kb_versions=merged_versions,
        entry_ids=list(dict.fromkeys(merged_entries)),  # dedup, preserve order
    )


def merge_irs(
    guitar_irs: list[GuitarProjectIR],
    drum_irs: list[DrumProjectIR],
    title: str,
) -> dict[str, Any]:
    """Merge multiple instrument IRs into a unified structure for GP5 export.

    Produces a dict (not a single IR dataclass) because the unified structure
    contains heterogeneous track types (guitar tracks + drum tracks). The GP5
    exporter will read this unified dict and write multi-track output.

    Tempo and time-signature maps are aligned: all tracks share the same
    source MIDI, so their rhythmic grids should be identical. The first
    available map is used as the canonical one.

    Args:
        guitar_irs: List of guitar project IRs (one per guitar track).
        drum_irs: List of drum project IRs (one per drum track).
        title: Project title for the merged result.

    Returns:
        A dict with the unified structure::

            {
                "title": str,
                "schema_version": "1.0-merged",
                "tempo_map": [...],
                "time_signatures": [...],
                "guitar_tracks": [...],
                "drum_tracks": [...],
                "knowledge": {...} | None,
                "style_label": str,
                "changes": [...],
                "warnings": [...],
            }
    """
    tempo_map = _merge_tempo_maps(guitar_irs, drum_irs)
    time_signatures = _merge_time_signatures(guitar_irs, drum_irs)
    changes = _merge_changes(guitar_irs, drum_irs)
    warnings = _collect_warnings(guitar_irs, drum_irs)
    knowledge = _merge_knowledge(guitar_irs, drum_irs)

    # Determine a style label: prefer guitar, fall back to drum, then "unknown".
    style_label = "unknown"
    for ir in guitar_irs:
        if ir.style_label != "unknown":
            style_label = ir.style_label
            break
    if style_label == "unknown":
        for ir in drum_irs:
            if ir.style_label != "unknown":
                style_label = ir.style_label
                break

    # Serialize tracks.
    guitar_tracks = [t for ir in guitar_irs for t in ir.tracks]
    drum_tracks = [t for ir in drum_irs for t in ir.tracks]

    guitar_tracks_dicts = [asdict(t) for t in guitar_tracks]
    drum_tracks_dicts = [asdict(t) for t in drum_tracks]

    # Total note count across all tracks.
    guitar_note_count = sum(
        len(m.events) for t in guitar_tracks for m in t.measures
    )
    drum_note_count = sum(
        len(m.events) for t in drum_tracks for m in t.measures
    )

    return {
        "title": title,
        "schema_version": "1.0-merged",
        "tempo_map": [asdict(e) for e in tempo_map],
        "time_signatures": [asdict(e) for e in time_signatures],
        "guitar_tracks": guitar_tracks_dicts,
        "drum_tracks": drum_tracks_dicts,
        "knowledge": asdict(knowledge) if knowledge else None,
        "style_label": style_label,
        "changes": [asdict(c) for c in changes],
        "warnings": warnings,
        "note_count": guitar_note_count + drum_note_count,
        "guitar_note_count": guitar_note_count,
        "drum_note_count": drum_note_count,
        "guitar_track_count": len(guitar_tracks),
        "drum_track_count": len(drum_tracks),
    }


__all__ = ["merge_irs"]

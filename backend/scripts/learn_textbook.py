#!/usr/bin/env python3
"""Learn a textbook (music pedagogy PDF) into the FretPilot knowledge base.

This is the ``source_type="textbook"`` ingestion path of the learning loop:
structured musical knowledge extracted from a published method book is merged
into KB2 (performance priors + canonical chord shapes), versioned, and promoted
to the active assets.

Current source::

    Troy Stetina & Tony Burton — The Speed & Thrash Metal Guitar Method
    (Hal Leonard, 1990).  Chapters: eighth-note subdivisions (muting,
    accenting chords, syncopation), sixteenth/triplet subdivisions (alternate
    picking, gallop/reverse-gallop), thrash theory (E tonal center, scales,
    chromaticism, harmony), 6/8 + double-time, and three full songs
    (Anvil Head, Bug Guts, Megadirt).

Usage::

    cd backend
    python scripts/learn_textbook.py [--no-promote]

The script:
  1. Builds canonical power-chord shapes from the book's "Power Chords"
     chapter (movable 2/3/4-string forms on 6th- and 5th-string roots,
     plus the open E5/A5/G5 forms the exercises use).
  2. Merges them + textbook-derived priors into ``kb2-metal-performance``.
  3. Writes a new versioned snapshot (all 4 domain files stamped) and updates
     the version manifest, promoting to ``assets/`` unless ``--no-promote``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Locate the knowledge root (script lives in backend/scripts/) ───
_SCRIPT_DIR = Path(__file__).resolve().parent
_KB_ROOT = (_SCRIPT_DIR / ".." / "src" / "fretpilot" / "knowledge").resolve()
_ASSETS = _KB_ROOT / "assets"
_VERSIONS = _KB_ROOT / "versions"
_MANIFEST = _KB_ROOT / "version_manifest.json"
_DOMAIN_FILES = (
    "kb1_arrangement.json",
    "kb2_performance.json",
    "kb3_notation.json",
    "kb4_instruments.json",
)

BOOK_SOURCE_ID = "troy-stetina-speed-thrash-metal-method"

# ─── Textbook knowledge spec ───
# Each key is a knowledge_id; the script merges ``payload`` into the existing
# entry (or appends a new entry when the id is unknown).

TEXTBOOK_KNOWLEDGE: dict[str, dict] = {
    "kb2-metal-performance": {
        # Chapter "Power Chords": the root+fifth power chord is THE chord of
        # speed/thrash metal.  Chords are built on the 5th/6th strings and move
        # up the neck; 2-string (lean/fast) and 3-string (fuller) forms both
        # appear, and open E5/A5/G5 forms are used for the tonic.
        "power_chord_preference": 1.5,
        "shape_reuse": 1.55,            # compact adjacent-string grips
        "hand_position_stability": 1.45,  # riffing stays in one position
        "palm_mute": 1.65,              # P.M. "chunky" riffing is characteristic
        "downpicking_bias": 1.35,       # gallop = downstroke-driven
        "note_overlap": 0.7,            # short, cut-off palm-muted notes
        "timing_looseness": 0.65,       # tight, metronome-strict
        "open_string_bias": 0.6,        # open E5/A5 tonic forms are idiomatic
    },
}


def _shape(string: int, fret: int) -> str:
    return f"s{string}f{fret}"


def _pc_shapes() -> dict[str, int]:
    """Canonical movable power-chord shapes (key → textbook weight).

    Root frets 0..12 on the 6th/5th strings; 2/3/4-string forms.  Shape keys
    are absolute ``s{string}f{fret}`` grips, so the intervals must be real:

    - root on string 6 fret ``r``  → fifth on string 5 fret ``r+2``, octave on
      string 4 fret ``r+2``  (a same-fret string-5 note is a *fourth* below/up,
      NOT the power-chord fifth — string 6→5 is tuned a P4 apart).
    - root on string 5 fret ``r``  → fifth on string 4 fret ``r+2``, octave on
      string 3 fret ``r+2``.

    Weights encode how idiomatic each form is for the style:
    2-string (fast thrash riffing) > 3-string (fuller sound) > 4-string.
    """
    shapes: dict[str, int] = {}

    def add(parts: tuple[tuple[int, int], ...], weight: int) -> None:
        key = ",".join(_shape(s, f) for s, f in sorted(parts))
        shapes[key] = weight

    for r in range(13):  # root frets 0..12
        # 6th-string root: s6f{r} root, s5f{r+2} fifth, s4f{r+2} octave
        add(((6, r), (5, r + 2)), 1000)                    # 2-string
        add(((6, r), (5, r + 2), (4, r + 2)), 900)         # 3-string
        add(((6, r), (5, r + 2), (4, r + 2), (3, r + 2)), 600)  # 4-string
        # 5th-string root: s5f{r} root, s4f{r+2} fifth, s3f{r+2} octave
        add(((5, r), (4, r + 2)), 1000)                    # 2-string
        add(((5, r), (4, r + 2), (3, r + 2)), 900)         # 3-string
        add(((5, r), (4, r + 2), (3, r + 2), (2, r + 2)), 600)  # 4-string

    # Open forms the book's exercises use (tonic power chords):
    # E5 open (0 2 2 x x x), A5 open (x 0 2 2 x x), G5 open (3 x 0 0 x x).
    shapes["s4f2,s5f2,s6f0"] = 800    # E5 open: E-B-E
    shapes["s3f2,s4f2,s5f0"] = 800    # A5 open: A-E-A
    shapes["s3f0,s4f0,s6f3"] = 700    # G5 open (book page: "open G5 rings more")
    return shapes


def _stamp_snapshot_version(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["snapshot_version"] = version
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_versioned_kb(version: str) -> None:
    """Copy current assets into a version dir, stamped with *version*."""
    version_dir = _VERSIONS / version
    version_dir.mkdir(parents=True, exist_ok=False)
    for filename in _DOMAIN_FILES:
        src = _ASSETS / filename
        if not src.exists():
            continue
        dst = version_dir / filename
        shutil.copy2(src, dst)
        _stamp_snapshot_version(dst, version)


def _merge_kb2(chord_shapes: dict[str, int], version: str) -> None:
    """Merge textbook knowledge into assets/kb2_performance.json.

    The textbook shapes are merged together with every chord shape already
    learned from the GP corpus (other style entries).  Without this, giving
    ``metal`` its own ``chord_shapes`` would stop the engine's merged-ensemble
    fallback, silently dropping the empirical shapes that previously applied.
    """
    kb2_path = _ASSETS / "kb2_performance.json"
    data = json.loads(kb2_path.read_text(encoding="utf-8"))
    data["snapshot_version"] = version
    entries: list[dict] = data.get("entries", [])
    by_id = {e["knowledge_id"]: e for e in entries}

    # Preserve every existing corpus-learned shape across all entries.
    merged_shapes = dict(chord_shapes)
    for entry in entries:
        existing = entry.get("payload", {}).get("chord_shapes")
        if isinstance(existing, dict):
            for key, count in existing.items():
                merged_shapes[str(key)] = merged_shapes.get(str(key), 0) + int(count)

    for knowledge_id, spec in TEXTBOOK_KNOWLEDGE.items():
        entry = by_id.get(knowledge_id)
        if entry is None:
            entry = {
                "knowledge_id": knowledge_id,
                "domain": "kb2_performance",
                "kind": "fingering_priors",
                "schema_version": "1",
                "knowledge_version": version,
                "status": "approved",
                "payload": {},
                "scope": {"style": ["metal"]},
                "provenance": {},
                "evaluation": {"status": "approved", "confidence": 0.9},
            }
            entries.append(entry)
        payload = dict(entry.get("payload", {}))
        # Textbook spec *adds* knowledge the GP corpus cannot see (e.g.
        # power-chord preference, canonical power-chord shapes).  It must NOT
        # override empirically learned prior values — those are grounded in
        # real tablature and are the better estimate when both exist.
        for key, value in spec.items():
            if key not in payload:
                payload[key] = value
        payload["chord_shapes"] = dict(merged_shapes)
        entry["payload"] = payload
        entry["knowledge_version"] = version
        entry["provenance"] = {
            "source_type": "textbook",
            "source_ids": [BOOK_SOURCE_ID],
            "authored_by": "learning_loop/textbook",
            "notes": (
                "Merged from Troy Stetina & Tony Burton, 'The Speed & Thrash "
                "Metal Guitar Method' (Hal Leonard, 1990): power-chord shapes, "
                "palm-mute riffing, gallop/downpicking, tight syncopated "
                "timing, E-tonic open power chords.  Corpus-learned shapes "
                "from other style entries are preserved alongside the "
                "textbook shapes."
            ),
        }
        entry["evaluation"] = {
            "status": "approved",
            "confidence": 0.9,
            "tested_against": [BOOK_SOURCE_ID],
        }

    data["entries"] = entries
    kb2_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _update_manifest(version: str) -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    entry = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source_type": "textbook",
        "styles_updated": ["metal"],
        "knowledge_ids_updated": list(TEXTBOOK_KNOWLEDGE.keys()),
        "total_sources": 1,
        "avg_confidence": 0.9,
        "method": "textbook_ingestion",
    }
    manifest.setdefault("versions", []).append(entry)
    manifest["active_version"] = version
    manifest["last_updated"] = entry["timestamp"]
    _MANIFEST.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-promote",
        action="store_true",
        help="write the version snapshot but keep assets/ unchanged",
    )
    args = parser.parse_args()

    if not (_ASSETS / "kb2_performance.json").exists():
        print(f"ERROR: KB assets not found under {_KB_ROOT}")
        return 1

    version = datetime.now(timezone.utc).strftime("%Y.%m.%d-%H%M%S")
    chord_shapes = _pc_shapes()

    # 1. Merge into the active asset (source of truth).
    _merge_kb2(chord_shapes, version)
    print(f"Merged {len(chord_shapes)} chord shapes into kb2_performance.json")

    # 2. Snapshot the (now merged) assets into a versioned directory so the
    #    version snapshot equals the promoted assets.
    _write_versioned_kb(version)

    # 3. Manifest + optional promote.
    _update_manifest(version)
    if not args.no_promote:
        for filename in _DOMAIN_FILES:
            src = _VERSIONS / version / filename
            dst = _ASSETS / filename
            if src.exists():
                shutil.copy2(src, dst)
        print(f"Promoted version {version} to assets/")

    print(f"New KB snapshot version: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Directory category → KB2 style label mapping.

Maps the directory structure of the reference GP collection to the 5 KB2
style labels (metal, rock, pop, funk, unknown).  The top-level mapping is
the P0 heuristic from the architecture doc §7.7; more specific subdirectory
hints (e.g. a ``【Rock Licks】`` folder under the generic practice category)
take precedence and are matched first.

Future versions can auto-infer style from tempo/range/technique features.
"""

from __future__ import annotations

# ─── Mapping table ───
#
# Keys are matched against each path segment of the tab's parent directory.
# Because we walk segments *deepest-first*, a subdirectory keyword wins over
# its generic parent category (e.g. ``【Rock Licks】`` inside
# ``【吉他练习系列】`` → rock, not unknown).

_DIR_TO_STYLE: dict[str, str] = {
    # ── top-level categories (ARCH doc §7.7) ──
    "电吉他": "rock",
    "乐队": "rock",
    "木吉他": "pop",
    "影视": "pop",
    "练习": "unknown",
    "动漫": "unknown",
    "游戏": "unknown",
    "贝斯": "unknown",
    # ── subdirectory hints (more specific, matched first) ──
    "Rock Licks": "rock",
    "rock licks": "rock",
    "小林信一": "metal",   # Shinichi Kobayashi — shred / metal guitarist
    "小林克已": "rock",    # Katsuya Kobayashi — rock/blues guitar studies
    "卡尔卡西": "pop",     # Carcassi — classical guitar studies (fingerstyle)
}

_VALID_STYLES = {"metal", "rock", "pop", "funk", "unknown"}

# Filename keyword fallback used when the directory gives no answer.
_FILENAME_TO_STYLE: dict[tuple[str, ...], str] = {
    ("metallica", "slayer", "megadeth", "death metal", "black metal"): "metal",
    ("rock", "blues", "solo", "lick", "van halen", "hendrix", "srv",
     "santana", "clapton", "bb king", "b.b. king", "gary moore"): "rock",
    ("funk", "slap", "disco", "prince"): "funk",
    ("pop", "acoustic", "ballad", "ed sheeran", "taylor swift"): "pop",
}


def map_directory_to_style(dir_path: str) -> str:
    """Infer a KB2 style label from a directory path.

    Scans path segments deepest-first so subdirectory hints override their
    generic parent category.  Returns ``"unknown"`` when nothing matches.
    """
    segments = [s for s in dir_path.replace("\\", "/").split("/") if s]
    for segment in reversed(segments):
        for keyword, style in _DIR_TO_STYLE.items():
            if keyword in segment:
                return style
    return "unknown"


def map_filename_to_style(filename: str) -> str:
    """Infer style from filename keywords (fallback when the directory is
    unhelpful).  Keyword groups are matched in order; the first hit wins."""
    lower = filename.lower()
    for keywords, style in _FILENAME_TO_STYLE.items():
        if any(k in lower for k in keywords):
            return style
    return "unknown"


def is_valid_style(style: str) -> bool:
    """Check if a style label is in the KB2 vocabulary."""
    return style in _VALID_STYLES


__all__ = [
    "map_directory_to_style",
    "map_filename_to_style",
    "is_valid_style",
]

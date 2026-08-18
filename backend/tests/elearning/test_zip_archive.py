"""Tests for the elearning API's GBK-aware zip archive extraction.

The reference GP collections are Windows-created zips whose entry names
are GBK-encoded.  On POSIX systems ``zipfile`` surfaces those names as
CP437 mojibake, which used to break style classification (every file
became ``unknown``).  These tests lock in the decoding fix.
"""

from __future__ import annotations

import struct
import zlib
import zipfile
from pathlib import Path

from fretpilot.api.routes.elearning import _decode_zip_name, _extract_archive


def _info(name: str, utf8_flag: bool = False) -> zipfile.ZipInfo:
    """Build a ZipInfo with a controllable UTF-8 flag bit (ZIP spec bit 11)."""
    info = zipfile.ZipInfo(name)
    info.flag_bits = 0x800 if utf8_flag else 0
    return info


def _make_gbk_zip(path: Path, entries: dict[str, bytes]) -> None:
    """Hand-craft a minimal ZIP whose entry names are GBK bytes.

    Python's ``zipfile`` writer always encodes non-ASCII names as UTF-8
    with the UTF-8 flag set, so a true GBK archive (no UTF-8 flag, names
    in GBK) has to be built byte-by-byte — exactly what Windows tools
    produce and what the reference GP collections use.
    """
    local_parts: list[bytes] = []
    central_parts: list[bytes] = []
    offset = 0
    for name, content in entries.items():
        name_bytes = name.encode("gbk")
        crc = zlib.crc32(content) & 0xFFFFFFFF
        # Local file header.
        local = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,  # signature
            20,  # version needed (2.0)
            0,  # flags (no UTF-8 flag → not UTF-8)
            0,  # compression: stored
            0, 0,  # mod time / date
            crc,
            len(content),  # compressed size
            len(content),  # uncompressed size
            len(name_bytes),  # filename length
            0,  # extra length
        )
        local_parts.append(local + name_bytes + content)

        # Central directory entry.
        central = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,  # signature
            20,  # version made by
            20,  # version needed
            0,  # flags
            0,  # compression: stored
            0, 0,  # mod time / date
            crc,
            len(content),
            len(content),
            len(name_bytes),
            0,  # extra length
            0,  # comment length
            0,  # disk number start
            0,  # internal attrs
            0,  # external attrs
            offset,  # local header offset
        )
        central_parts.append(central + name_bytes)
        offset += len(local + name_bytes + content)

    cd_offset = offset
    cd_size = sum(len(p) for p in central_parts)
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,  # signature
        0,  # disk number
        0,  # disk with central dir
        len(entries),  # entries on this disk
        len(entries),  # total entries
        cd_size,
        cd_offset,
        0,  # comment length
    )
    path.write_bytes(b"".join(local_parts) + b"".join(central_parts) + eocd)


def _read_zip(path: Path) -> zipfile.ZipFile:
    """Open a hand-crafted zip (must use our cp437→decode convention)."""
    return zipfile.ZipFile(path)


def test_decode_zip_name_recovers_gbk_chinese() -> None:
    """CP437 mojibake should decode back to the original Chinese name."""
    # GBK bytes of "【电吉他】/demo.gp5" interpreted as CP437 — exactly what
    # `zipfile.ZipInfo.filename` surfaces on POSIX for a Windows GBK zip.
    raw = "【电吉他】/demo.gp5".encode("gbk").decode("cp437")

    decoded = _decode_zip_name(_info(raw, utf8_flag=False))

    assert decoded == "【电吉他】/demo.gp5"


def test_decode_zip_name_passes_through_utf8() -> None:
    """Proper UTF-8 names (with the ZIP UTF-8 flag) must be untouched."""
    decoded = _decode_zip_name(_info("【木吉他】/song.gp5", utf8_flag=True))
    assert decoded == "【木吉他】/song.gp5"


def test_extract_archive_decodes_names(tmp_path: Path) -> None:
    """Extraction must produce decoded paths, not mojibake ones."""
    zip_path = tmp_path / "collection.zip"
    _make_gbk_zip(
        zip_path,
        {
            "【GTP谱】/【电吉他】/rock_solo.gp5": b"fake gp5",
            "【GTP谱】/【木吉他】/acoustic.gp4": b"fake gp4",
            "【GTP谱】/notes.txt": b"ignore me",
        },
    )

    dest = tmp_path / "out"
    dest.mkdir()
    files = _extract_archive(zip_path, dest)

    names = sorted(p.relative_to(dest).as_posix() for p in files)
    assert names == sorted([
        "【GTP谱】/【电吉他】/rock_solo.gp5",
        "【GTP谱】/【木吉他】/acoustic.gp4",
    ])
    assert (dest / "【GTP谱】/【电吉他】/rock_solo.gp5").read_bytes() == b"fake gp5"


def test_extract_archive_blocks_path_traversal(tmp_path: Path) -> None:
    """Zip-slip entries must be skipped, not written outside dest_dir."""
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # A traversal entry: "../evil.gp5".
        zf.writestr("../evil.gp5", b"evil")

    dest = tmp_path / "out"
    dest.mkdir()
    files = _extract_archive(zip_path, dest)

    assert files == []
    assert not (tmp_path / "evil.gp5").exists()

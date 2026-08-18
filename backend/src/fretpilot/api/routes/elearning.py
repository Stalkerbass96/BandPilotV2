"""E-learning routes — expose the learning loop to the frontend.

Provides:
  - ``POST /api/elearning/learn``     — upload GP files / zip archives; the
    server parses them, extracts fingering statistics, derives empirical
    priors and writes a new versioned KB snapshot.
  - ``GET  /api/elearning/versions``  — list KB versions + active version.
  - ``POST /api/elearning/rollback``  — roll the active KB back to a version.
  - ``GET  /api/elearning/diff``      — payload diff between two versions.
"""

from __future__ import annotations

import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from fretpilot.api.deps import get_current_user
from fretpilot.db.models import User
from fretpilot.elearning.gp_reader import GPReader
from fretpilot.elearning.kb_writer import KBWriter
from fretpilot.elearning.priors_deriver import PriorsDeriver
from fretpilot.elearning.stats_extractor import StatsExtractor
from fretpilot.elearning.style_mapper import map_filename_to_style

logger = logging.getLogger("fretpilot.api.elearning")

router = APIRouter()

# Knowledge root: <src>/fretpilot/knowledge (assets/ + versions/ live here).
# __file__ = .../fretpilot/api/routes/elearning.py → parents[2] = .../fretpilot
_KB_ROOT = Path(__file__).resolve().parents[2] / "knowledge"

# Upload limits.
_SUPPORTED_EXTENSIONS = (".gp3", ".gp4", ".gp5")
_MAX_FILES_PER_REQUEST = 300
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB total


def _kb_writer() -> KBWriter:
    return KBWriter(_KB_ROOT)


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """Decode a zip entry name written with a non-UTF-8 codepage.

    The reference GP archives were created on Windows with GBK-encoded
    filenames.  On POSIX systems ``ZipInfo.filename`` surfaces those bytes
    as CP437 mojibake (e.g. ``í╛╝¬╦√┴╖╧░╧╡┴╨í┐``).  Decode them back to
    the original Chinese so style classification (``style_mapper``) can
    actually match directory keywords like ``电吉他``.

    Strategy:
      1. Respect the ZIP spec flag bit 11 (filename is UTF-8).
      2. Otherwise recover the original bytes via ``cp437`` (the codepage
         the ``zipfile`` module used to produce ``info.filename``) and try
         UTF-8 first, then GBK.
      3. Fall back to the raw name when neither decoding succeeds.
    """
    if info.flag_bits & 0x800:  # ZIP spec: filename already UTF-8
        return info.filename
    try:
        raw_bytes = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename  # not cp437-representable → real text already
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw_bytes.decode("gbk")
        except UnicodeDecodeError:
            return info.filename


def _extract_archive(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Safely extract a zip archive and return discovered GP files.

    Handles GBK-encoded entry names (see :func:`_decode_zip_name`) and
    guards against path traversal (zip-slip).  Files are written to disk
    with their decoded names so downstream style classification works.
    """
    extracted: list[Path] = []
    dest_root = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = _decode_zip_name(info)
            # Guard against path traversal (zip-slip).
            target = (dest_root / name).resolve()
            if not str(target).startswith(str(dest_root)):
                logger.warning("Skip unsafe zip entry: %s", info.filename)
                continue
            if info.is_dir():
                (dest_root / name).mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            if name.lower().endswith(_SUPPORTED_EXTENSIONS):
                extracted.append(target)
    return extracted


@router.post("/learn", response_model=dict)
async def learn(
    user: User = Depends(get_current_user),
    files: list[UploadFile] = File(..., description="GP3/GP4/GP5 files or zip archives"),
    style: str | None = Form(None, description="Optional style override (rock/metal/pop/funk)"),
    promote: bool = Form(True, description="Immediately promote the new KB version to active"),
) -> dict:
    """Upload GP files or zips; run the full learning loop.

    Flow: save uploads → unzip archives → parse GP tabs → extract
    statistics → derive priors → write versioned KB snapshot.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    gp_paths: list[Path] = []
    total_bytes = 0
    failed_files: list[dict[str, str]] = []
    tabs = []
    parse_errors: list[dict[str, str]] = []

    # NOTE: parsing must happen inside the temp-dir context (the files are
    # deleted as soon as the ``with`` block exits).
    with tempfile.TemporaryDirectory(prefix="elearn_") as tmp:
        tmp_dir = Path(tmp)

        for upload in files:
            total_bytes += upload.size or 0
            if total_bytes > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Upload too large (max 200 MB)")

            name = upload.filename or "unnamed"
            dest = tmp_dir / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = await upload.read()
                dest.write_bytes(content)
            except OSError as exc:
                failed_files.append({"file": name, "error": str(exc)})
                continue

            lower = name.lower()
            if lower.endswith(".zip"):
                try:
                    gp_paths.extend(_extract_archive(dest, tmp_dir))
                except (zipfile.BadZipFile, OSError) as exc:
                    failed_files.append({"file": name, "error": f"bad zip: {exc}"})
            elif lower.endswith(_SUPPORTED_EXTENSIONS):
                gp_paths.append(dest)
            else:
                failed_files.append(
                    {"file": name, "error": "unsupported format (use .gp3/.gp4/.gp5/.zip)"}
                )

        if not gp_paths:
            raise HTTPException(
                status_code=400,
                detail={"message": "No supported GP files found", "failed": failed_files},
            )

        gp_paths = gp_paths[:_MAX_FILES_PER_REQUEST]

        # 1. Parse tabs (style override wins over filename inference).
        reader = GPReader()
        for gp_path in gp_paths:
            try:
                tab = reader.parse(
                    gp_path,
                    style_label=style if style else None,
                )
                if tab.notes:
                    tabs.append(tab)
                else:
                    parse_errors.append({"file": gp_path.name, "error": "no guitar notes"})
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                parse_errors.append({"file": gp_path.name, "error": str(exc)[:200]})

    if not tabs:
        raise HTTPException(
            status_code=422,
            detail={"message": "All files failed to parse", "failed": parse_errors},
        )

    # 2. Extract statistics per style.
    stats = StatsExtractor().extract(tabs)

    # 3. Derive empirical priors.
    source_ids_map = {
        style_label: [t.file_path for t in tabs if t.style_label == style_label]
        for style_label in stats
    }
    derived = PriorsDeriver().derive(stats, source_ids_map)

    # 4. Write KB version.
    writer = _kb_writer()
    new_version = writer.write(derived, promote=promote)

    # Serialise results for the frontend.
    stats_payload = [
        {
            "style": s.style_label,
            "sample_count": s.sample_count,
            "total_notes": s.total_notes,
            "open_string_rate": s.open_string_rate,
            "avg_string_skip": s.avg_string_skip,
            "note_overlap_rate": s.note_overlap_rate,
            "staccato_rate": s.staccato_rate,
            "top_chord_shapes": dict(list(s.chord_shape_top_k.items())[:5]),
        }
        for s in stats.values()
    ]
    priors_payload = [
        {
            "style": d.style_label,
            "knowledge_id": d.knowledge_id,
            "payload": d.payload,
            "confidence": d.confidence,
            "source_count": len(d.source_ids),
            "derivation_method": d.derivation_method,
        }
        for d in derived
    ]

    return {
        "code": 0,
        "data": {
            "parsed_files": len(tabs),
            "total_files": len(gp_paths),
            "failed_files": failed_files + parse_errors,
            "style_stats": stats_payload,
            "derived_priors": priors_payload,
            "new_version": new_version,
            "promoted": promote,
            "total_notes": sum(s.total_notes for s in stats.values()),
        },
        "message": "ok",
    }


@router.get("/versions", response_model=dict)
def list_versions(user: User = Depends(get_current_user)) -> dict:
    """List all KB versions with metadata, plus the active version."""
    writer = _kb_writer()
    versions = writer.list_versions()
    manifest = writer._load_manifest()  # noqa: SLF001 — same package
    return {
        "code": 0,
        "data": {
            "items": list(reversed(versions)),  # newest first
            "active_version": manifest.get("active_version", ""),
        },
        "message": "ok",
    }


class RollbackRequest(BaseModel):
    version: str


@router.post("/rollback", response_model=dict)
def rollback(
    req: RollbackRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Roll the active KB back to a specific version."""
    writer = _kb_writer()
    try:
        writer.rollback(req.version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Version not found: {req.version}")
    return {"code": 0, "data": {"active_version": req.version}, "message": "ok"}


@router.get("/diff", response_model=dict)
def diff_versions(
    a: str,
    b: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Compare KB2 payloads between two versions."""
    writer = _kb_writer()
    try:
        diff = writer.diff_versions(a, b)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": 0, "data": diff, "message": "ok"}


__all__ = ["router"]

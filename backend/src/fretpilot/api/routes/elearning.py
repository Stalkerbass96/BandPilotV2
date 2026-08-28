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
import stat
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from fretpilot.api.deps import get_current_admin
from fretpilot.artifacts import file_sha256
from fretpilot.config import get_settings
from fretpilot.db.models import User
from fretpilot.elearning.drum_priors_deriver import DrumPriorsDeriver
from fretpilot.elearning.drum_reader import DrumReader
from fretpilot.elearning.drum_stats_extractor import DrumStatsExtractor
from fretpilot.elearning.governance import CorpusGovernanceError
from fretpilot.elearning.gp_reader import GPReader
from fretpilot.elearning.kb_writer import ABComparator, KBWriter
from fretpilot.elearning.priors_deriver import PriorsDeriver
from fretpilot.elearning.stats_extractor import StatsExtractor

logger = logging.getLogger("fretpilot.api.elearning")

router = APIRouter()

# Upload limits.
_SUPPORTED_EXTENSIONS = (".gp3", ".gp4", ".gp5")
_MAX_FILES_PER_REQUEST = 300
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB total
_MAX_ARCHIVE_ENTRIES = 1_000
_MAX_EXTRACTED_BYTES = 500 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200


def _kb_writer() -> KBWriter:
    settings = get_settings()
    settings.ensure_knowledge_store()
    return KBWriter(settings.knowledge_root_path)


def _validate_learning_metadata(
    license_id: str,
    rights_confirmed: bool,
    quality_tier: str,
) -> dict[str, str | bool]:
    if not rights_confirmed or not license_id.strip():
        raise HTTPException(
            status_code=422,
            detail="Learning requires an identified license and confirmed training rights.",
        )
    if quality_tier not in {"reviewed", "expert"}:
        raise HTTPException(
            status_code=422,
            detail="quality_tier must be reviewed or expert",
        )
    return {
        "license_id": license_id.strip(),
        "rights_confirmed": True,
        "quality_tier": quality_tier,
    }


async def _ingest_uploads(
    files: list[UploadFile],
    tmp_dir: Path,
) -> tuple[list[Path], list[dict[str, str]]]:
    """Save uploads into ``tmp_dir``, unzip archives, and collect GP files.

    Args:
        files: Uploaded GP files and/or zip archives.
        tmp_dir: Destination directory (owned by the caller's temp context).

    Returns:
        ``(gp_paths, failed_files)`` — GP file paths plus per-file failures.
        Raises ``HTTPException(413)`` when the total upload exceeds the cap.
    """
    gp_paths: list[Path] = []
    failed_files: list[dict[str, str]] = []
    total_bytes = 0

    for index, upload in enumerate(files):
        name = upload.filename or "unnamed"
        safe_name = Path(name).name or "unnamed"
        dest = tmp_dir / f"{index:04d}-{safe_name}"
        try:
            upload_too_large = False
            with open(dest, "wb") as destination:
                while chunk := await upload.read(1024 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > _MAX_UPLOAD_BYTES:
                        upload_too_large = True
                        break
                    destination.write(chunk)
            if upload_too_large:
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail="Upload too large (max 200 MB)",
                )
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

    return gp_paths[: _MAX_FILES_PER_REQUEST], failed_files


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
    extracted_bytes = 0
    dest_root = dest_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ARCHIVE_ENTRIES:
            raise OSError(f"Archive contains too many entries (max {_MAX_ARCHIVE_ENTRIES})")
        for info in infos:
            name = _decode_zip_name(info)
            # Guard against path traversal (zip-slip).
            target = (dest_root / name).resolve()
            try:
                target.relative_to(dest_root)
            except ValueError:
                logger.warning("Skip unsafe zip entry: %s", info.filename)
                continue
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                logger.warning("Skip archive symlink: %s", info.filename)
                continue
            if info.flag_bits & 0x1:
                raise OSError("Encrypted archives are not supported")
            if info.file_size > _MAX_EXTRACTED_BYTES:
                raise OSError("Archive entry is too large")
            if info.compress_size == 0 and info.file_size > 0:
                raise OSError("Archive entry has an invalid compression ratio")
            if info.compress_size and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO:
                raise OSError("Archive compression ratio exceeds safety limit")
            extracted_bytes += info.file_size
            if extracted_bytes > _MAX_EXTRACTED_BYTES:
                raise OSError("Archive expands beyond the allowed size")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            actual_entry_bytes = 0
            with zf.open(info) as source, open(target, "wb") as destination:
                while chunk := source.read(1024 * 1024):
                    actual_entry_bytes += len(chunk)
                    if actual_entry_bytes > info.file_size:
                        raise OSError("Archive entry exceeded its declared size")
                    destination.write(chunk)
            if name.lower().endswith(_SUPPORTED_EXTENSIONS):
                extracted.append(target)
    return extracted


@router.post("/learn", response_model=dict)
async def learn(
    user: User = Depends(get_current_admin),
    files: list[UploadFile] = File(..., description="GP3/GP4/GP5 files or zip archives"),
    style: str | None = Form(None, description="Optional style override (rock/metal/pop/funk)"),
    promote: bool = Form(False, description="Promote only after evaluation and approval"),
    license_id: str = Form(..., description="License or corpus-rights identifier"),
    rights_confirmed: bool = Form(False, description="Confirm training use is permitted"),
    quality_tier: str = Form("reviewed", description="reviewed or expert"),
) -> dict:
    """Upload GP files or zips; run the full learning loop.

    Flow: save uploads → unzip archives → parse GP tabs → extract
    statistics → derive priors → write versioned KB snapshot.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if promote:
        raise HTTPException(
            status_code=409,
            detail="Direct promotion is disabled; create, evaluate, then promote the candidate.",
        )
    governance = _validate_learning_metadata(
        license_id, rights_confirmed, quality_tier
    )

    tabs = []
    parse_errors: list[dict[str, str]] = []
    source_ids_by_path: dict[str, str] = {}

    # NOTE: parsing must happen inside the temp-dir context (the files are
    # deleted as soon as the ``with`` block exits).
    with tempfile.TemporaryDirectory(prefix="elearn_") as tmp:
        tmp_dir = Path(tmp)
        gp_paths, failed_files = await _ingest_uploads(files, tmp_dir)

        if not gp_paths:
            raise HTTPException(
                status_code=400,
                detail={"message": "No supported GP files found", "failed": failed_files},
            )

        # 1. Parse tabs (style override wins over filename inference).
        reader = GPReader()
        for gp_path in gp_paths:
            try:
                source_ids_by_path[str(gp_path)] = f"sha256:{file_sha256(gp_path)}"
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
        style_label: [
            source_ids_by_path[t.file_path]
            for t in tabs
            if t.style_label == style_label
        ]
        for style_label in stats
    }
    derived = PriorsDeriver().derive(stats, source_ids_map)
    for prior in derived:
        prior.governance = dict(governance)

    # 4. Write KB version.
    writer = _kb_writer()
    new_version = writer.write(derived, promote=False)

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
            "promoted": False,
            "total_notes": sum(s.total_notes for s in stats.values()),
        },
        "message": "ok",
    }


@router.post("/learn/drum", response_model=dict)
async def learn_drum(
    user: User = Depends(get_current_admin),
    files: list[UploadFile] = File(..., description="GP3/GP4/GP5 files or zip archives with drum tracks"),
    style: str | None = Form(None, description="Optional style override (rock/metal/pop/funk/jazz)"),
    promote: bool = Form(False, description="Promote only after evaluation and approval"),
    license_id: str = Form(..., description="License or corpus-rights identifier"),
    rights_confirmed: bool = Form(False, description="Confirm training use is permitted"),
    quality_tier: str = Form("reviewed", description="reviewed or expert"),
) -> dict:
    """Upload GP files or zips; run the drum learning loop (StickPilot).

    Flow: save uploads → unzip archives → parse drum tracks → extract drum
    statistics → derive sticking priors → write versioned KB snapshot into
    ``drum_kb2_sticking.json``.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if promote:
        raise HTTPException(
            status_code=409,
            detail="Direct promotion is disabled; create, evaluate, then promote the candidate.",
        )
    governance = _validate_learning_metadata(
        license_id, rights_confirmed, quality_tier
    )

    tabs = []
    parse_errors: list[dict[str, str]] = []
    source_ids_by_path: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="elearn_drum_") as tmp:
        tmp_dir = Path(tmp)
        gp_paths, failed_files = await _ingest_uploads(files, tmp_dir)

        if not gp_paths:
            raise HTTPException(
                status_code=400,
                detail={"message": "No supported GP files found", "failed": failed_files},
            )

        # 1. Parse drum tracks (style override wins over filename inference).
        reader = DrumReader()
        for gp_path in gp_paths:
            try:
                source_ids_by_path[str(gp_path)] = f"sha256:{file_sha256(gp_path)}"
                tab = reader.parse(
                    gp_path,
                    style_label=style if style else None,
                )
                if tab.notes:
                    tabs.append(tab)
                else:
                    parse_errors.append({"file": gp_path.name, "error": "no drum notes"})
            except Exception as exc:  # noqa: BLE001 — per-file isolation
                parse_errors.append({"file": gp_path.name, "error": str(exc)[:200]})

    if not tabs:
        raise HTTPException(
            status_code=422,
            detail={"message": "All files failed to parse", "failed": parse_errors},
        )

    # 2. Extract drum statistics per style.
    stats = DrumStatsExtractor().extract(tabs)

    # 3. Derive empirical sticking priors.
    source_ids_map = {
        style_label: [
            source_ids_by_path[t.file_path]
            for t in tabs
            if t.style_label == style_label
        ]
        for style_label in stats
    }
    derived = DrumPriorsDeriver().derive(stats, source_ids_map)
    for prior in derived:
        prior.governance = dict(governance)
    if not derived:
        raise HTTPException(
            status_code=422,
            detail="No styles with enough samples (>=5 tabs per style) to derive priors",
        )

    # 4. Write KB version (routes priors into drum_kb2_sticking.json).
    writer = _kb_writer()
    new_version = writer.write(derived, promote=False)

    stats_payload = [
        {
            "style": s.style_label,
            "sample_count": s.sample_count,
            "total_notes": s.total_notes,
            "total_measures": s.total_measures,
            "hit_density": s.hit_density,
            "avg_inter_hit_gap_beats": s.avg_inter_hit_gap_beats,
            "velocity_mean": s.velocity_mean,
            "accent_rate": s.accent_rate,
            "ghost_note_rate": s.ghost_note_rate,
            "flam_rate": s.flam_rate,
            "double_stroke_rate": s.double_stroke_rate,
            "right_hand_rate": s.right_hand_rate,
            "hand_switch_pattern": s.hand_switch_pattern,
            "top_pieces": dict(list(s.piece_distribution.items())[:6]),
            "quarter_or_shorter_rate": s.quarter_or_shorter_rate,
            "voice_two_rate": s.voice_two_rate,
            "foot_voice_two_rate": s.foot_voice_two_rate,
            "top_written_durations": dict(
                list(s.duration_distribution.items())[:6]
            ),
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
            "promoted": False,
            "total_notes": sum(s.total_notes for s in stats.values()),
        },
        "message": "ok",
    }


@router.get("/versions", response_model=dict)
def list_versions(user: User = Depends(get_current_admin)) -> dict:
    """List all KB versions with metadata, plus the active version."""
    writer = _kb_writer()
    versions = writer.list_versions()
    manifest = writer.manifest()
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


class PromoteRequest(BaseModel):
    version: str


@router.post("/evaluate", response_model=dict)
async def evaluate_candidate(
    files: list[UploadFile] = File(..., description="Independent GP validation corpus"),
    version: str = Form(..., description="Candidate KB snapshot"),
    user: User = Depends(get_current_admin),
) -> dict:
    """Run server-side baseline/candidate A/B evaluation and record evidence."""

    writer = _kb_writer()
    active_version = str(writer.manifest().get("active_version", ""))
    if not active_version:
        raise HTTPException(status_code=409, detail="No active baseline KB version exists")
    if active_version == version:
        raise HTTPException(status_code=409, detail="Candidate is already the active version")

    with tempfile.TemporaryDirectory(prefix="elearn_eval_") as tmp:
        evaluation_dir = Path(tmp)
        gp_paths, failed = await _ingest_uploads(files, evaluation_dir)
        if not gp_paths:
            raise HTTPException(
                status_code=400,
                detail={"message": "No validation GP files found", "failed": failed},
            )
        try:
            validation_source_ids = {
                f"sha256:{file_sha256(path)}" for path in gp_paths
            }
            leaked_sources = validation_source_ids & writer.source_ids(version)
            if leaked_sources:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Validation corpus overlaps the candidate's training sources; "
                        "use independent score content."
                    ),
                )
            comparison = ABComparator(get_settings().knowledge_root_path).compare(
                evaluation_dir,
                active_version,
                version,
            )
            writer.record_evaluation(version, comparison)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "code": 0,
        "data": {"candidate": version, "baseline": active_version, **comparison},
        "message": "ok",
    }


@router.post("/promote", response_model=dict)
def promote_candidate(
    req: PromoteRequest,
    user: User = Depends(get_current_admin),
) -> dict:
    """Promote only a candidate which passes the deterministic quality gate."""

    writer = _kb_writer()
    try:
        writer.promote_evaluated(req.version)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CorpusGovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "data": {"active_version": req.version}, "message": "ok"}


@router.post("/rollback", response_model=dict)
def rollback(
    req: RollbackRequest,
    user: User = Depends(get_current_admin),
) -> dict:
    """Roll the active KB back to a specific version."""
    writer = _kb_writer()
    try:
        writer.rollback(req.version)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Version not found: {req.version}")
    except CorpusGovernanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"code": 0, "data": {"active_version": req.version}, "message": "ok"}


@router.get("/diff", response_model=dict)
def diff_versions(
    a: str,
    b: str,
    user: User = Depends(get_current_admin),
) -> dict:
    """Compare KB2 payloads between two versions."""
    writer = _kb_writer()
    try:
        diff = writer.diff_versions(a, b)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"code": 0, "data": diff, "message": "ok"}


__all__ = ["router"]

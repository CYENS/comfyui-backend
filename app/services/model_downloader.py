"""
Async streaming download service for ComfyUI model files.

Downloads are streamed from approved URLs directly to the ComfyUI models
directory. The destination path is determined by the requirement's folder
and model_name fields. A .tmp suffix is used during download and atomically
renamed on completion to prevent partially-downloaded files from being seen
by ComfyUI.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB per read
_PROGRESS_EVERY = 100 * 1024 * 1024  # log every 100 MiB


def _fmt_mb(n_bytes: int) -> str:
    return f"{n_bytes / 1024 / 1024:.1f} MiB"


async def download_model(
    model_name: str,
    folder: str,
    download_url: str,
    models_dir: str | None = None,
    progress_callback: Callable[[int], None] | None = None,
) -> Path:
    """
    Stream-download a model file from ``download_url`` into
    ``<models_dir>/<folder>/<model_name>``.

    Logs progress every 100 MiB, including percentage when content-length is
    known. Returns the destination path on success.
    """
    base = Path(models_dir or settings.comfy_models_dir)
    dest_dir = base / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / model_name

    if dest_path.exists():
        logger.info("Model already present, skipping download: %s", dest_path)
        return dest_path

    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    logger.info("Starting download: %s -> %s", download_url, dest_path)
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=30.0, read=3600.0, write=None, pool=None),
        ) as client:
            async with client.stream("GET", download_url) as resp:
                resp.raise_for_status()
                total_bytes = (
                    int(resp.headers["content-length"])
                    if "content-length" in resp.headers
                    else None
                )
                if total_bytes:
                    logger.info("File size: %s", _fmt_mb(total_bytes))
                else:
                    logger.info("File size: unknown")

                received = 0
                last_logged = 0
                last_pct = -1
                with open(tmp_path, "wb") as fh:
                    async for chunk in resp.aiter_bytes(_CHUNK_SIZE):
                        fh.write(chunk)
                        received += len(chunk)
                        if received - last_logged >= _PROGRESS_EVERY:
                            if total_bytes:
                                logger.info(
                                    "  %s / %s  (%.0f%%)",
                                    _fmt_mb(received),
                                    _fmt_mb(total_bytes),
                                    received / total_bytes * 100,
                                )
                            else:
                                logger.info("  %s received", _fmt_mb(received))
                            last_logged = received
                        if progress_callback and total_bytes:
                            pct = int(received / total_bytes * 100)
                            if pct - last_pct >= 5:
                                last_pct = pct
                                progress_callback(pct)

        tmp_path.rename(dest_path)
        logger.info(
            "Download complete: %s (%s)",
            dest_path,
            _fmt_mb(received),
        )
        return dest_path

    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


async def run_download(
    req_id: str,
    url: str,
    folder: str,
    model_name: str,
    session_factory: Any,
) -> None:
    """
    Background task wrapper: opens its own DB session, updates download_status/
    download_progress/download_error on the WorkflowModelRequirement row as the
    download proceeds.
    """
    from ..models import WorkflowModelRequirement  # local import to avoid circular

    db = session_factory()
    last_reported: list[int] = [-1]
    try:
        req = db.query(WorkflowModelRequirement).filter_by(id=req_id).one_or_none()
        if req:
            req.download_status = "downloading"
            db.commit()

        def on_progress(pct: int) -> None:
            if pct - last_reported[0] >= 5:
                last_reported[0] = pct
                r = db.query(WorkflowModelRequirement).filter_by(id=req_id).one_or_none()
                if r:
                    r.download_progress = pct
                    db.commit()

        await download_model(
            download_url=url,
            folder=folder,
            model_name=model_name,
            progress_callback=on_progress,
        )

        r = db.query(WorkflowModelRequirement).filter_by(id=req_id).one_or_none()
        if r:
            r.download_status = "completed"
            r.download_progress = 100
            db.commit()
    except Exception as exc:
        r = db.query(WorkflowModelRequirement).filter_by(id=req_id).one_or_none()
        if r:
            r.download_status = "failed"
            r.download_error = str(exc)
            db.commit()
        logger.error("Download failed for req %s (%s/%s): %s", req_id, folder, model_name, exc)
        raise
    finally:
        db.close()

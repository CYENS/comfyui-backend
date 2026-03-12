import asyncio
import hashlib
import json
import logging
import mimetypes
import sys
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import Asset, AssetType, AssetValidationCurrent, Job, JobStatus, ValidationStatus
from .services.comfy_client import ComfyClient

logger = logging.getLogger("backend.worker")


def configure_logging() -> None:
    level = getattr(logging, settings.worker_log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    log_path = Path(settings.worker_log_file)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        logger.exception("Failed to initialize file logging at %s", log_path)

    logger.info(
        "Worker logging initialized (level=%s, file=%s)", settings.worker_log_level, log_path
    )


def set_path(obj: dict, path: str, value):
    cur = obj
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _job_base_dir(job_id: str) -> Path:
    return Path(settings.storage_root) / "jobs" / job_id


def _safe_ext(filename: str, media_type: str | None) -> str:
    ext = Path(filename).suffix
    if ext:
        return ext
    guessed = mimetypes.guess_extension(media_type or "")
    return guessed or ".bin"


def _infer_asset_type(
    output_key: str,
    filename: str,
    media_type: str | None,
) -> AssetType:
    key = output_key.lower()
    mt = (media_type or "").lower()
    ext = Path(filename).suffix.lower()

    if "audio" in key or mt.startswith("audio/") or ext in {".mp3", ".wav", ".flac"}:
        return AssetType.AUDIO
    if "video" in key or mt.startswith("video/") or ext in {".mp4", ".mov", ".webm"}:
        return AssetType.VIDEO
    if (
        "image" in key
        or mt.startswith("image/")
        or ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    ):
        return AssetType.IMAGE
    if ext in {".ckpt", ".safetensors", ".onnx", ".pth"}:
        return AssetType.MODEL
    if "3d" in key or ext in {".glb", ".gltf", ".obj", ".ply", ".fbx", ".bvh"}:
        return AssetType.MESH
    return AssetType.OTHER


def _write_workflow_snapshot(job_id: str, graph: dict) -> None:
    target = _job_base_dir(job_id) / "workflow_used.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(graph, ensure_ascii=True, indent=2), encoding="utf-8")


async def _ingest_job_outputs(
    db: Session,
    job: Job,
    status: dict,
    client: ComfyClient,
) -> int:
    outputs = status.get("outputs")
    if not isinstance(outputs, dict):
        return 0

    output_dir = _job_base_dir(job.id) / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    ingested = 0
    seen: set[tuple[str, str, str]] = set()
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for output_key, items in node_output.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                if not filename:
                    continue
                subfolder = item.get("subfolder") or ""
                file_type = item.get("type") or "output"
                marker = (filename, subfolder, file_type)
                if marker in seen:
                    continue
                seen.add(marker)

                payload, content_type = await client.download_view(
                    filename=filename,
                    subfolder=subfolder,
                    type_=file_type,
                )

                asset_id = str(uuid.uuid4())
                ext = _safe_ext(filename, content_type)
                disk_path = output_dir / f"{asset_id}{ext}"
                disk_path.write_bytes(payload)

                checksum = hashlib.sha256(payload).hexdigest()
                asset_type = _infer_asset_type(output_key, filename, content_type)

                asset = Asset(
                    id=asset_id,
                    job_id=job.id,
                    workflow_id=job.workflow_id,
                    workflow_version_id=job.workflow_version_id,
                    type=asset_type,
                    file_path=str(disk_path),
                    original_filename=filename,
                    size_bytes=len(payload),
                    checksum_sha256=checksum,
                    media_type=content_type,
                )
                db.add(asset)
                db.add(
                    AssetValidationCurrent(
                        asset_id=asset_id,
                        status=ValidationStatus.PENDING,
                        moderator_user_id=None,
                        validated_at=None,
                        notes=None,
                    )
                )
                ingested += 1

    db.commit()
    return ingested


async def process_job(db: Session, job: Job, client: ComfyClient):
    logger.info("Processing job id=%s workflow_id=%s", job.id, job.workflow_id)
    job.status = JobStatus.SUBMITTED
    db.add(job)
    db.commit()

    workflow = job.workflow
    version = job.workflow_version
    graph = dict(version.prompt_json or {})
    _write_workflow_snapshot(job.id, graph)

    values = {iv.input_id: iv.value_json for iv in job.input_values}

    for definition in version.inputs_schema_json or []:
        input_id = definition.get("id")
        value = values.get(input_id, definition.get("default"))
        if value is None:
            continue

        for mapping in definition.get("mapping", []):
            node_id = mapping.get("node_id")
            path = mapping.get("path")
            node = graph.get(node_id)
            if node is None or path is None:
                continue
            set_path(node, path, value)

    extra_data = {
        "internal_job_id": job.id,
        "workflow_id": workflow.id,
        "workflow_version_id": version.id,
        "user_id": job.user_id,
    }

    submit_resp = await client.submit_prompt(prompt=graph, extra_data=extra_data)
    job.comfy_job_id = submit_resp.get("prompt_id")
    if not job.comfy_job_id:
        job.status = JobStatus.FAILED
        job.error_message = "ComfyUI did not return prompt_id"
        job.end_time = datetime.now(UTC)
        db.add(job)
        db.commit()
        logger.error("Job id=%s failed: ComfyUI did not return prompt_id", job.id)
        return
    db.add(job)
    db.commit()
    logger.info("Job id=%s submitted to ComfyUI as prompt_id=%s", job.id, job.comfy_job_id)

    while True:
        status = await client.get_job(job.comfy_job_id)
        status_str = status.get("status")

        if status_str == "in_progress" and job.status != JobStatus.RUNNING:
            job.status = JobStatus.RUNNING
            job.start_time = datetime.now(UTC)
            db.add(job)
            db.commit()
            logger.info("Job id=%s is now RUNNING", job.id)

        if status_str in ("completed", "failed", "cancelled"):
            job.end_time = datetime.now(UTC)
            if status_str == "completed":
                try:
                    ingested_count = await _ingest_job_outputs(db, job, status, client)
                    job.status = JobStatus.GENERATED
                    job.error_message = None
                    logger.info(
                        "Job id=%s completed successfully, ingested_assets=%s",
                        job.id,
                        ingested_count,
                    )
                except Exception as exc:
                    job.status = JobStatus.FAILED
                    job.error_message = f"Output ingestion failed: {exc}"
                    logger.exception("Job id=%s failed during output ingestion", job.id)
            elif status_str == "cancelled":
                job.status = JobStatus.CANCELLED
                job.error_message = None
                logger.warning("Job id=%s was cancelled by ComfyUI", job.id)
            else:
                job.status = JobStatus.FAILED
                job.error_message = (
                    status.get("execution_error")
                    or status.get("execution_status", {}).get("status_str")
                    or "ComfyUI job failed"
                )
                logger.error("Job id=%s failed in ComfyUI: %s", job.id, job.error_message)
            db.add(job)
            db.commit()
            break

        await asyncio.sleep(settings.poll_interval_sec)


async def worker_loop():
    async with ComfyClient() as client:
        logger.info("Worker loop started (poll_interval_sec=%s)", settings.poll_interval_sec)
        while True:
            db = SessionLocal()
            try:
                job = (
                    db.query(Job)
                    .filter(Job.status == JobStatus.QUEUED)
                    .order_by(Job.submitted_at.asc())
                    .first()
                )
                if not job:
                    await asyncio.sleep(settings.poll_interval_sec)
                    continue

                _ = job.workflow
                _ = job.workflow_version
                _ = job.input_values
                try:
                    await process_job(db, job, client)
                except Exception as exc:
                    logger.exception("Unexpected worker error while processing job id=%s", job.id)
                    job.status = JobStatus.FAILED
                    job.end_time = datetime.now(UTC)
                    job.error_message = f"Worker exception: {exc}"
                    db.add(job)
                    db.commit()
            finally:
                db.close()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(worker_loop())

import asyncio
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import Job, JobStatus
from .services.comfy_client import ComfyClient


def set_path(obj: dict, path: str, value):
    cur = obj
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def slugify_filename(text: str) -> str:
    out = []
    for ch in text.lower():
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:80]


async def process_job(db: Session, job: Job, client: ComfyClient):
    job.status = JobStatus.SUBMITTED
    db.add(job)
    db.commit()

    workflow = job.workflow
    version = job.workflow_version
    graph = dict(version.prompt_json or {})

    values = {iv.input_id: iv.value_json for iv in job.input_values}

    for definition in version.inputs_schema_json or []:
        input_id = definition.get("id")
        value = values.get(input_id, definition.get("default"))
        if input_id == "filename_prefix" and input_id not in values:
            # Generate deterministic filename prefix from text-like field
            base = str(values.get("text", "audio"))
            value = f"audio/{slugify_filename(base) or 'audio'}"
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
    db.add(job)
    db.commit()

    while True:
        status = await client.get_job(job.comfy_job_id)
        status_str = status.get("status")

        if status_str == "in_progress" and job.status != JobStatus.RUNNING:
            job.status = JobStatus.RUNNING
            job.start_time = datetime.now(UTC)
            db.add(job)
            db.commit()

        if status_str in ("completed", "failed", "cancelled"):
            job.end_time = datetime.now(UTC)
            if status_str == "completed":
                job.status = JobStatus.GENERATED
            elif status_str == "cancelled":
                job.status = JobStatus.CANCELLED
            else:
                job.status = JobStatus.FAILED
            db.add(job)
            db.commit()
            break

        await asyncio.sleep(settings.poll_interval_sec)


async def worker_loop():
    client = ComfyClient()
    try:
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
                await process_job(db, job, client)
            finally:
                db.close()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(worker_loop())

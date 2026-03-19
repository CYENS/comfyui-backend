import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Role,
    RoleName,
    User,
    UserRole,
    Workflow,
    WorkflowModelRequirement,
    WorkflowVersion,
)
from .security import hash_password
from .services.model_requirements import extract_from_api_json, extract_from_ui_json


def _hash_prompt(prompt: dict) -> str:
    data = json.dumps(prompt, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def ensure_roles(db: Session) -> dict[RoleName, str]:
    role_map: dict[RoleName, str] = {}
    for role_name in RoleName:
        role = db.query(Role).filter(Role.name == role_name).one_or_none()
        if role is None:
            role = Role(id=str(uuid.uuid4()), name=role_name)
            db.add(role)
            db.flush()
        role_map[role_name] = role.id
    return role_map


def seed_roles_and_system_user(db: Session) -> None:
    role_map = ensure_roles(db)

    # System actor used for seeded objects, not for interactive login.
    system = db.query(User).filter(User.id == "system-seed").one_or_none()
    if system is None:
        system = User(id="system-seed", username="system-seed", password_hash="!disabled")
        db.add(system)
        db.flush()

    # Dev override user — created so that job/asset provenance resolves in dev mode.
    if settings.auth_dev_mode:
        dev_id = settings.auth_dev_user_id
        dev_user = db.query(User).filter(User.id == dev_id).one_or_none()
        if dev_user is None:
            db.add(User(id=dev_id, username=dev_id, password_hash="!disabled"))
            db.flush()

    workflow_creator_role = role_map[RoleName.WORKFLOW_CREATOR]
    exists = (
        db.query(UserRole)
        .filter(UserRole.user_id == system.id, UserRole.role_id == workflow_creator_role)
        .one_or_none()
    )
    if exists is None:
        db.add(UserRole(user_id=system.id, role_id=workflow_creator_role))

    db.commit()


def seed_admin_user(db: Session, username: str, password: str) -> User:
    return seed_user_with_roles(db, username, password, [RoleName.ADMIN])


def seed_user_with_roles(
    db: Session,
    username: str,
    password: str,
    roles: list[RoleName],
) -> User:
    role_map = ensure_roles(db)
    user = db.query(User).filter(User.username == username).one_or_none()
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = hash_password(password)
        db.add(user)

    for role in roles:
        role_id = role_map[role]
        link = (
            db.query(UserRole)
            .filter(UserRole.user_id == user.id, UserRole.role_id == role_id)
            .one_or_none()
        )
        if link is None:
            db.add(UserRole(user_id=user.id, role_id=role_id))

    db.commit()
    db.refresh(user)
    return user


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _persist_requirements(db: Session, version_id: str, raw: list[dict]) -> None:
    db.query(WorkflowModelRequirement).filter(
        WorkflowModelRequirement.workflow_version_id == version_id
    ).delete()
    for r in raw:
        db.add(
            WorkflowModelRequirement(
                id=str(uuid.uuid4()),
                workflow_version_id=version_id,
                model_name=r["model_name"],
                folder=r["folder"],
                model_type=r["model_type"],
                download_url=r.get("download_url"),
                url_approved=False,
            )
        )


def _build_templates() -> list[dict[str, Any]]:
    seed_dir = Path(__file__).resolve().parents[1] / "seed" / "prompts"
    repo_root = Path(__file__).resolve().parents[2]

    audio_prompt = _load_json(repo_root / "prompts" / "audio_stable_audio_example.json")
    flux2_api = _load_json(seed_dir / "image_flux2_klein_text_to_image-api.json")
    flux2_ui = _load_json(seed_dir / "image_flux2_klein_text_to_image-ui.json")
    trellis_api = _load_json(seed_dir / "simple-image-to-3d-trellis-api.json")
    trellis_ui = _load_json(seed_dir / "simple-image-to-3d-trellis-ui.json")

    return [
        {
            "key": "flux2_klein_text_to_image",
            "name": "Flux 2 Klein — Text to Image",
            "description": "Generate images from a text prompt using the Flux 2 Klein 4B model.",
            "prompt_json": flux2_api,
            "ui_json": flux2_ui,
            "inputs_schema_json": [
                {
                    "id": "prompt",
                    "label": "Prompt",
                    "type": "string",
                    "required": True,
                    "default": "",
                    "mapping": [{"node_id": "76", "path": "inputs.value"}],
                },
                {
                    "id": "width",
                    "label": "Width",
                    "type": "number",
                    "required": False,
                    "default": 1024,
                    "mapping": [{"node_id": "75:68", "path": "inputs.value"}],
                },
                {
                    "id": "height",
                    "label": "Height",
                    "type": "number",
                    "required": False,
                    "default": 1024,
                    "mapping": [{"node_id": "75:69", "path": "inputs.value"}],
                },
                {
                    "id": "seed",
                    "label": "Seed",
                    "type": "number",
                    "required": False,
                    "default": 0,
                    "mapping": [{"node_id": "75:73", "path": "inputs.noise_seed"}],
                },
            ],
        },
        {
            "key": "simple_image_to_3d_trellis",
            "name": "Simple Image to 3D (Trellis)",
            "description": "Convert a single image into a 3D mesh using the Trellis 2 pipeline.",
            "prompt_json": trellis_api,
            "ui_json": trellis_ui,
            "inputs_schema_json": [
                {
                    "id": "image",
                    "label": "Input Image",
                    "type": "image",
                    "required": True,
                    "default": None,
                    "mapping": [{"node_id": "6", "path": "inputs.image"}],
                },
                {
                    "id": "seed",
                    "label": "Seed",
                    "type": "number",
                    "required": False,
                    "default": 0,
                    "mapping": [{"node_id": "41", "path": "inputs.seed"}],
                },
            ],
        },
        {
            "key": "text_to_audio",
            "name": "Text to Audio",
            "description": (
                "Generate audio clips from a text prompt using Stable Audio. "
                "Control the length in seconds and tweak the seed for variation."
            ),
            "prompt_json": audio_prompt,
            "ui_json": None,
            "inputs_schema_json": [
                {
                    "id": "text",
                    "label": "Prompt",
                    "type": "string",
                    "required": True,
                    "default": "",
                    "mapping": [{"node_id": "6", "path": "inputs.text"}],
                },
                {
                    "id": "seconds",
                    "label": "Length (s)",
                    "type": "number",
                    "required": False,
                    "default": 30,
                    "mapping": [{"node_id": "11", "path": "inputs.seconds"}],
                },
                {
                    "id": "seed",
                    "label": "Seed",
                    "type": "number",
                    "required": False,
                    "default": 0,
                    "mapping": [{"node_id": "3", "path": "inputs.seed"}],
                },
                {
                    "id": "filename_prefix",
                    "label": "Filename Prefix",
                    "type": "string",
                    "required": False,
                    "default": "audio/ComfyUI",
                    "mapping": [{"node_id": "19", "path": "inputs.filename_prefix"}],
                },
            ],
        },
    ]


def seed_workflows(db: Session) -> None:
    templates = _build_templates()

    for template in templates:
        wf = db.query(Workflow).filter(Workflow.key == template["key"]).one_or_none()
        if wf is None:
            wf = Workflow(
                id=str(uuid.uuid4()),
                key=template["key"],
                name=template["name"],
                description=template["description"],
                author_id="system-seed",
            )
            db.add(wf)
            db.flush()
        else:
            wf.name = template["name"]
            wf.description = template["description"]
            db.add(wf)

            version = WorkflowVersion(
                id=str(uuid.uuid4()),
                workflow_id=wf.id,
                version_number=1,
                prompt_json=template["prompt_json"],
                inputs_schema_json=template["inputs_schema_json"],
                prompt_hash=_hash_prompt(template["prompt_json"]),
                created_by_user_id="system-seed",
                change_note="initial seed",
                is_published=True,
            )
            db.add(version)
            db.flush()
            wf.current_version_id = version.id
            db.add(wf)

            # Extract and persist model requirements
            ui_json = template.get("ui_json")
            if ui_json:
                raw_reqs = extract_from_ui_json(ui_json)
            else:
                raw_reqs = extract_from_api_json(template["prompt_json"])
            _persist_requirements(db, version.id, raw_reqs)

    db.commit()


def _DRY_RUN_TEMPLATES() -> list[dict[str, Any]]:
    return _build_templates()

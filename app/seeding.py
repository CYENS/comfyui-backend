import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .config import settings
from .models import Role, RoleName, User, UserRole, Workflow, WorkflowVersion
from .security import hash_password


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


def seed_workflows(db: Session) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    audio_prompt_path = repo_root / "prompts" / "audio_stable_audio_example.json"
    audio_prompt = {}
    if audio_prompt_path.exists():
        audio_prompt = json.loads(audio_prompt_path.read_text(encoding="utf-8"))

    templates: list[dict[str, Any]] = [
        {
            "key": "text_to_image",
            "name": "Text to Image",
            "description": "Seeded text to image workflow",
            "prompt_json": {},
            "inputs_schema_json": [
                {
                    "id": "text",
                    "label": "Prompt",
                    "type": "string",
                    "required": True,
                    "default": "",
                    "mapping": [{"node_id": "17", "path": "inputs.text"}],
                }
            ],
        },
        {
            "key": "text_to_audio",
            "name": "Text to Audio",
            "description": "Seeded text to audio workflow",
            "prompt_json": audio_prompt,
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

    db.commit()

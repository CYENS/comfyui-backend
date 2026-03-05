import argparse
import os
from pathlib import Path

from .db import Base, SessionLocal, engine
from .models import RoleName
from .seeding import (
    seed_admin_user,
    seed_roles_and_system_user,
    seed_user_with_roles,
    seed_workflows,
)


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed roles, workflows, and admin user")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH), help="Path to .env file")
    args = parser.parse_args()

    load_env_file(Path(args.env_file))

    username = os.environ.get("USER_NAME")
    password = os.environ.get("USER_PASSWORD")

    if not username or not password:
        raise SystemExit(
            "Missing USER_NAME or USER_PASSWORD. Set them in env or in the env file."
        )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    admin_username = ""
    admin_user_id = ""
    try:
        seed_roles_and_system_user(db)
        seed_workflows(db)
        user = seed_admin_user(db, username=username, password=password)
        admin_username = user.username
        admin_user_id = user.id

        def seed_optional(env_user: str, env_pass: str, roles: list[RoleName]) -> None:
            u = os.environ.get(env_user)
            p = os.environ.get(env_pass)
            if not u and not p:
                return
            if not u or not p:
                raise SystemExit(f"Both {env_user} and {env_pass} must be set together.")
            created = seed_user_with_roles(db, username=u, password=p, roles=roles)
            print(f"Seeded user username={created.username} roles={[r.value for r in roles]}")

        seed_optional(
            "WORKFLOW_CREATOR_USER_NAME",
            "WORKFLOW_CREATOR_USER_PASSWORD",
            [RoleName.WORKFLOW_CREATOR],
        )
        seed_optional(
            "JOB_CREATOR_USER_NAME",
            "JOB_CREATOR_USER_PASSWORD",
            [RoleName.JOB_CREATOR],
        )
        seed_optional(
            "VIEWER_USER_NAME",
            "VIEWER_USER_PASSWORD",
            [RoleName.VIEWER],
        )
        seed_optional(
            "MODERATOR_USER_NAME",
            "MODERATOR_USER_PASSWORD",
            [RoleName.MODERATOR],
        )
    finally:
        db.close()

    print(f"Seeding complete. Admin username={admin_username} user_id={admin_user_id}")


if __name__ == "__main__":
    main()

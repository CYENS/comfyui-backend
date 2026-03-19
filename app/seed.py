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
    parser.add_argument(
        "--fresh", action="store_true", help="Drop and recreate the database before seeding"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation prompt (use with --fresh)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be seeded without writing to the database",
    )
    args = parser.parse_args()

    load_env_file(Path(args.env_file))

    username = os.environ.get("USER_NAME")
    password = os.environ.get("USER_PASSWORD")

    if not username or not password:
        raise SystemExit("Missing USER_NAME or USER_PASSWORD. Set them in env or in the env file.")

    if args.dry_run:
        print("[dry-run] Would seed:")
        print(f"  admin user: {username}")
        optional_users = [
            ("WORKFLOW_CREATOR_USER_NAME", "WORKFLOW_CREATOR_USER_PASSWORD", "workflow_creator"),
            ("JOB_CREATOR_USER_NAME", "JOB_CREATOR_USER_PASSWORD", "job_creator"),
            ("VIEWER_USER_NAME", "VIEWER_USER_PASSWORD", "viewer"),
            ("MODERATOR_USER_NAME", "MODERATOR_USER_PASSWORD", "moderator"),
        ]
        for env_user, env_pass, role in optional_users:
            u = os.environ.get(env_user)
            p = os.environ.get(env_pass)
            if u and p:
                print(f"  user: {u} roles=[{role}]")
        if args.fresh:
            print("[dry-run] Would drop and recreate all tables")
        from .seeding import _DRY_RUN_TEMPLATES

        for t in _DRY_RUN_TEMPLATES():
            print(f"  workflow: {t['key']!r} — {t['name']!r}")
            print(f"    description: {t['description']!r}")
            print(f"    inputs: {[i['id'] for i in t['inputs_schema_json']]}")
        print("[dry-run] No changes written.")
        return

    if args.fresh:
        if not args.yes:
            answer = (
                input("This will drop all tables and delete all data. Are you sure? [y/N] ")
                .strip()
                .lower()
            )
            if answer != "y":
                raise SystemExit("Aborted.")
        print("Dropping all tables…")
        Base.metadata.drop_all(bind=engine)
        print("Recreating schema…")

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

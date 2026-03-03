import argparse
import os
from pathlib import Path

from .db import Base, SessionLocal, engine
from .seeding import seed_admin_user, seed_roles_and_system_user, seed_workflows


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
    try:
        seed_roles_and_system_user(db)
        seed_workflows(db)
        user = seed_admin_user(db, username=username, password=password)
    finally:
        db.close()

    print(f"Seeding complete. Admin username={user.username} user_id={user.id}")


if __name__ == "__main__":
    main()

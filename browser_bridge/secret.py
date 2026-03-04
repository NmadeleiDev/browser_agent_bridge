from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_JWT_SECRET = "dev-insecure-change-me"
SECRET_FILE_ENV_VAR = "BRIDGE_JWT_SECRET_FILE"
DEFAULT_SECRET_FILE = "~/.browser_bridge/jwt_secret"


def secret_file_path() -> Path:
    return Path(os.getenv(SECRET_FILE_ENV_VAR, DEFAULT_SECRET_FILE)).expanduser()


def generate_secret() -> str:
    return secrets.token_urlsafe(48)


def read_secret(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def write_secret(path: Path, value: str, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Secret file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Best effort on platforms/filesystems that do not support POSIX perms.
        pass


def setup_local_secret(*, secret: str | None = None, overwrite: bool = False) -> tuple[str, Path]:
    value = (secret or generate_secret()).strip()
    if not value:
        raise RuntimeError("Secret value must not be empty")
    path = secret_file_path()
    write_secret(path, value, overwrite=overwrite)
    return value, path


def ensure_non_default_secret(current_secret: str) -> tuple[str, Path | None, bool]:
    if current_secret != DEFAULT_JWT_SECRET:
        return current_secret, None, False

    path = secret_file_path()
    existing = read_secret(path)
    if existing:
        return existing, path, False

    value, saved_path = setup_local_secret()
    return value, saved_path, True

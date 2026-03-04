from __future__ import annotations

from pathlib import Path

from browser_bridge import secret


def test_ensure_non_default_secret_uses_env_secret(monkeypatch) -> None:
    monkeypatch.delenv(secret.SECRET_FILE_ENV_VAR, raising=False)
    value, path, created = secret.ensure_non_default_secret("explicit-secret")
    assert value == "explicit-secret"
    assert path is None
    assert created is False


def test_ensure_non_default_secret_creates_file_on_default(monkeypatch, tmp_path) -> None:
    secret_path = tmp_path / "jwt_secret"
    monkeypatch.setenv(secret.SECRET_FILE_ENV_VAR, str(secret_path))

    value, path, created = secret.ensure_non_default_secret(secret.DEFAULT_JWT_SECRET)

    assert created is True
    assert path == secret_path
    assert value
    assert secret_path.exists()
    assert secret_path.read_text(encoding="utf-8").strip() == value


def test_ensure_non_default_secret_reuses_existing_file(monkeypatch, tmp_path) -> None:
    secret_path = tmp_path / "jwt_secret"
    secret_path.write_text("preexisting\n", encoding="utf-8")
    monkeypatch.setenv(secret.SECRET_FILE_ENV_VAR, str(secret_path))

    value, path, created = secret.ensure_non_default_secret(secret.DEFAULT_JWT_SECRET)

    assert value == "preexisting"
    assert path == Path(secret_path)
    assert created is False

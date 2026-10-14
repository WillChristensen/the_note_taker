import pytest
from pydantic import ValidationError

from app.security import AuthSettings, hash_password, verify_password


def test_password_hash_can_be_verified_without_storing_plaintext() -> None:
    password = "correct horse battery staple"

    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash)
    assert not verify_password("incorrect password", password_hash)


def test_password_hash_rejects_empty_password() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        hash_password("")


def test_auth_settings_load_secret_and_token_expiration_from_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 32)
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "45")

    settings = AuthSettings()

    assert settings.secret_key.get_secret_value() == "a" * 32
    assert settings.access_token_expire_minutes == 45


def test_auth_settings_requires_strong_secret(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "too-short")

    with pytest.raises(ValidationError):
        AuthSettings()


def test_auth_settings_requires_positive_token_expiration(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 32)
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_EXPIRE_MINUTES", "0")

    with pytest.raises(ValidationError):
        AuthSettings()

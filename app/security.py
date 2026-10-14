from datetime import UTC, datetime, timedelta

import jwt
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_")

    secret_key: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=30, gt=0)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty")
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def create_access_token(subject: str, settings: AuthSettings) -> str:
    expires_at = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": subject, "exp": expires_at},
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_access_token(token: str, settings: AuthSettings) -> str:
    payload = jwt.decode(
        token,
        settings.secret_key.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    subject = payload["sub"]
    if not isinstance(subject, str) or not subject.isdecimal():
        raise jwt.InvalidTokenError("Invalid token subject")
    return subject

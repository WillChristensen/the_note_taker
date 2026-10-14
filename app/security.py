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

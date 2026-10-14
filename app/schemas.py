from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegistration(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value


class UserRead(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessToken(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

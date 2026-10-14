from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


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


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Team name must not be blank")
        return normalized


class TeamRead(BaseModel):
    id: int
    name: str
    created_by_user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().casefold()
        return value


class MemberRead(BaseModel):
    user_id: int
    email: EmailStr
    role: str
    joined_at: datetime


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Note title must not be blank")
        return normalized


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Note title must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_patch(self) -> "NoteUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one note field must be provided")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Note fields must not be null")
        return self


class NoteRead(BaseModel):
    id: int
    team_id: int
    author_id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

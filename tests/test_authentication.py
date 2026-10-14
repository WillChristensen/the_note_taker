from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.auth_dependencies import get_current_user
from app.auth_routes import router as auth_router
from app.database import Base, create_database_engine, get_db
from app.models import User

AUTH_SECRET = "test-only-secret-key-with-at-least-32-chars"
PASSWORD = "a secure password"


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", AUTH_SECRET)
    engine = create_database_engine(f"sqlite:///{tmp_path / 'authentication.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    test_app = FastAPI()
    test_app.include_router(auth_router)

    def override_get_db():
        with session_factory() as session:
            yield session

    test_app.dependency_overrides[get_db] = override_get_db

    @test_app.get("/protected")
    def protected_route(user: User = Depends(get_current_user)) -> dict[str, str]:
        return {"email": user.email}

    with TestClient(test_app) as client:
        try:
            yield client, session_factory
        finally:
            engine.dispose()


def test_login_returns_bearer_token_for_valid_credentials(auth_client) -> None:
    client, _ = auth_client
    client.post(
        "/auth/register", json={"email": "person@example.com", "password": PASSWORD}
    )

    response = client.post(
        "/auth/token",
        data={"username": " PERSON@EXAMPLE.COM ", "password": PASSWORD},
    )

    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert token["expires_in"] == 1800
    assert token["access_token"]
    claims = jwt.decode(
        token["access_token"], AUTH_SECRET, algorithms=["HS256"]
    )
    assert claims["sub"] == "1"
    assert claims["exp"] > datetime.now(UTC).timestamp()

    protected_response = client.get(
        "/protected", headers={"Authorization": f"Bearer {token['access_token']}"}
    )
    assert protected_response.status_code == 200
    assert protected_response.json() == {"email": "person@example.com"}


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("missing@example.com", PASSWORD),
        ("person@example.com", "wrong password"),
    ],
)
def test_login_rejects_invalid_credentials_with_same_response(
    auth_client, email, password
) -> None:
    client, _ = auth_client
    client.post(
        "/auth/register", json={"email": "person@example.com", "password": PASSWORD}
    )

    response = client.post(
        "/auth/token", data={"username": email, "password": password}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_deleted_user_cannot_log_in_or_use_existing_token(auth_client) -> None:
    client, session_factory = auth_client
    client.post(
        "/auth/register", json={"email": "person@example.com", "password": PASSWORD}
    )
    login_response = client.post(
        "/auth/token",
        data={"username": "person@example.com", "password": PASSWORD},
    )
    token = login_response.json()["access_token"]
    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == "person@example.com"))
        assert user is not None
        user.deleted_at = datetime.now(UTC)
        session.commit()

    login_after_delete = client.post(
        "/auth/token",
        data={"username": "person@example.com", "password": PASSWORD},
    )
    protected_response = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )

    assert login_after_delete.status_code == 401
    assert protected_response.status_code == 401
    assert protected_response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token_kind",
    ["malformed", "expired", "wrong-signature", "missing-expiration", "invalid-subject"],
)
def test_protected_route_rejects_invalid_tokens(auth_client, token_kind) -> None:
    client, _ = auth_client
    if token_kind == "malformed":
        token = "not-a-jwt"
    else:
        secret = "different-secret-key-with-at-least-32-chars"
        claims = {"sub": "1", "exp": datetime.now(UTC) + timedelta(minutes=1)}
        if token_kind == "expired":
            secret = AUTH_SECRET
            claims["exp"] = datetime.now(UTC) - timedelta(minutes=1)
        elif token_kind == "missing-expiration":
            secret = AUTH_SECRET
            claims.pop("exp")
        elif token_kind == "invalid-subject":
            secret = AUTH_SECRET
            claims["sub"] = "not-a-user-id"
        token = jwt.encode(claims, secret, algorithm="HS256")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_route_requires_bearer_token(auth_client) -> None:
    client, _ = auth_client

    response = client.get("/protected")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

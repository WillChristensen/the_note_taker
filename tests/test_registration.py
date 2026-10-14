import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine, get_db
from app.main import app
from app.models import User
from app.security import verify_password


@pytest.fixture
def client(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'registration.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        try:
            yield test_client, session_factory
        finally:
            app.dependency_overrides.pop(get_db, None)
            engine.dispose()


def test_register_creates_user_with_normalized_email_and_password_hash(
    client,
) -> None:
    client, session_factory = client
    response = client.post(
        "/auth/register",
        json={"email": "  Person@Example.COM ", "password": "a secure password"},
    )

    assert response.status_code == 201
    response_body = response.json()
    assert response_body["email"] == "person@example.com"
    assert response_body["id"] > 0
    assert response_body["created_at"]
    assert "password" not in response_body
    assert "password_hash" not in response_body

    with session_factory() as session:
        user = session.scalar(
            select(User).where(User.email == "person@example.com")
        )
        assert user is not None
        assert user.password_hash != "a secure password"
        assert verify_password("a secure password", user.password_hash)


def test_register_rejects_duplicate_email_case_insensitively(client) -> None:
    client, _ = client
    first_response = client.post(
        "/auth/register",
        json={"email": "person@example.com", "password": "a secure password"},
    )
    duplicate_response = client.post(
        "/auth/register",
        json={"email": " PERSON@EXAMPLE.COM ", "password": "another password"},
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "An account with this email already exists"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "a secure password"},
        {"email": "person@example.com", "password": "short"},
        {"email": "person@example.com", "password": "x" * 129},
        {"email": "person@example.com"},
    ],
)
def test_register_rejects_invalid_input(client, payload) -> None:
    client, _ = client
    response = client.post("/auth/register", json=payload)

    assert response.status_code == 422

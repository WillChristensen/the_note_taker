from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine, get_db
from app.main import app
from app.models import Membership, Team, TeamRole, User

AUTH_SECRET = "test-only-secret-key-with-at-least-32-chars"
PASSWORD = "a secure password"


@pytest.fixture
def team_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET_KEY", AUTH_SECRET)
    engine = create_database_engine(f"sqlite:///{tmp_path / 'teams.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        try:
            yield client, session_factory
        finally:
            app.dependency_overrides.pop(get_db, None)
            engine.dispose()


def register_and_login(client: TestClient, email: str) -> str:
    registration = client.post(
        "/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert registration.status_code == 201
    login = client.post(
        "/auth/token", data={"username": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def test_create_team_assigns_creator_owner_membership(team_client) -> None:
    client, session_factory = team_client
    token = register_and_login(client, "owner@example.com")

    response = client.post(
        "/teams",
        json={"name": "  Product Team  "},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Product Team"
    assert body["created_by_user_id"] == 1
    assert body["id"] > 0
    assert body["created_at"]

    with session_factory() as session:
        user = session.get(User, body["created_by_user_id"])
        team = session.get(Team, body["id"])
        assert user is not None
        assert team is not None
        membership = session.scalar(
            select(Membership).where(
                Membership.team_id == team.id,
                Membership.user_id == user.id,
            )
        )
        assert membership is not None
        assert membership.role is TeamRole.OWNER


def test_list_teams_only_returns_active_teams_for_current_member(team_client) -> None:
    client, session_factory = team_client
    first_token = register_and_login(client, "first@example.com")
    second_token = register_and_login(client, "second@example.com")

    first_created = client.post(
        "/teams",
        json={"name": "First team's team"},
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second_created = client.post(
        "/teams",
        json={"name": "Second team's team"},
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert first_created.status_code == second_created.status_code == 201

    with session_factory() as session:
        first_team = session.get(Team, first_created.json()["id"])
        second_team = session.get(Team, second_created.json()["id"])
        assert first_team is not None
        assert second_team is not None
        first_team.deleted_at = datetime.now(UTC)
        session.commit()

    first_list = client.get(
        "/teams", headers={"Authorization": f"Bearer {first_token}"}
    )
    second_list = client.get(
        "/teams", headers={"Authorization": f"Bearer {second_token}"}
    )

    assert first_list.status_code == 200
    assert first_list.json() == []
    assert second_list.status_code == 200
    assert [team["id"] for team in second_list.json()] == [
        second_created.json()["id"]
    ]


def test_team_routes_require_authentication(team_client) -> None:
    client, _ = team_client

    create_response = client.post("/teams", json={"name": "No auth"})
    list_response = client.get("/teams")

    assert create_response.status_code == 401
    assert list_response.status_code == 401
    assert create_response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 201],
)
def test_create_team_rejects_invalid_name(team_client, name: str) -> None:
    client, _ = team_client
    token = register_and_login(client, "owner@example.com")

    response = client.post(
        "/teams",
        json={"name": name},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422

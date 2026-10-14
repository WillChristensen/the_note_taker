from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine, get_db
from app.main import app
from app.models import Membership, Note, Team, TeamRole, User

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


def test_owner_can_list_members_and_add_existing_user(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team = client.post(
        "/teams",
        json={"name": "Shared team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    team_id = team.json()["id"]

    add_response = client.post(
        f"/teams/{team_id}/members",
        json={"email": " MEMBER@EXAMPLE.COM "},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    list_response = client.get(
        f"/teams/{team_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert add_response.status_code == 201
    assert add_response.json()["email"] == "member@example.com"
    assert add_response.json()["role"] == "member"
    assert list_response.status_code == 200
    assert {entry["email"] for entry in list_response.json()} == {
        "owner@example.com",
        "member@example.com",
    }

    member_teams = client.get(
        "/teams", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert [listed["id"] for listed in member_teams.json()] == [team_id]

    with session_factory() as session:
        membership = session.scalar(
            select(Membership).where(
                Membership.team_id == team_id,
                Membership.user_id == 2,
            )
        )
        assert membership is not None
        assert membership.role is TeamRole.MEMBER


def test_non_owner_cannot_manage_or_view_team_members(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    member_list = client.get(
        f"/teams/{team_id}/members",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    outsider_list = client.get(
        f"/teams/{team_id}/members",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )
    member_add = client.post(
        f"/teams/{team_id}/members",
        json={"email": "outsider@example.com"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    outsider_add = client.post(
        f"/teams/{team_id}/members",
        json={"email": "outsider@example.com"},
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    for response in (member_list, outsider_list, member_add, outsider_add):
        assert response.status_code == 403


@pytest.mark.parametrize(
    ("email", "expected_status", "expected_detail"),
    [
        ("unknown@example.com", 404, "Active user not found"),
        ("deleted@example.com", 404, "Active user not found"),
        (
                "member@example.com",
                409,
                "User is already a member of this team",
        ),
    ],
)
def test_owner_add_member_handles_missing_deleted_and_duplicate_users(
        team_client, email, expected_status, expected_detail
) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    register_and_login(client, "member@example.com")
    deleted_registration = client.post(
        "/auth/register",
        json={"email": "deleted@example.com", "password": PASSWORD},
    )
    assert deleted_registration.status_code == 201
    with session_factory() as session:
        deleted_user = session.get(User, deleted_registration.json()["id"])
        assert deleted_user is not None
        deleted_user.deleted_at = datetime.now(UTC)
        session.commit()
    team_id = client.post(
        "/teams",
        json={"name": "Manage team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    if email == "member@example.com":
        client.post(
            f"/teams/{team_id}/members",
            json={"email": email},
            headers={"Authorization": f"Bearer {owner_token}"},
        )

    response = client.post(
        f"/teams/{team_id}/members",
        json={"email": email},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_deleted_team_cannot_list_or_add_members(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    list_response = client.get(
        f"/teams/{team_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    add_response = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert list_response.status_code == 404
    assert add_response.status_code == 404


def test_team_member_can_create_note_and_author_is_authenticated_user(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    added_member = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert added_member.status_code == 201

    response = client.post(
        f"/teams/{team_id}/notes",
        json={
            "title": "  Meeting notes  ",
            "content": "Discussed the launch plan.",
            "author_id": 1,
        },
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["team_id"] == team_id
    assert body["author_id"] == 2
    assert body["title"] == "Meeting notes"
    assert body["content"] == "Discussed the launch plan."
    assert body["id"] > 0
    assert body["created_at"]
    assert body["updated_at"]

    with session_factory() as session:
        stored_note = session.get(Note, body["id"])
        assert stored_note is not None
        assert stored_note.author_id == 2


def test_non_member_cannot_create_team_note(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]

    response = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Unauthorized note", "content": "Should not be saved"},
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Team membership required"}


def test_cannot_create_note_for_missing_or_deleted_team(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}
    deleted_team_response = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Note", "content": "Content"},
        headers=headers,
    )
    missing_team_response = client.post(
        "/teams/9999/notes",
        json={"title": "Note", "content": "Content"},
        headers=headers,
    )

    assert deleted_team_response.status_code == 404
    assert missing_team_response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "content": "Content"},
        {"title": "   ", "content": "Content"},
        {"title": "x" * 201, "content": "Content"},
        {"title": "Title", "content": ""},
        {"content": "Content"},
    ],
)
def test_create_note_rejects_invalid_input(team_client, payload) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]

    response = client.post(
        f"/teams/{team_id}/notes",
        json=payload,
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == 422


def test_create_note_requires_authentication(team_client) -> None:
    client, _ = team_client

    response = client.post(
        "/teams/1/notes",
        json={"title": "Note", "content": "Content"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_team_member_can_list_notes_newest_first_with_pagination(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    membership = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert membership.status_code == 201
    other_team_id = client.post(
        "/teams",
        json={"name": "Other team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]

    note_ids = []
    for title in ("First", "Second", "Third", "Fourth"):
        response = client.post(
            f"/teams/{team_id}/notes",
            json={"title": title, "content": f"{title} content"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert response.status_code == 201
        note_ids.append(response.json()["id"])
    other_note = client.post(
        f"/teams/{other_team_id}/notes",
        json={"title": "Other team's note", "content": "Not in this list"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert other_note.status_code == 201

    same_timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    with session_factory() as session:
        for note_id in note_ids:
            note = session.get(Note, note_id)
            assert note is not None
            note.created_at = same_timestamp
        session.commit()

    response = client.get(
        f"/teams/{team_id}/notes?limit=2&offset=1",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 200
    assert [note["id"] for note in response.json()] == list(
        reversed(note_ids)
    )[1:3]
    assert all(note["team_id"] == team_id for note in response.json())

    final_page = client.get(
        f"/teams/{team_id}/notes?limit=2&offset=2",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert [note["id"] for note in final_page.json()] == list(
        reversed(note_ids)
    )[2:4]


@pytest.mark.parametrize(
    "query",
    ["?limit=0", "?limit=101", "?offset=-1"],
)
def test_list_team_notes_rejects_invalid_pagination(team_client, query: str) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]

    response = client.get(
        f"/teams/{team_id}/notes{query}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == 422


def test_list_team_notes_requires_membership_and_authentication(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]

    unauthenticated = client.get(f"/teams/{team_id}/notes")
    outsider = client.get(
        f"/teams/{team_id}/notes",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    assert unauthenticated.status_code == 401
    assert outsider.status_code == 403
    assert outsider.json() == {"detail": "Team membership required"}


def test_list_team_notes_returns_not_found_for_missing_or_deleted_team(
        team_client,
) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}
    deleted_team = client.get(f"/teams/{team_id}/notes", headers=headers)
    missing_team = client.get("/teams/9999/notes", headers=headers)

    assert deleted_team.status_code == 404
    assert missing_team.status_code == 404


def test_team_member_can_retrieve_note(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    membership = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert membership.status_code == 201
    created_note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Planning", "content": "Review the launch plan."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created_note.status_code == 201

    response = client.get(
        f"/teams/{team_id}/notes/{created_note.json()['id']}",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 200
    assert response.json() == created_note.json()


def test_cannot_retrieve_note_outside_team_or_missing_note(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    first_team_id = client.post(
        "/teams",
        json={"name": "First team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    second_team_id = client.post(
        "/teams",
        json={"name": "Second team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{second_team_id}/notes",
        json={"title": "Private to second", "content": "Team-scoped note."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert note.status_code == 201

    wrong_team = client.get(
        f"/teams/{first_team_id}/notes/{note.json()['id']}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    missing_note = client.get(
        f"/teams/{first_team_id}/notes/9999",
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert wrong_team.status_code == 404
    assert wrong_team.json() == {"detail": "Note not found"}
    assert missing_note.status_code == 404
    assert missing_note.json() == {"detail": "Note not found"}


def test_non_member_cannot_retrieve_team_note(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Private note", "content": "Members only."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert note.status_code == 201

    response = client.get(
        f"/teams/{team_id}/notes/{note.json()['id']}",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Team membership required"}


def test_retrieve_team_note_requires_authentication(team_client) -> None:
    client, _ = team_client

    response = client.get("/teams/1/notes/1")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_retrieve_note_returns_not_found_for_missing_or_deleted_team(
        team_client,
) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}
    deleted_team = client.get(f"/teams/{team_id}/notes/1", headers=headers)
    missing_team = client.get("/teams/9999/notes/1", headers=headers)

    assert deleted_team.status_code == 404
    assert missing_team.status_code == 404


def test_team_member_can_update_note_fields_and_updated_at(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    membership = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert membership.status_code == 201
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Planning", "content": "Initial content"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert note.status_code == 201

    response = client.patch(
        f"/teams/{team_id}/notes/{note.json()['id']}",
        json={"title": "  Updated planning  "},
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Updated planning"
    assert response.json()["content"] == "Initial content"
    assert response.json()["author_id"] == note.json()["author_id"]
    assert response.json()["updated_at"] > note.json()["updated_at"]

    content_update = client.patch(
        f"/teams/{team_id}/notes/{note.json()['id']}",
        json={"content": "Revised content"},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert content_update.status_code == 200
    assert content_update.json()["title"] == "Updated planning"
    assert content_update.json()["content"] == "Revised content"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": None},
        {"content": ""},
        {"content": None},
    ],
)
def test_update_note_rejects_empty_or_invalid_patch(team_client, payload) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Planning", "content": "Initial content"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    response = client.patch(
        f"/teams/{team_id}/notes/{note.json()['id']}",
        json=payload,
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    assert response.status_code == 422


def test_non_member_cannot_update_team_note(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Private note", "content": "Members only."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    response = client.patch(
        f"/teams/{team_id}/notes/{note.json()['id']}",
        json={"title": "Unauthorized change"},
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Team membership required"}


def test_update_note_is_team_scoped_and_requires_authentication(team_client) -> None:
    client, _ = team_client
    owner_token = register_and_login(client, "owner@example.com")
    first_team_id = client.post(
        "/teams",
        json={"name": "First team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    second_team_id = client.post(
        "/teams",
        json={"name": "Second team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{second_team_id}/notes",
        json={"title": "Private to second", "content": "Team-scoped note."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    wrong_team = client.patch(
        f"/teams/{first_team_id}/notes/{note.json()['id']}",
        json={"title": "Should not update"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    missing_note = client.patch(
        f"/teams/{first_team_id}/notes/9999",
        json={"title": "Missing"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    unauthenticated = client.patch(
        f"/teams/{first_team_id}/notes/{note.json()['id']}",
        json={"title": "Unauthenticated"},
    )

    assert wrong_team.status_code == 404
    assert wrong_team.json() == {"detail": "Note not found"}
    assert missing_note.status_code == 404
    assert missing_note.json() == {"detail": "Note not found"}
    assert unauthenticated.status_code == 401


def test_update_note_returns_not_found_for_missing_or_deleted_team(
        team_client,
) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}
    deleted_team = client.patch(
        f"/teams/{team_id}/notes/1",
        json={"title": "Update"},
        headers=headers,
    )
    missing_team = client.patch(
        "/teams/9999/notes/1",
        json={"title": "Update"},
        headers=headers,
    )

    assert deleted_team.status_code == 404
    assert missing_team.status_code == 404


def test_team_member_can_permanently_delete_note(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    member_token = register_and_login(client, "member@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Notes team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    membership = client.post(
        f"/teams/{team_id}/members",
        json={"email": "member@example.com"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert membership.status_code == 201
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Temporary note", "content": "Delete me."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert note.status_code == 201
    note_id = note.json()["id"]

    deleted = client.delete(
        f"/teams/{team_id}/notes/{note_id}",
        headers={"Authorization": f"Bearer {member_token}"},
    )

    assert deleted.status_code == 204
    assert deleted.content == b""
    with session_factory() as session:
        assert session.get(Note, note_id) is None
    assert client.get(
        f"/teams/{team_id}/notes/{note_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).status_code == 404
    assert client.get(
        f"/teams/{team_id}/notes",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json() == []


def test_non_member_cannot_delete_team_note(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    outsider_token = register_and_login(client, "outsider@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Private team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Private note", "content": "Keep this note."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    note_id = note.json()["id"]

    response = client.delete(
        f"/teams/{team_id}/notes/{note_id}",
        headers={"Authorization": f"Bearer {outsider_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Team membership required"}
    with session_factory() as session:
        assert session.get(Note, note_id) is not None


def test_delete_note_is_team_scoped_and_requires_authentication(team_client) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    first_team_id = client.post(
        "/teams",
        json={"name": "First team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    second_team_id = client.post(
        "/teams",
        json={"name": "Second team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    note = client.post(
        f"/teams/{second_team_id}/notes",
        json={"title": "Scoped note", "content": "Remain unchanged."},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    note_id = note.json()["id"]

    wrong_team = client.delete(
        f"/teams/{first_team_id}/notes/{note_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    missing_note = client.delete(
        f"/teams/{first_team_id}/notes/9999",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    unauthenticated = client.delete(
        f"/teams/{second_team_id}/notes/{note_id}"
    )

    assert wrong_team.status_code == 404
    assert wrong_team.json() == {"detail": "Note not found"}
    assert missing_note.status_code == 404
    assert missing_note.json() == {"detail": "Note not found"}
    assert unauthenticated.status_code == 401
    with session_factory() as session:
        assert session.get(Note, note_id) is not None


def test_delete_note_returns_not_found_for_missing_or_deleted_team(
        team_client,
) -> None:
    client, session_factory = team_client
    owner_token = register_and_login(client, "owner@example.com")
    team_id = client.post(
        "/teams",
        json={"name": "Deleted team"},
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()["id"]
    with session_factory() as session:
        team = session.get(Team, team_id)
        assert team is not None
        team.deleted_at = datetime.now(UTC)
        session.commit()

    headers = {"Authorization": f"Bearer {owner_token}"}
    deleted_team = client.delete(f"/teams/{team_id}/notes/1", headers=headers)
    missing_team = client.delete("/teams/9999/notes/1", headers=headers)

    assert deleted_team.status_code == 404
    assert missing_team.status_code == 404


def test_note_crud_lifecycle_as_team_member(team_client) -> None:
    client, _ = team_client
    token = register_and_login(client, "owner@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    team_response = client.post(
        "/teams",
        json={"name": "CRUD lifecycle team"},
        headers=headers,
    )
    assert team_response.status_code == 201
    team_id = team_response.json()["id"]

    created = client.post(
        f"/teams/{team_id}/notes",
        json={"title": "Initial title", "content": "Initial content"},
        headers=headers,
    )
    assert created.status_code == 201
    note_id = created.json()["id"]
    assert created.json()["team_id"] == team_id

    listed = client.get(f"/teams/{team_id}/notes", headers=headers)
    assert listed.status_code == 200
    assert [note["id"] for note in listed.json()] == [note_id]

    retrieved = client.get(
        f"/teams/{team_id}/notes/{note_id}",
        headers=headers,
    )
    assert retrieved.status_code == 200
    assert retrieved.json() == created.json()

    updated = client.patch(
        f"/teams/{team_id}/notes/{note_id}",
        json={"title": "Updated title", "content": "Updated content"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated title"
    assert updated.json()["content"] == "Updated content"
    assert updated.json()["author_id"] == created.json()["author_id"]
    assert updated.json()["updated_at"] > created.json()["updated_at"]

    deleted = client.delete(
        f"/teams/{team_id}/notes/{note_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert deleted.content == b""

    listed_after_delete = client.get(f"/teams/{team_id}/notes", headers=headers)
    retrieved_after_delete = client.get(
        f"/teams/{team_id}/notes/{note_id}",
        headers=headers,
    )
    deleted_again = client.delete(
        f"/teams/{team_id}/notes/{note_id}",
        headers=headers,
    )
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json() == []
    assert retrieved_after_delete.status_code == 404
    assert deleted_again.status_code == 404

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine
from app.models import Membership, Note, Team, TeamRole, User


@pytest.fixture
def db_session(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'models.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        yield session
    engine.dispose()


def test_user_email_must_be_unique(db_session) -> None:
    db_session.add_all(
        [
            User(email="person@example.com", password_hash="hash-1"),
            User(email="person@example.com", password_hash="hash-2"),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_team_requires_existing_creator(db_session) -> None:
    db_session.add(Team(name="Small team", created_by_user_id=999))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_team_creator_relationship(db_session) -> None:
    user = User(email="owner@example.com", password_hash="hash")
    team = Team(name="Small team", creator=user)
    db_session.add(team)
    db_session.commit()

    assert team.creator.email == "owner@example.com"
    assert user.teams_created == [team]


def test_user_can_belong_to_multiple_teams(db_session) -> None:
    user = User(email="member@example.com", password_hash="hash")
    first_team = Team(name="First team", creator=user)
    second_team = Team(name="Second team", creator=user)
    first_membership = Membership(team=first_team, user=user, role=TeamRole.OWNER)
    second_membership = Membership(team=second_team, user=user)
    db_session.add_all([first_membership, second_membership])
    db_session.commit()

    assert first_membership.role is TeamRole.OWNER
    assert second_membership.role is TeamRole.MEMBER
    assert len(user.memberships) == 2


def test_user_cannot_join_same_team_twice(db_session) -> None:
    user = User(email="member@example.com", password_hash="hash")
    team = Team(name="Small team", creator=user)
    db_session.add_all(
        [
            Membership(team=team, user=user, role=TeamRole.OWNER),
            Membership(team=team, user=user, role=TeamRole.MEMBER),
        ]
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_membership_role_is_limited_to_supported_values(db_session) -> None:
    user = User(email="member@example.com", password_hash="hash")
    team = Team(name="Small team", creator=user)
    db_session.add_all([user, team])
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO memberships (team_id, user_id, role, joined_at) "
                "VALUES (:team_id, :user_id, 'admin', CURRENT_TIMESTAMP)"
            ),
            {"team_id": team.id, "user_id": user.id},
        )


def test_notes_have_team_and_author_relationships_and_ordering_index(db_session) -> None:
    user = User(email="author@example.com", password_hash="hash")
    team = Team(name="Small team", creator=user)
    older = Note(
        team=team,
        author=user,
        title="Older note",
        content="First",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = Note(
        team=team,
        author=user,
        title="Newer note",
        content="Second",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db_session.add_all([older, newer])
    db_session.commit()

    ordered_notes = db_session.scalars(
        select(Note).where(Note.team_id == team.id).order_by(Note.created_at.desc())
    ).all()
    index_columns = {
        tuple(column.name for column in index.columns) for index in Note.__table__.indexes
    }

    assert [note.title for note in ordered_notes] == ["Newer note", "Older note"]
    assert ("team_id", "created_at") in index_columns
    assert newer in team.notes
    assert newer in user.notes_written
    assert newer.updated_at is not None
    original_updated_at = newer.updated_at
    newer.title = "Edited note"
    db_session.commit()
    db_session.refresh(newer)
    assert newer.updated_at > original_updated_at


def test_soft_deleting_owner_and_team_preserves_notes(db_session) -> None:
    user = User(email="owner@example.com", password_hash="hash")
    team = Team(name="Small team", creator=user)
    note = Note(team=team, author=user, title="Keep me", content="Note content")
    db_session.add(note)
    db_session.commit()

    deleted_at = datetime.now(UTC)
    user.deleted_at = deleted_at
    team.deleted_at = deleted_at
    db_session.commit()
    db_session.expire_all()

    stored_note = db_session.get(Note, note.id)
    stored_user = db_session.get(User, user.id)
    stored_team = db_session.get(Team, team.id)
    assert stored_user is not None and stored_user.deleted_at is not None
    assert stored_team is not None and stored_team.deleted_at is not None
    assert stored_note is not None
    assert stored_note.title == "Keep me"
    assert stored_note.author.email == "owner@example.com"

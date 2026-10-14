import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine
from app.models import Membership, Team, TeamRole, User


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

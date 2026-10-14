import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base, create_database_engine
from app.models import Team, User


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

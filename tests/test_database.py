from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_database_engine


def test_database_engine_connects_with_isolated_database(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'test.db'}")
    test_session_factory = sessionmaker(bind=engine)

    with test_session_factory() as session:
        assert isinstance(session, Session)
        assert session.scalar(text("SELECT 1")) == 1

    engine.dispose()

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migration_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_migrations_upgrade_downgrade_and_upgrade_fresh_database(
        tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"users", "teams", "memberships", "notes", "alembic_version"} <= set(
            inspector.get_table_names()
        )
        assert [
                   index["name"] for index in inspector.get_indexes("notes")
               ] == ["ix_notes_team_created_at"]
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(database_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        assert {"users", "teams", "memberships", "notes"} <= set(
            inspect(engine).get_table_names()
        )
    finally:
        engine.dispose()

from alembic import command
from alembic.config import Config

from app.db.models import Base


def test_alembic_upgrade_head_on_fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fresh_alembic.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    assert db_path.exists()


def test_alembic_tables_match_models_on_fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect

    db_path = tmp_path / "fresh_alembic_tables.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(Config("alembic.ini"), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    expected = set(Base.metadata.tables)

    assert actual == expected

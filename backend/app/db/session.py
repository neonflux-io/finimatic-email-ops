from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


_engine = None
_SessionMaker = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False)


def _normalize_database_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + url.split("sqlite+aiosqlite:///", 1)[1]
    return url


def configure_database(database_url: str | None = None):
    global _engine
    url = _normalize_database_url(database_url or os.getenv("DATABASE_URL", "sqlite:///./finimatic.db"))
    if url.startswith("sqlite:///"):
        db_path = url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args, future=True)
    _SessionMaker.configure(bind=_engine)
    return _engine


def get_engine():
    global _engine
    if _engine is None:
        configure_database()
    return _engine


def init_db() -> None:
    Base.metadata.create_all(bind=get_engine())
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if "replies" in table_names:
        reply_columns = {column["name"] for column in inspector.get_columns("replies")}
        if "archived_at" not in reply_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE replies ADD COLUMN archived_at DATETIME"))
        if "external_message_id" not in reply_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE replies ADD COLUMN external_message_id VARCHAR"))
        if "intent" not in reply_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE replies ADD COLUMN intent TEXT"))
    if "drafts" in table_names:
        draft_columns = {column["name"] for column in inspector.get_columns("drafts")}
        if "notes" not in draft_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE drafts ADD COLUMN notes TEXT"))
        if "source" not in draft_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE drafts ADD COLUMN source VARCHAR"))
        if "rejected" not in draft_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE drafts ADD COLUMN rejected BOOLEAN NOT NULL DEFAULT 0"))
    if "contacts" in table_names:
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
        if "auto_reply_override" not in contact_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE contacts ADD COLUMN auto_reply_override TEXT"))
        if "deleted_at" not in contact_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE contacts ADD COLUMN deleted_at DATETIME"))
    if "conversation_messages" in table_names:
        message_columns = {column["name"] for column in inspector.get_columns("conversation_messages")}
        if "auto_sent" not in message_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE conversation_messages ADD COLUMN auto_sent BOOLEAN NOT NULL DEFAULT 0"))
    if "follow_up_sequences" in table_names:
        followup_columns = {column["name"] for column in inspector.get_columns("follow_up_sequences")}
        if "pending_draft_id" not in followup_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE follow_up_sequences ADD COLUMN pending_draft_id VARCHAR"))
    if "agent_sessions" in table_names:
        agent_session_columns = {column["name"] for column in inspector.get_columns("agent_sessions")}
        for column_name in ("context_loaded_at", "contact_name_map", "turn_history", "current_channel"):
            if column_name not in agent_session_columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE agent_sessions ADD COLUMN {column_name} TEXT"))


def SessionLocal() -> Session:
    if _engine is None:
        configure_database()
    return _SessionMaker()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

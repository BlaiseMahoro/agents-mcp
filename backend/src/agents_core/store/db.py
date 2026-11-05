"""SQLite persistence. JSON columns hold the pydantic payloads verbatim."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine

from agents_core.config import get_config
from agents_core.schemas import utcnow


class Conversation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str = "New chat"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    id: str = Field(primary_key=True)
    conversation_id: str = Field(index=True, foreign_key="conversation.id")
    role: str  # "user" | "assistant"
    mode: str = "auto"
    content: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class PlanRow(SQLModel, table=True):
    __tablename__ = "plan"
    id: str = Field(primary_key=True)
    conversation_id: str | None = Field(default=None, index=True)
    status: str = "draft"
    data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class RunRow(SQLModel, table=True):
    __tablename__ = "run"
    id: str = Field(primary_key=True)
    plan_id: str = Field(index=True)
    status: str = "running"
    data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class ReportRow(SQLModel, table=True):
    __tablename__ = "research_report"
    id: str = Field(primary_key=True)
    conversation_id: str | None = Field(default=None, index=True)
    data: dict[str, Any] = Field(sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSON))


@lru_cache
def engine():
    cfg = get_config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    eng = create_engine(f"sqlite:///{cfg.db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def session() -> Session:
    return Session(engine(), expire_on_commit=False)

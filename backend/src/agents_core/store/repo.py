"""Read/write helpers over the tables. Keeps SQL out of the agents."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from agents_core.schemas import ExecutionReport, Plan, ResearchReport, new_id, utcnow
from agents_core.store.db import Conversation, Message, PlanRow, ReportRow, RunRow, session

# --- Conversations ------------------------------------------------------------


def create_conversation(title: str = "New chat", owner: str | None = None) -> Conversation:
    conv = Conversation(id=new_id("conv"), title=title, owner=owner)
    with session() as s:
        s.add(conv)
        s.commit()
    return conv


def list_conversations(owner: str | None = None) -> list[Conversation]:
    """All chats locally; in demo mode only the given visitor's."""
    q = select(Conversation).order_by(col(Conversation.updated_at).desc())
    if owner is not None:
        q = q.where(Conversation.owner == owner)
    with session() as s:
        return list(s.exec(q))


def get_conversation(conv_id: str) -> Conversation | None:
    with session() as s:
        return s.get(Conversation, conv_id)


def rename_conversation(conv_id: str, title: str) -> None:
    with session() as s:
        conv = s.get(Conversation, conv_id)
        if conv:
            conv.title = title
            s.add(conv)
            s.commit()


def delete_conversation(conv_id: str) -> None:
    with session() as s:
        for m in s.exec(select(Message).where(Message.conversation_id == conv_id)):
            s.delete(m)
        conv = s.get(Conversation, conv_id)
        if conv:
            s.delete(conv)
        s.commit()


def add_message(conv_id: str, role: str, content: str, mode: str = "auto", events: list[dict[str, Any]] | None = None) -> Message:
    msg = Message(id=new_id("msg"), conversation_id=conv_id, role=role, content=content, mode=mode, events=events or [])
    with session() as s:
        s.add(msg)
        conv = s.get(Conversation, conv_id)
        if conv:
            conv.updated_at = utcnow()
            s.add(conv)
        s.commit()
    return msg


def update_message(msg: Message) -> None:
    with session() as s:
        s.merge(msg)
        s.commit()


def list_messages(conv_id: str) -> list[Message]:
    with session() as s:
        return list(s.exec(select(Message).where(Message.conversation_id == conv_id).order_by(col(Message.created_at))))


# --- Plans / runs / reports ---------------------------------------------------


def save_plan(plan: Plan) -> Plan:
    with session() as s:
        s.merge(PlanRow(id=plan.id, conversation_id=plan.conversation_id, status=plan.status, data=plan.model_dump(mode="json"), created_at=plan.created_at))
        s.commit()
    return plan


def get_plan(plan_id: str) -> Plan | None:
    with session() as s:
        row = s.get(PlanRow, plan_id)
        return Plan.model_validate(row.data) if row else None


def list_plans(conversation_id: str | None = None) -> list[Plan]:
    q = select(PlanRow).order_by(col(PlanRow.created_at).desc())
    if conversation_id:
        q = q.where(PlanRow.conversation_id == conversation_id)
    with session() as s:
        return [Plan.model_validate(r.data) for r in s.exec(q)]


def latest_plan(conversation_id: str) -> Plan | None:
    plans = list_plans(conversation_id)
    return plans[0] if plans else None


def save_run(report: ExecutionReport) -> None:
    with session() as s:
        s.merge(RunRow(id=report.id, plan_id=report.plan_id, status=report.status, data=report.model_dump(mode="json"), created_at=report.started_at))
        s.commit()


def get_run(run_id: str) -> ExecutionReport | None:
    with session() as s:
        row = s.get(RunRow, run_id)
        return ExecutionReport.model_validate(row.data) if row else None


def save_report(report: ResearchReport, conversation_id: str | None) -> str:
    rid = new_id("rep")
    with session() as s:
        s.add(ReportRow(id=rid, conversation_id=conversation_id, data=report.model_dump(mode="json")))
        s.commit()
    return rid


def latest_report(conversation_id: str) -> ResearchReport | None:
    with session() as s:
        row = s.exec(
            select(ReportRow).where(ReportRow.conversation_id == conversation_id).order_by(col(ReportRow.created_at).desc())
        ).first()
        return ResearchReport.model_validate(row.data) if row else None

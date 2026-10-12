"""SQLAlchemy models. DecisionRecord is the backbone: one row per candidate."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class DecisionRecord(Base):
    __tablename__ = "decision_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)  # paper|live|backtest
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    setup: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    features: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ml_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    ml_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jev: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # state, answers, version
    gate_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    final_status: Mapped[str] = mapped_column(String(32), index=True)  # e.g. filled|rejected_ml
    rejection_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timings_ms: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    hypothetical_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class Trade(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decision_records.id"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(16), index=True)
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    entry_ts: Mapped[datetime] = mapped_column(DateTime)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    costs: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), index=True)
    run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(1000))


class ConfigChange(Base):
    __tablename__ = "config_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    file: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(String)


def make_session_factory(url: str) -> sessionmaker[Any]:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return sessionmaker(engine)

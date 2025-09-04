# app/models/contract_analysis.py
from sqlalchemy import (
    BigInteger, Integer, String, Text, TIMESTAMP, text, JSON as SAJSON,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from app.db import Base

# Each classified clause (per chunk)
class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)  # id from vector table
    clause_type: Mapped[str] = mapped_column(String(64), nullable=False)
    heading: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    extracted_json: Mapped[dict | None] = mapped_column(SAJSON, nullable=True)
    created_at = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("contract_id", "chunk_id", name="uniq_clause_per_chunk"),
        Index("idx_clauses_contract_type", "contract_id", "clause_type"),
    )

# Risks derived from rules
class Risk(Base):
    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"), index=True, nullable=False)
    severity: Mapped[int] = mapped_column(nullable=False)  # 1..10
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index("idx_risks_contract_sev", "contract_id", "severity"),)

# Alerts (renewal windows, high risk, etc.)
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Optional FKs; remove ForeignKey(...) if you don’t want DB-level constraints
    contract_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contracts.id"), index=True, nullable=False
    )
    risk_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("risks.id"), nullable=True
    )

    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="risk")  # e.g. risk, renewal_notice, sla_breach
    severity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    channel_json = mapped_column(MySQLJSON, nullable=True)     # {"email":[...],"sms":[...],"calendar":true}
    due_at = mapped_column(TIMESTAMP, nullable=True)           # store UTC in app
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open|sent|failed
    notified_at = mapped_column(TIMESTAMP, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        # Dedupe: one alert per (contract, risk, kind). Allows multiple NULL risk_id rows (MySQL semantics).
        UniqueConstraint("contract_id", "risk_id", "kind", name="uniq_alert_per_risk"),
        Index("idx_alerts_contract_status", "contract_id", "status"),
        Index("idx_alerts_status", "status"),       # runner scans all open alerts
        Index("idx_alerts_due", "due_at"),
    )

# Audit log for each pipeline step / decision
class AuditEvent(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contract_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")  # system/user/email
    event: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., CLASSIFIED, RISKED
    payload: Mapped[dict | None] = mapped_column(SAJSON, nullable=True)
    created_at = mapped_column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))

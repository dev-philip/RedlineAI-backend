# app/services/contract_processing.py
from __future__ import annotations
import re
from typing import Iterable, Dict, Any, List, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import tidb_engine
from app.services.contract_vector_store import get_vectorstore
from app.models.contract_analysis import Clause, Risk, AuditEvent

# Very tiny heuristic classifier (replace with LLM later)
CLAUSE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Auto-Renewal", re.compile(r"\b(auto(\s|-)?renew|automatic renewal)\b", re.I)),
    ("Termination",  re.compile(r"\btermination\b", re.I)),
    ("Indemnity",    re.compile(r"\bindemnif(y|ication|ies)\b", re.I)),
    ("Confidentiality", re.compile(r"\bconfidential(ity)?\b", re.I)),
    ("Governing Law", re.compile(r"\bgoverning law|jurisdiction\b", re.I)),
    ("Liability Cap", re.compile(r"\bliability cap|limitation of liability\b", re.I)),
    ("Payment", re.compile(r"\bpayment|fees|charges\b", re.I)),
    ("SLA Uptime", re.compile(r"\buptime|service level|SLA\b", re.I)),
]

# Toy rules engine (replace with policy YAML later)
def evaluate_rules(clause_type: str, text: str) -> list[Dict[str, Any]]:
    rules: list[Dict[str, Any]] = []
    if clause_type == "Auto-Renewal":
        # High risk if notice window > 60 days or no notice mentioned
        m = re.search(r"(\d{1,3})\s*(day|days)", text, re.I)
        if not m:
            rules.append(dict(rule_id="AR-001", severity=8,
                              rationale="Auto-renewal clause without clear notice window.",
                              suggested_fix="Add 'Either party may opt out with 30 days’ prior written notice.'"))
        else:
            days = int(m.group(1))
            if days > 60:
                rules.append(dict(rule_id="AR-002", severity=7,
                                  rationale=f"Notice window {days} days (>60).",
                                  suggested_fix="Reduce to 30 days’ notice or remove auto-renewal."))
    if clause_type == "Liability Cap":
        if re.search(r"\b(one|1)\s*month\b", text, re.I):
            rules.append(dict(rule_id="LC-001", severity=9,
                              rationale="Liability cap equals one month of fees.",
                              suggested_fix="Cap at 12 months of fees, exclude indirect damages only."))
    return rules

async def run_processing(contract_id: str) -> dict:
    """
    Reads chunks for a contract from the vector table, classifies, evaluates risk, and stores results.
    """
    vs = get_vectorstore()
    # Pull chunks by metadata filter
    # NOTE: TiDBVectorStore supports metadata filtering.
    chunks = vs.similarity_search(
        query="*", k=1000, filter={"contract_id": contract_id}
    )
    # Remove potential duplicates (ids)
    seen = set()
    unique_docs = []
    for d in chunks:
        if d.metadata.get("id"):
            if d.metadata["id"] in seen: continue
            seen.add(d.metadata["id"])
        unique_docs.append(d)

    created = {"clauses": 0, "risks": 0}

    async with AsyncSession(tidb_engine) as session:
        async with session.begin():
            # Log
            session.add(AuditEvent(contract_id=contract_id, actor="system", event="PROCESS_START"))

            for d in unique_docs:
                txt = d.page_content or ""
                cid = d.metadata.get("id") or d.metadata.get("chunk_id") or d.metadata.get("source_id") or d.metadata.get("vector_id") or ""
                heading = d.metadata.get("heading") or d.metadata.get("section") or None

                # classify (first match wins)
                ctype = None
                for label, pat in CLAUSE_PATTERNS:
                    if pat.search(txt):
                        ctype = label
                        break
                if not ctype:
                    continue  # skip non-clauses for now

                clause = Clause(
                    contract_id=contract_id,
                    chunk_id=str(cid)[:64],
                    clause_type=ctype,
                    heading=heading,
                    confidence=0.6,           # placeholder until LLM classifier
                    extracted_json=None,
                )
                session.add(clause)
                await session.flush()  # get clause.id
                created["clauses"] += 1

                # risk rules
                for rule in evaluate_rules(ctype, txt):
                    r = Risk(
                        contract_id=contract_id,
                        clause_id=clause.id,
                        severity=rule["severity"],
                        rule_id=rule["rule_id"],
                        rationale=rule["rationale"],
                        suggested_fix=rule.get("suggested_fix"),
                    )
                    session.add(r)
                    created["risks"] += 1

            session.add(AuditEvent(contract_id=contract_id, actor="system", event="PROCESS_DONE", payload=created))

    return created

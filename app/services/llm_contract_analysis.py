# app/services/llm_contract_analysis.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import json
import math
import re
import time

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

# Reuse your canonical writer
from app.services.contract_processing import write_to_canonical

# --- OpenAI client (uses env OPENAI_API_KEY) ---
try:
    from openai import OpenAI
    _client = OpenAI()
except Exception:  # keep app booting if SDK missing
    _client = None


# -------------------------- Models --------------------------

ALLOWED_CLAUSES = [
    "Confidentiality",
    "Termination",
    "Indemnity",
    "IP",
    "DPA",
    "SLA Uptime",
    "Auto-Renewal",
    "Governing Law",
    "Payment",
    "Liability Cap",
    "Other",
]

class LabeledClause(BaseModel):
    chunk_id: str
    clause_type: str
    confidence: float = Field(ge=0.0, le=1.0)

class RiskFinding(BaseModel):
    chunk_id: str
    clause_type: str
    severity: int = Field(ge=0, le=10)
    rationale: str
    suggested_fix: str
    rule_id: str = "llm:v1"


# -------------------------- Utils --------------------------

def _truncate_for_prompt(txt: str, max_chars: int = 3000) -> str:
    if txt and len(txt) > max_chars:
        return txt[:max_chars] + " …"
    return txt or ""

def _json_or_none(s: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(s)
    except Exception:
        return None

def _response_json(client: OpenAI, model: str, messages: List[Dict[str, str]], timeout: int = 40) -> Optional[Dict[str, Any]]:
    """
    Calls Chat Completions in JSON mode and returns parsed object or None.
    """
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=messages,
        temperature=0.0,
        timeout=timeout,
    )
    content = (resp.choices[0].message.content or "").strip()
    return _json_or_none(content)

async def _fetch_chunks(session: AsyncSession, contract_id: str) -> List[Dict[str, Any]]:
    """
    Read chunks from your vector table (tidb_vector_langchain).
    Returns: [{chunk_id, content, meta}]
    """
    tbl = getattr(settings, "langchain_table", "tidb_vector_langchain")
    sql = text(f"""
        SELECT
          id AS chunk_id,
          document AS content,
          meta
        FROM {tbl}
        WHERE JSON_UNQUOTE(JSON_EXTRACT(meta, '$.contract_id')) = :cid
        ORDER BY CAST(JSON_UNQUOTE(JSON_EXTRACT(meta, '$.chunk_index')) AS UNSIGNED), id
    """)
    rows = (await session.execute(sql, {"cid": contract_id})).mappings().all()
    return [{"chunk_id": r["chunk_id"], "content": r["content"], "meta": r["meta"]} for r in rows]


# -------------------------- LLM Steps --------------------------

def _build_classifier_messages(batch: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    allowed = ", ".join(ALLOWED_CLAUSES)
    system = (
        "You are a meticulous contracts analyst. "
        "Label each text chunk with a single clause type from this closed set: "
        f"{allowed}. If unsure, choose 'Other'. "
        "Return strict JSON with key 'labels': array of {chunk_id, clause_type, confidence}."
    )

    # Keep payload compact to reduce tokens
    payload = {
        "chunks": [
            {
                "chunk_id": c["chunk_id"],
                "text": _truncate_for_prompt(c["content"], 3000),
            }
            for c in batch
        ]
    }

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload)},
    ]

def _build_risk_messages(batch: List[LabeledClause], source_map: Dict[str, str], policy_text: Optional[str]) -> List[Dict[str, str]]:
    policy = policy_text or (
        "Use common-sense SaaS/commercial contracting defaults. "
        "Score severity 0–10 (10 = severe). Provide a short rationale and a concrete suggested fix."
    )

    system = (
        "You are a senior commercial counsel. "
        "Assess risk for each clause chunk given internal policy text. "
        "Return strict JSON with key 'risks': array of "
        "{chunk_id, clause_type, severity (0-10), rationale, suggested_fix, rule_id}."
    )

    payload = {
        "policy": policy,
        "items": [
            {
                "chunk_id": lc.chunk_id,
                "clause_type": lc.clause_type,
                "text": _truncate_for_prompt(source_map.get(lc.chunk_id, ""), 3000),
            }
            for lc in batch
        ],
    }

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload)},
    ]


def _classify_batch(client: OpenAI, model: str, batch: List[Dict[str, Any]]) -> List[LabeledClause]:
    msgs = _build_classifier_messages(batch)
    data = _response_json(client, model, msgs)
    out: List[LabeledClause] = []

    if not data or "labels" not in data:
        # fallback: everything Other at mid confidence
        return [LabeledClause(chunk_id=c["chunk_id"], clause_type="Other", confidence=0.5) for c in batch]

    for item in data.get("labels", []):
        try:
            lc = LabeledClause(**item)
        except ValidationError:
            # sanitize/clip bad values if LLM drifts
            cid = str(item.get("chunk_id"))
            ctype = item.get("clause_type") if item.get("clause_type") in ALLOWED_CLAUSES else "Other"
            conf = item.get("confidence", 0.5)
            conf = max(0.0, min(float(conf), 1.0)) if isinstance(conf, (int, float)) else 0.5
            lc = LabeledClause(chunk_id=cid, clause_type=ctype, confidence=conf)
        out.append(lc)

    # Ensure one label per chunk (keep highest confidence if duplicates)
    best_by_chunk: Dict[str, LabeledClause] = {}
    for lc in out:
        if lc.chunk_id not in best_by_chunk or lc.confidence > best_by_chunk[lc.chunk_id].confidence:
            best_by_chunk[lc.chunk_id] = lc
    return list(best_by_chunk.values())


def _assess_batch(client: OpenAI, model: str, labeled: List[LabeledClause], source_map: Dict[str, str], policy_text: Optional[str]) -> List[RiskFinding]:
    msgs = _build_risk_messages(labeled, source_map, policy_text)
    data = _response_json(client, model, msgs)
    out: List[RiskFinding] = []

    if not data or "risks" not in data:
        # if the model fails, return zeros
        return [
            RiskFinding(
                chunk_id=lc.chunk_id,
                clause_type=lc.clause_type,
                severity=0,
                rationale="",
                suggested_fix="",
                rule_id="llm:v1"
            )
            for lc in labeled
        ]

    for item in data.get("risks", []):
        try:
            rf = RiskFinding(**item)
        except ValidationError:
            # sanitize
            cid = str(item.get("chunk_id"))
            ctype = item.get("clause_type") if item.get("clause_type") in ALLOWED_CLAUSES else "Other"
            sev = item.get("severity", 0)
            try:
                sev = int(sev)
            except Exception:
                sev = 0
            sev = max(0, min(sev, 10))
            rf = RiskFinding(
                chunk_id=cid,
                clause_type=ctype,
                severity=sev,
                rationale=str(item.get("rationale") or ""),
                suggested_fix=str(item.get("suggested_fix") or ""),
                rule_id=str(item.get("rule_id") or "llm:v1"),
            )
        out.append(rf)

    # one risk row per chunk (keep highest severity if duplicates)
    best_by_chunk: Dict[str, RiskFinding] = {}
    for rf in out:
        if rf.chunk_id not in best_by_chunk or rf.severity > best_by_chunk[rf.chunk_id].severity:
            best_by_chunk[rf.chunk_id] = rf
    return list(best_by_chunk.values())


# -------------------------- Orchestrator --------------------------

async def process_contract_with_llm(
    session: AsyncSession,
    contract_id: str,
    *,
    model: Optional[str] = None,
    batch_size: int = 10,
    policy_text: Optional[str] = None,
    sleep_between_calls: float = 0.0,  # set to small value if rate-limited
) -> Dict[str, int]:
    """
    End-to-end (LLM):
      1) Fetch chunks
      2) LLM classify in batches
      3) LLM risk assessment in batches
      4) Write clauses/risks
    """
    if _client is None:
        # Safety: if no OpenAI client installed, do nothing
        return {"clauses": 0, "risks": 0, "alerts": 0}

    model = model or getattr(settings, "llm_model_name", "gpt-4o-mini")

    # 1) chunks
    chunks = await _fetch_chunks(session, contract_id)
    if not chunks:
        return {"clauses": 0, "risks": 0, "alerts": 0}

    # source lookup
    source_map = {c["chunk_id"]: c["content"] for c in chunks}

    # 2) classify
    labeled: List[LabeledClause] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        labeled.extend(_classify_batch(_client, model, batch))
        if sleep_between_calls:
            time.sleep(sleep_between_calls)

    # 3) assess risk
    risks: List[RiskFinding] = []
    for i in range(0, len(labeled), batch_size):
        sub = labeled[i : i + batch_size]
        risks.extend(_assess_batch(_client, model, sub, source_map, policy_text))
        if sleep_between_calls:
            time.sleep(sleep_between_calls)

    # 4) adapt to write_to_canonical() expected format
    findings: List[Dict[str, Any]] = []
    for rf in risks:
        findings.append(
            {
                "chunk_id": rf.chunk_id,
                "clause_type": rf.clause_type,
                "confidence": next((lc.confidence for lc in labeled if lc.chunk_id == rf.chunk_id), 0.7),
                "severity": rf.severity,
                "rationale": rf.rationale,
                "suggested_fix": rf.suggested_fix,
                "extracted_json": "{}",   # future extractor step
                "rule_id": rf.rule_id,
            }
        )

    # 5) write
    return await write_to_canonical(session, contract_id, findings)

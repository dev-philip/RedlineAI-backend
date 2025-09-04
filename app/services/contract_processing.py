# app/services/contract_processing.py
from typing import Dict, Any, List, Optional, Tuple
import json
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

# NEW: pull in the alert helper
from app.services.alerts_agent import (
    should_alert,
    derive_due_at,
    draft_alert_message,
    create_alert_for_risk,
    ALERT_SEVERITY_THRESHOLD_DEFAULT,
)

# you can also read this from settings
ALERT_SEVERITY_THRESHOLD = 8


# ---------------- config / utils ----------------
TABLE_NAME = getattr(settings, "langchain_table", "tidb_vector_langchain")

def _maybe_json_loads(val):
    if val is None:
        return {}
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return {"raw": val}


# ---------- clause classifier (regexy but practical) ----------
KEYWORD_MAP: List[Tuple[str, str]] = [
    (r"\bauto[- ]?renew\b|\bautomatic renewal\b", "Auto-Renewal"),
    (r"\bindemnif(?:y|ies|ication)\b|\bhold harmless\b", "Indemnity"),
    (r"\bconfidential(?:ity)?\b|\bnon[- ]?disclosure\b|\bnda\b", "Confidentiality"),
    (r"\btermination\b|\bterm ends\b|\bnotice of termination\b", "Termination"),
    (r"\buptime\b|\bavailability\b|\bservice level\b|\bsla\b", "SLA Uptime"),
    (r"\bliability cap\b|\blimitation of liability\b|\bcap on damages\b", "Liability Cap"),
    (r"\bgoverning law\b|\bjurisdiction\b|\bvenue\b", "Governing Law"),
    (r"\bpayment\b|\bfees?\b|\bcharges?\b|\binvoice\b", "Payment"),
    (r"\bmaintenance\b|\brepairs?\b|\bhvac\b|\bair conditioning\b", "Maintenance"),
    (r"\bsublet\b|\bsublease\b|\bassignment\b", "Subletting"),
    (r"\brent (?:increase|escalat)|\bescalation\b|\bannual increase\b", "Rent Escalation"),
]

def classify_clause(clause_text: str) -> Tuple[str, float]:
    t = clause_text.lower()
    for pat, label in KEYWORD_MAP:
        if re.search(pat, t):
            return label, 0.85
    return "Other", 0.40


# ---------- simple helpers ----------
_pct_re = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_notice_re = re.compile(
    r"(?:notice(?:\s+of)?\s*(?:non[- ]?renewal|termination)?\s*(?:at\s+least\s*)?)(\d+)\s*(?:day|days)",
    re.I,
)

def _find_percentages(text: str) -> List[float]:
    return [float(m.group(1)) for m in _pct_re.finditer(text)]

def _find_notice_days(text: str) -> List[int]:
    return [int(m.group(1)) for m in _notice_re.finditer(text)]

def _contains_any(t: str, *words: str) -> bool:
    return any(w in t for w in words)


# ---------- risk assessor (heuristics you can later replace with policy rules/LLMs) ----------
def assess_risk(clause_type: str, clause_text: str) -> Tuple[int, str, str]:
    """
    Return (severity 0–10, rationale, suggested_fix).
    Tuned to leases so you'll actually see risks in sample data.
    """
    t = clause_text.lower()

    if clause_type == "Auto-Renewal":
        days = _find_notice_days(t)
        if not days:
            return 7, "Auto-renewal without a clear non-renewal notice window.", "Add a 30–60 day non-renewal notice."
        max_days = max(days)
        if max_days > 60:
            return 6, f"Non-renewal notice window is long ({max_days} days).", "Reduce the window to ≤ 30 days."
        return 0, "", ""

    if clause_type == "Rent Escalation":
        pcts = _find_percentages(t)
        if pcts:
            max_pct = max(pcts)
            if max_pct > 5.0:
                return 7, f"High rent escalation detected ({max_pct}%).", "Cap annual escalation at ≤ 3%."
            if max_pct > 3.0:
                return 5, f"Rent escalation above typical threshold ({max_pct}%).", "Negotiate 3% cap."
        if "escalat" in t or "increase" in t:
            return 4, "Rent escalation mentioned without explicit cap.", "Add explicit annual cap (≤ 3%)."
        return 0, "", ""

    if clause_type == "Maintenance":
        if _contains_any(t, "hvac", "air conditioning"):
            if _contains_any(t, "tenant") and _contains_any(t, "pay", "responsible", "cost", "expense"):
                return 6, "Tenant appears responsible for HVAC costs.", "Limit tenant HVAC costs or shift to landlord."
        if "repair" in t and "tenant" in t and _contains_any(t, "all costs", "at its expense"):
            return 5, "Tenant broadly responsible for repairs.", "Add carve-outs or cost caps."
        return 0, "", ""

    if clause_type == "Liability Cap":
        if _contains_any(t, "unlimited", "without limit", "no limit"):
            return 9, "Unlimited liability detected.", "Cap liability to 12 months of fees."
        if not _contains_any(t, "cap", "limit", "limitation"):
            return 6, "No explicit liability cap found.", "Add liability cap (e.g., 12 months of fees)."
        return 0, "", ""

    if clause_type == "Governing Law":
        if _contains_any(t, "outside", "foreign", "non-local", "non local"):
            return 5, "Non-local governing law may be unfavorable.", "Switch to your home jurisdiction."
        return 0, "", ""

    if clause_type == "Indemnity":
        if _contains_any(t, "defend", "indemnify", "hold harmless") and not _contains_any(t, "exclude", "except", "carve-out", "carve out"):
            return 4, "Broad indemnity without clear carve-outs.", "Add standard carve-outs (gross negligence, wilful misconduct)."
        return 0, "", ""

    if clause_type == "SLA Uptime":
        pcts = _find_percentages(t)
        if pcts:
            max_pct = max(pcts)
            if max_pct < 99.9:
                return 8, f"SLA uptime below 99.9% ({max_pct}%).", "Increase uptime to ≥ 99.9% or add service credits."
        return 0, "", ""

    # Others → no risk by default
    return 0, "", ""


# ---------- data access ----------
async def fetch_chunks_for_contract(session: AsyncSession, contract_id: str) -> List[Dict[str, Any]]:
    """
    Returns [{chunk_id, content, metadata}] for this contract,
    reading from the vector table (meta JSON column).
    """
    sql = text(
        f"""
        SELECT
          id AS chunk_id,
          document AS content,
          meta AS metadata
        FROM {TABLE_NAME}
        WHERE JSON_UNQUOTE(JSON_EXTRACT(meta, '$.contract_id')) = :cid
        ORDER BY CAST(JSON_UNQUOTE(JSON_EXTRACT(meta, '$.chunk_index')) AS UNSIGNED), id
        """
    )
    rows = (await session.execute(sql, {"cid": contract_id})).mappings().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "chunk_id": r["chunk_id"],              # UUID stored by TiDB Vector integration
                "content": r["content"],
                "metadata": _maybe_json_loads(r["metadata"]),
            }
        )
    return out


async def write_to_canonical(
    session: AsyncSession,
    contract_id: str,
    findings: List[Dict[str, Any]],
    *,
    alert_threshold: int = ALERT_SEVERITY_THRESHOLD_DEFAULT,
    use_llm_alerts: bool = False,
) -> Dict[str, int]:
    """
    Upsert into canonical tables:
      - clauses(contract_id, chunk_id) UNIQUE (recommended)
      - risks referencing clauses.id
    Also: create an alert for high-severity risks (>= alert_threshold).
    """
    written_clauses = 0
    written_risks = 0

    for f in findings:
        # Normalize extracted_json
        exjson = f.get("extracted_json", "{}")
        if isinstance(exjson, (dict, list)):
            exjson = json.dumps(exjson)

        # 1) Upsert clause and fetch id via LAST_INSERT_ID
        await session.execute(
            text("""
                INSERT INTO clauses (contract_id, chunk_id, clause_type, confidence, extracted_json)
                VALUES (:cid, :chunk_id, :ctype, :conf, :exjson)
                ON DUPLICATE KEY UPDATE
                    clause_type     = VALUES(clause_type),
                    confidence      = VALUES(confidence),
                    extracted_json  = VALUES(extracted_json),
                    id              = LAST_INSERT_ID(id)
            """),
            {
                "cid": contract_id,
                "chunk_id": f["chunk_id"],
                "ctype": f["clause_type"],
                "conf": float(f.get("confidence", 0.0)),
                "exjson": exjson,
            },
        )
        rid = await session.execute(text("SELECT LAST_INSERT_ID()"))
        clause_id = int(rid.scalar_one())
        written_clauses += 1

        # 2) Insert risk row if there is something to persist
        severity = int(f.get("severity", 0))
        rationale = f.get("rationale", "")
        suggested_fix = f.get("suggested_fix", "")
        rule_id = f.get("rule_id", "heuristic:v1")

        if severity > 0 or rationale or suggested_fix:
            await session.execute(
                text("""
                    INSERT INTO risks (contract_id, clause_id, severity, rule_id, rationale, suggested_fix)
                    VALUES (:cid, :clause_id, :sev, :rule_id, :why, :fix)
                """),
                {
                    "cid": contract_id,
                    "clause_id": clause_id,
                    "sev": severity,
                    "rule_id": rule_id,
                    "why": rationale,
                    "fix": suggested_fix,
                },
            )
            # fetch the risk id for alert de-dupe/linking
            rid2 = await session.execute(text("SELECT LAST_INSERT_ID()"))
            risk_id = int(rid2.scalar_one())
            written_risks += 1

            # 3) Create alert for high-severity risks
            risk_for_alert = {
                "severity": severity,
                "clause_type": f.get("clause_type", "Clause"),
                "rationale": rationale,
                "suggested_fix": suggested_fix,
            }
            if should_alert(risk_for_alert, threshold=alert_threshold):
                # draft message (optionally LLM-polished) + derive due_at if we detect "NN day"
                message = await draft_alert_message(risk_for_alert, use_llm=use_llm_alerts)
                due_at = derive_due_at(risk_for_alert)

                # optional: set default channels here, or leave {} to let the dispatcher decide
                channels = {}  # e.g., {"email":["legal@acme.com"],"sms":["+15550001111"],"calendar":True}

                await create_alert_for_risk(
                    session=session,
                    contract_id=contract_id,
                    risk_id=risk_id,
                    severity=severity,
                    message=message,
                    due_at=due_at,
                    kind="risk_high",
                    status="open",
                    channels=channels,
                )

    await session.commit()
    return {"clauses": written_clauses, "risks": written_risks}

# ---------- main pipeline ----------
async def process_contract(session: AsyncSession, contract_id: str) -> Dict[str, int]:
    """
    Minimal pipeline:
      1) load chunks from vector table
      2) classify + assess risk
      3) write to `clauses` & `risks`
    """
    chunks = await fetch_chunks_for_contract(session, contract_id)
    findings: List[Dict[str, Any]] = []

    for ch in chunks:
        ctype, conf = classify_clause(ch["content"])
        sev, why, fix = assess_risk(ctype, ch["content"])
        findings.append(
            {
                "chunk_id": ch["chunk_id"],         # UUID from vector table
                "clause_type": ctype,
                "confidence": conf,
                "severity": sev,
                "rationale": why,
                "suggested_fix": fix,
                "extracted_json": "{}",             # placeholder for structured extraction
                "rule_id": "heuristic:v1",
            }
        )

    return await write_to_canonical(session, contract_id, findings)


# ---------- risks listing with useful context ----------
async def list_risks(
    session: AsyncSession,
    contract_id: str,
    min_severity: int = 1,
    clause_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Returns risks with clause type and vector-store context:
    - snippet (LEFT(document, 200))
    - page, heading, chunk_index (from meta JSON)
    """
    base_sql = f"""
        SELECT
          r.id AS risk_id,
          r.severity,
          r.rule_id,
          r.rationale,
          r.suggested_fix,
          c.clause_type,
          c.chunk_id,
          LEFT(t.document, :snip) AS snippet,
          CAST(JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.page')) AS UNSIGNED)       AS page,
          JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.heading'))                       AS heading,
          CAST(JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.chunk_index')) AS UNSIGNED) AS chunk_index
        FROM risks r
        JOIN clauses c ON c.id = r.clause_id
        LEFT JOIN {TABLE_NAME} t ON t.id = c.chunk_id
        WHERE r.contract_id = :cid
          AND r.severity >= :minsev
    """

    params: Dict[str, Any] = {"cid": contract_id, "minsev": min_severity, "snip": 200}

    if clause_type:
        base_sql += " AND c.clause_type = :ctype"
        params["ctype"] = clause_type

    base_sql += " ORDER BY r.severity DESC, r.id DESC LIMIT 500"

    rows = (await session.execute(text(base_sql), params)).mappings().all()
    return [
        {
            "risk_id": r["risk_id"],
            "severity": r["severity"],
            "rule_id": r["rule_id"],
            "rationale": r["rationale"],
            "suggested_fix": r["suggested_fix"],
            "clause_type": r["clause_type"],
            "chunk_id": r["chunk_id"],
            "snippet": r["snippet"],
            "page": r["page"],
            "heading": r["heading"],
            "chunk_index": r["chunk_index"],
        }
        for r in rows
    ]

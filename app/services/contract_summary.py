# app/services/contract_summary.py
from typing import Any, Dict, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings

async def build_contract_summary(
    session: AsyncSession,
    contract_id: str,
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    Builds an exec-style summary for a contract:
      - contract info
      - counts (chunks, clauses, risks by severity)
      - clause-type breakdown
      - top risks (with snippet + page/heading when available)
    """
    vec_tbl = getattr(settings, "langchain_table", "tidb_vector_langchain")

    # --- Contract info ---
    row = (
        await session.execute(
            text("""
                SELECT id, tenant, doc_type, original_filename, sha256, uploaded_at
                FROM contracts
                WHERE id = :cid
            """),
            {"cid": contract_id},
        )
    ).mappings().first()

    contract_info = {
        "contract_id": contract_id,
        "tenant": row.get("tenant") if row else None,
        "doc_type": row.get("doc_type") if row else None,
        "original_filename": row.get("original_filename") if row else None,
        "sha256": row.get("sha256") if row else None,
        "uploaded_at": row.get("uploaded_at") if row else None,
    }

    # --- Counts: chunks / clauses / risks (by severity buckets) ---
    chunks_count = (
        await session.execute(
            text(f"""
                SELECT COUNT(*) AS n
                FROM {vec_tbl}
                WHERE JSON_UNQUOTE(JSON_EXTRACT(meta, '$.contract_id')) = :cid
            """),
            {"cid": contract_id},
        )
    ).scalar_one()

    clauses_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM clauses WHERE contract_id = :cid"),
            {"cid": contract_id},
        )
    ).scalar_one()

    risk_counts = (
        await session.execute(
            text("""
                SELECT
                  COUNT(*)                                                   AS total,
                  SUM(CASE WHEN severity >= 8               THEN 1 ELSE 0 END) AS high,
                  SUM(CASE WHEN severity BETWEEN 5 AND 7    THEN 1 ELSE 0 END) AS medium,
                  SUM(CASE WHEN severity BETWEEN 1 AND 4    THEN 1 ELSE 0 END) AS low
                FROM risks
                WHERE contract_id = :cid
            """),
            {"cid": contract_id},
        )
    ).mappings().first() or {"total": 0, "high": 0, "medium": 0, "low": 0}

    # --- Clause breakdown ---
    clause_breakdown_rows = (
        await session.execute(
            text("""
                SELECT clause_type, COUNT(*) AS cnt, ROUND(AVG(confidence), 2) AS avg_conf
                FROM clauses
                WHERE contract_id = :cid
                GROUP BY clause_type
                ORDER BY cnt DESC
                LIMIT 50
            """),
            {"cid": contract_id},
        )
    ).mappings().all()

    clause_breakdown: List[Dict[str, Any]] = [
        {
            "clause_type": r["clause_type"],
            "count": int(r["cnt"]),
            "avg_confidence": float(r["avg_conf"]) if r["avg_conf"] is not None else None,
        }
        for r in clause_breakdown_rows
    ]

    # --- Top risks (join vector table for snippet + page/heading) ---
    top_risk_rows = (
        await session.execute(
            text(f"""
                SELECT
                  r.id AS risk_id,
                  r.severity, r.rule_id, r.rationale, r.suggested_fix,
                  c.clause_type, c.chunk_id,
                  LEFT(t.document, 200) AS snippet,
                  CAST(JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.page')) AS UNSIGNED)       AS page,
                  JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.heading'))                       AS heading,
                  CAST(JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.chunk_index')) AS UNSIGNED) AS chunk_index
                FROM risks r
                JOIN clauses c ON c.id = r.clause_id
                LEFT JOIN {vec_tbl} t ON t.id = c.chunk_id
                WHERE r.contract_id = :cid
                ORDER BY r.severity DESC, r.id DESC
                LIMIT :topn
            """),
            {"cid": contract_id, "topn": top_n},
        )
    ).mappings().all()

    top_risks: List[Dict[str, Any]] = [
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
        for r in top_risk_rows
    ]

    return {
        "contract": contract_info,
        "counts": {
            "chunks": int(chunks_count),
            "clauses": int(clauses_count),
            "risks_total": int(risk_counts.get("total", 0)),
            "risks_by_severity": {
                "high": int(risk_counts.get("high", 0)),
                "medium": int(risk_counts.get("medium", 0)),
                "low": int(risk_counts.get("low", 0)),
            },
        },
        "clause_breakdown": clause_breakdown,
        "top_risks": top_risks,
    }

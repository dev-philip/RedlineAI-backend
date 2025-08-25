# app/schemas/ingestion.py
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    """
    Response for each uploaded file after ingestion.
    """
    file_name: str
    contract_id: Optional[str] = None   # UUID from contracts table
    sha256: Optional[str] = None        # checksum used for idempotency
    chunks: int = 0
    stored_ids: List[str] = Field(default_factory=list)   # row IDs returned by vector store
    metadata: Dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False               # true if duplicate detected (tenant + sha256)

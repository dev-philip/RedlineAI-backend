# app/schemas/analysis.py
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class QARequest(BaseModel):
    question: str
    k: int = 6
    mmr: bool = False

class QAMatch(BaseModel):
    text: str
    score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class QAResponse(BaseModel):
    contract_id: str
    matches: List[QAMatch] = Field(default_factory=list)

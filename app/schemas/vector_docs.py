from pydantic import BaseModel

class VectorDocCreate(BaseModel):
    title: str
    content: str

class VectorDocOut(BaseModel):
    id: int
    title: str
    content: str

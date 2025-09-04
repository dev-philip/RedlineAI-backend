# app/schemas/user.py
from pydantic import BaseModel, EmailStr

class UserCreate(BaseModel):
    email: EmailStr
    name: str
    google_id: str

class UserCreateResponse(BaseModel):
    id: int          # ⬅️ int now (used to be str/UUID)
    email: EmailStr
    name: str

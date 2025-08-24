from pydantic import BaseModel, EmailStr

class StudentCreate(BaseModel):
    name: str
    email: EmailStr

class StudentOut(BaseModel):
    id: int
    name: str
    email: EmailStr

    class Config:
        from_attributes = True

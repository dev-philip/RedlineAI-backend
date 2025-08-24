# app/routers/tidb_router.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_tidb_session as get_session
from app.models.students import Student
from app.schemas.students import StudentCreate, StudentOut

router = APIRouter()

@router.post("/students", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
async def create_student(payload: StudentCreate, db: AsyncSession = Depends(get_session)):
    # Check unique email
    exists = await db.execute(select(Student).where(Student.email == payload.email))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists")

    student = Student(name=payload.name, email=payload.email)
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return student

@router.get("/students", response_model=list[StudentOut])
async def list_students(db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(Student).order_by(Student.id.desc()))
    return result.scalars().all()

@router.get("/students/{student_id}", response_model=StudentOut)
async def get_student(student_id: int, db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student

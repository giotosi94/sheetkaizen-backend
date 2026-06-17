from fastapi import APIRouter
from app.database import db
from app.models.user import UserCreate, UserLogin
from datetime import datetime, timezone

router = APIRouter()


@router.post("/register")
async def register(user: UserCreate):
    return {
        "token": "no-auth",
        "user": {
            "id": "default",
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": "admin",
            "reparto": user.reparto,
            "linee": user.linee,
        },
    }


@router.post("/login")
async def login(credentials: UserLogin):
    return {
        "token": "no-auth",
        "user": {
            "id": "default",
            "username": "default",
            "email": credentials.email,
            "full_name": "Default User",
            "role": "admin",
            "reparto": "Generale",
            "linee": [],
        },
    }


@router.get("/me")
async def get_me():
    return {
        "id": "default",
        "username": "default",
        "email": "default@lindt.com",
        "full_name": "Default User",
        "role": "admin",
        "reparto": "Generale",
        "linee": [],
        "team": None,
    }

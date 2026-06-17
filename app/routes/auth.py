from fastapi import APIRouter, HTTPException, Depends
from app.database import db
from app.models.user import UserCreate, UserLogin
from app.middleware.auth import get_current_user
from app.config import settings
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt

router = APIRouter()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@router.post("/register")
async def register(user: UserCreate):
    existing = await db.users.find_one({"$or": [{"email": user.email}, {"username": user.username}]})
    if existing:
        raise HTTPException(status_code=400, detail="Email o username già esistente")

    count = await db.users.count_documents({})

    user_doc = {
        "username": user.username,
        "email": user.email,
        "password_hash": hash_password(user.password),
        "full_name": user.full_name,
        "role": "admin" if count == 0 else user.role,
        "reparto": user.reparto,
        "linee": user.linee,
        "team": user.team,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.users.insert_one(user_doc)
    token = create_token(str(result.inserted_id))

    return {
        "token": token,
        "user": {
            "id": str(result.inserted_id),
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user_doc["role"],
            "reparto": user.reparto,
            "linee": user.linee,
        },
    }


@router.post("/login")
async def login(credentials: UserLogin):
    user = await db.users.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(status_code=401, detail="Email o password errati")

    if not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email o password errati")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Account disattivato")

    token = create_token(str(user["_id"]))

    return {
        "token": token,
        "user": {
            "id": str(user["_id"]),
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "reparto": user["reparto"],
            "linee": user.get("linee", []),
        },
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["_id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "role": current_user["role"],
        "reparto": current_user["reparto"],
        "linee": current_user.get("linee", []),
        "team": current_user.get("team"),
    }

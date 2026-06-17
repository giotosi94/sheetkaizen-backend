from fastapi import APIRouter, HTTPException
from app.database import db
from app.models.user import UserUpdate
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


@router.get("/")
async def get_users():
    users = []
    cursor = db.users.find({})
    async for user in cursor:
        user["_id"] = str(user["_id"])
        user.pop("password_hash", None)
        users.append(user)
    return users


@router.get("/{user_id}")
async def get_user(user_id: str):
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    user["_id"] = str(user["_id"])
    user.pop("password_hash", None)
    return user


@router.put("/{user_id}")
async def update_user(user_id: str, update: UserUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return {"message": "Utente aggiornato"}


@router.delete("/{user_id}")
async def delete_user(user_id: str):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return {"message": "Utente disattivato"}

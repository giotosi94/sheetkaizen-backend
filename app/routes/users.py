from fastapi import APIRouter, HTTPException, Depends
from app.database import db
from app.models.user import UserUpdate
from app.middleware.auth import get_current_user, require_admin
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


@router.get("/")
async def get_users(current_user: dict = Depends(require_admin)):
    users = []
    cursor = db.users.find({"is_active": True})
    async for user in cursor:
        user["_id"] = str(user["_id"])
        del user["password_hash"]
        users.append(user)
    return users


@router.get("/{user_id}")
async def get_user(user_id: str, current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    user["_id"] = str(user["_id"])
    del user["password_hash"]
    return user


@router.put("/{user_id}")
async def update_user(user_id: str, update: UserUpdate, current_user: dict = Depends(require_admin)):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return {"message": "Utente aggiornato"}


@router.delete("/{user_id}")
async def delete_user(user_id: str, current_user: dict = Depends(require_admin)):
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)}, {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return {"message": "Utente disattivato"}

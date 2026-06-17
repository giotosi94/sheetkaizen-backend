from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.config import settings
from app.database import db
from bson import ObjectId

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token non valido")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token scaduto")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token non valido")

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise HTTPException(status_code=401, detail="Utente non trovato")

    user["_id"] = str(user["_id"])
    return user


async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accesso riservato agli admin")
    return current_user


async def require_manager_or_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Accesso riservato a manager e admin")
    return current_user

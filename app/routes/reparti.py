from fastapi import APIRouter, HTTPException, Depends
from app.database import database
from app.models.reparto import RepartoCreate, RepartoUpdate
from app.middleware.auth import require_admin
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


@router.get("/")
async def get_reparti():
    reparti = []
    cursor = db.reparti.find({"is_active": {"$ne": False}})
    async for rep in cursor:
        rep["_id"] = str(rep["_id"])
        reparti.append(rep)
    return reparti


@router.post("/")
async def create_reparto(reparto: RepartoCreate, current_user: dict = Depends(require_admin)):
    doc = {
        "nome": reparto.nome,
        "linee": [l.dict() for l in reparto.linee],
        "responsabile_id": reparto.responsabile_id,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db.reparti.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Reparto creato"}


@router.put("/{reparto_id}")
async def update_reparto(reparto_id: str, update: RepartoUpdate, current_user: dict = Depends(require_admin)):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    if "linee" in update_data:
        update_data["linee"] = [l if isinstance(l, dict) else l.dict() for l in update_data["linee"]]

    result = await db.reparti.update_one({"_id": ObjectId(reparto_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto non trovato")
    return {"message": "Reparto aggiornato"}


@router.delete("/{reparto_id}")
async def delete_reparto(reparto_id: str, current_user: dict = Depends(require_admin)):
    await db.reparti.update_one({"_id": ObjectId(reparto_id)}, {"$set": {"is_active": False}})
    return {"message": "Reparto disattivato"}

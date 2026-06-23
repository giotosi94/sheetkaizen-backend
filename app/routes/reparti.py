from fastapi import APIRouter, HTTPException
from app.database import db
from app.models.reparto import RepartoCreate, RepartoUpdate, LineaModel, MacchinaModel
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


def serialize_reparto(rep: dict) -> dict:
    """Converte ObjectId in stringa per la risposta."""
    rep["_id"] = str(rep["_id"])
    return rep


# ============================================================
# CRUD REPARTI
# ============================================================
@router.get("/")
async def get_reparti(include_inactive: bool = False):
    """Lista reparti con linee e macchine annidate."""
    query = {} if include_inactive else {"$or": [{"attivo": True}, {"is_active": True}]}
    reparti = []
    cursor = db.reparti.find(query).sort("nome", 1)
    async for rep in cursor:
        # Backward compat: se manca "attivo", deriva da is_active
        if "attivo" not in rep:
            rep["attivo"] = rep.get("is_active", True)
        reparti.append(serialize_reparto(rep))
    return reparti


@router.get("/{reparto_id}")
async def get_reparto(reparto_id: str):
    """Dettaglio singolo reparto."""
    rep = await db.reparti.find_one({"_id": ObjectId(reparto_id)})
    if not rep:
        raise HTTPException(status_code=404, detail="Reparto non trovato")
    if "attivo" not in rep:
        rep["attivo"] = rep.get("is_active", True)
    return serialize_reparto(rep)


@router.post("/")
async def create_reparto(reparto: RepartoCreate):
    doc = {
        "nome": reparto.nome,
        "codice": reparto.codice,
        "descrizione": reparto.descrizione or "",
        "linee": [l.dict() for l in reparto.linee],
        "responsabile_id": reparto.responsabile_id,
        "attivo": reparto.attivo,
        "is_active": True,  # backward compat
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.reparti.insert_one(doc)
    created = await db.reparti.find_one({"_id": result.inserted_id})
    return serialize_reparto(created)


@router.put("/{reparto_id}")
async def update_reparto(reparto_id: str, update: RepartoUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    
    if "linee" in update_data:
        update_data["linee"] = [
            l if isinstance(l, dict) else l.dict()
            for l in update_data["linee"]
        ]
    
    # Sync attivo ↔ is_active per backward compat
    if "attivo" in update_data:
        update_data["is_active"] = update_data["attivo"]
    elif "is_active" in update_data:
        update_data["attivo"] = update_data["is_active"]
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id)},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto non trovato")
    
    updated = await db.reparti.find_one({"_id": ObjectId(reparto_id)})
    return serialize_reparto(updated)


@router.delete("/{reparto_id}")
async def delete_reparto(reparto_id: str, hard: bool = False):
    """Soft delete di default. Usa ?hard=true per cancellazione fisica."""
    if hard:
        result = await db.reparti.delete_one({"_id": ObjectId(reparto_id)})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Reparto non trovato")
        return {"message": "Reparto eliminato definitivamente"}
    else:
        await db.reparti.update_one(
            {"_id": ObjectId(reparto_id)},
            {"$set": {"attivo": False, "is_active": False, "updated_at": datetime.now(timezone.utc)}}
        )
        return {"message": "Reparto disattivato"}


# ============================================================
# CRUD LINEE (granulare, dentro un Reparto)
# ============================================================
@router.post("/{reparto_id}/linee")
async def add_linea(reparto_id: str, linea: LineaModel):
    """Aggiunge una linea a un reparto."""
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id)},
        {
            "$push": {"linee": linea.dict()},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto non trovato")
    return linea.dict()


@router.put("/{reparto_id}/linee/{linea_id}")
async def update_linea(reparto_id: str, linea_id: str, linea: LineaModel):
    """Aggiorna una linea esistente."""
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id), "linee.id": linea_id},
        {
            "$set": {
                "linee.$": linea.dict(),
                "updated_at": datetime.now(timezone.utc),
            }
        }
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto o linea non trovati")
    return linea.dict()


@router.delete("/{reparto_id}/linee/{linea_id}")
async def delete_linea(reparto_id: str, linea_id: str):
    """Rimuove una linea da un reparto."""
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id)},
        {
            "$pull": {"linee": {"id": linea_id}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Linea non trovata")
    return {"message": "Linea eliminata"}


# ============================================================
# CRUD MACCHINE (granulare, dentro una Linea di un Reparto)
# ============================================================
@router.post("/{reparto_id}/linee/{linea_id}/macchine")
async def add_macchina(reparto_id: str, linea_id: str, macchina: MacchinaModel):
    """Aggiunge una macchina a una linea."""
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id), "linee.id": linea_id},
        {
            "$push": {"linee.$.macchine": macchina.dict()},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto o linea non trovati")
    return macchina.dict()


@router.put("/{reparto_id}/linee/{linea_id}/macchine/{macchina_id}")
async def update_macchina(reparto_id: str, linea_id: str, macchina_id: str, macchina: MacchinaModel):
    """Aggiorna una macchina esistente.
    Uso arrayFilters per puntare alla macchina giusta dentro l'array nested.
    """
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id)},
        {
            "$set": {
                "linee.$[l].macchine.$[m]": macchina.dict(),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        array_filters=[
            {"l.id": linea_id},
            {"m.id": macchina_id},
        ]
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reparto/linea/macchina non trovati")
    return macchina.dict()


@router.delete("/{reparto_id}/linee/{linea_id}/macchine/{macchina_id}")
async def delete_macchina(reparto_id: str, linea_id: str, macchina_id: str):
    """Rimuove una macchina da una linea."""
    result = await db.reparti.update_one(
        {"_id": ObjectId(reparto_id), "linee.id": linea_id},
        {
            "$pull": {"linee.$.macchine": {"id": macchina_id}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Macchina non trovata")
    return {"message": "Macchina eliminata"}

from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.pillar import PillarCreate, PillarUpdate, LinkKaizenToPillarPayload
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

router = APIRouter()


# ============================================================
# UTILS
# ============================================================
def serialize(doc: dict) -> dict:
    """Converti ObjectId in stringa per JSON."""
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


def empty_step():
    return {
        "completato": False,
        "note": "",
    }


# ============================================================
# LIST + DETAIL
# ============================================================
@router.get("/")
async def get_pillars(
    attivo: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
):
    """Lista pillar con eventuali filtri."""
    query = {}
    if attivo is not None:
        query["attivo"] = attivo
    if search:
        query["$or"] = [
            {"label": {"$regex": search, "$options": "i"}},
            {"sigla": {"$regex": search, "$options": "i"}},
            {"descrizione": {"$regex": search, "$options": "i"}},
        ]
    
    items = []
    cursor = db.pillars.find(query).sort([("sigla", 1)])
    async for d in cursor:
        items.append(serialize(d))
    return items


@router.get("/{pillar_id}")
async def get_pillar(pillar_id: str):
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")
    return serialize(pillar)


@router.get("/{pillar_id}/kaizens")
async def get_pillar_kaizens(pillar_id: str):
    """Restituisce tutti i Kaizen collegati a questo pillar."""
    kaizens = []
    cursor = db.kaizens.find({"pillar_id": pillar_id}).sort("created_at", -1)
    async for k in cursor:
        k["_id"] = str(k["_id"])
        kaizens.append(k)
    return kaizens


@router.get("/{pillar_id}/stats")
async def get_pillar_stats(pillar_id: str):
    """Statistiche sintetiche del pillar (per dashboard card)."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")
    
    # Conta kaizen per livello
    stats = {
        "totale_kaizen": 0,
        "quick": 0,
        "standard": 0,
        "major": 0,
        "aperti": 0,
        "chiusi": 0,
        "in_corso": 0,
    }
    
    cursor = db.kaizens.find({"pillar_id": pillar_id})
    async for k in cursor:
        stats["totale_kaizen"] += 1
        livello = k.get("livello") or "Quick"
        if "Quick" in livello:
            stats["quick"] += 1
        elif "Standard" in livello:
            stats["standard"] += 1
        elif "Major" in livello:
            stats["major"] += 1
        
        stato = k.get("stato", "Aperto")
        if stato == "Aperto":
            stats["aperti"] += 1
        elif stato in ["Chiuso", "Done"]:
            stats["chiusi"] += 1
        else:
            stats["in_corso"] += 1
    
    # Step completati
    steps_completed = 0
    for step_key in ["step1_kpi_definition", "step2_pareto_analysis", "step3_target_definition", "step4_implementation", "step5_close_the_loop"]:
        if pillar.get(step_key, {}).get("completato"):
            steps_completed += 1
    stats["steps_completed"] = steps_completed
    stats["steps_total"] = 5
    
    return stats


# ============================================================
# CREATE
# ============================================================
@router.post("/")
async def create_pillar(pillar: PillarCreate):
    # Verifica sigla univoca
    existing = await db.pillars.find_one({"sigla": pillar.sigla.upper()})
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Esiste già un pillar con sigla '{pillar.sigla.upper()}'"
        )
    
    now = datetime.now(timezone.utc)
    anno_corrente = pillar.anno or now.year
    
    doc = {
        "sigla": pillar.sigla.upper(),
        "label": pillar.label,
        "descrizione": pillar.descrizione or "",
        "icon": pillar.icon,
        "color": pillar.color,
        
        "leader": pillar.leader,
        "leader_email": pillar.leader_email,
        "members": pillar.members,
        
        "anno": anno_corrente,
        "note": pillar.note or "",
        
        # 5 Step inizialmente vuoti
        "step1_kpi_definition": empty_step() | {"kpis": []},
        "step2_pareto_analysis": empty_step() | {"losses": [], "allegati": []},
        "step3_target_definition": empty_step() | {"progetti": []},
        "step4_implementation": empty_step() | {"snapshot_at": None},
        "step5_close_the_loop": empty_step() | {"bridge_data": [], "lezioni_apprese": ""},
        
        "gantt_items": [],
        "maturity_grid": {},
        
        "created_at": now,
        "updated_at": now,
        "created_by": "Default User",
    }
    
    result = await db.pillars.insert_one(doc)
    created = await db.pillars.find_one({"_id": result.inserted_id})
    return serialize(created)


# ============================================================
# UPDATE
# ============================================================
@router.put("/{pillar_id}")
async def update_pillar(pillar_id: str, update: PillarUpdate):
    existing = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Pillar non trovato")
    
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    
    # Verifica sigla univoca se cambiata
    if "sigla" in update_data:
        update_data["sigla"] = update_data["sigla"].upper()
        if update_data["sigla"] != existing.get("sigla"):
            other = await db.pillars.find_one({
                "sigla": update_data["sigla"],
                "_id": {"$ne": ObjectId(pillar_id)}
            })
            if other:
                raise HTTPException(
                    status_code=400,
                    detail=f"Esiste già un pillar con sigla '{update_data['sigla']}'"
                )
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": update_data}
    )
    
    updated = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    return serialize(updated)


# ============================================================
# LINK / UNLINK KAIZEN
# ============================================================
@router.post("/{pillar_id}/link-kaizen")
async def link_kaizen(pillar_id: str, payload: LinkKaizenToPillarPayload):
    """Collega un Kaizen a questo Pillar.
    Un Kaizen può essere collegato a UN SOLO pillar alla volta.
    Se ne aveva un altro, viene riassegnato.
    """
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")
    
    kaizen = await db.kaizens.find_one({"_id": ObjectId(payload.kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    # Aggiorna il kaizen con pillar_id
    feed_entry = {
        "utente": "Default User",
        "azione": f"🏛️ Collegato al Pillar {pillar.get('sigla')} ({pillar.get('label')})",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.kaizens.update_one(
        {"_id": ObjectId(payload.kaizen_id)},
        {
            "$set": {
                "pillar_id": pillar_id,
                "pillar_sigla": pillar.get("sigla"),
                "pillar_label": pillar.get("label"),
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"feed": feed_entry},
        }
    )
    
    return {
        "message": f"Kaizen collegato al Pillar {pillar.get('sigla')}",
        "pillar_id": pillar_id,
        "pillar_sigla": pillar.get("sigla"),
    }


@router.delete("/{pillar_id}/unlink-kaizen/{kaizen_id}")
async def unlink_kaizen(pillar_id: str, kaizen_id: str):
    """Scollega un Kaizen dal Pillar."""
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    pillar_sigla = pillar.get("sigla", "?") if pillar else "?"
    
    feed_entry = {
        "utente": "Default User",
        "azione": f"🔓 Scollegato dal Pillar {pillar_sigla}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {
            "$set": {
                "pillar_id": None,
                "pillar_sigla": None,
                "pillar_label": None,
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"feed": feed_entry},
        }
    )
    
    return {"message": f"Kaizen scollegato dal Pillar {pillar_sigla}"}


# ============================================================
# DELETE
# ============================================================
@router.delete("/{pillar_id}")
async def delete_pillar(pillar_id: str):
    """Soft delete del pillar (lo disattiva).
    I Kaizen collegati rimangono ma perdono il riferimento."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")
    
    # Conta kaizen collegati
    kaizens_count = await db.kaizens.count_documents({"pillar_id": pillar_id})
    
    # Scollega tutti i kaizen
    if kaizens_count > 0:
        await db.kaizens.update_many(
            {"pillar_id": pillar_id},
            {"$set": {
                "pillar_id": None,
                "pillar_sigla": None,
                "pillar_label": None,
            }}
        )
    
    await db.pillars.delete_one({"_id": ObjectId(pillar_id)})
    return {
        "message": f"Pillar eliminato",
        "kaizens_scollegati": kaizens_count
    }

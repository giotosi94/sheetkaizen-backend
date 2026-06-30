from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.pillar import PillarCreate, PillarUpdate, LinkKaizenToPillarPayload
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional, Dict, Any

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

    stats = {
        # Kaizen
        "totale_kaizen": 0,
        "quick": 0,
        "standard": 0,
        "major": 0,
        "kaizen_aperti": 0,
        "kaizen_in_corso": 0,
        "kaizen_chiusi": 0,
        # Compat retro (vecchie chiavi)
        "aperti": 0,
        "in_corso": 0,
        "chiusi": 0,
        # Action Plan
        "totale_ap": 0,
        "ap_da_fare": 0,
        "ap_in_corso": 0,
        "ap_done": 0,
        # Step KPI
        "steps_completed": 0,
        "steps_total": 5,
    }

    # KAIZEN
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
            stats["kaizen_aperti"] += 1
            stats["aperti"] += 1
        elif stato in ["Chiuso", "Done"]:
            stats["kaizen_chiusi"] += 1
            stats["chiusi"] += 1
        else:
            stats["kaizen_in_corso"] += 1
            stats["in_corso"] += 1

    # ACTION PLAN
    cursor = db.action_plans.find({
        "pillar_id": pillar_id,
        "is_active": {"$ne": False},
    })
    async for ap in cursor:
        # Esclude AP cancellati
        if ap.get("is_cancelled"):
            continue
        stats["totale_ap"] += 1
        stato = (ap.get("stato") or "").lower()
        if stato in ["done", "completato", "chiuso", "completed", "fatto"]:
            stats["ap_done"] += 1
        elif stato in ["in corso", "in_corso", "in_progress", "wip", "doing"]:
            stats["ap_in_corso"] += 1
        else:
            # Tutto il resto (Da Valutare, To Do, Aperto, ecc.)
            stats["ap_da_fare"] += 1

    # STEP KPI MANAGEMENT (dalle analyses attive, oppure legacy se non ci sono)
    analyses = pillar.get("analyses", [])
    if analyses:
        # Prendi la prima analisi attiva
        active = next((a for a in analyses if a.get("status") == "active"), None)
        if active:
            for step_key in [
                "step1_kpi_definition",
                "step2_pareto_analysis",
                "step3_target_definition",
                "step4_implementation",
                "step5_close_the_loop",
            ]:
                if active.get(step_key, {}).get("completato"):
                    stats["steps_completed"] += 1
    else:
        # Legacy: leggi direttamente dal pillar
        for step_key in [
            "step1_kpi_definition",
            "step2_pareto_analysis",
            "step3_target_definition",
            "step4_implementation",
            "step5_close_the_loop",
        ]:
            if pillar.get(step_key, {}).get("completato"):
                stats["steps_completed"] += 1

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
# ============================================================
# 🆕 ANALYSES — Gestione analisi multiple del 5 Step KPI
# ============================================================

from uuid import uuid4


def _empty_analysis(label: str = ""):
    """Crea una struttura analisi vuota."""
    return {
        "id": str(uuid4()),
        "label": label or f"Analisi {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "status": "active",  # active | archived
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archived_at": None,
        "step1_kpi_definition": {"completato": False, "note": ""},
        "step2_pareto_analysis": {"completato": False, "note": ""},
        "step3_target_definition": {"completato": False, "note": ""},
        "step4_implementation": {"completato": False, "note": ""},
        "step5_close_the_loop": {"completato": False, "note": ""},
    }


@router.get("/{pillar_id}/analyses")
async def list_analyses(pillar_id: str):
    """Restituisce la lista delle analisi del Pillar (active + archived)."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    analyses = pillar.get("analyses", [])

    # Backfill: se ci sono step1-5 legacy ma niente analyses, creane una default
    if not analyses and any(pillar.get(f"step{i}_{n}") for i, n in [
        (1, "kpi_definition"), (2, "pareto_analysis"),
        (3, "target_definition"), (4, "implementation"), (5, "close_the_loop")
    ]):
        legacy = {
            "id": str(uuid4()),
            "label": "Analisi principale",
            "status": "active",
            "created_at": (pillar.get("created_at") or datetime.now(timezone.utc)).isoformat() if isinstance(pillar.get("created_at"), datetime) else datetime.now(timezone.utc).isoformat(),
            "archived_at": None,
            "step1_kpi_definition": pillar.get("step1_kpi_definition") or {"completato": False, "note": ""},
            "step2_pareto_analysis": pillar.get("step2_pareto_analysis") or {"completato": False, "note": ""},
            "step3_target_definition": pillar.get("step3_target_definition") or {"completato": False, "note": ""},
            "step4_implementation": pillar.get("step4_implementation") or {"completato": False, "note": ""},
            "step5_close_the_loop": pillar.get("step5_close_the_loop") or {"completato": False, "note": ""},
        }
        analyses = [legacy]
        await db.pillars.update_one(
            {"_id": ObjectId(pillar_id)},
            {"$set": {"analyses": analyses}}
        )

    return analyses


@router.post("/{pillar_id}/analyses")
async def create_analysis(pillar_id: str, payload: Dict[str, Any]):
    """Crea una nuova analisi VUOTA per il Pillar."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    label = (payload or {}).get("label", "").strip() or f"Analisi {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    new_analysis = _empty_analysis(label)

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {
            "$push": {"analyses": new_analysis},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )

    return new_analysis


@router.put("/{pillar_id}/analyses/{analysis_id}")
async def update_analysis(pillar_id: str, analysis_id: str, payload: Dict[str, Any]):
    """Aggiorna i campi di una specifica analisi (label, step1-5, status, ecc.)."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    analyses = pillar.get("analyses", [])
    found = False
    for i, a in enumerate(analyses):
        if a.get("id") == analysis_id:
            # Aggiorno solo i campi presenti nel payload
            for key, value in (payload or {}).items():
                analyses[i][key] = value
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Analisi non trovata")

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": {"analyses": analyses, "updated_at": datetime.now(timezone.utc)}}
    )
    return analyses[i]


@router.post("/{pillar_id}/analyses/{analysis_id}/archive")
async def archive_analysis(pillar_id: str, analysis_id: str):
    """Archivia una analisi (status = archived)."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    analyses = pillar.get("analyses", [])
    found = False
    for i, a in enumerate(analyses):
        if a.get("id") == analysis_id:
            analyses[i]["status"] = "archived"
            analyses[i]["archived_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Analisi non trovata")

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": {"analyses": analyses, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Analisi archiviata", "analysis": analyses[i]}


@router.post("/{pillar_id}/analyses/{analysis_id}/restore")
async def restore_analysis(pillar_id: str, analysis_id: str):
    """Riporta una analisi archiviata in stato active."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    analyses = pillar.get("analyses", [])
    found = False
    for i, a in enumerate(analyses):
        if a.get("id") == analysis_id:
            analyses[i]["status"] = "active"
            analyses[i]["archived_at"] = None
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Analisi non trovata")

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": {"analyses": analyses, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Analisi ripristinata", "analysis": analyses[i]}


@router.delete("/{pillar_id}/analyses/{analysis_id}")
async def delete_analysis(pillar_id: str, analysis_id: str):
    """Elimina definitivamente una analisi (use con cautela!)."""
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(status_code=404, detail="Pillar non trovato")

    analyses = [a for a in pillar.get("analyses", []) if a.get("id") != analysis_id]

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": {"analyses": analyses, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Analisi eliminata"}

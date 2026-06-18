from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.action_plan import ActionPlanCreate, ActionPlanUpdate
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

router = APIRouter()


async def get_next_numero():
    """Genera codice progressivo tipo AP-0001, AP-0042."""
    last = await db.action_plans.find_one(sort=[("created_at", -1)])
    if last and "numero" in last:
        try:
            num = int(last["numero"].split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"AP-{num:04d}"


def calcola_stato_scadenza(data_scadenza, stato_attuale):
    """Calcola se l'action plan è in ritardo / in scadenza."""
    if stato_attuale in ["Completato", "Annullato"]:
        return stato_attuale
    if not data_scadenza:
        return stato_attuale
    try:
        if isinstance(data_scadenza, str):
            scadenza = datetime.fromisoformat(data_scadenza.replace("Z", "+00:00"))
        else:
            scadenza = data_scadenza
        if scadenza.tzinfo is None:
            scadenza = scadenza.replace(tzinfo=timezone.utc)
        oggi = datetime.now(timezone.utc)
        giorni = (scadenza - oggi).days
        if giorni < 0:
            return "In Ritardo"
        elif giorni <= 3:
            return "In Scadenza"
    except Exception:
        pass
    return stato_attuale


# ============================================================
# LIST + FILTRI
# ============================================================
@router.get("/")
async def get_action_plans(
    stato: Optional[str] = Query(None),
    responsabile: Optional[str] = Query(None),
    reparto: Optional[str] = Query(None),
    priorita: Optional[str] = Query(None),
    kaizen_id: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    query = {"is_active": {"$ne": False}}
    if stato:
        query["stato"] = stato
    if responsabile:
        query["responsabile"] = responsabile
    if reparto:
        query["reparto"] = reparto
    if priorita:
        query["priorita"] = priorita
    if kaizen_id:
        query["kaizen_id"] = kaizen_id
    if categoria:
        query["categoria"] = categoria
    if search:
        query["$or"] = [
            {"titolo": {"$regex": search, "$options": "i"}},
            {"numero": {"$regex": search, "$options": "i"}},
            {"descrizione": {"$regex": search, "$options": "i"}},
        ]

    plans = []
    cursor = db.action_plans.find(query).sort("created_at", -1)
    async for p in cursor:
        p["_id"] = str(p["_id"])
        # Aggiorna stato dinamico (In Ritardo / In Scadenza)
        p["stato_visuale"] = calcola_stato_scadenza(
            p.get("data_scadenza"), p.get("stato", "Aperto")
        )
        plans.append(p)
    return plans


@router.get("/stats/summary")
async def get_stats():
    """Statistiche aggregate per dashboard action plan."""
    pipeline = [
        {"$match": {"is_active": {"$ne": False}}},
        {"$group": {"_id": "$stato", "count": {"$sum": 1}}},
    ]
    results = {}
    async for item in db.action_plans.aggregate(pipeline):
        results[item["_id"]] = item["count"]

    # Conteggio in ritardo
    in_ritardo = 0
    oggi = datetime.now(timezone.utc)
    cursor = db.action_plans.find({
        "is_active": {"$ne": False},
        "stato": {"$nin": ["Completato", "Annullato"]},
        "data_scadenza": {"$lt": oggi},
    })
    async for _ in cursor:
        in_ritardo += 1
    results["in_ritardo"] = in_ritardo
    return results


@router.get("/{plan_id}")
async def get_action_plan(plan_id: str):
    plan = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    plan["_id"] = str(plan["_id"])
    plan["stato_visuale"] = calcola_stato_scadenza(
        plan.get("data_scadenza"), plan.get("stato", "Aperto")
    )
    return plan


# ============================================================
# CREATE
# ============================================================
@router.post("/")
async def create_action_plan(plan: ActionPlanCreate):
    numero = await get_next_numero()

    doc = {
        "numero": numero,
        "titolo": plan.titolo,
        "descrizione": plan.descrizione,
        "categoria": plan.categoria,  # Sicurezza, Qualità, Manutenzione, 5S, …
        "priorita": plan.priorita or "Media",  # Bassa | Media | Alta | Critica
        "stato": "Aperto",  # Aperto | In Corso | In Verifica | Completato | Annullato
        "responsabile": plan.responsabile,
        "responsabile_email": plan.responsabile_email,
        "reparto": plan.reparto,
        "linea": plan.linea,
        "macchina": plan.macchina,
        "kaizen_id": plan.kaizen_id,  # link opzionale al Kaizen di origine
        "data_emissione": datetime.now(timezone.utc),
        "data_scadenza": plan.data_scadenza,
        "data_completamento": None,
        "avanzamento": 0,  # 0-100
        "allegati": [],
        "note": [],
        "creatore_nome": "Default User",
        "creatore_id": "default",
        "feed": [{
            "utente": "Default User",
            "azione": "Action Plan creato",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.action_plans.insert_one(doc)

    # Se collegato a un Kaizen, aggiorna il riferimento
    if plan.kaizen_id:
        try:
            await db.kaizens.update_one(
                {"_id": ObjectId(plan.kaizen_id)},
                {"$push": {"action_plans": str(result.inserted_id)}}
            )
        except Exception:
            pass

    return {
        "id": str(result.inserted_id),
        "numero": numero,
        "message": f"Action Plan {numero} creato",
    }


# ============================================================
# UPDATE
# ============================================================
@router.put("/{plan_id}")
async def update_action_plan(plan_id: str, update: ActionPlanUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    # Se stato diventa Completato, salva data
    if update_data.get("stato") == "Completato":
        update_data["data_completamento"] = datetime.now(timezone.utc)
        update_data["avanzamento"] = 100

    feed_entry = {
        "utente": "Default User",
        "azione": f"Action Plan aggiornato ({update_data.get('stato', 'modifica')})",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": update_data, "$push": {"feed": feed_entry}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Action Plan aggiornato"}


# ============================================================
# NOTE / AVANZAMENTO RAPIDO
# ============================================================
@router.post("/{plan_id}/nota")
async def aggiungi_nota(plan_id: str, payload: dict):
    """Aggiunge una nota di avanzamento."""
    testo = payload.get("testo", "").strip()
    if not testo:
        raise HTTPException(status_code=400, detail="Testo nota mancante")

    nota = {
        "testo": testo,
        "utente": payload.get("utente", "Default User"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    feed_entry = {
        "utente": payload.get("utente", "Default User"),
        "azione": "Nota aggiunta",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$push": {"note": nota, "feed": feed_entry},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Nota aggiunta"}


@router.patch("/{plan_id}/avanzamento")
async def aggiorna_avanzamento(plan_id: str, payload: dict):
    """Aggiorna % avanzamento (0-100)."""
    avanzamento = payload.get("avanzamento")
    if avanzamento is None or not (0 <= int(avanzamento) <= 100):
        raise HTTPException(status_code=400, detail="Avanzamento deve essere 0-100")

    update_data = {
        "avanzamento": int(avanzamento),
        "updated_at": datetime.now(timezone.utc),
    }
    if int(avanzamento) == 100:
        update_data["stato"] = "Completato"
        update_data["data_completamento"] = datetime.now(timezone.utc)

    feed_entry = {
        "utente": "Default User",
        "azione": f"Avanzamento aggiornato a {avanzamento}%",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": update_data, "$push": {"feed": feed_entry}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Avanzamento aggiornato"}


# ============================================================
# DELETE (soft)
# ============================================================
@router.delete("/{plan_id}")
async def delete_action_plan(plan_id: str):
    """Soft delete: nasconde l'action plan."""
    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Action Plan disattivato"}

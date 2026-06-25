from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.action_plan import (
    ActionPlanCreate, ActionPlanUpdate, ChecklistItem, Commento, Allegato, LinkEntita
)
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
import re
import uuid


router = APIRouter()


# ============================================================
# UTILS
# ============================================================
async def get_next_numero():
    """Genera codice progressivo tipo AP-0001."""
    last = await db.action_plans.find_one(sort=[("created_at", -1)])
    if last and "numero" in last:
        try:
            num = int(last["numero"].split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"AP-{num:04d}"


def extract_mentions_and_tags(text: str):
    """Estrae @mentions e #tags da un testo."""
    if not text:
        return [], []
    mentions = re.findall(r"@([a-zA-Z0-9._-]+)", text)
    tags = re.findall(r"#([a-zA-Z0-9_-]+)", text)
    return list(set(mentions)), list(set(tags))


async def is_ap_locked(plan: dict) -> bool:
    """Restituisce True se lo stato attuale dell'AP è 'terminal' (lock)."""
    stato_label = plan.get("stato")
    if not stato_label:
        return False
    config = await db.configurazioni.find_one({
        "tipo": "stato_ap",
        "label": stato_label,
    })
    if not config:
        return False
    return bool(config.get("is_terminal", False))


async def is_stato_terminal(stato_label: str) -> bool:
    """Restituisce True se uno stato (per label) è marcato come terminal."""
    if not stato_label:
        return False
    config = await db.configurazioni.find_one({
        "tipo": "stato_ap",
        "label": stato_label,
    })
    if not config:
        return False
    return bool(config.get("is_terminal", False))


async def resolve_pillar_from_parent(parent_type: str, parent_id: str) -> Optional[str]:
    """Risolve il pillar_id automaticamente in base al parent."""
    if not parent_type or not parent_id:
        return None
    
    if parent_type == "pillar":
        return parent_id
    
    if parent_type == "kaizen":
        try:
            kaizen = await db.kaizens.find_one({"_id": ObjectId(parent_id)})
            if kaizen:
                return kaizen.get("pillar_id")
        except Exception:
            pass
    
    return None


def calcola_health_score(plan: dict) -> int:
    score = 100
    
    if plan.get("stato") in ["Done", "Cancelled"] or plan.get("is_cancelled"):
        return 100
    
    scadenza = plan.get("data_scadenza")
    if scadenza:
        try:
            if isinstance(scadenza, str):
                scadenza = datetime.fromisoformat(scadenza.replace("Z", "+00:00"))
            if scadenza.tzinfo is None:
                scadenza = scadenza.replace(tzinfo=timezone.utc)
            if scadenza < datetime.now(timezone.utc):
                score -= 30
        except Exception:
            pass
    else:
        score -= 10
    
    if not plan.get("responsabile"):
        score -= 20
    
    if plan.get("is_blocked"):
        score -= 30
    
    updated = plan.get("updated_at")
    if updated:
        try:
            if isinstance(updated, str):
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            days_since_update = (datetime.now(timezone.utc) - updated).days
            if days_since_update > 14:
                score -= 10
        except Exception:
            pass
    
    if plan.get("avanzamento", 0) >= 75:
        score += 10
    
    return max(0, min(100, score))


def calcola_stato_visuale(plan: dict) -> str:
    """Calcola stato visuale con flag dinamici (In Ritardo / In Scadenza / Annullato)."""
    # 🆕 Annullato ha priorità su tutto
    if plan.get("is_cancelled"):
        return "Annullato"
    
    stato = plan.get("stato", "Backlog")
    if stato in ["Done", "Cancelled"]:
        return stato
    
    scadenza = plan.get("data_scadenza")
    if not scadenza:
        return stato
    
    try:
        if isinstance(scadenza, str):
            scadenza = datetime.fromisoformat(scadenza.replace("Z", "+00:00"))
        if scadenza.tzinfo is None:
            scadenza = scadenza.replace(tzinfo=timezone.utc)
        giorni = (scadenza - datetime.now(timezone.utc)).days
        if giorni < 0:
            return "In Ritardo"
        elif giorni <= 3:
            return "In Scadenza"
    except Exception:
        pass
    return stato


def enrich_plan(plan: dict) -> dict:
    """Aggiunge campi calcolati al plan prima di restituirlo."""
    plan["_id"] = str(plan["_id"])
    plan["stato_visuale"] = calcola_stato_visuale(plan)
    plan["health_score"] = calcola_health_score(plan)
    if "parent_id" in plan and plan["parent_id"]:
        plan["parent_id"] = str(plan["parent_id"])
    return plan


# ============================================================
# LIST con filtri ricchi
# ============================================================
@router.get("/")
async def get_action_plans(
    # Filtri classificazione
    stato: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None),
    priorita: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    categoria_perdita: Optional[str] = Query(None),
    quinta_m: Optional[str] = Query(None),
    
    # Filtri assegnazione
    responsabile: Optional[str] = Query(None),
    
    # Filtri struttura aziendale
    reparto: Optional[str] = Query(None),
    linea: Optional[str] = Query(None),
    macchina: Optional[str] = Query(None),
    
    # Filtri parent / contesto
    parent_type: Optional[str] = Query(None),
    pillar_id: Optional[str] = Query(None),
    dashboard_id: Optional[str] = Query(None),
    gant_step_id: Optional[str] = Query(None),  # 🆕 filtro per step del Gant
    
    # 🆕 Filtro cancellati
    include_cancelled: Optional[bool] = Query(False),
    only_cancelled: Optional[bool] = Query(False),
    
    # Altri
    tag: Optional[str] = Query(None),
    parent_id: Optional[str] = Query(None),
    linked_to_type: Optional[str] = Query(None),
    linked_to_id: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
):
    """Lista action plans con filtri trasversali."""
    query = {"is_active": {"$ne": False}}
    
    # 🆕 Gestione cancellati
    if only_cancelled:
        query["is_cancelled"] = True
    elif not include_cancelled:
        query["is_cancelled"] = {"$ne": True}
    
    # Classificazione
    if stato:
        query["stato"] = stato
    if tipo:
        query["tipo"] = tipo
    if priorita:
        query["priorita"] = priorita
    if categoria:
        query["categoria"] = categoria
    if categoria_perdita:
        query["categoria_perdita"] = categoria_perdita
    if quinta_m:
        query["quinta_m"] = quinta_m
    
    # Assegnazione
    if responsabile:
        query["responsabile"] = responsabile
    
    # Struttura aziendale
    if reparto:
        query["reparto"] = reparto
    if linea:
        query["linea"] = linea
    if macchina:
        query["macchina"] = macchina
    
    # Contesto / parent
    if parent_type:
        query["parent_type"] = parent_type
    if pillar_id:
        query["pillar_id"] = pillar_id
    if dashboard_id:
        query["dashboard_id"] = dashboard_id
    if gant_step_id:
        # Filtro speciale: 'none' = standalone (AP senza step), altrimenti id step preciso
        if gant_step_id == 'none':
            query["gant_step_id"] = {"$in": [None, ""]}
        else:
            query["gant_step_id"] = gant_step_id
    
    if tag:
        query["tags"] = tag
    if parent_id:
        query["parent_id"] = parent_id
    
    if linked_to_type and linked_to_id:
        query["links"] = {
            "$elemMatch": {"entity_type": linked_to_type, "entity_id": linked_to_id}
        }
    
    if overdue:
        query["data_scadenza"] = {"$lt": datetime.now(timezone.utc)}
        query["stato"] = {"$nin": ["Done", "Cancelled"]}
    
    if search:
        query["$or"] = [
            {"titolo": {"$regex": search, "$options": "i"}},
            {"numero": {"$regex": search, "$options": "i"}},
            {"descrizione": {"$regex": search, "$options": "i"}},
            {"tags": {"$regex": search, "$options": "i"}},
        ]
    
    plans = []
    cursor = db.action_plans.find(query).sort("created_at", -1)
    async for p in cursor:
        plans.append(enrich_plan(p))
    return plans


# ============================================================
# STATS — dashboard widget data
# ============================================================
@router.get("/stats/summary")
async def get_stats(
    reparto: Optional[str] = Query(None),
    responsabile: Optional[str] = Query(None),
):
    """Statistiche aggregate per dashboard / widget."""
    match = {"is_active": {"$ne": False}, "is_cancelled": {"$ne": True}}
    if reparto:
        match["reparto"] = reparto
    if responsabile:
        match["responsabile"] = responsabile
    
    pipeline = [
        {"$match": match},
        {"$facet": {
            "per_stato": [{"$group": {"_id": "$stato", "count": {"$sum": 1}}}],
            "per_priorita": [{"$group": {"_id": "$priorita", "count": {"$sum": 1}}}],
            "per_tipo": [{"$group": {"_id": "$tipo", "count": {"$sum": 1}}}],
            "totale": [{"$count": "count"}],
        }}
    ]
    
    result = await db.action_plans.aggregate(pipeline).to_list(1)
    data = result[0] if result else {}
    
    per_stato = {item["_id"]: item["count"] for item in data.get("per_stato", []) if item["_id"]}
    per_priorita = {item["_id"]: item["count"] for item in data.get("per_priorita", []) if item["_id"]}
    per_tipo = {item["_id"]: item["count"] for item in data.get("per_tipo", []) if item["_id"]}
    totale = data.get("totale", [{}])[0].get("count", 0) if data.get("totale") else 0
    
    overdue_count = await db.action_plans.count_documents({
        **match,
        "stato": {"$nin": ["Done", "Cancelled"]},
        "data_scadenza": {"$lt": datetime.now(timezone.utc)},
    })
    
    # 🆕 Conteggio annullati
    cancelled_count = await db.action_plans.count_documents({
        "is_active": {"$ne": False},
        "is_cancelled": True,
        **({"reparto": reparto} if reparto else {}),
        **({"responsabile": responsabile} if responsabile else {}),
    })
    
    return {
        "totale": totale,
        "per_stato": per_stato,
        "per_priorita": per_priorita,
        "per_tipo": per_tipo,
        "overdue": overdue_count,
        "cancelled": cancelled_count,  # 🆕
    }


# ============================================================
# GET singolo (con figli e commenti)
# ============================================================
@router.get("/{plan_id}")
async def get_action_plan(plan_id: str, include_children: bool = False):
    plan = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    enriched = enrich_plan(plan)
    
    if include_children:
        children = []
        async for c in db.action_plans.find({"parent_id": plan_id, "is_active": {"$ne": False}}):
            children.append(enrich_plan(c))
        enriched["children"] = children
    
    return enriched


# ============================================================
# CREATE
# ============================================================
@router.post("/")
async def create_action_plan(plan: ActionPlanCreate):
    numero = await get_next_numero()
    
    auto_mentions, auto_tags = extract_mentions_and_tags(plan.descrizione or "")
    mentions = list(set(plan.mentions + auto_mentions))
    tags = list(set(plan.tags + auto_tags))
    
    checklist = []
    for item in plan.checklist:
        item_dict = item.dict() if hasattr(item, 'dict') else item
        item_dict["id"] = str(uuid.uuid4())
        checklist.append(item_dict)
    
    derived_parent_type = plan.parent_type or "standalone"
    derived_parent_id = plan.parent_id
    if plan.kaizen_id and not plan.parent_id:
        derived_parent_type = "kaizen"
        derived_parent_id = plan.kaizen_id
    
    auto_pillar_id = plan.pillar_id
    if not auto_pillar_id and derived_parent_type and derived_parent_id:
        auto_pillar_id = await resolve_pillar_from_parent(derived_parent_type, derived_parent_id)
    
    doc = {
        "numero": numero,
        "titolo": plan.titolo,
        "descrizione": plan.descrizione or "",
        
        "tipo": plan.tipo or None,
        "priorita": plan.priorita or None,
        "stato": plan.stato or None,
        "categoria_perdita": plan.categoria_perdita or plan.tipo_perdita,
        "quinta_m": plan.quinta_m,
        
        "parent_type": derived_parent_type,
        "parent_id": derived_parent_id,
        "parent_label": plan.parent_label,
        "pillar_id": auto_pillar_id,
        "dashboard_id": plan.dashboard_id,
        
        # Legacy
        "categoria": plan.categoria,
        "tipo_perdita": plan.tipo_perdita,
        "kaizen_id": plan.kaizen_id or (derived_parent_id if derived_parent_type == "kaizen" else None),
        
        "tags": tags,
        "mentions": mentions,
        
        "responsabile": plan.responsabile,
        "responsabile_email": plan.responsabile_email,
        "reporter": plan.reporter or "Default User",
        "watchers": plan.watchers,
        
        "reparto": plan.reparto,
        "linea": plan.linea,
        "macchina": plan.macchina,
        
        "data_emissione": datetime.now(timezone.utc),
        "data_inizio": plan.data_inizio,
        "data_scadenza": plan.data_scadenza,
        "data_completamento": None,
        
        "avanzamento": 0,
        "checklist": checklist,
        
        "children_ids": [],
        
        "links": [link.dict() for link in plan.links],
        
        "commenti": [],
        "allegati": [],
        "feed": [{
            "id": str(uuid.uuid4()),
            "utente": "Default User",
            "azione": "Action Plan creato",
            "tipo_evento": "create",
            "timestamp": datetime.now(timezone.utc),
        }],
        
        "is_blocked": False,
        "blocking_reason": None,
        
        # 🆕 Stato cancellazione (default attivo)
        "is_cancelled": False,
        "cancelled_reason": None,
        "cancelled_at": None,
        "cancelled_by": None,
        
        # 🆕 Gantt fields
        "dependencies": plan.dependencies or [],
        "gantt_progress": plan.gantt_progress or 0,
        "gantt_milestone": plan.gantt_milestone or False,
        "gant_step_id": plan.gant_step_id,  # 🆕 step Gant macro (None = standalone)
        
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    
    result = await db.action_plans.insert_one(doc)
    
    if plan.parent_id and derived_parent_type == "standalone":
        try:
            await db.action_plans.update_one(
                {"_id": ObjectId(plan.parent_id)},
                {"$push": {"children_ids": str(result.inserted_id)}}
            )
        except Exception:
            pass
    
    created = await db.action_plans.find_one({"_id": result.inserted_id})
    return enrich_plan(created)


# ============================================================
# UPDATE
# ============================================================
@router.put("/{plan_id}")
async def update_action_plan(plan_id: str, update: ActionPlanUpdate):
    existing = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    
    # 🔒 LOCK: se AP è in stato terminale, blocca tutte le modifiche
    # tranne il cambio di stato (necessario per la riapertura)
    if await is_ap_locked(existing):
        allowed_keys = {"stato"}
        attempted_keys = set(update_data.keys())
        forbidden = attempted_keys - allowed_keys
        if forbidden:
            raise HTTPException(
                status_code=403,
                detail=f"Action Plan chiuso (stato terminale). Riaprilo prima di modificarlo.",
            )
    
    if "parent_type" in update_data or "parent_id" in update_data:
        new_parent_type = update_data.get("parent_type", existing.get("parent_type"))
        new_parent_id = update_data.get("parent_id", existing.get("parent_id"))
        if new_parent_type and new_parent_id and "pillar_id" not in update_data:
            resolved = await resolve_pillar_from_parent(new_parent_type, new_parent_id)
            if resolved:
                update_data["pillar_id"] = resolved
    
    if "tipo_perdita" in update_data and "categoria_perdita" not in update_data:
        update_data["categoria_perdita"] = update_data["tipo_perdita"]
    
    if "descrizione" in update_data:
        auto_mentions, auto_tags = extract_mentions_and_tags(update_data["descrizione"])
        existing_mentions = update_data.get("mentions") or existing.get("mentions", [])
        existing_tags = update_data.get("tags") or existing.get("tags", [])
        update_data["mentions"] = list(set(existing_mentions + auto_mentions))
        update_data["tags"] = list(set(existing_tags + auto_tags))
    
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    if update_data.get("stato") == "Done":
        update_data["data_completamento"] = datetime.now(timezone.utc)
        update_data["avanzamento"] = 100
    
    # 🔓 Detection riapertura: se sto cambiando da terminale -> non terminale
    was_terminal = await is_stato_terminal(existing.get("stato"))
    new_stato = update_data.get("stato")
    is_riapertura = (
        was_terminal
        and new_stato is not None
        and not await is_stato_terminal(new_stato)
    )
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": "Default User",
        "azione": (
            f"🔓 Riaperto: stato {existing.get('stato')} → {new_stato}"
            if is_riapertura
            else "AP aggiornato"
        ),
        "tipo_evento": "reopen" if is_riapertura else "update",
        "changes": {k: v for k, v in update_data.items() if k != "updated_at"},
        "timestamp": datetime.now(timezone.utc),
    }
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": update_data, "$push": {"feed": feed_entry}},
    )
    
    updated = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    return enrich_plan(updated)


# ============================================================
# COMMENTI
# ============================================================
@router.post("/{plan_id}/commenti")
async def add_commento(plan_id: str, payload: dict):
    testo = payload.get("testo", "").strip()
    autore = payload.get("autore", "Default User")
    if not testo:
        raise HTTPException(status_code=400, detail="Testo commento mancante")
    
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if ap and await is_ap_locked(ap):
        raise HTTPException(status_code=403, detail="Action Plan chiuso. Riaprilo per aggiungere commenti.")
    
    mentions, tags = extract_mentions_and_tags(testo)
    
    commento = {
        "id": str(uuid.uuid4()),
        "autore": autore,
        "autore_avatar": payload.get("autore_avatar"),
        "testo": testo,
        "mentions": mentions,
        "timestamp": datetime.now(timezone.utc),
        "edited_at": None,
        "reactions": [],
    }
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": autore,
        "azione": "Commento aggiunto",
        "tipo_evento": "comment",
        "timestamp": datetime.now(timezone.utc),
    }
    
    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$push": {"commenti": commento, "feed": feed_entry},
            "$addToSet": {"mentions": {"$each": mentions}, "tags": {"$each": tags}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="AP non trovato")
    return {"message": "Commento aggiunto", "commento": commento}


@router.delete("/{plan_id}/commenti/{commento_id}")
async def delete_commento(plan_id: str, commento_id: str):
    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$pull": {"commenti": {"id": commento_id}}},
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Commento non trovato")
    return {"message": "Commento eliminato"}


# ============================================================
# CHECKLIST
# ============================================================
@router.post("/{plan_id}/checklist")
async def add_checklist_item(plan_id: str, payload: dict):
    testo = payload.get("testo", "").strip()
    if not testo:
        raise HTTPException(status_code=400, detail="Testo mancante")
    
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if ap and await is_ap_locked(ap):
        raise HTTPException(status_code=403, detail="Action Plan chiuso. Riaprilo per modificare la checklist.")
    
    item = {
        "id": str(uuid.uuid4()),
        "testo": testo,
        "completato": False,
        "completato_da": None,
        "completato_at": None,
    }
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$push": {"checklist": item}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return item


@router.patch("/{plan_id}/checklist/{item_id}")
async def toggle_checklist_item(plan_id: str, item_id: str, payload: dict):
    completato = payload.get("completato", False)
    utente = payload.get("utente", "Default User")
    
    update_fields = {
        "checklist.$.completato": completato,
        "checklist.$.completato_da": utente if completato else None,
        "checklist.$.completato_at": datetime.now(timezone.utc) if completato else None,
    }
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id), "checklist.id": item_id},
        {"$set": update_fields, "$currentDate": {"updated_at": True}},
    )
    return {"message": "Item aggiornato"}


@router.delete("/{plan_id}/checklist/{item_id}")
async def delete_checklist_item(plan_id: str, item_id: str):
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$pull": {"checklist": {"id": item_id}}},
    )
    return {"message": "Item eliminato"}


# ============================================================
# LINKS (polymorphic linking)
# ============================================================
@router.post("/{plan_id}/links")
async def add_link(plan_id: str, link: LinkEntita):
    link_dict = link.dict()
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$push": {"links": link_dict}, "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    return link_dict


@router.delete("/{plan_id}/links")
async def remove_link(plan_id: str, entity_type: str, entity_id: str):
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$pull": {"links": {"entity_type": entity_type, "entity_id": entity_id}}},
    )
    return {"message": "Link rimosso"}


# ============================================================
# CAMBIO STATO (Kanban drag&drop)
# ============================================================
@router.patch("/{plan_id}/stato")
async def cambia_stato(plan_id: str, payload: dict):
    nuovo_stato = payload.get("stato")
    if not nuovo_stato:
        raise HTTPException(status_code=400, detail="Stato mancante")
    
    existing = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    update_data = {"stato": nuovo_stato, "updated_at": datetime.now(timezone.utc)}
    if nuovo_stato == "Done":
        update_data["data_completamento"] = datetime.now(timezone.utc)
        update_data["avanzamento"] = 100
    elif nuovo_stato == "In Corso" and not existing.get("data_inizio"):
        update_data["data_inizio"] = datetime.now(timezone.utc)
    
    # 🔓 Detection riapertura: da terminale a non-terminale
    was_terminal = await is_stato_terminal(existing.get("stato"))
    new_terminal = await is_stato_terminal(nuovo_stato)
    is_riapertura = was_terminal and not new_terminal
    is_chiusura = (not was_terminal) and new_terminal
    
    if is_riapertura:
        azione = f"🔓 Riaperto: stato {existing.get('stato')} → {nuovo_stato}"
        tipo_evento = "reopen"
    elif is_chiusura:
        azione = f"🔒 Chiuso: stato → {nuovo_stato}"
        tipo_evento = "close"
    else:
        azione = f"Stato → {nuovo_stato}"
        tipo_evento = "status_change"
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": payload.get("utente", "Default User"),
        "azione": azione,
        "tipo_evento": tipo_evento,
        "timestamp": datetime.now(timezone.utc),
    }
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": update_data, "$push": {"feed": feed_entry}},
    )
    return {"message": f"Stato aggiornato a {nuovo_stato}"}


# ============================================================
# DELETE (soft)
# ============================================================
@router.delete("/{plan_id}")
async def delete_action_plan(plan_id: str):
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"message": "Action Plan disattivato"}


# ============================================================
# 🆕 CANCELLAZIONE LOGICA (annullamento con motivo)
# ============================================================
class CancelPayload(BaseModel):
    reason: str
    user: Optional[str] = "Default User"


@router.post("/{plan_id}/cancel")
async def cancel_action_plan(plan_id: str, payload: CancelPayload):
    """Annulla un Action Plan (logico, non eliminazione fisica).
    Richiede motivazione obbligatoria. L'AP resta in DB e può essere ripristinato.
    """
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not ap:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Motivo annullamento obbligatorio")
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": payload.user,
        "azione": f"🚫 Annullato — Motivo: {payload.reason}",
        "tipo_evento": "cancel",
        "timestamp": datetime.now(timezone.utc),
    }
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$set": {
                "is_cancelled": True,
                "cancelled_reason": payload.reason.strip(),
                "cancelled_at": datetime.now(timezone.utc),
                "cancelled_by": payload.user,
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"feed": feed_entry},
        }
    )
    
    return {"message": "Action Plan annullato", "reason": payload.reason}


@router.post("/{plan_id}/restore")
async def restore_action_plan(plan_id: str, user: Optional[str] = "Default User"):
    """Ripristina un Action Plan annullato (lo riporta tra gli attivi)."""
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not ap:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    if not ap.get("is_cancelled"):
        raise HTTPException(status_code=400, detail="Action Plan non è annullato")
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": user,
        "azione": f"♻️ Ripristinato dall'annullamento",
        "tipo_evento": "restore",
        "timestamp": datetime.now(timezone.utc),
    }
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$set": {
                "is_cancelled": False,
                "cancelled_reason": None,
                "cancelled_at": None,
                "cancelled_by": None,
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"feed": feed_entry},
        }
    )
    
    return {"message": "Action Plan ripristinato"}


# ============================================================
# KAIZEN LINK — endpoint dedicati per integrazione Kaizen polimorfico
# ============================================================
@router.get("/by-kaizen/{kaizen_id}")
async def get_action_plans_by_kaizen(kaizen_id: str):
    """Restituisce tutti gli Action Plan collegati a uno specifico Kaizen."""
    plans = []
    
    cursor = db.action_plans.find({
        "$or": [
            {"kaizen_id": kaizen_id},
            {"parent_type": "kaizen", "parent_id": kaizen_id},
        ],
        "is_active": {"$ne": False}
    }).sort("created_at", -1)
    async for p in cursor:
        plans.append(enrich_plan(p))
    
    cursor = db.action_plans.find({
        "links": {"$elemMatch": {"entity_type": "kaizen", "entity_id": kaizen_id}},
        "is_active": {"$ne": False}
    }).sort("created_at", -1)
    async for p in cursor:
        p_id = str(p["_id"])
        if not any(existing["_id"] == p_id for existing in plans):
            plans.append(enrich_plan(p))
    
    return plans


class LinkKaizenPayload(BaseModel):
    kaizen_id: str
    kaizen_numero: Optional[str] = None


@router.post("/{plan_id}/link-kaizen")
async def link_kaizen_to_ap(plan_id: str, payload: LinkKaizenPayload):
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not ap:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    try:
        kaizen = await db.kaizens.find_one({"_id": ObjectId(payload.kaizen_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Kaizen ID non valido")
    
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    kaizen_numero = payload.kaizen_numero or kaizen.get("numero") or payload.kaizen_id[:8]
    pillar_id_from_kaizen = kaizen.get("pillar_id")
    
    new_link = {
        "entity_type": "kaizen",
        "entity_id": payload.kaizen_id,
        "entity_label": kaizen_numero,
        "link_type": "related_to",
    }
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": "Default User",
        "azione": f"🔗 Collegato a Kaizen {kaizen_numero}",
        "tipo_evento": "link_kaizen",
        "timestamp": datetime.now(timezone.utc),
    }
    
    set_data = {
        "kaizen_id": payload.kaizen_id,
        "parent_type": "kaizen",
        "parent_id": payload.kaizen_id,
        "parent_label": kaizen_numero,
        "updated_at": datetime.now(timezone.utc),
    }
    if pillar_id_from_kaizen:
        set_data["pillar_id"] = pillar_id_from_kaizen
    
    result = await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$set": set_data,
            "$addToSet": {"links": new_link},
            "$push": {"feed": feed_entry},
        }
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="AP non trovato")
    
    return {
        "message": f"Action Plan collegato al Kaizen {kaizen_numero}",
        "kaizen_id": payload.kaizen_id,
        "kaizen_numero": kaizen_numero,
        "pillar_id": pillar_id_from_kaizen,
    }


@router.delete("/{plan_id}/link-kaizen/{kaizen_id}")
async def unlink_kaizen_from_ap(plan_id: str, kaizen_id: str):
    ap = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not ap:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    
    kaizen_numero = "Kaizen"
    for link in ap.get("links", []):
        if link.get("entity_type") == "kaizen" and link.get("entity_id") == kaizen_id:
            kaizen_numero = link.get("entity_label", "Kaizen")
            break
    
    feed_entry = {
        "id": str(uuid.uuid4()),
        "utente": "Default User",
        "azione": f"🔓 Scollegato da Kaizen {kaizen_numero}",
        "tipo_evento": "unlink_kaizen",
        "timestamp": datetime.now(timezone.utc),
    }
    
    update_ops = {
        "$pull": {"links": {"entity_type": "kaizen", "entity_id": kaizen_id}},
        "$push": {"feed": feed_entry},
        "$set": {"updated_at": datetime.now(timezone.utc)},
    }
    
    if ap.get("parent_type") == "kaizen" and ap.get("parent_id") == kaizen_id:
        update_ops["$set"]["parent_type"] = "standalone"
        update_ops["$set"]["parent_id"] = None
        update_ops["$set"]["parent_label"] = None
        update_ops["$set"]["pillar_id"] = None
    
    if ap.get("kaizen_id") == kaizen_id:
        update_ops["$set"]["kaizen_id"] = None
    
    update_ops_clean = {}
    for op_key, op_val in update_ops.items():
        if op_val:
            update_ops_clean[op_key] = op_val
    
    await db.action_plans.update_one(
        {"_id": ObjectId(plan_id)},
        update_ops_clean
    )
    
    return {"message": f"Action Plan scollegato da {kaizen_numero}"}

# ──────────────────────────────────────────
# ALLEGATI
# ──────────────────────────────────────────

class AllegatoPayload(BaseModel):
    nome: str
    tipo: str  # "image/jpeg", "application/pdf", ecc.
    dimensione: int  # in bytes
    data: str  # base64 con prefisso "data:..." già incluso
    autore: Optional[str] = "Default User"


@router.post("/{plan_id}/allegati")
async def add_allegato(plan_id: str, payload: AllegatoPayload):
    """Aggiunge un allegato (base64) all'AP."""
    plan = await get_collection().find_one({"_id": ObjectId(plan_id)})
    if not plan:
        raise HTTPException(404, "Action Plan non trovato")

    allegati = plan.get("allegati", [])

    # Limite max 10 allegati per AP
    if len(allegati) >= 10:
        raise HTTPException(400, "Massimo 10 allegati per Action Plan")

    nuovo_allegato = {
        "id": str(ObjectId()),
        "nome": payload.nome,
        "tipo": payload.tipo,
        "dimensione": payload.dimensione,
        "data": payload.data,
        "autore": payload.autore,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await get_collection().update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$push": {"allegati": nuovo_allegato},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    return {"success": True, "allegato_id": nuovo_allegato["id"]}


@router.delete("/{plan_id}/allegati/{allegato_id}")
async def remove_allegato(plan_id: str, allegato_id: str):
    """Rimuove un allegato dall'AP."""
    result = await get_collection().update_one(
        {"_id": ObjectId(plan_id)},
        {
            "$pull": {"allegati": {"id": allegato_id}},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    if result.modified_count == 0:
        raise HTTPException(404, "Allegato non trovato")
    return {"success": True}

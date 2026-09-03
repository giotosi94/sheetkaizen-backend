from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import random

from pydantic import BaseModel

from app.database import db
from app.middleware.auth import get_current_user

router = APIRouter()

TIPI = ["Sicurezza", "Ambiente"]
STATI = ["Bozza", "Aperto", "In gestione", "Chiuso"]
GRAVITA = ["Bassa", "Media", "Alta", "Critica"]
PRIORITA = ["Bassa", "Media", "Alta"]


def _is_admin(current_user: dict) -> bool:
    role = str(current_user.get("role") or current_user.get("ruolo") or "").strip().lower()
    return role in {"admin", "administrator", "amministratore"}


def _require_admin(current_user: dict):
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Funzione riservata agli amministratori")


def _user_id(current_user: dict) -> str:
    value = current_user.get("_id") or current_user.get("id")
    if not value:
        raise HTTPException(status_code=401, detail="Utente non valido")
    return str(value)


def _user_name(current_user: dict) -> str:
    return (
        current_user.get("full_name")
        or current_user.get("name")
        or current_user.get("username")
        or current_user.get("email")
        or "Utente"
    )


async def _genera_codice() -> str:
    for _ in range(20):
        codice = str(random.randint(100000, 999999))
        exists = await db.segnalazioni.find_one({"codice": codice}, {"_id": 1})
        if not exists:
            return codice
    return str(int(datetime.now(timezone.utc).timestamp()))


async def _terminal_labels() -> set:
    labels = set()
    async for config in db.configurazioni.find({"tipo": "stato_ap", "is_terminal": True}):
        if config.get("label"):
            labels.add(config["label"])
    if not labels:
        labels = {"Chiuso", "Done", "Completato"}
    return labels


async def _linked_action_plans(segnalazione_id: str) -> list:
    ids = [segnalazione_id]
    if ObjectId.is_valid(segnalazione_id):
        ids.append(ObjectId(segnalazione_id))
    query = {
        "parent_type": "segnalazione",
        "parent_id": {"$in": ids},
        "is_active": {"$ne": False},
    }
    plans = []
    async for plan in db.action_plans.find(query).sort("created_at", -1):
        plans.append({
            "_id": str(plan["_id"]),
            "numero": plan.get("numero"),
            "titolo": plan.get("titolo"),
            "tipo": plan.get("tipo"),
            "stato": plan.get("stato"),
            "priorita": plan.get("priorita"),
            "responsabile": plan.get("responsabile"),
            "data_scadenza": plan.get("data_scadenza"),
            "is_cancelled": bool(plan.get("is_cancelled")),
        })
    return plans


async def _conteggio_azioni_aperte(segnalazione_id: str) -> int:
    plans = await _linked_action_plans(segnalazione_id)
    terminal = await _terminal_labels()
    return sum(1 for p in plans if not p["is_cancelled"] and p.get("stato") not in terminal)


async def _notifica_nuova_segnalazione(doc: dict):
    now = datetime.now(timezone.utc)
    admin_query = {
        "$or": [
            {"role": {"$in": ["admin", "administrator", "amministratore"]}},
            {"ruolo": {"$in": ["admin", "administrator", "amministratore"]}},
        ]
    }
    notifiche = []
    async for user in db.users.find(admin_query, {"_id": 1}):
        notifiche.append({
            "user_id": str(user["_id"]),
            "title": f"Nuova segnalazione di {doc.get('tipo')}",
            "message": f"{doc.get('codice')} - {doc.get('reparto') or 'reparto n.d.'} - da {doc.get('segnalatore_nome') or 'operatore'}",
            "action_url": f"/segnalazioni?open={str(doc['_id'])}",
            "entity_label": "Segnalazione",
            "entity_title": doc.get("codice"),
            "is_read": False,
            "created_at": now,
            "read_at": None,
        })
    if notifiche:
        await db.notifications.insert_many(notifiche)


class SegnalazioneCreate(BaseModel):
    tipo: str = "Sicurezza"


class SegnalazioneUpdate(BaseModel):
    tipo: Optional[str] = None
    responsabile_id: Optional[str] = None
    responsabile_nome: Optional[str] = None
    data_evento: Optional[str] = None
    ora_evento: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    descrizione: Optional[str] = None
    persona_coinvolta: Optional[str] = None
    persone_presenti: Optional[str] = None
    azioni_immediate: Optional[str] = None
    azioni_suggerite: Optional[str] = None
    allegati: Optional[list] = None
    immagini: Optional[list] = None


class ClassificazioneUpdate(BaseModel):
    categoria: Optional[str] = None
    gravita: Optional[str] = None
    priorita: Optional[str] = None
    note_gestione: Optional[str] = None


class ChiusuraPayload(BaseModel):
    nota_verifica_efficacia: str


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    for field in ("created_at", "updated_at", "data_chiusura"):
        value = doc.get(field)
        if isinstance(value, datetime):
            doc[field] = value.isoformat()
    return doc


@router.get("/")
async def list_segnalazioni(
    tipo: Optional[str] = Query(None),
    stato: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    query = {"is_active": {"$ne": False}}
    if tipo:
        query["tipo"] = tipo
    if stato:
        query["stato"] = stato

    if not _is_admin(current_user):
        query["segnalatore_id"] = _user_id(current_user)

    items = []
    cursor = db.segnalazioni.find(query).sort("created_at", -1)
    async for doc in cursor:
        items.append(_serialize(doc))
    return items


@router.get("/stats/summary")
async def stats(current_user: dict = Depends(get_current_user)):
    match = {"is_active": {"$ne": False}}
    if not _is_admin(current_user):
        match["segnalatore_id"] = _user_id(current_user)

    pipeline = [
        {"$match": match},
        {"$group": {"_id": {"tipo": "$tipo", "stato": "$stato"}, "count": {"$sum": 1}}},
    ]
    results = {}
    async for item in db.segnalazioni.aggregate(pipeline):
        tipo = item["_id"].get("tipo") or "Altro"
        stato = item["_id"].get("stato") or "Aperto"
        results.setdefault(tipo, {})[stato] = item["count"]
    return results


@router.post("/")
async def create_segnalazione(payload: SegnalazioneCreate, current_user: dict = Depends(get_current_user)):
    tipo = payload.tipo if payload.tipo in TIPI else "Sicurezza"
    now = datetime.now(timezone.utc)
    doc = {
        "codice": await _genera_codice(),
        "tipo": tipo,
        "stato": "Bozza",
        "segnalatore_id": _user_id(current_user),
        "segnalatore_nome": _user_name(current_user),
        "responsabile_id": None,
        "responsabile_nome": None,
        "data_evento": None,
        "ora_evento": None,
        "reparto": None,
        "linea": None,
        "macchina": None,
        "descrizione": "",
        "persona_coinvolta": "",
        "persone_presenti": "",
        "azioni_immediate": "",
        "azioni_suggerite": "",
        "allegati": [],
        "immagini": [],
        "categoria": None,
        "gravita": None,
        "priorita": None,
        "note_gestione": "",
        "nota_verifica_efficacia": None,
        "chiusura_verificata_da": None,
        "data_chiusura": None,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.segnalazioni.insert_one(doc)
    created = await db.segnalazioni.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.get("/{segnalazione_id}")
async def get_segnalazione(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    doc = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    if not _is_admin(current_user) and doc.get("segnalatore_id") != _user_id(current_user):
        raise HTTPException(status_code=403, detail="Non autorizzato")
    return _serialize(doc)


@router.get("/{segnalazione_id}/action-plans")
async def get_action_plans_collegati(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    plans = await _linked_action_plans(segnalazione_id)
    terminal = await _terminal_labels()
    aperti = sum(1 for p in plans if not p["is_cancelled"] and p.get("stato") not in terminal)
    return {
        "items": plans,
        "count": len(plans),
        "aperti": aperti,
    }


async def _get_editable(segnalazione_id: str, current_user: dict):
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    doc = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    is_owner = doc.get("segnalatore_id") == _user_id(current_user)
    if not _is_admin(current_user) and not is_owner:
        raise HTTPException(status_code=403, detail="Non autorizzato")
    return doc


@router.put("/{segnalazione_id}")
async def update_segnalazione(
    segnalazione_id: str,
    payload: SegnalazioneUpdate,
    current_user: dict = Depends(get_current_user),
):
    doc = await _get_editable(segnalazione_id, current_user)
    if doc.get("stato") == "Chiuso" and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Segnalazione chiusa")

    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if "tipo" in updates and updates["tipo"] not in TIPI:
        updates.pop("tipo")
    updates["updated_at"] = datetime.now(timezone.utc)

    await db.segnalazioni.update_one({"_id": doc["_id"]}, {"$set": updates})
    updated = await db.segnalazioni.find_one({"_id": doc["_id"]})
    return _serialize(updated)


@router.post("/{segnalazione_id}/termina")
async def termina_inserimento(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    doc = await _get_editable(segnalazione_id, current_user)
    if not doc.get("descrizione"):
        raise HTTPException(status_code=400, detail="La descrizione dell'evento e obbligatoria")
    await db.segnalazioni.update_one(
        {"_id": doc["_id"]},
        {"$set": {"stato": "Aperto", "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.segnalazioni.find_one({"_id": doc["_id"]})
    return _serialize(updated)


@router.patch("/{segnalazione_id}/classificazione")
async def classifica(
    segnalazione_id: str,
    payload: ClassificazioneUpdate,
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db.segnalazioni.update_one({"_id": ObjectId(segnalazione_id)}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    updated = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    return _serialize(updated)


@router.patch("/{segnalazione_id}/in-gestione")
async def in_gestione(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    await db.segnalazioni.update_one(
        {"_id": ObjectId(segnalazione_id)},
        {"$set": {"stato": "In gestione", "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    if not updated:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    return _serialize(updated)


@router.patch("/{segnalazione_id}/riapri")
async def riapri(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    _require_admin(current_user)
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    await db.segnalazioni.update_one(
        {"_id": ObjectId(segnalazione_id)},
        {"$set": {"stato": "In gestione", "data_chiusura": None, "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    if not updated:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")
    return _serialize(updated)


@router.patch("/{segnalazione_id}/chiudi")
async def chiudi(
    segnalazione_id: str,
    payload: ChiusuraPayload,
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    if not ObjectId.is_valid(segnalazione_id):
        raise HTTPException(status_code=400, detail="ID non valido")
    doc = await db.segnalazioni.find_one({"_id": ObjectId(segnalazione_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Segnalazione non trovata")

    aperti = await _conteggio_azioni_aperte(segnalazione_id)
    if aperti > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile chiudere: {aperti} Action Plan collegat{'o' if aperti == 1 else 'i'} ancora apert{'o' if aperti == 1 else 'i'}",
        )

    nota = (payload.nota_verifica_efficacia or "").strip()
    if not nota:
        raise HTTPException(status_code=400, detail="La nota di verifica efficacia e obbligatoria per chiudere")

    now = datetime.now(timezone.utc)
    await db.segnalazioni.update_one(
        {"_id": doc["_id"]},
        {"$set": {
            "stato": "Chiuso",
            "nota_verifica_efficacia": nota,
            "chiusura_verificata_da": _user_name(current_user),
            "data_chiusura": now,
            "updated_at": now,
        }},
    )
    updated = await db.segnalazioni.find_one({"_id": doc["_id"]})
    return _serialize(updated)


@router.delete("/{segnalazione_id}")
async def delete_segnalazione(segnalazione_id: str, current_user: dict = Depends(get_current_user)):
    doc = await _get_editable(segnalazione_id, current_user)
    await db.segnalazioni.update_one(
        {"_id": doc["_id"]},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"message": "Segnalazione eliminata"}

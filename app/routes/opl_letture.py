from datetime import datetime, timezone
import hashlib
import json
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import db
from app.middleware.auth import get_current_user

router = APIRouter()


def _object_id(value: str, label: str = "ID") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail=f"{label} non valido")
    return ObjectId(value)


def _utc_datetime(value):
    if not value:
        return None

    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return None

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _iso_datetime(value):
    normalized = _utc_datetime(value)
    return normalized.isoformat() if normalized else None


def _current_user_id(current_user: dict) -> str:
    value = current_user.get("_id") or current_user.get("id")
    if not value:
        raise HTTPException(status_code=401, detail="Utente autenticato non valido")
    return str(value)


def _hash_versione(doc: dict) -> str:
    base = {
        "numero": doc.get("numero"),
        "versione": doc.get("versione", 1),
        "file_id": doc.get("file_id"),
        "opl_data": doc.get("opl_data"),
        "titolo": doc.get("titolo"),
    }
    raw = json.dumps(base, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _serialize_lettura(lettura: dict) -> dict:
    result = dict(lettura)
    result["_id"] = str(result["_id"])
    result["assigned_at"] = _iso_datetime(result.get("assigned_at"))
    result["confirmed_at"] = _iso_datetime(result.get("confirmed_at"))
    result["scadenza"] = _iso_datetime(result.get("scadenza"))
    return result


class PubblicaPayload(BaseModel):
    user_ids: List[str] = Field(default_factory=list)
    reparti: List[str] = Field(default_factory=list)
    linee: List[str] = Field(default_factory=list)
    macchine: List[str] = Field(default_factory=list)
    ruoli: List[str] = Field(default_factory=list)
    scadenza: str


class ConfermaPayload(BaseModel):
    confirmation_text: str = "Confermo di aver letto e compreso"


async def _risolvi_destinatari(payload: PubblicaPayload) -> list:
    query_or = []

    valid_user_ids = [ObjectId(value) for value in payload.user_ids if ObjectId.is_valid(value)]
    if valid_user_ids:
        query_or.append({"_id": {"$in": valid_user_ids}})

    if payload.reparti:
        query_or.append({"reparto": {"$in": payload.reparti}})

    if payload.linee:
        query_or.append({"linee": {"$in": payload.linee}})

    if payload.macchine:
        query_or.append({"macchine": {"$in": payload.macchine}})

    if payload.ruoli:
        query_or.append({"role": {"$in": payload.ruoli}})

    if not query_or:
        return []

    active_filter = {
        "$or": [
            {"is_active": True},
            {"is_active": {"$exists": False}, "attivo": {"$ne": False}},
        ]
    }

    users = []
    seen = set()
    cursor = db.users.find({"$and": [active_filter, {"$or": query_or}]})

    async for user in cursor:
        user_id = str(user["_id"])
        if user_id in seen:
            continue
        seen.add(user_id)
        users.append(user)

    return users


@router.get("/da-leggere")
async def opl_da_leggere(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    items = []

    cursor = db.opl_letture.find({
        "user_id": user_id,
        "status": "da_leggere",
    }).sort("assigned_at", -1)

    async for lettura in cursor:
        items.append(_serialize_lettura(lettura))

    return {
        "items": items,
        "count": len(items),
    }


@router.post("/{documento_id}/pubblica")
async def pubblica_opl(
    documento_id: str,
    payload: PubblicaPayload,
    current_user: dict = Depends(get_current_user),
):
    document_object_id = _object_id(documento_id, "ID documento")
    doc = await db.documenti.find_one({"_id": document_object_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    if doc.get("tipo") != "OPL":
        raise HTTPException(status_code=400, detail="Il documento selezionato non è una OPL")

    if not payload.reparti and not payload.user_ids:
        raise HTTPException(status_code=400, detail="Seleziona almeno un reparto")

    scadenza = _utc_datetime(payload.scadenza)
    if not scadenza:
        raise HTTPException(status_code=400, detail="Scadenza non valida")

    now = datetime.now(timezone.utc)
    if scadenza < now:
        raise HTTPException(status_code=400, detail="La scadenza non può essere nel passato")

    destinatari = await _risolvi_destinatari(payload)
    if not destinatari:
        raise HTTPException(status_code=400, detail="Nessun destinatario trovato per i criteri scelti")

    versione = doc.get("versione", 1)
    document_hash = _hash_versione(doc)
    publisher_id = _current_user_id(current_user)

    letture = []
    notifiche = []

    for user in destinatari:
        user_id = str(user["_id"])
        existing = await db.opl_letture.find_one({
            "document_id": documento_id,
            "version": versione,
            "user_id": user_id,
        })

        if existing:
            if existing.get("status") != "confermata":
                await db.opl_letture.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "document_number": doc.get("numero"),
                        "document_title": doc.get("titolo"),
                        "document_hash": document_hash,
                        "scadenza": scadenza,
                        "updated_at": now,
                    }},
                )
            continue

        user_name = user.get("full_name") or user.get("name") or user.get("username") or user.get("email")

        letture.append({
            "document_id": documento_id,
            "document_number": doc.get("numero"),
            "document_title": doc.get("titolo"),
            "version": versione,
            "document_hash": document_hash,
            "user_id": user_id,
            "user_name": user_name,
            "user_email": user.get("email"),
            "reparto": user.get("reparto"),
            "linee": user.get("linee", []),
            "role": user.get("role"),
            "status": "da_leggere",
            "assigned_at": now,
            "confirmed_at": None,
            "scadenza": scadenza,
            "assigned_by": publisher_id,
            "created_at": now,
            "updated_at": now,
        })

        notifiche.append({
            "user_id": user_id,
            "type": "opl_da_leggere",
            "title": "Nuova OPL da leggere",
            "message": f"{doc.get('numero')} - {doc.get('titolo')}",
            "entity_type": "opl",
            "entity_id": documento_id,
            "entity_label": doc.get("numero"),
            "entity_title": doc.get("titolo"),
            "action_url": f"/da-leggere?opl={documento_id}",
            "is_read": False,
            "read_at": None,
            "created_at": now,
        })

    if letture:
        await db.opl_letture.insert_many(letture)

    if notifiche:
        await db.notifications.insert_many(notifiche)

    await db.documenti.update_one(
        {"_id": document_object_id},
        {"$set": {
            "pubblicata": True,
            "versione_pubblicata": versione,
            "hash_pubblicato": document_hash,
            "data_pubblicazione": now,
            "stato": "Approvato",
            "scadenza_lettura": scadenza,
            "reparti_assegnati": payload.reparti,
            "linee_assegnate": payload.linee,
            "updated_at": now,
        }},
    )

    return {
        "message": "OPL pubblicata e assegnata",
        "destinatari": len(destinatari),
        "assegnazioni_create": len(letture),
        "assegnazioni_esistenti": len(destinatari) - len(letture),
    }


@router.post("/{documento_id}/conferma")
async def conferma_lettura(
    documento_id: str,
    payload: ConfermaPayload,
    current_user: dict = Depends(get_current_user),
):
    document_object_id = _object_id(documento_id, "ID documento")
    doc = await db.documenti.find_one({"_id": document_object_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    versione = doc.get("versione_pubblicata") or doc.get("versione", 1)
    user_id = _current_user_id(current_user)

    lettura = await db.opl_letture.find_one({
        "document_id": documento_id,
        "version": versione,
        "user_id": user_id,
    })

    if not lettura:
        raise HTTPException(status_code=404, detail="Nessuna assegnazione di lettura per questa versione")

    if lettura.get("status") == "confermata":
        return {
            "message": "Lettura già confermata",
            "confirmed_at": _iso_datetime(lettura.get("confirmed_at")),
        }

    confirmation_text = payload.confirmation_text.strip()
    if confirmation_text != "Confermo di aver letto e compreso":
        raise HTTPException(status_code=400, detail="Testo di conferma non valido")

    current_hash = doc.get("hash_pubblicato") or _hash_versione(doc)
    if lettura.get("document_hash") and lettura.get("document_hash") != current_hash:
        raise HTTPException(status_code=409, detail="La versione pubblicata è cambiata. Riapri la OPL")

    now = datetime.now(timezone.utc)

    await db.opl_letture.update_one(
        {"_id": lettura["_id"]},
        {"$set": {
            "status": "confermata",
            "confirmed_at": now,
            "confirmation_text": confirmation_text,
            "authentication_method": "local_test",
            "confirmed_hash": current_hash,
            "updated_at": now,
        }},
    )

    await db.notifications.update_many(
        {
            "user_id": user_id,
            "type": "opl_da_leggere",
            "entity_id": documento_id,
            "is_read": False,
        },
        {"$set": {
            "is_read": True,
            "read_at": now,
        }},
    )

    return {
        "message": "Lettura confermata",
        "confirmed_at": now.isoformat(),
        "version": versione,
    }


@router.get("/{documento_id}/report")
async def report_opl(
    documento_id: str,
    current_user: dict = Depends(get_current_user),
):
    document_object_id = _object_id(documento_id, "ID documento")
    doc = await db.documenti.find_one({"_id": document_object_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    versione = doc.get("versione_pubblicata") or doc.get("versione", 1)
    now = datetime.now(timezone.utc)
    righe = []
    confermati = 0
    da_leggere = 0
    in_ritardo = 0

    cursor = db.opl_letture.find({
        "document_id": documento_id,
        "version": versione,
    }).sort("user_name", 1)

    async for lettura in cursor:
        stato = lettura.get("status", "da_leggere")
        scadenza = _utc_datetime(lettura.get("scadenza"))
        ritardo = stato != "confermata" and scadenza is not None and scadenza < now

        if stato == "confermata":
            confermati += 1
            stato_report = "Confermata"
        else:
            da_leggere += 1
            if ritardo:
                in_ritardo += 1
                stato_report = "In ritardo"
            else:
                stato_report = "Da leggere"

        righe.append({
            "user_id": lettura.get("user_id"),
            "user_name": lettura.get("user_name"),
            "user_email": lettura.get("user_email"),
            "reparto": lettura.get("reparto"),
            "linee": lettura.get("linee", []),
            "role": lettura.get("role"),
            "status": stato_report,
            "assigned_at": _iso_datetime(lettura.get("assigned_at")),
            "confirmed_at": _iso_datetime(lettura.get("confirmed_at")),
            "scadenza": _iso_datetime(lettura.get("scadenza")),
            "document_hash": lettura.get("document_hash"),
            "confirmed_hash": lettura.get("confirmed_hash"),
        })

    totale = len(righe)
    completamento = round((confermati / totale) * 100, 1) if totale else 0.0

    return {
        "documento": {
            "id": documento_id,
            "numero": doc.get("numero"),
            "titolo": doc.get("titolo"),
            "versione": versione,
            "data_pubblicazione": _iso_datetime(doc.get("data_pubblicazione")),
            "scadenza_lettura": _iso_datetime(doc.get("scadenza_lettura")),
            "hash_pubblicato": doc.get("hash_pubblicato"),
            "reparti_assegnati": doc.get("reparti_assegnati", []),
            "linee_assegnate": doc.get("linee_assegnate", []),
        },
        "riepilogo": {
            "destinatari": totale,
            "confermati": confermati,
            "da_leggere": da_leggere,
            "in_ritardo": in_ritardo,
            "completamento": completamento,
        },
        "righe": righe,
    }

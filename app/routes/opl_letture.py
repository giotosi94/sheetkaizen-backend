from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
from bson import ObjectId
import hashlib
import json

from app.database import db
from app.middleware.auth import get_current_user

router = APIRouter()


def _hash_versione(doc: dict) -> str:
    base = {
        "numero": doc.get("numero"),
        "versione": doc.get("versione"),
        "file_id": doc.get("file_id"),
        "opl_data": doc.get("opl_data"),
        "titolo": doc.get("titolo"),
    }
    raw = json.dumps(base, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _serialize(lettura: dict) -> dict:
    lettura["_id"] = str(lettura["_id"])
    for campo in ("assigned_at", "confirmed_at"):
        if isinstance(lettura.get(campo), datetime):
            lettura[campo] = lettura[campo].isoformat()
    return lettura


class PubblicaPayload(BaseModel):
    user_ids: List[str] = []
    reparti: List[str] = []
    linee: List[str] = []
    macchine: List[str] = []
    ruoli: List[str] = []
    scadenza: Optional[str] = None


async def _risolvi_destinatari(payload: PubblicaPayload) -> Listquery_or = []

    if payload.user_ids:
        ids = []
        for uid in payload.user_ids:
            try:
                ids.append(ObjectId(uid))
            except Exception:
                continue
        if ids:
            query_or.append({"_id": {"$in": ids}})

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

    query = {"is_active": True, "$or": query_or}

    utenti = []
    seen = set()
    cursor = db.users.find(query)
    async for u in cursor:
        uid = str(u["_id"])
        if uid in seen:
            continue
        seen.add(uid)
        utenti.append(u)

    return utenti


@router.post("/{documento_id}/pubblica")
async def pubblica_opl(
    documento_id: str,
    payload: PubblicaPayload,
    current_user: dict = Depends(get_current_user),
):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(404, "Documento non trovato")

    versione = doc.get("versione", 1)
    doc_hash = _hash_versione(doc)
    now = datetime.now(timezone.utc)

    destinatari = await _risolvi_destinatari(payload)

    if not destinatari:
        raise HTTPException(400, "Nessun destinatario trovato per i criteri scelti")

    scadenza = None
    if payload.scadenza:
        try:
            scadenza = datetime.fromisoformat(payload.scadenza)
        except Exception:
            scadenza = None

    await db.opl_letture.delete_many({
        "document_id": documento_id,
        "version": versione,
        "status": "da_leggere",
    })

    letture = []
    for u in destinatari:
        uid = str(u["_id"])

        esiste = await db.opl_letture.find_one({
            "document_id": documento_id,
            "version": versione,
            "user_id": uid,
            "status": "confermata",
        })
        if esiste:
            continue

        letture.append({
            "document_id": documento_id,
            "document_number": doc.get("numero"),
            "document_title": doc.get("titolo"),
            "version": versione,
            "document_hash": doc_hash,
            "user_id": uid,
            "user_name": u.get("full_name") or u.get("username"),
            "user_email": u.get("email"),
            "reparto": u.get("reparto"),
            "role": u.get("role"),
            "status": "da_leggere",
            "assigned_at": now,
            "confirmed_at": None,
            "scadenza": scadenza,
        })

    if letture:
        await db.opl_letture.insert_many(letture)

    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": {
            "pubblicata": True,
            "versione_pubblicata": versione,
            "hash_pubblicato": doc_hash,
            "data_pubblicazione": now,
            "stato": "Approvato",
            "scadenza_lettura": scadenza,
            "updated_at": now,
        }}
    )

    notifiche = [{
        "user_id": l["user_id"],
        "type": "opl_da_leggere",
        "title": "Nuova OPL da leggere",
        "message": f"{doc.get('numero')} - {doc.get('titolo')}",
        "entity_type": "opl",
        "entity_id": documento_id,
        "entity_label": doc.get("numero"),
        "entity_title": doc.get("titolo"),
        "action_url": f"/documenti?opl={documento_id}",
        "is_read": False,
        "read_at": None,
        "created_at": now,
    } for l in letture]

    if notifiche:
        await db.notifications.insert_many(notifiche)

    return {
        "message": "OPL pubblicata",
        "destinatari": len(destinatari),
        "assegnazioni_create": len(letture),
    }


@router.get("/da-leggere")
async def opl_da_leggere(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["_id"])

    letture = []
    cursor = db.opl_letture.find({
        "user_id": user_id,
        "status": "da_leggere",
    }).sort("assigned_at", -1)

    async for l in cursor:
        letture.append(_serialize(l))

    return {
        "items": letture,
        "count": len(letture),
    }


class ConfermaPayload(BaseModel):
    confirmation_text: str = "Confermo di aver letto e compreso"


@router.post("/{documento_id}/conferma")
async def conferma_lettura(
    documento_id: str,
    payload: ConfermaPayload,
    current_user: dict = Depends(get_current_user),
):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(404, "Documento non trovato")

    user_id = str(current_user["_id"])
    versione = doc.get("versione", 1)

    lettura = await db.opl_letture.find_one({
        "document_id": documento_id,
        "version": versione,
        "user_id": user_id,
    })

    if not lettura:
        raise HTTPException(404, "Nessuna assegnazione di lettura per questa versione")

    if lettura.get("status") == "confermata":
        return {"message": "Lettura già confermata"}

    now = datetime.now(timezone.utc)

    await db.opl_letture.update_one(
        {"_id": lettura["_id"]},
        {"$set": {
            "status": "confermata",
            "confirmed_at": now,
            "confirmation_text": payload.confirmation_text,
            "authentication_method": "local_test",
            "confirmed_hash": doc.get("hash_pubblicato") or _hash_versione(doc),
        }}
    )

    return {"message": "Lettura confermata"}


@router.get("/{documento_id}/report")
async def report_opl(
    documento_id: str,
    current_user: dict = Depends(get_current_user),
):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(404, "Documento non trovato")

    versione = doc.get("versione", 1)
    now = datetime.now(timezone.utc)

    righe = []
    confermati = 0
    da_leggere = 0
    in_ritardo = 0

    cursor = db.opl_letture.find({
        "document_id": documento_id,
        "version": versione,
    }).sort("user_name", 1)

    async for l in cursor:
        stato = l.get("status")
        scad = l.get("scadenza")

        ritardo = False
        if stato != "confermata" and scad:
            if isinstance(scad, str):
                try:
                    scad = datetime.fromisoformat(scad)
                except Exception:
                    scad = None
            if scad and scad < now:
                ritardo = True

        if stato == "confermata":
            confermati += 1
        else:
            da_leggere += 1
            if ritardo:
                in_ritardo += 1

        righe.append({
            "user_name": l.get("user_name"),
            "reparto": l.get("reparto"),
            "role": l.get("role"),
            "status": "In ritardo" if ritardo else (
                "Confermata" if stato == "confermata" else "Da leggere"
            ),
            "assigned_at": l.get("assigned_at").isoformat() if isinstance(l.get("assigned_at"), datetime) else None,
            "confirmed_at": l.get("confirmed_at").isoformat() if isinstance(l.get("confirmed_at"), datetime) else None,
        })

    totale = len(righe)
    completamento = round((confermati / totale) * 100, 1) if totale else 0

    return {
        "documento": {
            "numero": doc.get("numero"),
            "titolo": doc.get("titolo"),
            "versione": versione,
            "data_pubblicazione": doc.get("data_pubblicazione").isoformat() if isinstance(doc.get("data_pubblicazione"), datetime) else None,
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

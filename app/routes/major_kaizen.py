from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.major_kaizen import (
    MajorKaizenCreate, MajorKaizenUpdate, StepDataUpdate, GateApproval
)
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel

router = APIRouter()


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


async def get_next_numero() -> str:
    last = await db.major_kaizen.find_one(sort=[("created_at", -1)])
    if last and "numero" in last:
        try:
            num = int(str(last["numero"]).split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"MAJ-{num:04d}"


def init_steps_data(snapshot: dict) -> dict:
    steps_data = {}
    for step in snapshot.get("steps", []):
        sid = step.get("step_id")
        if not sid:
            continue
        steps_data[sid] = {
            "stato": "non_iniziato",
            "attivita": {},
            "dati": {},
            "metodologie_usate": [],
            "output_compilati": {},
            "note": "",
            "gate": {
                "approvato": False,
                "approvato_da": None,
                "data": None,
                "note": "",
            },
        }
    return steps_data


def calcola_completamento(steps_data: dict) -> int:
    if not steps_data:
        return 0
    total = len(steps_data)
    completati = sum(1 for s in steps_data.values() if s.get("stato") == "completato")
    return round((completati / total) * 100) if total else 0


@router.get("/")
async def get_major_kaizens(
    plant_id: Optional[str] = Query(None),
    stato: Optional[str] = Query(None),
):
    query = {"is_active": {"$ne": False}}
    if plant_id:
        query["plant_id"] = plant_id
    if stato:
        query["stato"] = stato
    items = []
    cursor = db.major_kaizen.find(query).sort("created_at", -1)
    async for m in cursor:
        items.append(serialize(m))
    return items


@router.get("/{major_id}")
async def get_major_kaizen(major_id: str):
    major = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not major:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    return serialize(major)


@router.post("/")
async def create_major_kaizen(payload: MajorKaizenCreate):
    try:
        route = await db.route_catalog.find_one({"_id": ObjectId(payload.route_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="route_id non valido")
    if not route:
        raise HTTPException(status_code=404, detail="Route non trovata")
    if route.get("stato") != "pubblicata":
        raise HTTPException(status_code=400, detail="La Route selezionata non e pubblicata")

    snapshot = {k: v for k, v in route.items() if k != "_id"}
    snapshot["route_id_originale"] = str(route["_id"])

    numero = await get_next_numero()
    steps_data = init_steps_data(snapshot)

    doc = payload.model_dump(exclude={"route_id"})
    doc["numero"] = numero
    doc["route_codice"] = snapshot.get("codice")
    doc["route_nome"] = snapshot.get("nome")
    doc["route_versione"] = snapshot.get("versione")
    doc["route_snapshot"] = snapshot
    doc["steps_data"] = steps_data
    doc["stato"] = "In corso"
    doc["percentuale_completamento"] = 0
    doc["linked_kaizen_ids"] = []
    doc["linked_action_plan_ids"] = []
    doc["linked_opl_ids"] = []
    doc["linked_document_ids"] = []
    doc["is_active"] = True
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = datetime.now(timezone.utc)

    result = await db.major_kaizen.insert_one(doc)
    created = await db.major_kaizen.find_one({"_id": result.inserted_id})
    return serialize(created)


@router.put("/{major_id}")
async def update_major_kaizen(major_id: str, update: MajorKaizenUpdate):
    existing = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    update_data = {k: v for k, v in update.model_dump(exclude_none=True).items()}
    if "steps_data" in update_data:
        update_data["percentuale_completamento"] = calcola_completamento(update_data["steps_data"])
    update_data["updated_at"] = datetime.now(timezone.utc)
    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$set": update_data},
    )
    updated = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    return serialize(updated)


@router.patch("/{major_id}/step/{step_id}")
async def update_step(major_id: str, step_id: str, payload: StepDataUpdate):
    existing = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    steps_data = existing.get("steps_data", {})
    if step_id not in steps_data:
        raise HTTPException(status_code=404, detail="Step non trovato nello snapshot")

    current = steps_data[step_id]
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        current[key] = value
    steps_data[step_id] = current

    pct = calcola_completamento(steps_data)
    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$set": {
            "steps_data": steps_data,
            "percentuale_completamento": pct,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    updated = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    return serialize(updated)


@router.patch("/{major_id}/step/{step_id}/gate")
async def approve_gate(major_id: str, step_id: str, payload: GateApproval):
    existing = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    steps_data = existing.get("steps_data", {})
    if step_id not in steps_data:
        raise HTTPException(status_code=404, detail="Step non trovato")

    steps_data[step_id]["gate"] = {
        "approvato": payload.approvato,
        "approvato_da": payload.approvato_da,
        "data": datetime.now(timezone.utc) if payload.approvato else None,
        "note": payload.note or "",
    }
    if payload.approvato:
        steps_data[step_id]["stato"] = "completato"

    pct = calcola_completamento(steps_data)
    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$set": {
            "steps_data": steps_data,
            "percentuale_completamento": pct,
            "updated_at": datetime.now(timezone.utc),
        }},
    )
    updated = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    return serialize(updated)


class LinkKaizenPayload(BaseModel):
    kaizen_id: str


@router.post("/{major_id}/link-kaizen")
async def link_kaizen(major_id: str, payload: LinkKaizenPayload):
    major = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not major:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    try:
        kaizen = await db.kaizens.find_one({"_id": ObjectId(payload.kaizen_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="kaizen_id non valido")
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")

    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$addToSet": {"linked_kaizen_ids": payload.kaizen_id},
         "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    await db.kaizens.update_one(
        {"_id": ObjectId(payload.kaizen_id)},
        {"$set": {"major_parent_id": major_id, "updated_at": datetime.now(timezone.utc)}},
    )
    updated = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    return serialize(updated)


@router.delete("/{major_id}/link-kaizen/{kaizen_id}")
async def unlink_kaizen(major_id: str, kaizen_id: str):
    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$pull": {"linked_kaizen_ids": kaizen_id},
         "$set": {"updated_at": datetime.now(timezone.utc)}},
    )
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {"$set": {"major_parent_id": None, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"message": "Kaizen scollegato dal Major"}


@router.get("/{major_id}/linked-kaizens")
async def get_linked_kaizens(major_id: str):
    major = await db.major_kaizen.find_one({"_id": ObjectId(major_id)})
    if not major:
        raise HTTPException(status_code=404, detail="Major Kaizen non trovato")
    ids = major.get("linked_kaizen_ids", [])
    kaizens = []
    for kid in ids:
        try:
            k = await db.kaizens.find_one({"_id": ObjectId(kid)})
            if k:
                kaizens.append(serialize(k))
        except Exception:
            continue
    return kaizens


@router.delete("/{major_id}")
async def delete_major_kaizen(major_id: str):
    await db.major_kaizen.update_one(
        {"_id": ObjectId(major_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"message": "Major Kaizen disattivato"}

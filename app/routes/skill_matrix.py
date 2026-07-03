from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

from app.database import db
from app.models.skill_matrix import (
    SkillMatrixCreate,
    SkillMatrixUpdate,
    SkillCompetenzaCreate,
    SkillCompetenzaUpdate,
)
from app.middleware.auth import get_current_user

router = APIRouter()


def _serialize(doc):
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


# ─────────────────────────────────────────────
# COMPETENZE PER PILLAR (configurabile per pillar)
# ─────────────────────────────────────────────

@router.get("/pillars/{pillar_id}/skill-competenze")
async def list_competenze(pillar_id: str):
    """Lista tutte le competenze configurate per un pillar."""
    competenze = []
    cursor = db.skill_competenze.find({"pillar_id": pillar_id}).sort("ordine", 1)
    async for c in cursor:
        competenze.append(_serialize(c))
    return competenze


@router.post("/pillars/{pillar_id}/skill-competenze")
async def create_competenza(pillar_id: str, payload: SkillCompetenzaCreate):
    doc = {
        **payload.dict(),
        "pillar_id": pillar_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.skill_competenze.insert_one(doc)
    created = await db.skill_competenze.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.put("/pillars/{pillar_id}/skill-competenze/{competenza_id}")
async def update_competenza(pillar_id: str, competenza_id: str, payload: SkillCompetenzaUpdate):
    update = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc)
    result = await db.skill_competenze.update_one(
        {"_id": ObjectId(competenza_id), "pillar_id": pillar_id},
        {"$set": update},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Competenza non trovata")
    updated = await db.skill_competenze.find_one({"_id": ObjectId(competenza_id)})
    return _serialize(updated)


@router.delete("/pillars/{pillar_id}/skill-competenze/{competenza_id}")
async def delete_competenza(pillar_id: str, competenza_id: str):
    result = await db.skill_competenze.delete_one(
        {"_id": ObjectId(competenza_id), "pillar_id": pillar_id}
    )
    if result.deleted_count == 0:
        raise HTTPException(404, "Competenza non trovata")
    return {"message": "Competenza eliminata"}


# ─────────────────────────────────────────────
# SKILL MATRIX (per pillar / anno)
# ─────────────────────────────────────────────

@router.get("/pillars/{pillar_id}/skill-matrix")
async def list_matrix_years(pillar_id: str):
    """Lista tutti gli anni disponibili per la skill matrix di un pillar."""
    years = []
    cursor = db.skill_matrix.find({"pillar_id": pillar_id}).sort("anno", -1)
    async for m in cursor:
        years.append({
            "id": str(m["_id"]),
            "anno": m.get("anno"),
            "members_count": len(m.get("members", [])),
            "competenze_count": len(m.get("competenze", [])),
            "updated_at": m.get("updated_at"),
        })
    return years


@router.get("/pillars/{pillar_id}/skill-matrix/{anno}")
async def get_matrix_by_year(pillar_id: str, anno: int):
    """Restituisce la matrice per un dato anno. Se non esiste, la crea vuota."""
    matrix = await db.skill_matrix.find_one({"pillar_id": pillar_id, "anno": anno})
    if not matrix:
        # Auto-crea vuota con le competenze correnti del pillar
        competenze_cursor = db.skill_competenze.find({"pillar_id": pillar_id}).sort("ordine", 1)
        competenze = []
        async for c in competenze_cursor:
            competenze.append({
                "id": str(c["_id"]),
                "label": c.get("label"),
                "codice": c.get("codice"),
                "categoria_id": c.get("categoria_id"),
                "ordine": c.get("ordine", 0),
            })

        doc = {
            "pillar_id": pillar_id,
            "anno": anno,
            "competenze": competenze,
            "members": [],
            "valori": {},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = await db.skill_matrix.insert_one(doc)
        matrix = await db.skill_matrix.find_one({"_id": result.inserted_id})

    return _serialize(matrix)


@router.put("/pillars/{pillar_id}/skill-matrix/{anno}")
async def update_matrix(pillar_id: str, anno: int, payload: SkillMatrixUpdate):
    """Aggiorna una skill matrix esistente."""
    update = {k: v for k, v in payload.dict(exclude_unset=True).items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc)

    result = await db.skill_matrix.update_one(
        {"pillar_id": pillar_id, "anno": anno},
        {"$set": update},
        upsert=True,
    )
    updated = await db.skill_matrix.find_one({"pillar_id": pillar_id, "anno": anno})
    return _serialize(updated)


@router.post("/pillars/{pillar_id}/skill-matrix/{anno}/duplicate-from/{from_anno}")
async def duplicate_from_previous_year(pillar_id: str, anno: int, from_anno: int):
    """Copia la matrice da un anno precedente (con Current che diventa nuovo Starting)."""
    source = await db.skill_matrix.find_one({"pillar_id": pillar_id, "anno": from_anno})
    if not source:
        raise HTTPException(404, f"Matrice {from_anno} non trovata")

    # Verifica che la nuova non esista già
    existing = await db.skill_matrix.find_one({"pillar_id": pillar_id, "anno": anno})
    if existing:
        raise HTTPException(400, f"Matrice {anno} esiste già")

    # Il current dell'anno precedente diventa lo starting del nuovo
    new_valori = {}
    for key, cell in (source.get("valori") or {}).items():
        current_val = cell.get("current")
        new_valori[key] = {
            "starting": current_val,  # nuovo anno parte dal current del precedente
            "current": None,
            "target": cell.get("target"),  # mantieni target o azzera?
            "note": None,
        }

    doc = {
        "pillar_id": pillar_id,
        "anno": anno,
        "competenze": source.get("competenze", []),
        "members": source.get("members", []),
        "valori": new_valori,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.skill_matrix.insert_one(doc)
    created = await db.skill_matrix.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.delete("/pillars/{pillar_id}/skill-matrix/{anno}")
async def delete_matrix(pillar_id: str, anno: int):
    result = await db.skill_matrix.delete_one({"pillar_id": pillar_id, "anno": anno})
    if result.deleted_count == 0:
        raise HTTPException(404, "Matrice non trovata")
    return {"message": "Matrice eliminata"}

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

from app.database import db
from app.middleware.auth import get_current_user

router = APIRouter()


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────

class FolderCreate(BaseModel):
    nome: str
    parent_id: Optional[str] = None
    ordine: Optional[int] = 0


class FolderUpdate(BaseModel):
    nome: Optional[str] = None
    parent_id: Optional[str] = None
    ordine: Optional[int] = None


class MoveAnalisiPayload(BaseModel):
    folder_id: Optional[str] = None  # None = root


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _serialize(doc):
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


async def _build_path(pillar_id: str, parent_id: Optional[str], nome: str) -> str:
    if not parent_id:
        return nome
    parent = await db.pillar_folders.find_one(
        {"_id": ObjectId(parent_id), "pillar_id": pillar_id}
    )
    if not parent:
        raise HTTPException(404, "Cartella padre non trovata")
    parent_path = parent.get("path", parent.get("nome", ""))
    return f"{parent_path}/{nome}"


async def _would_create_cycle(folder_id: str, new_parent_id: str, pillar_id: str) -> bool:
    if folder_id == new_parent_id:
        return True
    current = new_parent_id
    depth = 0
    while current and depth < 100:
        parent = await db.pillar_folders.find_one(
            {"_id": ObjectId(current), "pillar_id": pillar_id}
        )
        if not parent:
            return False
        if str(parent.get("parent_id")) == folder_id:
            return True
        current = parent.get("parent_id")
        depth += 1
    return False


async def _refresh_descendants_path(pillar_id: str, folder_id: str):
    folder = await db.pillar_folders.find_one(
        {"_id": ObjectId(folder_id), "pillar_id": pillar_id}
    )
    if not folder:
        return
    base_path = folder.get("path", folder.get("nome", ""))
    children_cursor = db.pillar_folders.find(
        {"pillar_id": pillar_id, "parent_id": folder_id}
    )
    async for child in children_cursor:
        new_path = f"{base_path}/{child.get('nome', '')}"
        await db.pillar_folders.update_one(
            {"_id": child["_id"]},
            {"$set": {"path": new_path, "updated_at": datetime.now(timezone.utc)}},
        )
        await _refresh_descendants_path(pillar_id, str(child["_id"]))


# ─────────────────────────────────────────────
# ROUTES: FOLDERS
# ─────────────────────────────────────────────

@router.get("/pillars/{pillar_id}/folders")
async def list_folders(pillar_id: str, user=Depends(get_current_user)):
    """Lista tutte le cartelle del pillar (piatta, ordinata per path)."""
    folders = []
    cursor = db.pillar_folders.find({"pillar_id": pillar_id}).sort([("path", 1), ("ordine", 1)])
    async for f in cursor:
        folders.append(_serialize(f))
    return folders


@router.post("/pillars/{pillar_id}/folders")
async def create_folder(pillar_id: str, payload: FolderCreate, user=Depends(get_current_user)):
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(400, "Nome cartella obbligatorio")

    path = await _build_path(pillar_id, payload.parent_id, nome)

    existing = await db.pillar_folders.find_one({"pillar_id": pillar_id, "path": path})
    if existing:
        raise HTTPException(400, f"Cartella già esistente: {path}")

    doc = {
        "pillar_id": pillar_id,
        "nome": nome,
        "parent_id": payload.parent_id,
        "path": path,
        "ordine": payload.ordine or 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.pillar_folders.insert_one(doc)
    created = await db.pillar_folders.find_one({"_id": result.inserted_id})
    return _serialize(created)


@router.put("/pillars/{pillar_id}/folders/{folder_id}")
async def update_folder(
    pillar_id: str,
    folder_id: str,
    payload: FolderUpdate,
    user=Depends(get_current_user),
):
    folder = await db.pillar_folders.find_one(
        {"_id": ObjectId(folder_id), "pillar_id": pillar_id}
    )
    if not folder:
        raise HTTPException(404, "Cartella non trovata")

    updates = {}
    new_nome = folder.get("nome")
    new_parent = folder.get("parent_id")

    if payload.nome is not None:
        n = payload.nome.strip()
        if not n:
            raise HTTPException(400, "Nome non valido")
        new_nome = n
        updates["nome"] = n

    if payload.parent_id is not None:
        target_parent = payload.parent_id or None
        if target_parent:
            if await _would_create_cycle(folder_id, target_parent, pillar_id):
                raise HTTPException(400, "Spostamento non valido: creerebbe un ciclo")
        new_parent = target_parent
        updates["parent_id"] = target_parent

    if payload.ordine is not None:
        updates["ordine"] = payload.ordine

    if "nome" in updates or "parent_id" in updates:
        new_path = await _build_path(pillar_id, new_parent, new_nome)
        conflict = await db.pillar_folders.find_one(
            {"pillar_id": pillar_id, "path": new_path, "_id": {"$ne": ObjectId(folder_id)}}
        )
        if conflict:
            raise HTTPException(400, f"Cartella già esistente: {new_path}")
        updates["path"] = new_path

    updates["updated_at"] = datetime.now(timezone.utc)

    await db.pillar_folders.update_one(
        {"_id": ObjectId(folder_id)},
        {"$set": updates},
    )

    if "path" in updates:
        await _refresh_descendants_path(pillar_id, folder_id)

    updated = await db.pillar_folders.find_one({"_id": ObjectId(folder_id)})
    return _serialize(updated)


@router.delete("/pillars/{pillar_id}/folders/{folder_id}")
async def delete_folder(
    pillar_id: str,
    folder_id: str,
    user=Depends(get_current_user),
):
    """Elimina cartella (consentito solo se vuota: no sotto-cartelle, no analisi)."""
    folder = await db.pillar_folders.find_one(
        {"_id": ObjectId(folder_id), "pillar_id": pillar_id}
    )
    if not folder:
        raise HTTPException(404, "Cartella non trovata")

    children = await db.pillar_folders.count_documents(
        {"pillar_id": pillar_id, "parent_id": folder_id}
    )
    if children > 0:
        raise HTTPException(400, "Cartella non vuota: contiene sotto-cartelle")

    # Check analisi dentro (le analisi sono embedded nel pillar)
    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    analyses = (pillar or {}).get("analyses", [])
    analisi_dentro = sum(1 for a in analyses if a.get("folder_id") == folder_id)
    if analisi_dentro > 0:
        raise HTTPException(400, "Cartella non vuota: contiene analisi")

    await db.pillar_folders.delete_one({"_id": ObjectId(folder_id)})
    return {"message": "Cartella eliminata"}


# ─────────────────────────────────────────────
# ROUTE: MOVE ANALISI (embedded in pillar.analyses[])
# ─────────────────────────────────────────────

@router.put("/pillars/{pillar_id}/analyses/{analysis_id}/move")
async def move_analysis(
    pillar_id: str,
    analysis_id: str,
    payload: MoveAnalisiPayload,
    user=Depends(get_current_user),
):
    """Sposta un'analisi (embedded in pillar.analyses[]) in una cartella o in root."""
    target = payload.folder_id or None

    if target:
        folder = await db.pillar_folders.find_one(
            {"_id": ObjectId(target), "pillar_id": pillar_id}
        )
        if not folder:
            raise HTTPException(404, "Cartella destinazione non trovata")

    pillar = await db.pillars.find_one({"_id": ObjectId(pillar_id)})
    if not pillar:
        raise HTTPException(404, "Pillar non trovato")

    analyses = pillar.get("analyses", [])
    found = False
    for i, a in enumerate(analyses):
        if a.get("id") == analysis_id:
            analyses[i]["folder_id"] = target
            found = True
            break

    if not found:
        raise HTTPException(404, "Analisi non trovata")

    await db.pillars.update_one(
        {"_id": ObjectId(pillar_id)},
        {"$set": {"analyses": analyses, "updated_at": datetime.now(timezone.utc)}},
    )

    return {"message": "Analisi spostata", "folder_id": target, "analysis_id": analysis_id}

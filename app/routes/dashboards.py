from fastapi import APIRouter, HTTPException, Depends
from app.database import db
from app.models.dashboard import DashboardCreate, DashboardUpdate
from app.middleware.auth import get_current_user
from bson import ObjectId
from datetime import datetime, timezone
import copy

router = APIRouter()


def _serialize(doc):
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


def _can_view(dashboard, user):
    """Verifica se l'utente può vedere la dashboard."""
    # Admin vede tutto
    if user.get("role") == "admin":
        return True

    visibilita = dashboard.get("visibilita", "pubblico")

    # Pubblico → tutti
    if visibilita == "pubblico":
        return True

    # Creatore vede sempre la sua dashboard
    if dashboard.get("creatore_id") == user.get("id"):
        return True

    # Reparto → solo utenti dello stesso reparto
    if visibilita == "reparto":
        user_reparto = user.get("reparto")
        dash_reparto = dashboard.get("reparto")
        return user_reparto and dash_reparto and user_reparto == dash_reparto

    # Privato → solo creatore + utenti autorizzati
    if visibilita == "privato":
        return user.get("id") in (dashboard.get("utenti_autorizzati_ids") or [])

    return False


@router.get("/")
async def get_dashboards(current_user: dict = Depends(get_current_user)):
    """Restituisce solo le dashboard visibili all'utente corrente."""
    dashboards = []
    cursor = db.dashboards.find({}).sort("created_at", -1)
    async for d in cursor:
        if _can_view(d, current_user):
            dashboards.append(_serialize(d))
    return dashboards


@router.get("/{dashboard_id}")
async def get_dashboard(
    dashboard_id: str,
    current_user: dict = Depends(get_current_user),
):
    dashboard = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")

    if not _can_view(dashboard, current_user):
        raise HTTPException(status_code=403, detail="Non hai accesso a questa dashboard")

    return _serialize(dashboard)


@router.post("/")
async def create_dashboard(
    dashboard: DashboardCreate,
    current_user: dict = Depends(get_current_user),
):
    doc = {
        **dashboard.dict(),
        "creatore_id": current_user.get("id"),
        "creatore_nome": current_user.get("full_name") or current_user.get("username"),
        "action_plans": [],
        "is_template": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.dashboards.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Dashboard creata"}


@router.put("/{dashboard_id}")
async def update_dashboard(
    dashboard_id: str,
    update: DashboardUpdate,
    current_user: dict = Depends(get_current_user),
):
    existing = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")

    # Solo admin o creatore può modificare
    if current_user.get("role") != "admin" and existing.get("creatore_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Solo creatore o admin può modificare")

    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    await db.dashboards.update_one({"_id": ObjectId(dashboard_id)}, {"$set": update_data})
    return {"message": "Dashboard aggiornata"}


@router.post("/{dashboard_id}/duplicate")
async def duplicate_dashboard(
    dashboard_id: str,
    current_user: dict = Depends(get_current_user),
):
    original = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not original:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")

    if not _can_view(original, current_user):
        raise HTTPException(status_code=403, detail="Non hai accesso a questa dashboard")

    new_dash = copy.deepcopy(original)
    del new_dash["_id"]
    new_dash["nome"] = f"{original['nome']} (copia)"
    new_dash["creatore_id"] = current_user.get("id")
    new_dash["creatore_nome"] = current_user.get("full_name") or current_user.get("username")
    new_dash["created_at"] = datetime.now(timezone.utc)
    new_dash["updated_at"] = datetime.now(timezone.utc)

    result = await db.dashboards.insert_one(new_dash)
    return {"id": str(result.inserted_id), "message": "Dashboard duplicata"}


@router.delete("/{dashboard_id}")
async def delete_dashboard(
    dashboard_id: str,
    current_user: dict = Depends(get_current_user),
):
    existing = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")

    # Solo admin o creatore può eliminare
    if current_user.get("role") != "admin" and existing.get("creatore_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Solo creatore o admin può eliminare")

    await db.dashboards.delete_one({"_id": ObjectId(dashboard_id)})
    return {"message": "Dashboard eliminata"}

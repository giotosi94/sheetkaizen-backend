from fastapi import APIRouter, HTTPException
from app.database import db
from app.models.dashboard import DashboardCreate, DashboardUpdate
from bson import ObjectId
from datetime import datetime, timezone
import copy

router = APIRouter()


@router.get("/")
async def get_dashboards():
    dashboards = []
    cursor = db.dashboards.find({}).sort("created_at", -1)
    async for d in cursor:
        d["_id"] = str(d["_id"])
        dashboards.append(d)
    return dashboards


@router.get("/{dashboard_id}")
async def get_dashboard(dashboard_id: str):
    dashboard = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not dashboard:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")
    dashboard["_id"] = str(dashboard["_id"])
    return dashboard


@router.post("/")
async def create_dashboard(dashboard: DashboardCreate):
    doc = {
        **dashboard.dict(),
        "creatore_id": "default",
        "action_plans": [],
        "is_template": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.dashboards.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Dashboard creata"}


@router.put("/{dashboard_id}")
async def update_dashboard(dashboard_id: str, update: DashboardUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    result = await db.dashboards.update_one({"_id": ObjectId(dashboard_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")
    return {"message": "Dashboard aggiornata"}


@router.post("/{dashboard_id}/duplicate")
async def duplicate_dashboard(dashboard_id: str):
    original = await db.dashboards.find_one({"_id": ObjectId(dashboard_id)})
    if not original:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")

    new_dash = copy.deepcopy(original)
    del new_dash["_id"]
    new_dash["nome"] = f"{original['nome']} (copia)"
    new_dash["creatore_id"] = "default"
    new_dash["created_at"] = datetime.now(timezone.utc)
    new_dash["updated_at"] = datetime.now(timezone.utc)

    result = await db.dashboards.insert_one(new_dash)
    return {"id": str(result.inserted_id), "message": "Dashboard duplicata"}


@router.delete("/{dashboard_id}")
async def delete_dashboard(dashboard_id: str):
    result = await db.dashboards.delete_one({"_id": ObjectId(dashboard_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Dashboard non trovata")
    return {"message": "Dashboard eliminata"}

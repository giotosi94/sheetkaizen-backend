from fastapi import APIRouter, HTTPException, Depends
from app.database import db
from app.models.action_plan import ActionPlanCreate, ActionPlanUpdate
from app.middleware.auth import get_current_user
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


@router.get("/")
async def get_action_plans(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == "user":
        query["$or"] = [
            {"reparto": current_user["reparto"]},
            {"responsabile_id": current_user["_id"]},
        ]

    plans = []
    cursor = db.action_plans.find(query).sort("data_scadenza", 1)
    async for plan in cursor:
        plan["_id"] = str(plan["_id"])
        plans.append(plan)
    return plans


@router.get("/my")
async def get_my_action_plans(current_user: dict = Depends(get_current_user)):
    plans = []
    cursor = db.action_plans.find({"responsabile_id": current_user["_id"]}).sort("data_scadenza", 1)
    async for plan in cursor:
        plan["_id"] = str(plan["_id"])
        plans.append(plan)
    return plans


@router.get("/overdue")
async def get_overdue_plans(current_user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    query = {"data_scadenza": {"$lt": now}, "stato": {"$ne": "Completato"}}
    if current_user["role"] == "user":
        query["reparto"] = current_user["reparto"]

    plans = []
    cursor = db.action_plans.find(query).sort("data_scadenza", 1)
    async for plan in cursor:
        plan["_id"] = str(plan["_id"])
        plans.append(plan)
    return plans


@router.get("/{plan_id}")
async def get_action_plan(plan_id: str, current_user: dict = Depends(get_current_user)):
    plan = await db.action_plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    plan["_id"] = str(plan["_id"])
    return plan


@router.post("/")
async def create_action_plan(plan: ActionPlanCreate, current_user: dict = Depends(get_current_user)):
    doc = {
        **plan.dict(),
        "data_emissione": datetime.now(timezone.utc),
        "data_completamento": None,
        "stato": "Da Fare",
        "allegati": [],
        "created_by": current_user["_id"],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.action_plans.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "Action Plan creato"}


@router.put("/{plan_id}")
async def update_action_plan(plan_id: str, update: ActionPlanUpdate, current_user: dict = Depends(get_current_user)):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    if update_data.get("stato") == "Completato" and "data_completamento" not in update_data:
        update_data["data_completamento"] = datetime.now(timezone.utc)

    result = await db.action_plans.update_one({"_id": ObjectId(plan_id)}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Action Plan aggiornato"}


@router.delete("/{plan_id}")
async def delete_action_plan(plan_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.action_plans.delete_one({"_id": ObjectId(plan_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Action Plan non trovato")
    return {"message": "Action Plan eliminato"}

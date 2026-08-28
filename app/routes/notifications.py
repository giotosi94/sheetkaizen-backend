from fastapi import APIRouter, Depends, HTTPException, Query
from app.database import db
from app.middleware.auth import get_current_user
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional


router = APIRouter()


def serialize_notification(notification: dict) -> dict:
    notification["_id"] = str(notification["_id"])

    if isinstance(notification.get("created_at"), datetime):
        notification["created_at"] = notification["created_at"].isoformat()

    if isinstance(notification.get("read_at"), datetime):
        notification["read_at"] = notification["read_at"].isoformat()

    return notification


@router.get("/")
async def get_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])

    query = {
        "user_id": user_id,
    }

    if unread_only:
        query["is_read"] = False

    notifications = []

    cursor = (
        db.notifications
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
    )

    async for notification in cursor:
        notifications.append(
            serialize_notification(notification)
        )

    unread_count = await db.notifications.count_documents({
        "user_id": user_id,
        "is_read": False,
    })

    return {
        "items": notifications,
        "unread_count": unread_count,
    }


@router.get("/unread-count")
async def get_unread_notification_count(
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])

    count = await db.notifications.count_documents({
        "user_id": user_id,
        "is_read": False,
    })

    return {
        "unread_count": count,
    }


@router.patch("/{notification_id}/read")
async def mark_notification_as_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
):
    try:
        object_id = ObjectId(notification_id)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Notifica ID non valido",
        )

    user_id = str(current_user["_id"])

    result = await db.notifications.update_one(
        {
            "_id": object_id,
            "user_id": user_id,
        },
        {
            "$set": {
                "is_read": True,
                "read_at": datetime.now(timezone.utc),
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Notifica non trovata",
        )

    return {
        "message": "Notifica letta",
    }


@router.patch("/read-all")
async def mark_all_notifications_as_read(
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user["_id"])
    now = datetime.now(timezone.utc)

    result = await db.notifications.update_many(
        {
            "user_id": user_id,
            "is_read": False,
        },
        {
            "$set": {
                "is_read": True,
                "read_at": now,
            }
        },
    )

    return {
        "message": "Notifiche lette",
        "updated_count": result.modified_count,
    }

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from app.database import db
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId
import io

router = APIRouter()


def get_bucket():
    return AsyncIOMotorGridFSBucket(db._db, bucket_name="uploads")


@router.post("/image")
async def upload_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Solo immagini sono accettate")

    bucket = get_bucket()
    contents = await file.read()

    if len(contents) > 10 * 1024 * 1024:  # max 10MB
        raise HTTPException(status_code=400, detail="Immagine troppo grande (max 10MB)")

    file_id = await bucket.upload_from_stream(
        file.filename,
        contents,
        metadata={"content_type": file.content_type},
    )

    return {
        "id": str(file_id),
        "filename": file.filename,
        "url": f"/api/uploads/image/{file_id}",
    }


@router.get("/image/{file_id}")
async def get_image(file_id: str):
    bucket = get_bucket()
    try:
        stream = await bucket.open_download_stream(ObjectId(file_id))
        content_type = stream.metadata.get("content_type", "image/jpeg") if stream.metadata else "image/jpeg"
        data = await stream.read()
        return StreamingResponse(io.BytesIO(data), media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Immagine non trovata")


@router.delete("/image/{file_id}")
async def delete_image(file_id: str):
    bucket = get_bucket()
    try:
        await bucket.delete(ObjectId(file_id))
        return {"message": "Immagine eliminata"}
    except Exception:
        raise HTTPException(status_code=404, detail="Immagine non trovata")
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

MAX_DOCUMENT_SIZE = 20 * 1024 * 1024


@router.post("/document")
async def upload_document(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Formato non supportato. Sono accettati PDF, Word ed Excel"
        )

    contents = await file.read()

    if len(contents) > MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Documento troppo grande (max 20 MB)"
        )

    bucket = get_bucket()

    file_id = await bucket.upload_from_stream(
        file.filename,
        contents,
        metadata={
            "content_type": file.content_type,
            "file_type": "document",
        },
    )

    return {
        "id": str(file_id),
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(contents),
        "url": f"/api/uploads/document/{file_id}",
    }


@router.get("/document/{file_id}")
async def get_document(file_id: str):
    bucket = get_bucket()

    try:
        stream = await bucket.open_download_stream(ObjectId(file_id))
        metadata = stream.metadata or {}
        content_type = metadata.get(
            "content_type",
            "application/octet-stream"
        )
        filename = stream.filename or "documento"
        data = await stream.read()

        headers = {
            "Content-Disposition": (
                f"inline; filename*=UTF-8''{quote(filename)}"
            )
        }

        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers=headers,
        )
    except Exception:
        raise HTTPException(
            status_code=404,
            detail="Documento non trovato"
        )


@router.delete("/document/{file_id}")
async def delete_document(file_id: str):
    bucket = get_bucket()

    try:
        await bucket.delete(ObjectId(file_id))
        return {"message": "Documento eliminato"}
    except Exception:
        raise HTTPException(
            status_code=404,
            detail="Documento non trovato"
        )

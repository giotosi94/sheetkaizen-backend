from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import io

from app.database import db
from app.models.documento import DocumentoCreate, DocumentoUpdate
from app.utils.compressor import compress_file

router = APIRouter()


def get_bucket():
    """Restituisce il bucket GridFS, garantendo connessione attiva."""
    db._ensure()
    return AsyncIOMotorGridFSBucket(db._db, bucket_name="documenti_files")


async def get_next_numero(tipo: str):
    """Genera codice progressivo tipo OPL-0001, SOP-0042."""
    prefix = tipo.upper()
    last = await db.documenti.find_one(
        {"tipo": tipo},
        sort=[("created_at", -1)]
    )
    if last and "numero" in last:
        try:
            num = int(last["numero"].split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"{prefix}-{num:04d}"


# ============================================================
# LIST + DETAIL
# ============================================================
@router.get("/")
async def get_documenti(
    tipo: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    reparto: Optional[str] = Query(None),
    stato: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    query = {"is_active": {"$ne": False}}
    if tipo:
        query["tipo"] = tipo
    if categoria:
        query["categoria"] = categoria
    if reparto:
        query["reparto"] = reparto
    if stato:
        query["stato"] = stato
    if search:
        query["$or"] = [
            {"titolo": {"$regex": search, "$options": "i"}},
            {"numero": {"$regex": search, "$options": "i"}},
            {"descrizione": {"$regex": search, "$options": "i"}},
        ]
    docs = []
    cursor = db.documenti.find(query).sort("created_at", -1)
    async for d in cursor:
        d["_id"] = str(d["_id"])
        docs.append(d)
    return docs


@router.get("/stats/summary")
async def get_stats():
    """Statistiche aggregate per la dashboard."""
    pipeline = [
        {"$match": {"is_active": {"$ne": False}}},
        {"$group": {
            "_id": {"tipo": "$tipo", "stato": "$stato"},
            "count": {"$sum": 1},
        }},
    ]
    results = {}
    async for item in db.documenti.aggregate(pipeline):
        tipo = item["_id"]["tipo"]
        stato = item["_id"]["stato"]
        if tipo not in results:
            results[tipo] = {}
        results[tipo][stato] = item["count"]
    return results


@router.get("/{documento_id}")
async def get_documento(documento_id: str):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    doc["_id"] = str(doc["_id"])
    return doc


# ============================================================
# UPLOAD (nuovo documento)
# ============================================================
@router.post("/upload")
async def upload_documento(
    file: UploadFile = File(...),
    titolo: str = Form(...),
    tipo: str = Form("OPL"),
    categoria: Optional[str] = Form(None),
    reparto: Optional[str] = Form(None),
    linea: Optional[str] = Form(None),
    macchina: Optional[str] = Form(None),
    autore: Optional[str] = Form(None),
    descrizione: Optional[str] = Form(None),
    tag: Optional[str] = Form(None),
    compress: bool = Form(True),
):
    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    original_size = len(contents)
    final_filename = file.filename
    compression_info = {}

    # 🗜️ COMPRESSIONE AUTOMATICA
    if compress:
        contents, final_filename, compression_info = compress_file(
            contents, file.filename, file.content_type or ""
        )

    bucket = get_bucket()
    file_id = await bucket.upload_from_stream(
        final_filename,
        contents,
        metadata={
            "content_type": file.content_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    numero = await get_next_numero(tipo)

    tag_list = []
    if tag:
        tag_list = [t.strip() for t in tag.split(",") if t.strip()]

    doc = {
        "numero": numero,
        "titolo": titolo,
        "tipo": tipo,
        "categoria": categoria,
        "reparto": reparto,
        "linea": linea,
        "macchina": macchina,
        "autore": autore,
        "descrizione": descrizione,
        "tag": tag_list,
        "stato": "Bozza",
        "versione": 1,
        "file_id": str(file_id),
        "file_name": final_filename,
        "file_name_originale": file.filename,
        "file_size": len(contents),
        "file_size_originale": original_size,
        "file_content_type": file.content_type,
        "compressione": compression_info,
        "versioni_precedenti": [],
        "kaizen_collegati": [],
        "source": "manual_upload",
        "sharepoint_path": None,
        "sharepoint_id": None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    result = await db.documenti.insert_one(doc)

    return {
        "id": str(result.inserted_id),
        "numero": numero,
        "message": f"Documento {numero} creato",
        "compressione": compression_info,
    }


# ============================================================
# UPLOAD NUOVA VERSIONE
# ============================================================
@router.post("/{documento_id}/upload-version")
async def upload_new_version(
    documento_id: str,
    file: UploadFile = File(...),
    compress: bool = Form(True),
):
    """Carica una nuova versione di un documento esistente."""
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    original_size = len(contents)
    final_filename = file.filename
    compression_info = {}

    # 🗜️ COMPRESSIONE AUTOMATICA
    if compress:
        contents, final_filename, compression_info = compress_file(
            contents, file.filename, file.content_type or ""
        )

    bucket = get_bucket()
    file_id = await bucket.upload_from_stream(
        final_filename,
        contents,
        metadata={
            "content_type": file.content_type,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    nuova_versione = doc.get("versione", 1) + 1
    versioni_precedenti = doc.get("versioni_precedenti", [])
    versioni_precedenti.append({
        "versione": doc.get("versione", 1),
        "file_id": doc.get("file_id"),
        "file_name": doc.get("file_name"),
        "data": doc.get("updated_at"),
    })

    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": {
            "versione": nuova_versione,
            "file_id": str(file_id),
            "file_name": final_filename,
            "file_name_originale": file.filename,
            "file_size": len(contents),
            "file_size_originale": original_size,
            "file_content_type": file.content_type,
            "compressione": compression_info,
            "versioni_precedenti": versioni_precedenti,
            "stato": "In Revisione",
            "updated_at": datetime.now(timezone.utc),
        }}
    )
    return {
        "message": f"Versione {nuova_versione} caricata",
        "compressione": compression_info,
    }


# ============================================================
# DOWNLOAD
# ============================================================
@router.get("/{documento_id}/file")
async def download_file(documento_id: str, download: bool = False):
    """
    Restituisce il file del documento.
    - download=true → Content-Disposition: attachment (forza download)
    - download=false (default) → inline (preview nel browser)
    """
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc or not doc.get("file_id"):
        raise HTTPException(status_code=404, detail="File non trovato")
    bucket = get_bucket()
    try:
        stream = await bucket.open_download_stream(ObjectId(doc["file_id"]))
        content_type = (
            stream.metadata.get("content_type", "application/octet-stream")
            if stream.metadata else "application/octet-stream"
        )
        data = await stream.read()
        disposition = "attachment" if download else "inline"
        filename = doc.get("file_name", "documento")
        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{filename}"',
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File non trovato: {str(e)}")


@router.get("/{documento_id}/version/{versione}")
async def download_version(documento_id: str, versione: int):
    """Scarica una versione precedente specifica del documento."""
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    if doc.get("versione") == versione:
        return await download_file(documento_id)
    versioni = doc.get("versioni_precedenti", [])
    target = next((v for v in versioni if v["versione"] == versione), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Versione {versione} non trovata")
    bucket = get_bucket()
    try:
        stream = await bucket.open_download_stream(ObjectId(target["file_id"]))
        content_type = (
            stream.metadata.get("content_type", "application/octet-stream")
            if stream.metadata else "application/octet-stream"
        )
        data = await stream.read()
        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{target.get("file_name", "documento")}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File non trovato: {str(e)}")


# ============================================================
# UPDATE + DELETE
# ============================================================
@router.put("/{documento_id}")
async def update_documento(documento_id: str, update: DocumentoUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    if update_data.get("stato") == "Approvato" and "data_approvazione" not in update_data:
        update_data["data_approvazione"] = datetime.now(timezone.utc)
    result = await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": update_data}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    return {"message": "Documento aggiornato"}


@router.delete("/{documento_id}")
async def delete_documento(documento_id: str):
    """Soft delete: nasconde documento ma mantiene file su GridFS."""
    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Documento disattivato"}

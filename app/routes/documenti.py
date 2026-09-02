from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional
import io
import os
import re
import json
import base64
import hmac
import hashlib
import time
from pydantic import BaseModel

from app.database import db
from app.models.documento import DocumentoCreate, DocumentoUpdate
from app.utils.compressor import compress_file
from app.middleware.auth import get_current_user
from app.services.opl_historical_importer import analyze_excel, trim_workbook

router = APIRouter()


PREVIEW_SECRET = os.getenv("PREVIEW_TOKEN_SECRET") or os.getenv("JWT_SECRET") or "change-me-preview-secret"


def generate_preview_token(documento_id: str, ttl_seconds: int = 300) -> str:
    expires = int(time.time()) + ttl_seconds
    payload = f"{documento_id}:{expires}"
    sig = hmac.new(PREVIEW_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def verify_preview_token(documento_id: str, token: str) -> bool:
    try:
        expires_str, sig = token.split(".", 1)
        expires = int(expires_str)
        if expires < time.time():
            return False
        payload = f"{documento_id}:{expires}"
        expected = hmac.new(PREVIEW_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def get_bucket():
    db._ensure()
    return AsyncIOMotorGridFSBucket(db._db, bucket_name="documenti_files")


async def get_next_numero(tipo: str):
    prefix = tipo.upper()
    max_number = 0
    cursor = db.documenti.find(
        {"tipo": tipo, "numero": {"$regex": f"^{prefix}-[0-9]+$", "$options": "i"}},
        {"numero": 1, "numero_progressivo": 1},
    )
    async for document in cursor:
        progressivo = document.get("numero_progressivo")
        if isinstance(progressivo, int):
            max_number = max(max_number, progressivo)
            continue
        match = re.fullmatch(rf"{re.escape(prefix)}-([0-9]+)", str(document.get("numero", "")), re.IGNORECASE)
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"{prefix}-{max_number + 1}"


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


def _require_admin(current_user: dict):
    role = str(current_user.get("role") or current_user.get("ruolo") or "").strip().lower()
    if role not in {"admin", "administrator", "amministratore"}:
        raise HTTPException(status_code=403, detail="Funzione riservata agli amministratori")


@router.get("/next-number/{tipo}")
async def get_next_document_number(tipo: str, current_user: dict = Depends(get_current_user)):
    if tipo.upper() == "OPL":
        _require_admin(current_user)
    numero = await get_next_numero(tipo.upper())
    return {"tipo": tipo.upper(), "numero": numero}


@router.post("/historical-opl/analyze")
async def analyze_historical_opl(
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    if not files:
        raise HTTPException(status_code=400, detail="Seleziona almeno un file Excel")
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Puoi analizzare massimo 10 file alla volta")

    results = []
    for file in files:
        filename = file.filename or "file.xlsx"
        extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if extension not in {"xlsx", "xlsm"}:
            results.append({"filename": filename, "error": "Formato non supportato. Usa .xlsx o .xlsm"})
            continue

        contents = await file.read()
        original_size = len(contents)
        if original_size > 50 * 1024 * 1024:
            results.append({"filename": filename, "error": "File troppo grande (max 50 MB)"})
            continue

        try:
            result = analyze_excel(contents, filename, include_preview=False)

            existing = None
            if result.get("numero"):
                existing = await db.documenti.find_one(
                    {"numero": result["numero"], "is_active": {"$ne": False}}, {"_id": 1}
                )

            result.update({
                "filename": filename,
                "original_size": original_size,
                "duplicate": existing is not None,
                "duplicate_id": str(existing["_id"]) if existing else None,
            })
            if existing:
                result.setdefault("warnings", []).append(f"Codifica {result['numero']} gia presente")
            results.append(result)
        except Exception as error:
            results.append({"filename": filename, "error": str(error)})

    next_number = await get_next_numero("OPL")
    return {
        "items": results,
        "count": len(results),
        "success": sum(1 for item in results if not item.get("error")),
        "errors": sum(1 for item in results if item.get("error")),
        "next_number": next_number,
        "mode": "analysis_only",
    }


@router.post("/historical-opl/import")
async def import_historical_opl(
    files: list[UploadFile] = File(...),
    items: str = Form(...),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)

    try:
        meta_list = json.loads(items)
    except Exception:
        raise HTTPException(status_code=400, detail="Dati non validi")

    meta_by_filename = {}
    for meta in meta_list:
        filename = (meta.get("filename") or "").strip()
        if filename:
            meta_by_filename[filename] = meta

    if not files or not meta_by_filename:
        raise HTTPException(status_code=400, detail="Nessuna OPL da importare")

    bucket = get_bucket()
    now = datetime.now(timezone.utc)
    created = []
    skipped = []

    for file in files:
        filename = file.filename or ""
        meta = meta_by_filename.get(filename)
        if not meta:
            continue

        numero = (meta.get("numero") or "").strip()
        if not numero:
            skipped.append({"filename": filename, "motivo": "Numero mancante"})
            continue

        esistente = await db.documenti.find_one(
            {"numero": numero, "is_active": {"$ne": False}},
            {"_id": 1},
        )
        if esistente:
            skipped.append({"numero": numero, "motivo": "Codifica gia presente"})
            continue

        contents = await file.read()
        original_size = len(contents)

        try:
            trimmed = trim_workbook(contents, meta.get("sheet") or "")
        except Exception:
            trimmed = contents

        final_filename = f"{numero}.xlsx"
        compression_info = {}
        try:
            trimmed, final_filename, compression_info = compress_file(
                trimmed,
                f"{numero}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        except Exception:
            compression_info = {}

        file_id = await bucket.upload_from_stream(
            final_filename,
            trimmed,
            metadata={
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "uploaded_at": now.isoformat(),
                "source": "historical_excel_import",
            },
        )

        progressivo = meta.get("numero_progressivo")
        if not isinstance(progressivo, int):
            match = re.fullmatch(r"OPL-([0-9]+)", numero, re.IGNORECASE)
            progressivo = int(match.group(1)) if match else None

        doc = {
            "numero": numero,
            "numero_progressivo": progressivo,
            "numero_originale": meta.get("numero_originale") or numero,
            "titolo": meta.get("titolo") or numero,
            "tipo": "OPL",
            "formato": "excel_storico",
            "categoria": meta.get("area_opl") or "Produzione",
            "reparto": meta.get("reparto"),
            "linea": meta.get("linea"),
            "macchina": None,
            "autore": None,
            "descrizione": "",
            "tag": ["opl-storica"],
            "stato": "Approvato",
            "versione": 1,
            "file_id": str(file_id),
            "file_name": final_filename,
            "file_name_originale": filename,
            "file_size": len(trimmed),
            "file_size_originale": original_size,
            "file_content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "compressione": compression_info,
            "opl_data": {
                "area_opl_label": meta.get("area_opl") or None,
                "tipo_opl_label": meta.get("tipo_opl") or None,
                "data_documento": meta.get("data_documento") or None,
            },
            "versioni_precedenti": [],
            "kaizen_collegati": [],
            "source": "historical_excel_import",
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        result = await db.documenti.insert_one(doc)
        created.append({"id": str(result.inserted_id), "numero": numero})

    next_number = await get_next_numero("OPL")
    return {
        "created": created,
        "skipped": skipped,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "next_number": next_number,
    }


@router.get("/{documento_id}")
async def get_documento(documento_id: str):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    doc["_id"] = str(doc["_id"])
    return doc


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
        "numero_progressivo": int(numero.split("-", 1)[1]) if numero.split("-", 1)[1].isdigit() else None,
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


@router.post("/{documento_id}/upload-version")
async def upload_new_version(
    documento_id: str,
    file: UploadFile = File(...),
    compress: bool = Form(True),
):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    contents = await file.read()
    if len(contents) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    original_size = len(contents)
    final_filename = file.filename
    compression_info = {}

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
            "is_active": True,
            "updated_at": datetime.now(timezone.utc),
        }}
    )
    return {
        "message": f"Versione {nuova_versione} caricata",
        "compressione": compression_info,
    }


@router.post("/bulk-upload")
async def bulk_upload_documenti(
    files: list[UploadFile] = File(...),
    autore: Optional[str] = Form(None),
    compress: bool = Form(True),
):
    if not files:
        raise HTTPException(status_code=400, detail="Nessun file ricevuto")

    results = {
        "totale": len(files),
        "creati": [],
        "aggiornati": [],
        "errori": [],
        "risparmio_totale_bytes": 0,
    }

    pattern_smart = r"(?i)\b(OPL|SOP|PROC|IST)\b[\s_\-]*(\d{1,5})"
    tipo_map = {"OPL": "OPL", "SOP": "SOP", "PROC": "Procedura", "IST": "Istruzione"}

    for file in files:
        try:
            contents = await file.read()
            if len(contents) > 50 * 1024 * 1024:
                results["errori"].append({
                    "filename": file.filename,
                    "errore": "File troppo grande (max 50MB)"
                })
                continue

            original_size = len(contents)

            filename_no_ext = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
            ext = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "pdf"

            match = re.search(pattern_smart, filename_no_ext)

            if match:
                tipo_raw = match.group(1).upper()
                tipo = tipo_map.get(tipo_raw, "OPL")
                numero_estratto = match.group(2)
                numero_completo = f"{tipo_raw}-{numero_estratto.zfill(3)}"

                titolo_raw = re.sub(pattern_smart, "", filename_no_ext, count=1)
                titolo_raw = re.sub(r"^[\s_\-]+", "", titolo_raw)
                titolo = re.sub(r"\s+", " ", titolo_raw.replace("_", " ")).strip()

                if not titolo:
                    titolo = filename_no_ext.replace("_", " ").strip()

                auto_parsed = True
            else:
                tipo = "OPL"
                titolo = filename_no_ext.replace("_", " ").replace("-", " ").strip()
                numero_completo = await get_next_numero(tipo)
                auto_parsed = False

            bucket = get_bucket()

            esistente = await db.documenti.find_one({"numero": numero_completo})

            final_filename = file.filename
            compression_info = {}
            if compress:
                contents, final_filename, compression_info = compress_file(
                    contents, file.filename, file.content_type or ""
                )

            results["risparmio_totale_bytes"] += (original_size - len(contents))

            file_id = await bucket.upload_from_stream(
                final_filename,
                contents,
                metadata={
                    "content_type": file.content_type,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "source": "bulk_upload",
                }
            )

            if esistente:
                nuova_versione = esistente.get("versione", 1) + 1
                versioni_precedenti = esistente.get("versioni_precedenti", [])
                versioni_precedenti.append({
                    "versione": esistente.get("versione", 1),
                    "file_id": esistente.get("file_id"),
                    "file_name": esistente.get("file_name"),
                    "data": esistente.get("updated_at"),
                })

                await db.documenti.update_one(
                    {"_id": esistente["_id"]},
                    {"$set": {
                        "versione": nuova_versione,
                        "file_id": str(file_id),
                        "file_name": final_filename,
                        "file_name_originale": file.filename,
                        "file_size": len(contents),
                        "file_size_originale": original_size,
                        "compressione": compression_info,
                        "versioni_precedenti": versioni_precedenti,
                        "stato": "Bozza",
                        "is_active": True,
                        "updated_at": datetime.now(timezone.utc),
                    }}
                )
                results["aggiornati"].append({
                    "filename": file.filename,
                    "numero": numero_completo,
                    "titolo": titolo,
                    "versione": nuova_versione,
                    "compressione": compression_info,
                })
            else:
                doc = {
                    "numero": numero_completo,
                    "titolo": titolo,
                    "tipo": tipo,
                    "categoria": "Da classificare",
                    "reparto": "",
                    "linea": "",
                    "macchina": "",
                    "autore": autore or "Bulk Upload",
                    "descrizione": "",
                    "tag": ["bulk-import"] + (["auto-parsed"] if auto_parsed else ["manual-title"]),
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
                    "source": "bulk_upload",
                    "sharepoint_path": None,
                    "sharepoint_id": None,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
                result = await db.documenti.insert_one(doc)
                results["creati"].append({
                    "filename": file.filename,
                    "numero": numero_completo,
                    "titolo": titolo,
                    "id": str(result.inserted_id),
                    "auto_parsed": auto_parsed,
                    "compressione": compression_info,
                })

        except Exception as e:
            results["errori"].append({
                "filename": file.filename,
                "errore": str(e)
            })

    results["risparmio_totale_mb"] = round(results["risparmio_totale_bytes"] / 1024 / 1024, 2)
    results["successo"] = len(results["creati"]) + len(results["aggiornati"])
    results["fallimenti"] = len(results["errori"])

    return results


@router.post("/{documento_id}/preview-token")
async def create_preview_token(documento_id: str, user=Depends(get_current_user)):
    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Documento non trovato")
    token = generate_preview_token(documento_id, ttl_seconds=300)
    return {"token": token, "expires_in": 300, "documento_id": documento_id}


async def _serve_preview(documento_id: str, token: str):
    if not verify_preview_token(documento_id, token):
        raise HTTPException(status_code=401, detail="Token preview non valido o scaduto")

    doc = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not doc or not doc.get("file_id"):
        raise HTTPException(status_code=404, detail="File non trovato")
    return doc


@router.get("/{documento_id}/preview.{ext}")
async def preview_file_with_ext(documento_id: str, ext: str, token: str = Query(...)):
    doc = await _serve_preview(documento_id, token)

    bucket = get_bucket()
    try:
        stream = await bucket.open_download_stream(ObjectId(doc["file_id"]))
        data = await stream.read()
        filename = doc.get("file_name", f"documento.{ext}")
        content_type_map = {
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt": "application/vnd.ms-powerpoint",
        }
        content_type = content_type_map.get(ext.lower())
        if not content_type and stream.metadata:
            content_type = stream.metadata.get("content_type", "application/octet-stream")
        if not content_type:
            content_type = "application/octet-stream"
        return StreamingResponse(
            io.BytesIO(data),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Access-Control-Allow-Origin": "*",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "public, max-age=300",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File non trovato: {str(e)}")


@router.get("/{documento_id}/file")
async def download_file(documento_id: str, download: bool = False):
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
    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Documento disattivato"}


class OplNativaPayload(BaseModel):
    titolo: str
    area_opl_id: Optional[str] = None
    area_opl_label: Optional[str] = None
    tipo_opl_id: Optional[str] = None
    tipo_opl_label: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    autore: Optional[str] = None
    problema: Optional[str] = ""
    causa: Optional[str] = ""
    miglioramento: Optional[str] = ""
    immagine_base64: Optional[str] = None
    verifica_1: Optional[str] = ""
    verifica_2: Optional[str] = ""
    verifica_3: Optional[str] = ""


@router.post("/opl-nativa")
async def create_opl_nativa(payload: OplNativaPayload):
    numero = await get_next_numero("OPL")

    file_id = None
    file_size = 0
    if payload.immagine_base64:
        try:
            b64 = payload.immagine_base64
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            file_size = len(img_bytes)
            if file_size > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Immagine troppo grande (max 5MB)")
            bucket = get_bucket()
            file_id = await bucket.upload_from_stream(
                f"{numero}_immagine.jpg",
                img_bytes,
                metadata={
                    "content_type": "image/jpeg",
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "source": "opl_nativa",
                },
            )
            file_id = str(file_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Errore immagine: {str(e)}")

    doc = {
        "numero": numero,
        "titolo": payload.titolo,
        "tipo": "OPL",
        "formato": "nativa",
        "categoria": payload.area_opl_label or "Operativa",
        "reparto": payload.reparto,
        "linea": payload.linea,
        "macchina": payload.macchina,
        "autore": payload.autore or "Utente LPW",
        "descrizione": (payload.miglioramento or "")[:200],
        "tag": ["opl-nativa"],
        "stato": "Bozza",
        "versione": 1,
        "numero_progressivo": int(numero.split("-", 1)[1]),
        "file_id": file_id,
        "file_name": f"{numero}_immagine.jpg" if file_id else None,
        "file_size": file_size,
        "file_content_type": "image/jpeg" if file_id else None,
        "opl_data": {
            "area_opl_id": payload.area_opl_id,
            "area_opl_label": payload.area_opl_label,
            "tipo_opl_id": payload.tipo_opl_id,
            "tipo_opl_label": payload.tipo_opl_label,
            "problema": payload.problema or "",
            "causa": payload.causa or "",
            "miglioramento": payload.miglioramento or "",
            "verifica_1": payload.verifica_1 or "",
            "verifica_2": payload.verifica_2 or "",
            "verifica_3": payload.verifica_3 or "",
        },
        "versioni_precedenti": [],
        "kaizen_collegati": [],
        "source": "opl_nativa_form",
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.documenti.insert_one(doc)
    created = await db.documenti.find_one({"_id": result.inserted_id})
    created["_id"] = str(created["_id"])
    return created


@router.put("/opl-nativa/{documento_id}")
async def update_opl_nativa(documento_id: str, payload: OplNativaPayload):
    existing = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="OPL non trovata")

    file_id = existing.get("file_id")
    file_size = existing.get("file_size", 0)
    if payload.immagine_base64 and not payload.immagine_base64.startswith("__existing"):
        try:
            b64 = payload.immagine_base64
            if b64.startswith("data:"):
                b64 = b64.split(",", 1)[1]
            img_bytes = base64.b64decode(b64)
            file_size = len(img_bytes)
            if file_size > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Immagine troppo grande (max 5MB)")
            bucket = get_bucket()
            new_id = await bucket.upload_from_stream(
                f"{existing.get('numero','OPL')}_immagine.jpg",
                img_bytes,
                metadata={
                    "content_type": "image/jpeg",
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                    "source": "opl_nativa_update",
                },
            )
            file_id = str(new_id)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Errore immagine: {str(e)}")

    updates = {
        "titolo": payload.titolo,
        "categoria": payload.area_opl_label or existing.get("categoria"),
        "reparto": payload.reparto,
        "linea": payload.linea,
        "macchina": payload.macchina,
        "autore": payload.autore or existing.get("autore"),
        "descrizione": (payload.miglioramento or "")[:200],
        "file_id": file_id,
        "file_size": file_size,
        "opl_data": {
            "area_opl_id": payload.area_opl_id,
            "area_opl_label": payload.area_opl_label,
            "tipo_opl_id": payload.tipo_opl_id,
            "tipo_opl_label": payload.tipo_opl_label,
            "problema": payload.problema or "",
            "causa": payload.causa or "",
            "miglioramento": payload.miglioramento or "",
            "verifica_1": payload.verifica_1 or "",
            "verifica_2": payload.verifica_2 or "",
            "verifica_3": payload.verifica_3 or "",
        },
        "updated_at": datetime.now(timezone.utc),
    }

    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": updates},
    )
    updated = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    updated["_id"] = str(updated["_id"])
    return updated


class OplAnnotationsPayload(BaseModel):
    annotations: list = []


@router.patch("/{documento_id}/opl-annotations")
async def update_opl_annotations(documento_id: str, payload: OplAnnotationsPayload):
    existing = await db.documenti.find_one({"_id": ObjectId(documento_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="OPL non trovata")

    opl_data = existing.get("opl_data", {}) or {}
    opl_data["annotations"] = payload.annotations or []

    await db.documenti.update_one(
        {"_id": ObjectId(documento_id)},
        {"$set": {
            "opl_data": opl_data,
            "updated_at": datetime.now(timezone.utc),
        }}
    )
    return {"message": "Annotazioni salvate", "count": len(payload.annotations or [])}


from fastapi import Request


@router.post("/sharepoint-import")
async def import_from_sharepoint(request: Request):
    data = await request.json()

    expected_key = os.getenv("SHAREPOINT_API_KEY", "")
    if not expected_key or data.get("api_key") != expected_key:
        raise HTTPException(status_code=401, detail="API key non valida")

    filename = data.get("filename", "")
    file_b64 = data.get("file_content_base64", "")
    sharepoint_url = data.get("sharepoint_url", "")
    uploaded_by = data.get("uploaded_by", "SharePoint Auto")

    if not filename or not file_b64:
        raise HTTPException(status_code=400, detail="filename e file_content_base64 obbligatori")

    pattern = r"^(OPL|SOP)-(\d{4}-\d+)_(.+)\.(pdf|docx|xlsx|pptx|png|jpg|jpeg)$"
    match = re.match(pattern, filename, re.IGNORECASE)

    if not match:
        raise HTTPException(
            status_code=400,
            detail=f"Nome file non valido. Atteso formato: TIPO-ANNO-NUM_Titolo.ext. Ricevuto: {filename}"
        )

    tipo = match.group(1).upper()
    numero_part = match.group(2)
    titolo_raw = match.group(3)
    estensione = match.group(4).lower()

    titolo = titolo_raw.replace("_", " ").strip()
    numero_completo = f"{tipo}-{numero_part}"

    esistente = await db.documenti.find_one({"numero": numero_completo})
    nuova_versione = 1
    versioni_precedenti = []

    if esistente:
        nuova_versione = esistente.get("versione", 1) + 1
        versioni_precedenti = esistente.get("versioni_precedenti", [])
        versioni_precedenti.append({
            "versione": esistente.get("versione", 1),
            "file_id": esistente.get("file_id"),
            "file_name": esistente.get("file_name"),
            "data": esistente.get("updated_at"),
        })

    try:
        file_bytes = base64.b64decode(file_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64 non valido: {str(e)}")

    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")

    original_size = len(file_bytes)
    final_filename = filename
    compression_info = {}

    file_bytes, final_filename, compression_info = compress_file(file_bytes, filename, "")

    bucket = get_bucket()
    file_id = await bucket.upload_from_stream(
        final_filename,
        file_bytes,
        metadata={
            "content_type": f"application/{estensione}",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "source": "sharepoint_auto",
        }
    )

    if esistente:
        await db.documenti.update_one(
            {"_id": esistente["_id"]},
            {"$set": {
                "versione": nuova_versione,
                "file_id": str(file_id),
                "file_name": final_filename,
                "file_name_originale": filename,
                "file_size": len(file_bytes),
                "file_size_originale": original_size,
                "compressione": compression_info,
                "versioni_precedenti": versioni_precedenti,
                "stato": "Bozza",
                "sharepoint_url": sharepoint_url,
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        return {
            "success": True,
            "documento_id": str(esistente["_id"]),
            "numero": numero_completo,
            "versione": nuova_versione,
            "azione": "nuova_versione",
            "messaggio": f"Documento {numero_completo} aggiornato a v{nuova_versione}"
        }
    else:
        doc = {
            "numero": numero_completo,
            "titolo": titolo,
            "tipo": tipo,
            "categoria": "Da classificare",
            "reparto": "",
            "linea": "",
            "macchina": "",
            "tag": ["auto-import", "sharepoint"],
            "autore": uploaded_by,
            "versione": 1,
            "stato": "Bozza",
            "file_id": str(file_id),
            "file_name": final_filename,
            "file_name_originale": filename,
            "file_size": len(file_bytes),
            "file_size_originale": original_size,
            "compressione": compression_info,
            "versioni_precedenti": [],
            "kaizen_collegati": [],
            "source": "sharepoint_auto",
            "sharepoint_url": sharepoint_url,
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = await db.documenti.insert_one(doc)
        return {
            "success": True,
            "documento_id": str(result.inserted_id),
            "numero": numero_completo,
            "versione": 1,
            "azione": "creato",
            "messaggio": f"Documento {numero_completo} importato"
        }

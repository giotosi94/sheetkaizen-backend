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
# BULK SMART UPLOAD — Upload multiplo con auto-parsing nomi
# ============================================================
import re

@router.post("/bulk-upload")
async def bulk_upload_documenti(
    files: list[UploadFile] = File(...),
    autore: Optional[str] = Form(None),
    compress: bool = Form(True),
):
    """
    Carica N file in batch.
    Auto-estrae tipo/numero/titolo dal nome file con convenzione:
      TIPO-ANNO-NUM_Titolo_Documento.ext
      Es: OPL-2026-001_Pulizia_Filtro_Bindler.pdf
    
    Se il nome NON rispetta la convenzione, usa il filename come titolo
    e assegna numero progressivo automatico.
    
    Se il numero esiste già → crea nuova versione automaticamente.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Nessun file ricevuto")

    results = {
        "totale": len(files),
        "creati": [],
        "aggiornati": [],  # nuove versioni
        "errori": [],
        "risparmio_totale_bytes": 0,
    }
    
    # Pattern per parsing nome file
    pattern = r"^(OPL|SOP|PROC|IST)-(\d{4})-(\d+)_(.+?)\.(pdf|docx|xlsx|pptx|png|jpg|jpeg|doc|xls|ppt)$"
    
    bucket = get_bucket()
    
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
            
            # 🔍 Parsing nome file
            match = re.match(pattern, file.filename, re.IGNORECASE)
            
            if match:
                # ✅ Nome conforme — estrai metadati
                tipo_raw = match.group(1).upper()
                tipo_map = {"OPL": "OPL", "SOP": "SOP", "PROC": "Procedura", "IST": "Istruzione"}
                tipo = tipo_map.get(tipo_raw, "OPL")
                
                anno = match.group(2)
                num = match.group(3)
                titolo_raw = match.group(4)
                titolo = titolo_raw.replace("_", " ").strip()
                numero_completo = f"{tipo_raw}-{anno}-{num}"
                auto_parsed = True
            else:
                # ⚠️ Nome non conforme — usa filename come titolo
                tipo = "OPL"
                titolo = file.filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
                numero_completo = await get_next_numero(tipo)
                auto_parsed = False
            
            # 🔍 Controllo duplicati
            esistente = await db.documenti.find_one({"numero": numero_completo})
            
            # 🗜️ Compressione
            final_filename = file.filename
            compression_info = {}
            if compress:
                contents, final_filename, compression_info = compress_file(
                    contents, file.filename, file.content_type or ""
                )
            
            results["risparmio_totale_bytes"] += (original_size - len(contents))
            
            # 💾 Salva file su GridFS
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
                # 🔄 NUOVA VERSIONE
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
                # ➕ NUOVO DOCUMENTO
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
    
    # 📊 Riepilogo finale
    results["risparmio_totale_mb"] = round(results["risparmio_totale_bytes"] / 1024 / 1024, 2)
    results["successo"] = len(results["creati"]) + len(results["aggiornati"])
    results["fallimenti"] = len(results["errori"])
    
    return results

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

# ============================================================
# AUTO-IMPORT DA SHAREPOINT (Power Automate)
# ============================================================
import os
import re
import base64
from fastapi import Request

@router.post("/sharepoint-import")
async def import_from_sharepoint(request: Request):
    """
    Endpoint chiamato da Power Automate quando viene caricato 
    un file nella cartella SharePoint monitorata.
    
    Convenzione naming file:
      OPL-2025-001_Titolo_Documento.pdf
      SOP-2025-014_Avviamento_Linea_3.docx
    
    Body JSON atteso:
    {
      "filename": "OPL-2025-001_Titolo.pdf",
      "file_content_base64": "JVBERi0xLjQK...",
      "sharepoint_url": "https://lindt.sharepoint.com/.../file.pdf",
      "uploaded_by": "giovanni.tosi@lindt.it",
      "api_key": "SHEETKAIZEN_SECRET_KEY"
    }
    """
    data = await request.json()
    
    # 🔐 Verifica API key
    expected_key = os.getenv("SHAREPOINT_API_KEY", "")
    if not expected_key or data.get("api_key") != expected_key:
        raise HTTPException(status_code=401, detail="API key non valida")
    
    filename = data.get("filename", "")
    file_b64 = data.get("file_content_base64", "")
    sharepoint_url = data.get("sharepoint_url", "")
    uploaded_by = data.get("uploaded_by", "SharePoint Auto")
    
    if not filename or not file_b64:
        raise HTTPException(
            status_code=400, 
            detail="filename e file_content_base64 obbligatori"
        )
    
    # 📝 Parse del nome file: TIPO-ANNO-NUM_Titolo.ext
    pattern = r"^(OPL|SOP)-(\d{4}-\d+)_(.+)\.(pdf|docx|xlsx|pptx|png|jpg|jpeg)$"
    match = re.match(pattern, filename, re.IGNORECASE)
    
    if not match:
        raise HTTPException(
            status_code=400,
            detail=f"Nome file non valido. Atteso formato: TIPO-ANNO-NUM_Titolo.ext (es: OPL-2025-001_Pulizia.pdf). Ricevuto: {filename}"
        )
    
    tipo = match.group(1).upper()
    numero_part = match.group(2)  # es: 2025-001
    titolo_raw = match.group(3)
    estensione = match.group(4).lower()
    
    titolo = titolo_raw.replace("_", " ").strip()
    numero_completo = f"{tipo}-{numero_part}"
    
    # 🔍 Controllo duplicati → se esiste, nuova versione
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
    
    # 📦 Decode base64
    try:
        file_bytes = base64.b64decode(file_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Base64 non valido: {str(e)}")
    
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File troppo grande (max 50MB)")
    
    original_size = len(file_bytes)
    final_filename = filename
    compression_info = {}
    
    # 🗜️ COMPRESSIONE AUTOMATICA
    file_bytes, final_filename, compression_info = compress_file(
        file_bytes, filename, ""
    )
    
    # 💾 Salva su GridFS
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
        # 🔄 UPDATE documento esistente (nuova versione)
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
                "stato": "Bozza",  # richiede ri-approvazione
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
        # ➕ CREATE nuovo documento
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

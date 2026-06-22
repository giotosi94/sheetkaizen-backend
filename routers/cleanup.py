"""
🗑️ CLEANUP TEMPORANEO — Rimuovere dopo l'uso
=============================================
Endpoint per pulire le collezioni vecchie prima del refactoring Settings.
Da chiamare 1 volta via Swagger, poi cancellare questo file.
"""
from fastapi import APIRouter, HTTPException
from database import db  # ← adatta l'import al tuo pattern (vedi nota sotto)

router = APIRouter(prefix="/cleanup", tags=["🗑️ Cleanup (TEMP)"])


@router.delete("/configurazioni")
async def cleanup_configurazioni():
    """Cancella TUTTI i record dalla collezione 'configurazioni'."""
    result = await db.configurazioni.delete_many({})
    return {
        "ok": True,
        "collezione": "configurazioni",
        "eliminati": result.deleted_count,
    }


@router.delete("/reparti")
async def cleanup_reparti():
    """Cancella TUTTI i record dalla collezione 'reparti'."""
    result = await db.reparti.delete_many({})
    return {
        "ok": True,
        "collezione": "reparti",
        "eliminati": result.deleted_count,
    }

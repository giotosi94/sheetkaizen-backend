from fastapi import APIRouter, Depends
from datetime import datetime, timezone

from app.database import db
from app.middleware.auth import get_current_user

router = APIRouter()


DEFAULT_AREA_OPL = [
    {"codice": "PROD", "label": "Produzione", "icon": "🏭", "color": "#3B82F6", "ordine": 1},
    {"codice": "QUAL", "label": "Qualità", "icon": "✅", "color": "#10B981", "ordine": 2},
    {"codice": "SICUR", "label": "Sicurezza", "icon": "🛡️", "color": "#EF4444", "ordine": 3},
]

DEFAULT_TIPO_OPL = [
    {"codice": "CONOSC", "label": "Conoscenza Base", "descrizione": "OPL informativa su procedure o standard esistenti", "icon": "📘", "color": "#6366F1", "ordine": 1},
    {"codice": "PROBL", "label": "Problema", "descrizione": "OPL creata a seguito di un problema riscontrato", "icon": "⚠️", "color": "#F59E0B", "ordine": 2},
    {"codice": "MIGLIO", "label": "Miglioramento", "descrizione": "OPL per condividere un miglioramento adottato", "icon": "💡", "color": "#10B981", "ordine": 3},
]


async def _upsert_config(tipo: str, item: dict):
    """Inserisce una configurazione solo se non esiste già (per codice)."""
    existing = await db.configurazioni.find_one({"tipo": tipo, "codice": item["codice"]})
    if existing:
        return {"codice": item["codice"], "created": False}
    doc = {
        "tipo": tipo,
        "codice": item["codice"],
        "label": item["label"],
        "descrizione": item.get("descrizione", ""),
        "icon": item.get("icon"),
        "color": item.get("color"),
        "parent_id": None,
        "parent_tipo": None,
        "ordine": item.get("ordine", 0),
        "attivo": True,
        "is_terminal": False,
        "metadata": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "created_by": "Setup OPL",
    }
    await db.configurazioni.insert_one(doc)
    return {"codice": item["codice"], "created": True}


@router.post("/setup-opl-configs")
async def setup_opl_configs(user=Depends(get_current_user)):
    """
    Endpoint one-shot per inserire le configurazioni base delle OPL Native.
    Idempotente: se già presenti, non le duplica.
    Chiamalo UNA SOLA VOLTA dopo il deploy.
    """
    results = {"area_opl": [], "tipo_opl": []}
    for item in DEFAULT_AREA_OPL:
        r = await _upsert_config("area_opl", item)
        results["area_opl"].append(r)
    for item in DEFAULT_TIPO_OPL:
        r = await _upsert_config("tipo_opl", item)
        results["tipo_opl"].append(r)
    return {
        "message": "Setup OPL completato",
        "results": results,
    }

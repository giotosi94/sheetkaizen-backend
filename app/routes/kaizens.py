from fastapi import APIRouter, HTTPException, Depends
from app.database import database
from app.models.kaizen import KaizenCreate, KaizenUpdate
from app.middleware.auth import get_current_user
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter()


async def get_next_numero():
    last = await db.kaizens.find_one(sort=[("created_at", -1)])
    if last and "numero" in last:
        try:
            num = int(last["numero"].split("-")[1]) + 1
        except (IndexError, ValueError):
            num = 1
    else:
        num = 1
    return f"RCA-{num:04d}"


@router.get("/")
async def get_kaizens(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == "user":
        query["reparto"] = current_user["reparto"]

    kaizens = []
    cursor = db.kaizens.find(query).sort("created_at", -1)
    async for k in cursor:
        k["_id"] = str(k["_id"])
        kaizens.append(k)
    return kaizens


@router.get("/{kaizen_id}")
async def get_kaizen(kaizen_id: str, current_user: dict = Depends(get_current_user)):
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    kaizen["_id"] = str(kaizen["_id"])
    return kaizen


@router.post("/")
async def create_kaizen(kaizen: KaizenCreate, current_user: dict = Depends(get_current_user)):
    numero = await get_next_numero()

    doc = {
        "numero": numero,
        "titolo": kaizen.titolo,
        "tipo": kaizen.tipo,
        "stato": "Aperto",
        "creatore_id": current_user["_id"],
        "creatore_nome": current_user["full_name"],
        "partecipanti": kaizen.partecipanti,
        "reparto": kaizen.reparto,
        "linea": kaizen.linea,
        "macchina": kaizen.macchina,
        "posto": kaizen.posto,
        "attrezzatura": kaizen.attrezzatura,
        "team": kaizen.team,
        "hashtag": kaizen.hashtag,
        "data_apertura": datetime.now(timezone.utc),
        "data_chiusura": None,
        "passo1_definizione": {
            "immagini": [],
            "che_cosa": "", "dove": "", "quando": "",
            "chi": "", "quale": "", "come": "",
        },
        "passo2_cause_probabili": {
            "people": [], "environment": [], "material": [],
            "measurement": [], "methods": [], "machine": [],
            "effetto": "",
        },
        "passo3_causa_radice": {
            "causa_probabile": "",
            "why_chain": [],
            "causa_radice_finale": "",
        },
        "piani_azione_immediati": [],
        "verifica_processo": {
            "condizioni_base_rispettate": {"valore": "", "osservazioni": ""},
            "conoscenza_macchina_processo": {"valore": "", "osservazioni": ""},
            "standard_esistenti": {"valore": "", "osservazioni": ""},
            "standard_chiari": {"valore": "", "osservazioni": ""},
            "standard_applicati": {"valore": "", "osservazioni": ""},
            "persone_conoscono_standard": {"valore": "", "osservazioni": ""},
        },
        "passo4_piani_azione": [],
        "fase5_valutazione_efficacia": {"osservazioni": "", "efficace": ""},
        "fase6_standardizzazione": {"osservazioni": "", "standard_creati": [], "replicato_su": []},
        "lavagna": "",
        "feed": [{
            "utente": current_user["full_name"],
            "azione": "Kaizen creato",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        "campi_custom": {},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.kaizens.insert_one(doc)
    return {"id": str(result.inserted_id), "numero": numero, "message": "Kaizen creato"}


@router.put("/{kaizen_id}")
async def update_kaizen(kaizen_id: str, update: KaizenUpdate, current_user: dict = Depends(get_current_user)):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    feed_entry = {
        "utente": current_user["full_name"],
        "azione": "Kaizen aggiornato",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    result = await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {"$set": update_data, "$push": {"feed": feed_entry}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    return {"message": "Kaizen aggiornato"}


@router.delete("/{kaizen_id}")
async def delete_kaizen(kaizen_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.kaizens.delete_one({"_id": ObjectId(kaizen_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    return {"message": "Kaizen eliminato"}

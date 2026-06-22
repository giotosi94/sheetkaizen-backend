from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.kaizen import KaizenCreate, KaizenUpdate, PromotePayload, LinkChildPayload, LIVELLI_KAIZEN
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

router = APIRouter()


# ============================================================
# UTILS
# ============================================================
def get_prefix(livello: str) -> str:
    """Prefisso numero basato sul livello."""
    if livello == "Quick":
        return "QK"
    elif livello == "Standard":
        return "STD"
    elif livello == "Major":
        return "MAJ"
    return "RCA"  # fallback per kaizen vecchi senza livello


async def get_next_numero(livello: str = "Quick"):
    """Genera numero progressivo per livello (es. QK-0001, STD-0042, MAJ-0007)."""
    prefix = get_prefix(livello)
    
    # Cerca l'ultimo kaizen con stesso prefisso
    last = await db.kaizens.find_one(
        {"numero": {"$regex": f"^{prefix}-"}},
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


def normalize_livello(livello: Optional[str], tipo: Optional[str]) -> str:
    """Normalizza il livello. Se non specificato, prova a dedurlo dal tipo."""
    if livello and livello in LIVELLI_KAIZEN:
        return livello
    if tipo:
        # Backward compat: kaizen vecchi usavano "Quick Kaizen" come tipo
        if "Quick" in tipo:
            return "Quick"
        if "Standard" in tipo:
            return "Standard"
        if "Major" in tipo:
            return "Major"
    return "Quick"


def serialize(doc: dict) -> dict:
    """Converte ObjectId in stringhe per il JSON."""
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    # parent_kaizen_id potrebbe già essere stringa o ObjectId
    if doc.get("parent_kaizen_id"):
        doc["parent_kaizen_id"] = str(doc["parent_kaizen_id"])
    return doc


# ============================================================
# LIST + DETAIL
# ============================================================
@router.get("/")
async def get_kaizens(
    livello: Optional[str] = Query(None),
    stato: Optional[str] = Query(None),
    reparto: Optional[str] = Query(None),
    parent_kaizen_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    """Lista kaizen con filtri opzionali (livello, stato, reparto, padre)."""
    query = {}
    if livello:
        query["livello"] = livello
    if stato:
        query["stato"] = stato
    if reparto:
        query["reparto"] = reparto
    if parent_kaizen_id is not None:
        # "null" string = solo kaizen senza padre (top-level)
        query["parent_kaizen_id"] = None if parent_kaizen_id == "null" else parent_kaizen_id
    if search:
        query["$or"] = [
            {"titolo": {"$regex": search, "$options": "i"}},
            {"numero": {"$regex": search, "$options": "i"}},
        ]
    
    kaizens = []
    cursor = db.kaizens.find(query).sort("created_at", -1)
    async for k in cursor:
        kaizens.append(serialize(k))
    return kaizens


@router.get("/{kaizen_id}")
async def get_kaizen(kaizen_id: str):
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    return serialize(kaizen)


# ============================================================
# CREATE
# ============================================================
@router.post("/")
async def create_kaizen(kaizen: KaizenCreate):
    # Normalizza livello
    livello = normalize_livello(kaizen.livello, kaizen.tipo)
    
    # Genera numero col prefisso giusto (QK/STD/MAJ)
    numero = await get_next_numero(livello)
    
    # Validazione gerarchia: solo Standard/Major possono avere figli
    # (cioè un Quick non può essere padre di altri Kaizen)
    if kaizen.parent_kaizen_id:
        parent = await db.kaizens.find_one({"_id": ObjectId(kaizen.parent_kaizen_id)})
        if not parent:
            raise HTTPException(status_code=400, detail="Parent Kaizen non trovato")
        parent_livello = parent.get("livello") or normalize_livello(None, parent.get("tipo"))
        if parent_livello == "Quick":
            raise HTTPException(
                status_code=400,
                detail="Un Quick Kaizen non può essere genitore di altri Kaizen"
            )

    doc = {
        "numero": numero,
        "titolo": kaizen.titolo,
        "livello": livello,
        "tipo": kaizen.tipo or f"{livello} Kaizen",
        "stato": "Aperto",
        "creatore_id": "default",
        "creatore_nome": "Default User",
        "partecipanti": kaizen.partecipanti,
        "reparto": kaizen.reparto,
        "linea": kaizen.linea,
        "macchina": kaizen.macchina,
        "posto": kaizen.posto,
        "attrezzatura": kaizen.attrezzatura,
        "team": kaizen.team,
        "hashtag": kaizen.hashtag,
        
        # Gerarchia
        "parent_kaizen_id": kaizen.parent_kaizen_id,
        "children_kaizen_ids": [],
        
        # Tipo perdita + categoria
        "tipo_perdita": kaizen.tipo_perdita,
        "categoria": kaizen.categoria,
        
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
        
        # Sezioni che si attiveranno per Standard/Major (vuote per ora)
        "standard_elements": None,
        "countermeasure_ladder": None,
        "step1_kpi_definition": None,
        "step2_pareto_analysis": None,
        "step3_target_definition": None,
        "step4_project_implementation": None,
        "step5_close_the_loop": None,
        "gantt": None,
        "cost_benefit": None,
        
        "lavagna": "",
        "feed": [{
            "utente": "Default User",
            "azione": f"{livello} Kaizen creato",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
        "campi_custom": {},
        
        # Storico promozioni/demozioni
        "livello_storia": [{
            "livello": livello,
            "quando": datetime.now(timezone.utc).isoformat(),
            "utente": "Default User",
            "motivo": "Creazione iniziale",
        }],
        
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    result = await db.kaizens.insert_one(doc)
    
    # Se ha un padre, aggiungilo alla lista children del padre
    if kaizen.parent_kaizen_id:
        await db.kaizens.update_one(
            {"_id": ObjectId(kaizen.parent_kaizen_id)},
            {"$push": {"children_kaizen_ids": str(result.inserted_id)},
             "$set": {"updated_at": datetime.now(timezone.utc)}}
        )
    
    return {"id": str(result.inserted_id), "numero": numero, "livello": livello, "message": "Kaizen creato"}


# ============================================================
# UPDATE
# ============================================================
@router.put("/{kaizen_id}")
async def update_kaizen(kaizen_id: str, update: KaizenUpdate):
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)

    feed_entry = {
        "utente": "Default User",
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


# ============================================================
# 🆕 PROMOTE / DEMOTE — Kaizen Polimorfico
# ============================================================
@router.patch("/{kaizen_id}/promote")
async def promote_kaizen(kaizen_id: str, payload: PromotePayload):
    """Promuove un Kaizen al livello successivo (Quick→Standard, Standard→Major)."""
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    livello_attuale = kaizen.get("livello") or normalize_livello(None, kaizen.get("tipo"))
    
    promotion_map = {"Quick": "Standard", "Standard": "Major"}
    nuovo_livello = promotion_map.get(livello_attuale)
    
    if not nuovo_livello:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile promuovere: {livello_attuale} è già il livello massimo"
        )
    
    # Aggiorna livello + traccia storia
    storia_entry = {
        "livello": nuovo_livello,
        "livello_precedente": livello_attuale,
        "quando": datetime.now(timezone.utc).isoformat(),
        "utente": "Default User",
        "motivo": payload.motivo or f"Promossa a {nuovo_livello}",
        "azione": "PROMOTE",
    }
    
    feed_entry = {
        "utente": "Default User",
        "azione": f"⬆️ Promosso a {nuovo_livello} Kaizen",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {
            "$set": {
                "livello": nuovo_livello,
                "tipo": f"{nuovo_livello} Kaizen",
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"livello_storia": storia_entry, "feed": feed_entry},
        }
    )
    
    return {"message": f"Promosso a {nuovo_livello}", "nuovo_livello": nuovo_livello}


@router.patch("/{kaizen_id}/demote")
async def demote_kaizen(kaizen_id: str, payload: PromotePayload):
    """Riporta un Kaizen al livello precedente (Major→Standard, Standard→Quick)."""
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    livello_attuale = kaizen.get("livello") or normalize_livello(None, kaizen.get("tipo"))
    
    demotion_map = {"Major": "Standard", "Standard": "Quick"}
    nuovo_livello = demotion_map.get(livello_attuale)
    
    if not nuovo_livello:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile retrocedere: {livello_attuale} è già il livello minimo"
        )
    
    # Se demoting da Major→Standard, controllo che non abbia figli Standard
    if livello_attuale == "Major":
        children_ids = kaizen.get("children_kaizen_ids", [])
        for child_id in children_ids:
            try:
                child = await db.kaizens.find_one({"_id": ObjectId(child_id)})
                if child and child.get("livello") == "Standard":
                    raise HTTPException(
                        status_code=400,
                        detail="Impossibile retrocedere: ha figli Standard Kaizen. Rimuovili prima."
                    )
            except Exception:
                continue
    
    storia_entry = {
        "livello": nuovo_livello,
        "livello_precedente": livello_attuale,
        "quando": datetime.now(timezone.utc).isoformat(),
        "utente": "Default User",
        "motivo": payload.motivo or f"Retrocesso a {nuovo_livello}",
        "azione": "DEMOTE",
    }
    
    feed_entry = {
        "utente": "Default User",
        "azione": f"⬇️ Retrocesso a {nuovo_livello} Kaizen",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {
            "$set": {
                "livello": nuovo_livello,
                "tipo": f"{nuovo_livello} Kaizen",
                "updated_at": datetime.now(timezone.utc),
            },
            "$push": {"livello_storia": storia_entry, "feed": feed_entry},
        }
    )
    
    return {"message": f"Retrocesso a {nuovo_livello}", "nuovo_livello": nuovo_livello}


# ============================================================
# 🆕 GERARCHIA — Children + Link/Unlink
# ============================================================
@router.get("/{kaizen_id}/children")
async def get_children(kaizen_id: str):
    """Restituisce la lista dei Kaizen figli."""
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    children_ids = kaizen.get("children_kaizen_ids", [])
    if not children_ids:
        return []
    
    children = []
    for cid in children_ids:
        try:
            child = await db.kaizens.find_one({"_id": ObjectId(cid)})
            if child:
                children.append(serialize(child))
        except Exception:
            continue
    return children


@router.post("/{kaizen_id}/link-child")
async def link_child(kaizen_id: str, payload: LinkChildPayload):
    """Aggancia un Kaizen esistente come figlio di questo."""
    parent = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not parent:
        raise HTTPException(status_code=404, detail="Parent Kaizen non trovato")
    
    parent_livello = parent.get("livello") or normalize_livello(None, parent.get("tipo"))
    if parent_livello == "Quick":
        raise HTTPException(status_code=400, detail="Un Quick Kaizen non può avere figli")
    
    child = await db.kaizens.find_one({"_id": ObjectId(payload.child_kaizen_id)})
    if not child:
        raise HTTPException(status_code=404, detail="Child Kaizen non trovato")
    
    # Aggiunge figlio al padre
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {"$addToSet": {"children_kaizen_ids": payload.child_kaizen_id},
         "$set": {"updated_at": datetime.now(timezone.utc)}}
    )
    # Imposta il padre nel figlio
    await db.kaizens.update_one(
        {"_id": ObjectId(payload.child_kaizen_id)},
        {"$set": {"parent_kaizen_id": kaizen_id, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"message": "Kaizen figlio collegato"}


@router.delete("/{kaizen_id}/link-child/{child_id}")
async def unlink_child(kaizen_id: str, child_id: str):
    """Scollega un Kaizen figlio."""
    await db.kaizens.update_one(
        {"_id": ObjectId(kaizen_id)},
        {"$pull": {"children_kaizen_ids": child_id},
         "$set": {"updated_at": datetime.now(timezone.utc)}}
    )
    await db.kaizens.update_one(
        {"_id": ObjectId(child_id)},
        {"$set": {"parent_kaizen_id": None, "updated_at": datetime.now(timezone.utc)}}
    )
    return {"message": "Kaizen figlio scollegato"}


# ============================================================
# 🆕 ACTION PLAN — Lista AP collegati al Kaizen
# ============================================================
@router.get("/{kaizen_id}/action-plans")
async def get_kaizen_action_plans(kaizen_id: str):
    """Restituisce tutti gli Action Plan collegati a questo Kaizen.
    Considera sia il campo legacy 'kaizen_id' che i links polimorfici.
    """
    plans = []
    
    # 1. Cerca AP che hanno kaizen_id = questo kaizen (campo legacy)
    cursor = db.action_plans.find({
        "kaizen_id": kaizen_id,
        "is_active": {"$ne": False}
    }).sort("created_at", -1)
    async for p in cursor:
        p["_id"] = str(p["_id"])
        plans.append(p)
    
    # 2. Cerca AP che hanno un link polimorfico verso questo kaizen
    cursor = db.action_plans.find({
        "links": {"$elemMatch": {"entity_type": "kaizen", "entity_id": kaizen_id}},
        "is_active": {"$ne": False}
    }).sort("created_at", -1)
    async for p in cursor:
        p_id = str(p["_id"])
        # Evita duplicati se l'AP è collegato in entrambi i modi
        if not any(existing["_id"] == p_id for existing in plans):
            p["_id"] = p_id
            plans.append(p)
    
    return plans


# ============================================================
# DELETE
# ============================================================
@router.delete("/{kaizen_id}")
async def delete_kaizen(kaizen_id: str):
    kaizen = await db.kaizens.find_one({"_id": ObjectId(kaizen_id)})
    if not kaizen:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    
    # Se ha un padre, rimuove il riferimento dal padre
    parent_id = kaizen.get("parent_kaizen_id")
    if parent_id:
        try:
            await db.kaizens.update_one(
                {"_id": ObjectId(parent_id)},
                {"$pull": {"children_kaizen_ids": kaizen_id}}
            )
        except Exception:
            pass
    
    # Se ha figli, li libera (li rende top-level)
    children_ids = kaizen.get("children_kaizen_ids", [])
    for cid in children_ids:
        try:
            await db.kaizens.update_one(
                {"_id": ObjectId(cid)},
                {"$set": {"parent_kaizen_id": None}}
            )
        except Exception:
            continue
    
    result = await db.kaizens.delete_one({"_id": ObjectId(kaizen_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Kaizen non trovato")
    return {"message": "Kaizen eliminato"}

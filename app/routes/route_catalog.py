from fastapi import APIRouter, HTTPException, Query
from app.database import db
from app.models.route_catalog import RouteCatalogCreate, RouteCatalogUpdate
from bson import ObjectId
from datetime import datetime, timezone
from typing import Optional

router = APIRouter()


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/")
async def get_routes(
    stato: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    plant_id: Optional[str] = Query(None),
):
    query = {}
    if stato:
        query["stato"] = stato
    if scope:
        query["scope"] = scope
    if plant_id:
        query["$or"] = [{"plant_id": plant_id}, {"scope": "corporate"}]
    routes = []
    cursor = db.route_catalog.find(query).sort("nome", 1)
    async for r in cursor:
        routes.append(serialize(r))
    return routes


@router.get("/{route_id}")
async def get_route(route_id: str):
    route = await db.route_catalog.find_one({"_id": ObjectId(route_id)})
    if not route:
        raise HTTPException(status_code=404, detail="Route non trovata")
    return serialize(route)


@router.post("/")
async def create_route(route: RouteCatalogCreate):
    doc = route.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = datetime.now(timezone.utc)
    result = await db.route_catalog.insert_one(doc)
    created = await db.route_catalog.find_one({"_id": result.inserted_id})
    return serialize(created)


@router.put("/{route_id}")
async def update_route(route_id: str, update: RouteCatalogUpdate):
    existing = await db.route_catalog.find_one({"_id": ObjectId(route_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Route non trovata")
    if existing.get("stato") == "pubblicata":
        raise HTTPException(
            status_code=400,
            detail="Una Route pubblicata non e modificabile. Duplicala come nuova versione.",
        )
    update_data = {k: v for k, v in update.model_dump(exclude_none=True).items()}
    update_data["updated_at"] = datetime.now(timezone.utc)
    await db.route_catalog.update_one(
        {"_id": ObjectId(route_id)},
        {"$set": update_data},
    )
    updated = await db.route_catalog.find_one({"_id": ObjectId(route_id)})
    return serialize(updated)


@router.post("/{route_id}/duplicate")
async def duplicate_route(route_id: str, nuova_versione: str = Query(...)):
    existing = await db.route_catalog.find_one({"_id": ObjectId(route_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Route non trovata")
    clone = {k: v for k, v in existing.items() if k != "_id"}
    clone["versione"] = nuova_versione
    clone["stato"] = "bozza"
    clone["created_at"] = datetime.now(timezone.utc)
    clone["updated_at"] = datetime.now(timezone.utc)
    result = await db.route_catalog.insert_one(clone)
    created = await db.route_catalog.find_one({"_id": result.inserted_id})
    return serialize(created)


@router.patch("/{route_id}/stato")
async def change_stato(route_id: str, stato: str = Query(...)):
    validi = ["bozza", "in_revisione", "pubblicata", "archiviata"]
    if stato not in validi:
        raise HTTPException(status_code=400, detail=f"Stato non valido. Usa uno di: {', '.join(validi)}")
    result = await db.route_catalog.update_one(
        {"_id": ObjectId(route_id)},
        {"$set": {"stato": stato, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Route non trovata")
    return {"message": f"Stato aggiornato a {stato}"}


@router.delete("/{route_id}")
async def delete_route(route_id: str):
    existing = await db.route_catalog.find_one({"_id": ObjectId(route_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Route non trovata")
    if existing.get("stato") == "pubblicata":
        raise HTTPException(status_code=400, detail="Non eliminare una Route pubblicata. Archiviala.")
    await db.route_catalog.delete_one({"_id": ObjectId(route_id)})
    return {"message": "Route eliminata"}


SCRAP_REDUCTION_ROUTE = {
    "codice": "process_scrap_reduction",
    "nome": "Process Scrap Reduction | Riduzione Scarti di Processo",
    "descrizione": "Route completa per la riduzione strutturata degli scarti di processo secondo il ciclo Definire-Ripristinare-Misurare-Stabilizzare-Ottimizzare-Sostenere.",
    "versione": "1.0",
    "scope": "corporate",
    "plant_id": None,
    "stato": "pubblicata",
    "steps": [
        {
            "step_id": "step_1",
            "ordine": 1,
            "titolo": "Definire",
            "obiettivo": "Definire chiaramente il problema, identificare le principali categorie di scarto, selezionare la priorita e formalizzare baseline e target.",
            "componente": "scrap_baseline",
            "durata_stimata": "1 settimana",
            "istruzioni": "Descrivi il problema, definisci il perimetro, mappa operazioni e tipologie di scarto, importa dati storici, costruisci il Pareto, seleziona lo scarto prioritario, definisci baseline e target.",
            "metodologie": ["Gemba Walk", "Pareto", "Stratificazione", "Analisi dati", "Process Mapping"],
            "output_obbligatori": ["Problema", "Perimetro", "KPI principale", "Unita di misura", "Baseline", "Target", "Periodo", "Fonte dati", "Pareto", "Categoria prioritaria"],
            "ruoli": ["Project Leader", "Sponsor"],
            "gate": {
                "titolo": "Gate 1",
                "criteri": ["Fenomeno misurato", "Fonte dati dichiarata", "Baseline presente", "Target presente", "Priorita selezionata"],
                "approvatori": ["Project Leader", "Sponsor"],
            },
        },
        {
            "step_id": "step_2",
            "ordine": 2,
            "titolo": "Ripristinare",
            "obiettivo": "Eliminare le anomalie evidenti, ripristinare le condizioni di base e definire il primo standard affidabile.",
            "componente": "basic_conditions",
            "durata_stimata": "1-2 settimane",
            "istruzioni": "Osserva il processo sul Gemba, formalizza la migliore pratica attuale, registra anomalie e tag, ripristina le condizioni originali, definisci standard di pulizia e ispezione, forma gli operatori.",
            "metodologie": ["Gemba Walk", "Tagging", "4M / 5M", "5 Perche", "Centerlining", "OPL", "Checklist pulizia e ispezione", "TWI", "Skill Matrix"],
            "output_obbligatori": ["Elenco anomalie", "Registro tag", "Fotografie prima e dopo", "Action Plan di ripristino", "Parametri critici", "Standard corrente", "Evidenza di formazione"],
            "ruoli": ["Process Owner", "Pillar Coach"],
            "gate": {
                "titolo": "Gate 2",
                "criteri": ["Anomalie critiche eliminate o pianificate", "Condizioni di base ripristinate", "Standard iniziale disponibile", "Baseline nuovamente misurata"],
                "approvatori": ["Process Owner", "Pillar Coach"],
            },
        },
        {
            "step_id": "step_3",
            "ordine": 3,
            "titolo": "Misurare",
            "obiettivo": "Introdurre un sistema affidabile e continuativo di registrazione degli scarti e delle deviazioni dallo standard.",
            "componente": "scrap_event_register",
            "durata_stimata": "2-3 settimane",
            "istruzioni": "Definisci cosa rappresenta un'anomalia, chi misura, cosa e quando registrare, collega ogni evento allo scarto generato, forma gli operatori, verifica quotidianamente la qualita della raccolta.",
            "metodologie": ["Standard Work", "Visual Management", "Data Collection Plan", "TWI", "Daily Review"],
            "output_obbligatori": ["Regola di registrazione", "Responsabilita", "Registro eventi", "Dati di scarto", "Registro anomalie", "Frequenza di revisione", "Evidenza di avvio raccolta", "Livello di completezza dati"],
            "ruoli": ["Project Leader", "Data Owner"],
            "gate": {
                "titolo": "Gate 3",
                "criteri": ["Sistema attivo", "Operatori formati", "Dati registrati correttamente", "Dati sufficienti per l'analisi"],
                "approvatori": ["Project Leader"],
            },
        },
        {
            "step_id": "step_4",
            "ordine": 4,
            "titolo": "Stabilizzare",
            "obiettivo": "Analizzare le anomalie prioritarie, identificare cause radice, implementare contromisure e verificare la non ricorrenza.",
            "componente": "anomaly_analysis",
            "durata_stimata": "3-4 settimane",
            "istruzioni": "Costruisci il Pareto delle anomalie, seleziona le prioritarie, analizza e valida le cause radice, definisci contromisure, crea Action Plan, collega Quick e Standard Kaizen, implementa e verifica.",
            "metodologie": ["Pareto", "Ishikawa", "5 Perche", "4M / 5M", "Matrice causa-effetto", "Stratificazione", "Test sperimentali", "Quick Kaizen", "Standard Kaizen"],
            "output_obbligatori": ["Pareto anomalie", "Analisi delle cause", "Cause radice validate", "Contromisure", "Action Plan", "Quick o Standard Kaizen collegati", "Risultati dei test", "Tabella delle ricorrenze", "Verifica di non ricorrenza"],
            "ruoli": ["Process Owner", "Subject Matter Expert"],
            "gate": {
                "titolo": "Gate 4",
                "criteri": ["Almeno una causa radice validata", "Contromisure implementate", "Riduzione misurabile delle anomalie", "Verifica di non ricorrenza"],
                "approvatori": ["Process Owner", "Subject Matter Expert"],
            },
        },
        {
            "step_id": "step_5",
            "ordine": 5,
            "titolo": "Ottimizzare",
            "obiettivo": "Migliorare ulteriormente il metodo applicando ECRS e riducendo attivita, tempi e scarti non necessari.",
            "componente": "ecrs_analysis",
            "durata_stimata": "2-3 settimane",
            "istruzioni": "Analizza le attivita che generano scarto, registra tempo e quantita, classifica le attivita, applica ECRS, definisci il metodo futuro, confronta prima e dopo, aggiorna lo standard.",
            "metodologie": ["ECRS", "Motion Analysis", "Time Study", "Standard Work", "SMED", "Visual Management"],
            "output_obbligatori": ["Tabella attivita", "Classificazione ECRS", "Opportunita di miglioramento", "Action Plan", "Metodo futuro", "Confronto prima/dopo", "Standard aggiornato", "Target aggiornato"],
            "ruoli": ["Project Leader", "Process Owner"],
            "gate": {
                "titolo": "Gate 5",
                "criteri": ["Metodo futuro definito", "Azioni completate", "Standard aggiornato", "Risultato confermato su piu eventi"],
                "approvatori": ["Project Leader", "Process Owner"],
            },
        },
        {
            "step_id": "step_6",
            "ordine": 6,
            "titolo": "Sostenere",
            "obiettivo": "Standardizzare il nuovo metodo, completare la formazione, confermare risultati e saving e introdurre un sistema di controllo nel tempo.",
            "componente": "sustainment_plan",
            "durata_stimata": "2-4 settimane",
            "istruzioni": "Completa gli Action Plan, aggiorna procedure e standard, crea OPL e checklist, forma gli operatori, verifica le competenze, definisci il Control Plan, registra il KPI finale, valida il saving, approva la chiusura.",
            "metodologie": ["OPL", "Checklist", "Visual Management", "Training Matrix", "Control Plan"],
            "output_obbligatori": ["Action Plan completati", "Standard definitivo", "OPL collegate", "Checklist", "Evidenze di formazione", "Training Matrix aggiornata", "KPI finale", "Saving previsto", "Saving verificato", "Control Plan", "Verifica efficacia", "Verifica di sostenibilita"],
            "ruoli": ["Project Leader", "Process Owner", "Sponsor"],
            "gate": {
                "titolo": "Gate finale",
                "criteri": ["Action Plan obbligatori chiusi", "KPI finale registrato", "Confronto baseline-target-finale", "Standard approvato", "Formazione completata", "Competenze verificate", "Risultato sostenuto per il periodo definito", "Saving validato"],
                "approvatori": ["Project Leader", "Process Owner", "Sponsor"],
            },
        },
    ],
}


@router.post("/seed")
async def seed_routes():
    existing = await db.route_catalog.find_one({
        "codice": SCRAP_REDUCTION_ROUTE["codice"],
        "versione": SCRAP_REDUCTION_ROUTE["versione"],
    })
    if existing:
        return {
            "message": "Route gia presente, nessuna azione eseguita",
            "route_id": str(existing["_id"]),
            "already_existed": True,
        }
    doc = dict(SCRAP_REDUCTION_ROUTE)
    doc["created_at"] = datetime.now(timezone.utc)
    doc["updated_at"] = datetime.now(timezone.utc)
    result = await db.route_catalog.insert_one(doc)
    return {
        "message": "Route Riduzione Scarti v1.0 creata",
        "route_id": str(result.inserted_id),
        "already_existed": False,
    }

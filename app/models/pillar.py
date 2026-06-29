from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


# ============================================================
# SUB-MODELS — 5 Step KPI Management
# ============================================================
class Step1KPIDefinition(BaseModel):
    """STEP 1 — Definizione KPI/KMI del pillar per l'anno."""
    completato: bool = False
    note: Optional[str] = ""
    # Lista KPI assegnati al pillar (referenze a tipi_perdita o testo libero)
    kpis: List[Dict[str, Any]] = []
    # Esempio elemento KPI:
    # {
    #   "id": "uuid",
    #   "label": "OEE",
    #   "tipo_perdita_id": "67abc..." (opzionale, link a Settings),
    #   "baseline": 65.0,
    #   "target": 75.0,
    #   "unit": "%",
    #   "owner": "Rota",
    #   "note": "..."
    # }


class Step2ParetoAnalysis(BaseModel):
    """STEP 2 — Analisi Pareto delle perdite per ogni KPI."""
    completato: bool = False
    note: Optional[str] = ""
    # Lista perdite identificate (top losses)
    losses: List[Dict[str, Any]] = []
    # Esempio elemento loss:
    # {
    #   "id": "uuid",
    #   "kpi_id": "uuid del KPI step1",
    #   "label": "Microfermate",
    #   "percent_impact": 35.0,
    #   "magnitude": "alto",  # alto/medio/basso
    #   "note": "..."
    # }
    # Allegati opzionali (Pareto chart)
    allegati: List[Dict[str, str]] = []


class Step3TargetDefinition(BaseModel):
    """STEP 3 — Definizione target + assegnazione progetti."""
    completato: bool = False
    note: Optional[str] = ""
    # Lista progetti (kaizen) assegnati per chiudere il gap
    progetti: List[Dict[str, Any]] = []
    # Esempio elemento progetto:
    # {
    #   "id": "uuid",
    #   "kaizen_id": "67abc..." (link al Kaizen),
    #   "kaizen_numero": "MAJ-0001",
    #   "kaizen_titolo": "...",
    #   "loss_target": "uuid del loss step2",
    #   "saving_atteso": 12000.0,
    #   "deadline": "2026-06-30"
    # }


class Step4Implementation(BaseModel):
    """STEP 4 — Monitoring esecuzione."""
    completato: bool = False
    note: Optional[str] = ""
    # Stato avanzamento (calcolato da Kaizen children)
    snapshot_at: Optional[datetime] = None


class Step5CloseTheLoop(BaseModel):
    """STEP 5 — Bridge chart e gap analysis."""
    completato: bool = False
    note: Optional[str] = ""
    # Bridge chart: per ogni KPI confronto baseline → planned → actual
    bridge_data: List[Dict[str, Any]] = []
    # Esempio:
    # {
    #   "kpi_id": "uuid",
    #   "label": "OEE",
    #   "baseline_year": 65.0,
    #   "planned_savings": 10.0,
    #   "actual_savings": 8.5,
    #   "gap": -1.5,
    #   "gap_reason": "Microfermate B11 non risolte completamente"
    # }
    lezioni_apprese: Optional[str] = ""


# ============================================================
# MAIN MODELS
# ============================================================
class PillarCreate(BaseModel):
    sigla: str  # es: "FI", "AM", "PM"
    label: str  # es: "Focused Improvement"
    descrizione: Optional[str] = ""
    icon: Optional[str] = None
    icon_image: Optional[str] = None  # 🆕 base64 dell'immagine
    color: Optional[str] = None
    
    # Leader e team
    leader: Optional[str] = None
    leader_id: Optional[str] = None  # 🆕 ID utente
    leader_email: Optional[str] = None
    members: List[str] = []  # lista nomi (legacy + cache)
    members_ids: List[str] = []  # 🆕 IDs degli utenti membri
    
    # Anno corrente di riferimento
    anno: Optional[int] = None  # se vuoto, usa anno corrente
    
    # Note iniziali
    note: Optional[str] = ""
    
    # 🆕 Calendario presenze (opzionale)
    presenze_config: Optional[Dict[str, Any]] = None


class PillarUpdate(BaseModel):
    sigla: Optional[str] = None
    label: Optional[str] = None
    descrizione: Optional[str] = None
    icon: Optional[str] = None
    icon_image: Optional[str] = None  # 🆕 base64 dell'immagine
    color: Optional[str] = None
    
    leader: Optional[str] = None
    leader_id: Optional[str] = None  # 🆕
    leader_email: Optional[str] = None
    members: Optional[List[str]] = None
    members_ids: Optional[List[str]] = None  # 🆕
    
    anno: Optional[int] = None
    note: Optional[str] = None
    
    # 5 Step KPI Management (tutti opzionali, si aggiornano singolarmente)
    step1_kpi_definition: Optional[Dict[str, Any]] = None
    step2_pareto_analysis: Optional[Dict[str, Any]] = None
    step3_target_definition: Optional[Dict[str, Any]] = None
    step4_implementation: Optional[Dict[str, Any]] = None
    step5_close_the_loop: Optional[Dict[str, Any]] = None

    # 🆕 Analisi multiple (lista di 5-step indipendenti)
    analyses: Optional[List[Dict[str, Any]]] = None
    
    # 🆕 Master Plan multi-anno (timeline trimestrale)
    gantt_items: Optional[List[Dict[str, Any]]] = None
    
    # Maturity Grid (futuro F-X)
    maturity_grid: Optional[Dict[str, Any]] = None
    
    # 🆕 Calendario presenze riunioni pillar
    presenze_config: Optional[Dict[str, Any]] = None
    
    # Stato pillar
    attivo: Optional[bool] = None


class LinkKaizenToPillarPayload(BaseModel):
    """Payload per linkare/dissociare un kaizen al pillar."""
    kaizen_id: str
    kaizen_numero: Optional[str] = None
    kaizen_titolo: Optional[str] = None

from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


# Livelli ufficiali Lindt FI Pillar
# Improvement Idea (futuro) → Quick → Standard → Major
LIVELLI_KAIZEN = ["Quick", "Standard", "Major"]


class KaizenCreate(BaseModel):
    titolo: str
    
    # 🆕 livello principale (Quick/Standard/Major)
    # Manteniamo anche "tipo" per backward compatibility
    livello: Optional[str] = "Quick"
    tipo: Optional[str] = None  # se vuoto, useremo livello come tipo
    
    reparto: str
    linea: Optional[str] = None
    macchina: Optional[str] = None
    posto: Optional[str] = None
    attrezzatura: Optional[str] = None
    team: Optional[str] = None
    hashtag: List[str] = []
    partecipanti: List[str] = []
    
    # 🆕 Gerarchia: kaizen padre (per Quick figli di Major/Standard)
    parent_kaizen_id: Optional[str] = None
    
    # 🆕 Tipo perdita TPM (riferimento alle Settings)
    tipo_perdita: Optional[str] = None
    categoria: Optional[str] = None


class KaizenUpdate(BaseModel):
    titolo: Optional[str] = None
    stato: Optional[str] = None
    livello: Optional[str] = None       # 🆕
    tipo: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    posto: Optional[str] = None
    attrezzatura: Optional[str] = None
    team: Optional[str] = None
    hashtag: Optional[List[str]] = None
    partecipanti: Optional[List[str]] = None
    data_chiusura: Optional[datetime] = None
    
    # 🆕 Tipo perdita TPM + categoria
    tipo_perdita: Optional[str] = None
    categoria: Optional[str] = None
    
    # 🆕 Gerarchia (per linkare/slinkare un padre)
    parent_kaizen_id: Optional[str] = None
    
    # Sezioni Quick Kaizen (esistenti)
    passo1_definizione: Optional[Dict[str, Any]] = None
    passo2_cause_probabili: Optional[Dict[str, Any]] = None
    passo3_causa_radice: Optional[Dict[str, Any]] = None
    piani_azione_immediati: Optional[List[Dict[str, Any]]] = None
    verifica_processo: Optional[Dict[str, Any]] = None
    passo4_piani_azione: Optional[List[str]] = None
    fase5_valutazione_efficacia: Optional[Dict[str, Any]] = None
    fase6_standardizzazione: Optional[Dict[str, Any]] = None
    lavagna: Optional[str] = None
    campi_custom: Optional[Dict[str, Any]] = None
    
    # 🆕 Sezioni speciali Standard/Major (le useremo nelle prossime fasi)
    
    # 8 Standard Elements scoring (Quick/Standard/Major)
    standard_elements: Optional[Dict[str, Any]] = None
    
    # Countermeasure Ladder (livello 1-6 Lindt)
    countermeasure_ladder: Optional[Dict[str, Any]] = None
    
    # 5 Step KPI Management (solo Major)
    step1_kpi_definition: Optional[Dict[str, Any]] = None
    step2_pareto_analysis: Optional[Dict[str, Any]] = None
    step3_target_definition: Optional[Dict[str, Any]] = None
    step4_project_implementation: Optional[Dict[str, Any]] = None
    step5_close_the_loop: Optional[Dict[str, Any]] = None
    
    # Gantt (Standard/Major)
    gantt: Optional[Dict[str, Any]] = None
    
    # Cost & Benefit (Major)
    cost_benefit: Optional[Dict[str, Any]] = None


# 🆕 Payload per cambio metodologia (Quick ↔ Standard ↔ Major)
class ChangeMethodologyPayload(BaseModel):
    nuovo_livello: str  # "Quick", "Standard", o "Major"
    motivo: Optional[str] = None  # opzionale ma consigliato


# 🆕 Payload legacy per promote/demote (manteniamo per backward compat)
class PromotePayload(BaseModel):
    motivo: Optional[str] = None


# 🆕 Payload per linkare un Kaizen figlio
class LinkChildPayload(BaseModel):
    child_kaizen_id: str

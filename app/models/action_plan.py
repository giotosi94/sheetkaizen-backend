from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ============================================================
# TIPI (str per supportare valori dinamici configurabili dalle Settings)
# ============================================================
TIPO_AP = str
PRIORITA = str
STATO = str


# ============================================================
# SUB-MODELS
# ============================================================
class ChecklistItem(BaseModel):
    id: Optional[str] = None
    testo: str
    completato: bool = False
    completato_da: Optional[str] = None
    completato_at: Optional[datetime] = None


class Commento(BaseModel):
    id: Optional[str] = None
    autore: str
    autore_avatar: Optional[str] = None
    testo: str
    mentions: List[str] = []
    timestamp: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    reactions: List[dict] = []


class Allegato(BaseModel):
    tipo: Literal["image", "file", "link"]
    url: str
    nome: str
    size: Optional[int] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class LinkEntita(BaseModel):
    """Link polimorfico verso qualsiasi entita dell'app."""
    entity_type: Literal["kaizen", "documento", "dashboard", "action_plan", "url"]
    entity_id: str
    entity_label: Optional[str] = None
    link_type: Optional[str] = "related_to"


# ============================================================
# CREATE
# ============================================================
class ActionPlanCreate(BaseModel):
    titolo: str
    descrizione: Optional[str] = ""
    
    # === CLASSIFICAZIONE (configurabili da Settings) ===
    tipo: Optional[TIPO_AP] = None
    priorita: Optional[PRIORITA] = None
    stato: Optional[STATO] = None
    categoria_perdita: Optional[str] = None
    
    # === HARD-CODED ===
    quinta_m: Optional[Literal["Machine", "Manodopera", "Metodo", "Materiale", "Misurazione"]] = None
    
    # === CONTESTO / PARENT ENTITY ===
    parent_type: Optional[Literal["kaizen", "pillar", "dashboard", "standalone"]] = "standalone"
    parent_id: Optional[str] = None
    parent_label: Optional[str] = None
    pillar_id: Optional[str] = None
    dashboard_id: Optional[str] = None
    
    # === LEGACY (deprecato) ===
    kaizen_id: Optional[str] = None
    categoria: Optional[str] = None
    tipo_perdita: Optional[str] = None
    
    # Tags & mentions
    tags: List[str] = []
    mentions: List[str] = []
    
    # Assignment
    responsabile: Optional[str] = None
    responsabile_email: Optional[str] = None
    reporter: Optional[str] = None
    watchers: List[str] = []
    
    # Location
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    
    # Dates
    data_inizio: Optional[datetime] = None
    data_scadenza: Optional[datetime] = None
    
    # Polymorphic links
    links: List[LinkEntita] = []
    
    # Initial checklist
    checklist: List[ChecklistItem] = []


# ============================================================
# UPDATE
# ============================================================
class ActionPlanUpdate(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    
    # Classificazione
    tipo: Optional[TIPO_AP] = None
    priorita: Optional[PRIORITA] = None
    stato: Optional[STATO] = None
    categoria_perdita: Optional[str] = None
    quinta_m: Optional[Literal["Machine", "Manodopera", "Metodo", "Materiale", "Misurazione"]] = None
    
    # Contesto
    parent_type: Optional[Literal["kaizen", "pillar", "dashboard", "standalone"]] = None
    parent_id: Optional[str] = None
    parent_label: Optional[str] = None
    pillar_id: Optional[str] = None
    dashboard_id: Optional[str] = None
    
    # Legacy
    categoria: Optional[str] = None
    tipo_perdita: Optional[str] = None
    kaizen_id: Optional[str] = None
    
    tags: Optional[List[str]] = None
    mentions: Optional[List[str]] = None
    
    responsabile: Optional[str] = None
    responsabile_email: Optional[str] = None
    reporter: Optional[str] = None
    watchers: Optional[List[str]] = None
    
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    
    data_inizio: Optional[datetime] = None
    data_scadenza: Optional[datetime] = None
    
    avanzamento: Optional[int] = None
    
    is_blocked: Optional[bool] = None
    blocking_reason: Optional[str] = None
    
    # 🆕 CANCELLAZIONE (annullamento logico — diverso da is_active soft delete)
    is_cancelled: Optional[bool] = None
    cancelled_reason: Optional[str] = None

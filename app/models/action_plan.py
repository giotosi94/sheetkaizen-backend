from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


# ============================================================
# ENUMS (validazione lato modello)
# ============================================================
TIPO_AP = Literal["Task", "Bug", "Improvement", "Audit", "Manutenzione", "Sicurezza"]
PRIORITA = Literal["Lowest", "Low", "Medium", "High", "Critical"]
STATO = Literal["Backlog", "Aperto", "In Corso", "In Verifica", "Done", "Cancelled"]


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
    reactions: List[dict] = []  # [{emoji, users:[]}]


class Allegato(BaseModel):
    tipo: Literal["image", "file", "link"]
    url: str
    nome: str
    size: Optional[int] = None
    uploaded_by: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class LinkEntita(BaseModel):
    """Link polimorfico verso qualsiasi entità dell'app."""
    entity_type: Literal["kaizen", "documento", "dashboard", "action_plan", "url"]
    entity_id: str
    entity_label: Optional[str] = None  # es: "K-0023", "OPL-254"
    link_type: Optional[str] = "related_to"  # blocks, related_to, duplicates, parent_of


# ============================================================
# CREATE
# ============================================================
class ActionPlanCreate(BaseModel):
    titolo: str
    descrizione: Optional[str] = ""
    tipo: Optional[TIPO_AP] = "Task"
    priorita: Optional[PRIORITA] = "Medium"
    stato: Optional[STATO] = "Backlog"
    categoria: Optional[str] = None
    
    # Tags & mentions (estratti dalla descrizione + manuali)
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
    
    # Hierarchy
    parent_id: Optional[str] = None
    
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
    tipo: Optional[TIPO_AP] = None
    priorita: Optional[PRIORITA] = None
    stato: Optional[STATO] = None
    categoria: Optional[str] = None
    
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

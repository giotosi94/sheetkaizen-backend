from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class SkillCompetenzaCreate(BaseModel):
    """Competenza dentro una categoria."""
    label: str
    codice: Optional[str] = None
    descrizione: Optional[str] = None
    categoria_id: str  # riferimento a configurazione categoria_skill
    ordine: Optional[int] = 0
    # Livelli minimi per persone che partono da capo (opzionale)
    livello_target_default: Optional[int] = None


class SkillCompetenzaUpdate(BaseModel):
    label: Optional[str] = None
    codice: Optional[str] = None
    descrizione: Optional[str] = None
    categoria_id: Optional[str] = None
    ordine: Optional[int] = None
    livello_target_default: Optional[int] = None


class SkillMatrixValoreCell(BaseModel):
    """Valore di una singola cella (persona x competenza)."""
    starting: Optional[int] = None   # 1-5
    current: Optional[int] = None    # 1-5
    target: Optional[int] = None     # 1-5
    note: Optional[str] = None


class SkillMatrixCreate(BaseModel):
    """Skill Matrix per un pillar in un dato anno."""
    pillar_id: str
    anno: int
    # Competenze configurate per il Pillar (snapshot al momento della creazione della matrice annuale)
    competenze: List[Dict[str, Any]] = []
    # Membri della matrice: [{user_id, user_name}]
    members: List[Dict[str, Any]] = []
    # Valori: {"user_id_competenza_id": {starting, current, target, note}}
    valori: Dict[str, Any] = {}


class SkillMatrixUpdate(BaseModel):
    competenze: Optional[List[Dict[str, Any]]] = None
    members: Optional[List[Dict[str, Any]]] = None
    valori: Optional[Dict[str, Any]] = None

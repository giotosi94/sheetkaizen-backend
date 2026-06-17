from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class KaizenCreate(BaseModel):
    titolo: str
    tipo: str = "Quick Kaizen"
    reparto: str
    linea: Optional[str] = None
    macchina: Optional[str] = None
    posto: Optional[str] = None
    attrezzatura: Optional[str] = None
    team: Optional[str] = None
    hashtag: List[str] = []
    partecipanti: List[str] = []


class KaizenUpdate(BaseModel):
    titolo: Optional[str] = None
    stato: Optional[str] = None
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

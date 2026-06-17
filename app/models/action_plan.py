from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ActionPlanCreate(BaseModel):
    titolo: str
    descrizione: Optional[str] = None
    origine: str = "standalone"
    origine_id: Optional[str] = None
    origine_nome: Optional[str] = None
    responsabile_id: str
    responsabile_nome: str
    reparto: str
    linea: Optional[str] = None
    macchina: Optional[str] = None
    data_scadenza: datetime
    priorita: str = "Media"
    note: Optional[str] = None


class ActionPlanUpdate(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    responsabile_id: Optional[str] = None
    responsabile_nome: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    data_scadenza: Optional[datetime] = None
    data_completamento: Optional[datetime] = None
    stato: Optional[str] = None
    priorita: Optional[str] = None
    note: Optional[str] = None

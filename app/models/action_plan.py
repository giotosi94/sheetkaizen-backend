from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ActionPlanCreate(BaseModel):
    titolo: str
    descrizione: Optional[str] = None
    categoria: Optional[str] = None  # Sicurezza, Qualità, Manutenzione, 5S, …
    priorita: Optional[str] = "Media"  # Bassa | Media | Alta | Critica
    responsabile: str
    responsabile_email: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    kaizen_id: Optional[str] = None
    data_scadenza: Optional[datetime] = None


class ActionPlanUpdate(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    categoria: Optional[str] = None
    priorita: Optional[str] = None
    stato: Optional[str] = None
    responsabile: Optional[str] = None
    responsabile_email: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    data_scadenza: Optional[datetime] = None
    avanzamento: Optional[int] = None

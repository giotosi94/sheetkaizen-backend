from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class DashboardCreate(BaseModel):
    nome: str
    descrizione: Optional[str] = None
    tipo: str = "Custom"
    reparto: Optional[str] = None
    visibilita: str = "pubblico"
    layout: List[Dict[str, Any]] = []


class DashboardUpdate(BaseModel):
    nome: Optional[str] = None
    descrizione: Optional[str] = None
    tipo: Optional[str] = None
    reparto: Optional[str] = None
    visibilita: Optional[str] = None
    layout: Optional[List[Dict[str, Any]]] = None

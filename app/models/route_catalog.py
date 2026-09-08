from pydantic import BaseModel, Field
from typing import Optional, List


class RouteGate(BaseModel):
    titolo: Optional[str] = None
    criteri: List[str] = Field(default_factory=list)
    approvatori: List[str] = Field(default_factory=list)


class RouteStep(BaseModel):
    step_id: str
    ordine: int
    titolo: str
    obiettivo: Optional[str] = ""
    componente: Optional[str] = None
    durata_stimata: Optional[str] = ""
    istruzioni: Optional[str] = ""
    metodologie: List[str] = Field(default_factory=list)
    output_obbligatori: List[str] = Field(default_factory=list)
    ruoli: List[str] = Field(default_factory=list)
    gate: Optional[RouteGate] = None


class RouteCatalogCreate(BaseModel):
    codice: str
    nome: str
    descrizione: Optional[str] = ""
    versione: str = "1.0"
    scope: str = "corporate"
    plant_id: Optional[str] = None
    stato: str = "bozza"
    steps: List[RouteStep] = Field(default_factory=list)


class RouteCatalogUpdate(BaseModel):
    codice: Optional[str] = None
    nome: Optional[str] = None
    descrizione: Optional[str] = None
    versione: Optional[str] = None
    scope: Optional[str] = None
    plant_id: Optional[str] = None
    stato: Optional[str] = None
    steps: Optional[List[RouteStep]] = None

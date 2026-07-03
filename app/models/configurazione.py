from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


# Tipologie supportate dal sistema Settings
TIPO_CONFIG = Literal[
    "tipi_action_plan",
    "ap_5m",                   # Man, Machine, Method, Material, Measurement
    "priorita_ap",             # Low, Medium, High, Critical
    "stato_ap",                # Da Valutare, Aperto, In Corso, In Verifica, Done
    "categorie_documento",     # OPL, SOP
    "categorie_perdita",
    "cluster_perdita",         # Raggruppamenti perdite per Pareto Pillar
    "argomenti",
    "tipi_meeting",            # Tipi di Meeting/Dashboard
    "categoria_skill",         # Categorie standard LPW per Skill Matrix
]


class ConfigurazioneCreate(BaseModel):
    tipo: TIPO_CONFIG
    label: str
    codice: Optional[str] = None
    descrizione: Optional[str] = ""
    icon: Optional[str] = None
    color: Optional[str] = None
    parent_id: Optional[str] = None
    parent_tipo: Optional[str] = None
    ordine: Optional[int] = 0
    attivo: Optional[bool] = True
    is_terminal: Optional[bool] = False
    metadata: Optional[dict] = {}


class ConfigurazioneUpdate(BaseModel):
    label: Optional[str] = None
    codice: Optional[str] = None
    descrizione: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    parent_id: Optional[str] = None
    parent_tipo: Optional[str] = None
    ordine: Optional[int] = None
    attivo: Optional[bool] = None
    is_terminal: Optional[bool] = None
    metadata: Optional[dict] = None


class RiordinaPayload(BaseModel):
    """Per drag&drop riordino: lista di {id, ordine}"""
    items: list[dict]

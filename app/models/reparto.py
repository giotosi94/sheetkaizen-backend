from pydantic import BaseModel
from typing import Optional, List


class LineaModel(BaseModel):
    nome: str
    macchine: List[str] = []


class RepartoCreate(BaseModel):
    nome: str
    linee: List[LineaModel] = []
    responsabile_id: Optional[str] = None


class RepartoUpdate(BaseModel):
    nome: Optional[str] = None
    linee: Optional[List[LineaModel]] = None
    responsabile_id: Optional[str] = None
    is_active: Optional[bool] = None

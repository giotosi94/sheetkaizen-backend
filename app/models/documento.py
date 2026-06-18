from pydantic import BaseModel
from typing import Optional, List


class DocumentoCreate(BaseModel):
    titolo: str
    tipo: str = "OPL"  # OPL | SOP | Procedura | Istruzione
    categoria: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    autore: Optional[str] = None
    descrizione: Optional[str] = None
    tag: List[str] = []


class DocumentoUpdate(BaseModel):
    titolo: Optional[str] = None
    tipo: Optional[str] = None
    categoria: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    autore: Optional[str] = None
    descrizione: Optional[str] = None
    tag: Optional[List[str]] = None
    stato: Optional[str] = None  # Bozza | In Revisione | Approvato | Obsoleto

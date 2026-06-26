from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class UserCreate(BaseModel):
    """Payload per la creazione di un nuovo utente."""
    username: str          # univoco, es "gtosi"
    email: EmailStr        # es "gtosi@lindt.com"
    nome: str              # nome completo "Giovanni Tosi"
    password: str          # password in chiaro (verrà hashata)

    # Anagrafica
    ruolo: str = "operator"  # "operator" | "office" | "manager" | "admin"
    foto_url: Optional[str] = None
    telefono: Optional[str] = None
    job_title: Optional[str] = None  # "TPM Development Engineer"

    # Reparto/Linea/Macchine (per operatori)
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchine: List[str] = []

    # Pillar (per ufficio/manager)
    pillar_ids: List[str] = []          # Pillar di cui fa parte
    pillar_leader_of: List[str] = []    # Pillar di cui è leader

    # Stato
    attivo: bool = True
    note: Optional[str] = None


class UserUpdate(BaseModel):
    """Payload per aggiornare un utente (tutti campi opzionali)."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    nome: Optional[str] = None
    password: Optional[str] = None

    ruolo: Optional[str] = None
    foto_url: Optional[str] = None
    telefono: Optional[str] = None
    job_title: Optional[str] = None

    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchine: Optional[List[str]] = None

    pillar_ids: Optional[List[str]] = None
    pillar_leader_of: Optional[List[str]] = None

    attivo: Optional[bool] = None
    note: Optional[str] = None


class UserLogin(BaseModel):
    """Payload per login (simulato per ora, vero in produzione)."""
    username: str
    password: str


class UserPublic(BaseModel):
    """Risposta pubblica utente (SENZA password hash)."""
    id: str
    username: str
    email: str
    nome: str
    ruolo: str
    foto_url: Optional[str] = None
    job_title: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchine: List[str] = []
    pillar_ids: List[str] = []
    pillar_leader_of: List[str] = []
    attivo: bool = True

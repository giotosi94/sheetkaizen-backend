from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# ──────────────────────────────────────────
# MODELLO USER (nuovo sistema utenti)
# ──────────────────────────────────────────

class UserCreate(BaseModel):
    """Payload per la creazione di un nuovo utente."""
    username: str
    email: EmailStr
    nome: str
    password: str

    # Anagrafica
    ruolo: str = "operator"
    foto_url: Optional[str] = None
    telefono: Optional[str] = None
    job_title: Optional[str] = None

    # Reparto/Linea/Macchine (per operatori)
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchine: List[str] = []

    # Pillar (per ufficio/manager)
    pillar_ids: List[str] = []
    pillar_leader_of: List[str] = []

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
    """Payload per login."""
    username: str
    password: str


class UserPublic(BaseModel):
    """Risposta pubblica utente (senza password hash)."""
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


# ──────────────────────────────────────────
# COMPATIBILITÀ con auth.py esistente (LEGACY)
# ──────────────────────────────────────────

class Token(BaseModel):
    """Token JWT."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Dati estratti dal token."""
    username: Optional[str] = None
    user_id: Optional[str] = None


class UserInDB(BaseModel):
    """Utente come salvato nel DB."""
    id: Optional[str] = None
    username: str
    email: str
    nome: str
    password_hash: str
    ruolo: str = "operator"
    attivo: bool = True


class PasswordChange(BaseModel):
    """Payload per cambio password."""
    old_password: str
    new_password: str


class PasswordReset(BaseModel):
    """Payload per reset password (richiesta)."""
    email: str


class PasswordResetConfirm(BaseModel):
    """Payload per conferma reset password."""
    token: str
    new_password: str


class UserResponse(BaseModel):
    """Risposta utente API."""
    id: str
    username: str
    email: str
    nome: str
    ruolo: str
    attivo: bool = True


class UserProfile(BaseModel):
    """Profilo utente esteso."""
    id: str
    username: str
    email: str
    nome: str
    ruolo: str
    foto_url: Optional[str] = None
    job_title: Optional[str] = None
    telefono: Optional[str] = None
    attivo: bool = True


class LoginResponse(BaseModel):
    """Risposta dopo login."""
    access_token: str
    token_type: str = "bearer"
    user: dict


class RefreshToken(BaseModel):
    """Payload per refresh token."""
    refresh_token: str


class UserRole(BaseModel):
    """Ruolo utente."""
    name: str
    permissions: List[str] = []

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
import bcrypt


# ============ RUOLI ============
ROLE_ADMIN = "admin"
ROLE_OFFICE = "office"
ROLE_PRODUCTION = "production"

VALID_ROLES = [ROLE_ADMIN, ROLE_OFFICE, ROLE_PRODUCTION]


# ============ INPUT MODELS ============

class UserCreate(BaseModel):
    """Modello per creazione utente (registrazione admin)"""
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: str = ROLE_OFFICE
    reparto: Optional[str] = None
    linee: List[str] = []
    team: Optional[str] = None


class UserLogin(BaseModel):
    """Modello per login email + password"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Modello per update utente (admin)"""
    full_name: Optional[str] = None
    role: Optional[str] = None
    reparto: Optional[str] = None
    linee: Optional[List[str]] = None
    team: Optional[str] = None
    is_active: Optional[bool] = None


class PasswordChange(BaseModel):
    """Modello per cambio password (utente)"""
    old_password: str
    new_password: str


# ============ DB MODEL ============

class UserInDB(BaseModel):
    """Modello User completo in DB"""
    id: Optional[str] = Field(default=None, alias="_id")
    username: str
    email: EmailStr
    password_hash: Optional[str] = None   # null se solo SSO
    azure_oid: Optional[str] = None        # null se solo locale (SSO Lindt futuro)
    full_name: str
    role: str = ROLE_OFFICE
    reparto: Optional[str] = None
    linee: List[str] = []
    team: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    class Config:
        populate_by_name = True


# ============ OUTPUT MODELS ============

class UserPublic(BaseModel):
    """Modello User restituito al frontend (senza password)"""
    id: str
    username: str
    email: str
    full_name: str
    role: str
    reparto: Optional[str] = None
    linee: List[str] = []
    team: Optional[str] = None
    is_active: bool = True
    last_login: Optional[datetime] = None


class Token(BaseModel):
    """Risposta login: JWT + dati utente"""
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


# ============ PASSWORD UTILS ============

def hash_password(password: str) -> str:
    """Hash bcrypt della password"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica password contro hash bcrypt"""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False

from fastapi import APIRouter, HTTPException, Depends, status
from datetime import datetime, timedelta, timezone
from bson import ObjectId
import jwt

from app.database import db
from app.config import settings
from app.middleware.auth import get_current_user, require_admin
from app.models.user import (
    UserCreate,
    UserLogin,
    UserPublic,
    Token,
    PasswordChange,
    hash_password,
    verify_password,
    VALID_ROLES,
    ROLE_ADMIN,
)

router = APIRouter()


# ============ HELPER ============

def _create_access_token(user_id: str, email: str, role: str) -> str:
    """Genera JWT firmato con scadenza configurata"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _user_to_public(user_doc: dict) -> UserPublic:
    """Converte doc Mongo in UserPublic (no password)"""
    return UserPublic(
        id=str(user_doc["_id"]),
        username=user_doc.get("username", ""),
        email=user_doc["email"],
        full_name=user_doc.get("full_name", ""),
        role=user_doc.get("role", "office"),
        reparto=user_doc.get("reparto"),
        linee=user_doc.get("linee", []),
        team=user_doc.get("team"),
        is_active=user_doc.get("is_active", True),
        last_login=user_doc.get("last_login"),
    )


# ============ REGISTER (solo admin) ============

@router.post("/register", response_model=UserPublic)
async def register(user: UserCreate, current_user=Depends(require_admin)):
    """
    Registra un nuovo utente. SOLO admin può chiamarlo.
    Per creare il PRIMO admin usa lo script scripts/seed_admin.py
    """
    # Validazione ruolo
    if user.role not in VALID_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Ruolo non valido. Validi: {VALID_ROLES}",
        )

    # Check email duplicata
    existing = await db.users.find_one({"email": user.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email già registrata")

    # Check username duplicato
    existing_username = await db.users.find_one({"username": user.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username già esistente")

    # Crea utente
    new_user = {
        "username": user.username,
        "email": user.email.lower(),
        "password_hash": hash_password(user.password),
        "azure_oid": None,
        "full_name": user.full_name,
        "role": user.role,
        "reparto": user.reparto,
        "linee": user.linee or [],
        "team": user.team,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "last_login": None,
    }

    result = await db.users.insert_one(new_user)
    new_user["_id"] = result.inserted_id

    return _user_to_public(new_user)


# ============ LOGIN ============

@router.post("/login", response_model=Token)
async def login(credentials: UserLogin):
    """
    Login con email + password.
    Restituisce JWT + dati utente.
    """
    user = await db.users.find_one({"email": credentials.email.lower()})

    if not user:
        raise HTTPException(status_code=401, detail="Credenziali non valide")

    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Utente disattivato")

    if not verify_password(credentials.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Credenziali non valide")

    # Aggiorna last_login
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login": datetime.now(timezone.utc)}},
    )
    user["last_login"] = datetime.now(timezone.utc)

    # Genera JWT
    token = _create_access_token(
        user_id=str(user["_id"]),
        email=user["email"],
        role=user.get("role", "office"),
    )

    return Token(
        access_token=token,
        token_type="bearer",
        user=_user_to_public(user),
    )


# ============ ME (utente corrente) ============

@router.get("/me", response_model=UserPublic)
async def get_me(current_user=Depends(get_current_user)):
    """Restituisce l'utente corrente dal JWT"""
    return _user_to_public(current_user)


# ============ CHANGE PASSWORD ============

@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    current_user=Depends(get_current_user),
):
    """Cambio password utente corrente"""
    if not verify_password(data.old_password, current_user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Password attuale errata")

    if len(data.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="La nuova password deve essere di almeno 8 caratteri",
        )

    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password_hash": hash_password(data.new_password)}},
    )

    return {"message": "Password aggiornata con successo"}


# ============ SSO AZURE (placeholder per Lindt) ============

@router.post("/sso/azure")
async def sso_azure_login():
    """
    Login SSO Azure AD / Entra ID (Lindt).
    DA IMPLEMENTARE in Fase 4 quando l'IT Lindt approva.
    """
    raise HTTPException(
        status_code=501,
        detail="SSO Azure non ancora implementato. Disponibile in Fase 4.",
    )
# ============ SETUP FIRST ADMIN (solo se DB vuoto) ============

@router.post("/setup-first-admin", response_model=UserPublic)
async def setup_first_admin(user: UserCreate):
    """
    Crea il PRIMO admin del sistema. Funziona SOLO se non esistono admin.
    Una volta creato il primo admin, questo endpoint diventa inutilizzabile.
    """
    # Verifica che NON ci siano già admin
    existing_admin = await db.users.find_one({"role": "admin"})
    if existing_admin:
        raise HTTPException(
            status_code=403,
            detail="Esiste già un admin. Usa /register con account admin.",
        )

    # Check email duplicata
    existing = await db.users.find_one({"email": user.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email già registrata")

    # Check username duplicato
    existing_username = await db.users.find_one({"username": user.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username già esistente")

    # Crea utente forzando role admin
    new_user = {
        "username": user.username,
        "email": user.email.lower(),
        "password_hash": hash_password(user.password),
        "azure_oid": None,
        "full_name": user.full_name,
        "role": "admin",
        "reparto": user.reparto,
        "linee": user.linee or [],
        "team": user.team,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "last_login": None,
    }

    result = await db.users.insert_one(new_user)
    new_user["_id"] = result.inserted_id

    return _user_to_public(new_user)

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class PersonaRef(BaseModel):
    id: Optional[str] = None
    nome: Optional[str] = None


class RuoliProgetto(BaseModel):
    sponsor: Optional[PersonaRef] = None
    project_leader: Optional[PersonaRef] = None
    process_owner: Optional[PersonaRef] = None
    pillar_coach: Optional[PersonaRef] = None
    data_owner: Optional[PersonaRef] = None
    subject_matter_expert: Optional[PersonaRef] = None
    team_members: List[PersonaRef] = Field(default_factory=list)


class RouteRoleAssignment(BaseModel):
    role_key: str
    role_label: str
    assegnazione: str = "single"
    utenti: List[PersonaRef] = Field(default_factory=list)


class MajorKPI(BaseModel):
    nome_kpi: Optional[str] = None
    unita: Optional[str] = None
    baseline: Optional[float] = None
    target: Optional[float] = None
    actual: Optional[float] = None
    valore_finale: Optional[float] = None
    saving_previsto: Optional[float] = None
    saving_verificato: Optional[float] = None


class MajorKaizenCreate(BaseModel):
    titolo: str
    descrizione: Optional[str] = ""
    motivo_strategico: Optional[str] = ""

    route_id: str

    creatore_id: Optional[str] = None
    creatore_nome: Optional[str] = None

    plant_id: Optional[str] = "induno"
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None

    pillar_id: Optional[str] = None
    pillar_sigla: Optional[str] = None
    pillar_label: Optional[str] = None

    dashboard_id: Optional[str] = None
    dashboard_nome: Optional[str] = None

    project_leader: Optional[PersonaRef] = None
    team_members: List[PersonaRef] = Field(default_factory=list)
    route_role_assignments: List[RouteRoleAssignment] = Field(default_factory=list)

    ruoli_progetto: Optional[RuoliProgetto] = None

    data_inizio: Optional[str] = None
    data_target: Optional[str] = None

    kpi: Optional[MajorKPI] = None


class MajorKaizenUpdate(BaseModel):
    titolo: Optional[str] = None
    descrizione: Optional[str] = None
    motivo_strategico: Optional[str] = None
    stato: Optional[str] = None

    creatore_id: Optional[str] = None
    creatore_nome: Optional[str] = None

    plant_id: Optional[str] = None
    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None

    pillar_id: Optional[str] = None
    pillar_sigla: Optional[str] = None
    pillar_label: Optional[str] = None

    dashboard_id: Optional[str] = None
    dashboard_nome: Optional[str] = None

    project_leader: Optional[PersonaRef] = None
    team_members: Optional[List[PersonaRef]] = None
    route_role_assignments: Optional[List[RouteRoleAssignment]] = None

    ruoli_progetto: Optional[RuoliProgetto] = None

    data_inizio: Optional[str] = None
    data_target: Optional[str] = None

    kpi: Optional[MajorKPI] = None

    steps_data: Optional[Dict[str, Any]] = None
    percentuale_completamento: Optional[int] = None


class StepDataUpdate(BaseModel):
    stato: Optional[str] = None
    attivita: Optional[Dict[str, Any]] = None
    dati: Optional[Dict[str, Any]] = None
    metodologie_usate: Optional[List[str]] = None
    output_compilati: Optional[Dict[str, Any]] = None
    note: Optional[str] = None


class GateApproval(BaseModel):
    approvato: bool = False
    approvato_da: Optional[str] = None
    note: Optional[str] = None

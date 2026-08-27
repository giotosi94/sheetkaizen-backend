from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


LIVELLI_KAIZEN = ["Quick", "Standard", "Major"]


class KaizenCreate(BaseModel):
    titolo: str

    livello: Optional[str] = "Quick"
    tipo: Optional[str] = None

    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    posto: Optional[str] = None
    attrezzatura: Optional[str] = None

    team: Optional[str] = None
    partecipanti: List[str] = Field(default_factory=list)

    creatore_id: Optional[str] = None
    creatore_nome: Optional[str] = None

    team_leader_id: Optional[str] = None
    team_leader_nome: Optional[str] = None

    team_members_ids: List[str] = Field(default_factory=list)
    team_members_nomi: List[str] = Field(default_factory=list)

    hashtag: List[str] = Field(default_factory=list)

    parent_kaizen_id: Optional[str] = None

    tipo_perdita: Optional[str] = None
    categoria: Optional[str] = None

    pillar_id: Optional[str] = None
    pillar_sigla: Optional[str] = None
    pillar_label: Optional[str] = None
    pillar_ids: List[str] = Field(default_factory=list)
    pillar_nomi: List[str] = Field(default_factory=list)
    pillar_sigle: List[str] = Field(default_factory=list)

    lavagna: Optional[str] = None
    lavagna_immagini: List[str] = Field(default_factory=list)
    lavagna_documenti: List[Dict[str, Any]] = Field(default_factory=list)

    dashboard_id: Optional[str] = None
    dashboard_nome: Optional[str] = None


class KaizenUpdate(BaseModel):
    titolo: Optional[str] = None
    stato: Optional[str] = None
    livello: Optional[str] = None
    tipo: Optional[str] = None

    reparto: Optional[str] = None
    linea: Optional[str] = None
    macchina: Optional[str] = None
    posto: Optional[str] = None
    attrezzatura: Optional[str] = None

    team: Optional[str] = None
    partecipanti: Optional[List[str]] = None

    creatore_id: Optional[str] = None
    creatore_nome: Optional[str] = None

    team_leader_id: Optional[str] = None
    team_leader_nome: Optional[str] = None

    team_members_ids: Optional[List[str]] = None
    team_members_nomi: Optional[List[str]] = None

    hashtag: Optional[List[str]] = None
    data_chiusura: Optional[datetime] = None

    tipo_perdita: Optional[str] = None
    categoria: Optional[str] = None

    pillar_id: Optional[str] = None
    pillar_sigla: Optional[str] = None
    pillar_label: Optional[str] = None
    pillar_ids: Optional[List[str]] = None
    pillar_nomi: Optional[List[str]] = None
    pillar_sigle: Optional[List[str]] = None

    dashboard_id: Optional[str] = None
    dashboard_nome: Optional[str] = None

    parent_kaizen_id: Optional[str] = None
    archiviato: Optional[bool] = None

    passo1_definizione: Optional[Dict[str, Any]] = None
    passo2_cause_probabili: Optional[Dict[str, Any]] = None
    passo3_causa_radice: Optional[Dict[str, Any]] = None
    piani_azione_immediati: Optional[List[Dict[str, Any]]] = None
    verifica_processo: Optional[Dict[str, Any]] = None
    passo4_piani_azione: Optional[List[str]] = None
    fase5_valutazione_efficacia: Optional[Dict[str, Any]] = None
    fase6_standardizzazione: Optional[Dict[str, Any]] = None

    loss_pareto: Optional[Dict[str, Any]] = None
    gemba_plan: Optional[Dict[str, Any]] = None
    gemba: Optional[Dict[str, Any]] = None
    obiettivi: Optional[Dict[str, Any]] = None
    risultati: Optional[Dict[str, Any]] = None
    standardizzazione: Optional[Dict[str, Any]] = None
    team_audit: Optional[Dict[str, Any]] = None

    lavagna: Optional[str] = None
    lavagna_immagini: Optional[List[str]] = None
    lavagna_documenti: Optional[List[Dict[str, Any]]] = None
    campi_custom: Optional[Dict[str, Any]] = None

    standard_elements: Optional[Dict[str, Any]] = None
    countermeasure_ladder: Optional[Dict[str, Any]] = None

    step1_kpi_definition: Optional[Dict[str, Any]] = None
    step2_pareto_analysis: Optional[Dict[str, Any]] = None
    step3_target_definition: Optional[Dict[str, Any]] = None
    step4_project_implementation: Optional[Dict[str, Any]] = None
    step5_close_the_loop: Optional[Dict[str, Any]] = None

    gantt: Optional[Dict[str, Any]] = None
    gant_master_plan: Optional[Dict[str, Any]] = None

    cost_benefit: Optional[Dict[str, Any]] = None


class ChangeMethodologyPayload(BaseModel):
    nuovo_livello: str
    motivo: Optional[str] = None


class PromotePayload(BaseModel):
    motivo: Optional[str] = None


class LinkChildPayload(BaseModel):
    child_kaizen_id: str

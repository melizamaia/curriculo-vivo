"""Contratos de dados (seção 5 do PRD).

Um único lugar define o que entra, o que sai e o que é gravado na auditoria.
As invariantes críticas da seção 5.5 são responsabilidade da barreira 3
(`core/guardrail.py`); aqui ficam apenas as garantias de forma.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --------------------------------------------------------------------------
# Vocabulários controlados
# --------------------------------------------------------------------------


class TipoObjeto(str, Enum):
    EMENTA = "ementa"
    PLANO_DE_AULA = "plano_de_aula"
    AULA = "aula"
    QUESTAO = "questao"
    OBJETO_DIGITAL = "objeto_digital"


class FonteTipo(str, Enum):
    ORGAO_OFICIAL = "orgao_oficial"
    DIRETRIZ_SOCIEDADE = "diretriz_sociedade"
    LITERATURA_REVISADA = "literatura_revisada"
    NAO_VALIDADA = "nao_validada"

    @property
    def validada(self) -> bool:
        """Com `EXIGIR_FONTE_OFICIAL=true`, só estas sustentam um alerta."""
        return self in FONTES_VALIDADAS


FONTES_VALIDADAS: frozenset[FonteTipo] = frozenset(
    {FonteTipo.ORGAO_OFICIAL, FonteTipo.DIRETRIZ_SOCIEDADE}
)


class NivelEvidencia(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    NA = "NA"


class Severidade(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"


# Ordem de prioridade do radar: o coordenador abre a fila pelo topo.
ORDEM_SEVERIDADE: dict[Severidade, int] = {
    Severidade.ALTA: 3,
    Severidade.MEDIA: 2,
    Severidade.BAIXA: 1,
}


class StatusAnalise(str, Enum):
    DEFASAGEM_DETECTADA = "defasagem_detectada"
    SEM_ACHADO = "sem_achado"
    ABSTIDO = "abstido"


class MotivoAbstencao(str, Enum):
    EVIDENCIA_INSUFICIENTE = "evidencia_insuficiente"
    FONTE_NAO_VALIDADA = "fonte_nao_validada"
    MATERIAL_SEM_REFERENCIA = "material_sem_referencia"
    FORA_DE_ESCOPO = "fora_de_escopo"
    OBJETO_INVALIDO = "objeto_invalido"
    # Não descreve o material: o alerta foi gerado e reprovou na barreira 3.
    # Em operação normal nunca aparece; se aparecer, é incidente (seção 5.5).
    ALERTA_DESCARTADO = "alerta_descartado"


# --------------------------------------------------------------------------
# 5.1 ObjetoAprendizagem
# --------------------------------------------------------------------------


class Trecho(BaseModel):
    """Unidade indexável de texto, do material ou da evidência."""

    model_config = ConfigDict(extra="ignore")

    trecho_id: str
    texto: str


class Referencia(BaseModel):
    """Referência citada pelo material didático.

    `ano` é opcional de propósito: objeto sem ano é inelegível e gera
    abstenção `material_sem_referencia`. Inventar a data seria exatamente a
    alucinação que o produto combate.
    """

    model_config = ConfigDict(extra="ignore")

    titulo: str
    fonte: str | None = None
    ano: int | None = Field(default=None, ge=1900, le=2100)
    url: str | None = None


class ObjetoAprendizagem(BaseModel):
    """Material didático analisado (plano de aula, aula, questão, ementa)."""

    model_config = ConfigDict(extra="ignore")

    objeto_id: str
    titulo: str = ""
    tipo: TipoObjeto = TipoObjeto.PLANO_DE_AULA
    curso: str | None = None
    disciplina: str | None = None
    periodo: str | None = None
    campus: list[str] = Field(default_factory=list)
    temas: list[str] = Field(default_factory=list)
    atualizado_em: date | None = None
    exemplo_ilustrativo: bool = True
    referencias: list[Referencia] = Field(default_factory=list)
    trechos: list[Trecho] = Field(default_factory=list)

    @property
    def anos_referencias(self) -> list[int]:
        return [r.ano for r in self.referencias if r.ano is not None]

    @property
    def ano_referencia(self) -> int | None:
        """`ano_material` da seção 6: o maior ano entre as referências.

        Critério conservador — comparar contra a referência mais nova que o
        material usa reduz falso alarme. `None` quando nenhuma é datada, e
        nesse caso a barreira 1 abstém com `material_sem_referencia`.
        """
        anos = self.anos_referencias
        return max(anos) if anos else None

    @property
    def texto_completo(self) -> str:
        """Título + trechos: o que a barreira 1 inspeciona e o retriever casa."""
        return " ".join([self.titulo, *(t.texto for t in self.trechos)]).strip()


# --------------------------------------------------------------------------
# 5.2 Evidencia
# --------------------------------------------------------------------------


class Evidencia(BaseModel):
    """Item da base curada do que está vigente."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    titulo: str
    fonte: str
    fonte_tipo: FonteTipo = FonteTipo.LITERATURA_REVISADA
    url: str | None = None
    publicado_em: date
    nivel_evidencia: NivelEvidencia = NivelEvidencia.NA
    temas: list[str] = Field(default_factory=list)
    practice_changing: bool = False
    substitui: list[str] = Field(default_factory=list)
    exemplo_ilustrativo: bool = True
    trechos: list[Trecho] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 5.3 Requisição
# --------------------------------------------------------------------------


class AnaliseRequest(BaseModel):
    """Análise por `objeto_id` do catálogo ou por payload completo."""

    model_config = ConfigDict(extra="ignore")

    objeto_id: str | None = None
    objeto: ObjetoAprendizagem | None = None

    @model_validator(mode="after")
    def _exige_um_dos_dois(self) -> AnaliseRequest:
        if not self.objeto_id and self.objeto is None:
            raise ValueError("informe objeto_id ou objeto")
        return self


# --------------------------------------------------------------------------
# 5.4 / 5.5 Resposta
# --------------------------------------------------------------------------


class EvidenciaCitada(BaseModel):
    """A citação que sustenta um alerta. Sem ela, não há alerta."""

    model_config = ConfigDict(extra="ignore")

    marcador: int = Field(ge=1, description="[0] é sempre a referência do material")
    doc_id: str
    trecho_id: str
    titulo: str
    fonte: str
    fonte_tipo: FonteTipo
    url: str | None = None
    publicado_em: date
    nivel_evidencia: NivelEvidencia
    trecho: str
    score: float
    exemplo_ilustrativo: bool = True


class Defasagem(BaseModel):
    """Um tema do objeto cuja referência é mais antiga que a evidência vigente."""

    model_config = ConfigDict(extra="ignore")

    tema: str
    severidade: Severidade
    gap_meses: int
    practice_changing: bool
    justificativa: str
    evidencia: EvidenciaCitada


class AnaliseResponse(BaseModel):
    """Resultado de uma análise — com defasagens, sem achado ou abstida."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    status: StatusAnalise
    objeto_id: str
    titulo: str = ""
    curso: str | None = None
    disciplina: str | None = None
    ano_referencia_material: int | None = None
    severidade_maxima: Severidade | None = None
    defasagens: list[Defasagem] = Field(default_factory=list)
    confianca: float = 0.0
    motivo_abstencao: MotivoAbstencao | None = None
    alertas: list[str] = Field(default_factory=list)
    modo_sintese: str = "extrativa"
    latencia_ms: float = 0.0
    aviso: str = (
        "Apoio à revisão curricular. Não substitui a decisão pedagógica do "
        "docente e do colegiado."
    )


# --------------------------------------------------------------------------
# 5.6 Radar
# --------------------------------------------------------------------------


class RadarResponse(BaseModel):
    """Varredura do catálogo ordenada por severidade: a fila do coordenador."""

    model_config = ConfigDict(extra="ignore")

    gerado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    versao_indice: str
    total_objetos: int
    objetos_com_defasagem: int
    por_severidade: dict[str, int] = Field(default_factory=dict)
    abstencoes: dict[str, int] = Field(default_factory=dict)
    por_curso: dict[str, int] = Field(default_factory=dict)
    por_disciplina: dict[str, int] = Field(default_factory=dict)
    itens: list[AnaliseResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 5.7 Auditoria
# --------------------------------------------------------------------------


class OrigemAnalise(str, Enum):
    """De onde veio a análise. Toda análise é auditada, inclusive as do radar;
    a origem só separa as do radar das métricas de latência por request."""

    ANALISE = "analise"
    RADAR = "radar"


class RegistroAuditoria(BaseModel):
    """Trilha reconstruível. O material entra como hash, nunca em texto claro."""

    model_config = ConfigDict(extra="ignore")

    request_id: str
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    origem: OrigemAnalise = OrigemAnalise.ANALISE
    objeto_id: str
    objeto_hash: str
    curso: str | None = None
    disciplina: str | None = None
    status: StatusAnalise
    motivo_abstencao: MotivoAbstencao | None = None
    severidade_maxima: Severidade | None = None
    confianca: float = 0.0
    evidencias_citadas: list[str] = Field(default_factory=list)
    trechos_citados: list[str] = Field(default_factory=list)
    scores: list[float] = Field(default_factory=list)
    modo_sintese: str = "extrativa"
    latencia_ms: float = 0.0
    versao_indice: str = ""


# --------------------------------------------------------------------------
# 5.8 Eventos Kafka
# --------------------------------------------------------------------------


class EventoEvidenciaIndexada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    doc_id: str
    versao_indice: str
    practice_changing: bool
    trechos_indexados: int


class EventoDefasagemDetectada(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objeto_id: str
    curso: str | None = None
    disciplina: str | None = None
    severidade: Severidade
    doc_id: str
    versao_indice: str


# --------------------------------------------------------------------------
# Operação (seção 7)
# --------------------------------------------------------------------------


class MetricasResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_analises: int = 0
    por_status: dict[str, int] = Field(default_factory=dict)
    taxa_abstencao: float = 0.0
    latencia_media_ms: float = 0.0
    latencia_p95_ms: float = 0.0
    modo_sintese: str = "extrativa"
    versao_indice: str = ""
    evidencias_indexadas: int = 0
    objetos_catalogados: int = 0


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    versao: str
    detalhes: dict[str, Any] = Field(default_factory=dict)

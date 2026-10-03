"""Configuração do serviço.

Nenhuma variável é obrigatória (seção 9 do PRD): o serviço sobe com todos os
fallbacks — sem Mongo, sem Kafka e sem chave de LLM — e registra em que modo
entrou.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Parâmetros de operação, todos sobrescrevíveis por ambiente."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Identificação ----------------------------------------------------
    app_nome: str = "Currículo Vivo"
    app_versao: str = "1.0.0"

    # --- Detecção ---------------------------------------------------------
    limiar_confianca: float = Field(default=0.18, ge=0.0, le=1.0)
    top_k: int = Field(default=3, ge=1, le=50)
    exigir_fonte_oficial: bool = True

    # --- Tabela de severidade (seção 6) -----------------------------------
    gap_meses_alta: int = Field(default=24, ge=0)
    gap_meses_media: int = Field(default=12, ge=0)
    gap_meses_minimo_sem_pc: int = Field(default=12, ge=0)
    gap_meses_media_sem_pc: int = Field(default=36, ge=0)
    alerta_revisao_objeto_dias: int = Field(default=1095, ge=0)

    # --- Dados ------------------------------------------------------------
    caminho_evidencias: Path = Path("data/evidencias/base_curada.json")
    caminho_material: Path = Path("data/material/catalogo.json")

    # --- Auditoria --------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "curriculo_vivo"
    mongo_timeout_ms: int = Field(default=1500, ge=100)
    auditoria_limite_memoria: int = Field(default=1000, ge=1)

    # --- Mensageria -------------------------------------------------------
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "ingestor-curriculo"
    kafka_topic_evidencia_nova: str = "evidencia.nova"
    kafka_topic_evidencia_indexada: str = "evidencia.indexada"
    # Mensagem reprovada na validação vai para cá, com o motivo, e o offset
    # é confirmado: sem isso, uma mensagem malformada trava a partição.
    kafka_topic_evidencia_rejeitada: str = "evidencia.rejeitada"
    kafka_topic_defasagem: str = "defasagem.detectada"

    # --- Síntese da justificativa ----------------------------------------
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = Field(default=700, ge=1)
    custo_por_1k_tokens: float = Field(default=0.015, ge=0.0)

    # --- Avisos fixos de resposta ----------------------------------------
    aviso_padrao: str = (
        "Apoio à revisão curricular. Não substitui a decisão pedagógica do "
        "docente e do colegiado."
    )

    @field_validator("caminho_evidencias", "caminho_material")
    @classmethod
    def _absolutizar(cls, valor: Path) -> Path:
        """Resolve caminho relativo contra a raiz do projeto.

        Sem isso, o serviço só acharia o corpus se fosse iniciado do diretório
        certo — e a demo falharia por detalhe de shell.
        """
        return valor if valor.is_absolute() else RAIZ_PROJETO / valor

    @property
    def usa_llm(self) -> bool:
        """Chave vazia é o padrão: justificativa extrativa, sem rede."""
        return bool(self.anthropic_api_key.strip())

    @property
    def modo_sintese(self) -> str:
        return "abstrativa" if self.usa_llm else "extrativa"

    @property
    def limiar_alerta_confianca_limite(self) -> float:
        """Abaixo disso, a barreira 4 anexa alerta de confiança no limiar."""
        return self.limiar_confianca * 1.5


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância única — o índice e os limiares não mudam em tempo de request."""
    return Settings()

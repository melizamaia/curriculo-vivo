"""Síntese da justificativa de uma defasagem (ADR-4).

Extrativa por padrão: um template sobre os campos da evidência, sem rede e
sem custo. Com `ANTHROPIC_API_KEY`, um LLM redige o texto — mas os marcadores
são atribuídos aqui, antes da chamada, e o modelo só recebe a instrução de
usá-los. Quem decide se a justificativa vale é a barreira 3, que roda igual
nos dois modos: este módulo não valida a própria saída.

Falha de infraestrutura do LLM (rede, rate limit, recusa, resposta truncada)
cai para a extrativa daquela defasagem. Isso é diferente de o LLM responder
um texto ruim: texto ruim segue para a barreira 3 e é descartado, para que a
regressão apareça como `alerta_descartado` em vez de ser mascarada.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.core.detector import Comparacao
from app.core.guardrail import MARCADOR_MATERIAL
from app.models import EvidenciaCitada

logger = logging.getLogger(__name__)

MODO_EXTRATIVA = "extrativa"
MODO_ABSTRATIVA = "abstrativa"

# Recusa por classificador volta para outro modelo no servidor, roteada pela
# categoria da recusa, em vez de chegar aqui como `stop_reason: "refusal"`.
_BETA_FALLBACK = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class ContextoJustificativa:
    """Tudo que a justificativa pode afirmar. Nada fora disso."""

    tema: str
    comparacao: Comparacao
    evidencia: EvidenciaCitada


@dataclass(frozen=True)
class Sintese:
    texto: str
    modo: str
    tokens: int = 0


class GeradorJustificativa(Protocol):
    modo: str

    def gerar(self, contexto: ContextoJustificativa) -> Sintese: ...


# --------------------------------------------------------------------------
# Extrativa
# --------------------------------------------------------------------------


class JustificativaExtrativa:
    """Template determinístico. O trecho entra literal, entre aspas."""

    modo = MODO_EXTRATIVA

    def gerar(self, contexto: ContextoJustificativa) -> Sintese:
        ev = contexto.evidencia
        comp = contexto.comparacao
        classificacao = (
            "classificada como practice-changing"
            if comp.practice_changing
            else "sem mudança de prática declarada"
        )
        texto = (
            f"O material se apoia em referência de {comp.ano_material} "
            f"[{MARCADOR_MATERIAL}]. {ev.fonte} publicou em "
            f"{ev.publicado_em.isoformat()} evidência {classificacao} sobre "
            f"{contexto.tema}, {comp.gap_meses} meses depois: "
            f"\"{ev.trecho}\" [{ev.marcador}]."
        )
        return Sintese(texto=texto, modo=self.modo)


# --------------------------------------------------------------------------
# Abstrativa (LLM)
# --------------------------------------------------------------------------

_SYSTEM = (
    "Você redige a justificativa de um alerta de defasagem curricular, lida "
    "por um coordenador de curso de Medicina. Use exclusivamente os dados "
    "fornecidos na mensagem. Escreva em português, em no máximo duas frases, "
    "sem formatação. Cite a referência do material com o marcador [0] e a "
    "evidência com o marcador indicado; não use nenhum outro marcador. Não "
    "acrescente fatos, condutas, doses ou recomendações que não estejam no "
    "trecho da evidência. Responda apenas com o texto da justificativa."
)


class FalhaLLM(Exception):
    """O LLM não entregou texto utilizável por motivo de infraestrutura."""


class JustificativaLLM:
    """Justificativa redigida por LLM, com a extrativa como rede de segurança.

    `cliente` é injetável para teste; sem ele, o cliente do SDK é criado na
    primeira chamada, para que o serviço suba sem o pacote quando a chave
    está vazia.
    """

    modo = MODO_ABSTRATIVA

    def __init__(
        self,
        settings: Settings | None = None,
        cliente: Any | None = None,
        reserva: GeradorJustificativa | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._cliente = cliente
        self._reserva = reserva or JustificativaExtrativa()

    def gerar(self, contexto: ContextoJustificativa) -> Sintese:
        try:
            return self._chamar(contexto)
        except FalhaLLM as exc:
            motivo = str(exc)
        except Exception as exc:  # erro do SDK: rede, auth, rate limit, 5xx
            motivo = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "LLM indisponível para tema=%s doc_id=%s (%s); usando extrativa",
            contexto.tema,
            contexto.evidencia.doc_id,
            motivo,
        )
        return self._reserva.gerar(contexto)

    def _chamar(self, contexto: ContextoJustificativa) -> Sintese:
        resposta = self._obter_cliente().beta.messages.create(
            model=self.settings.llm_model,
            max_tokens=self.settings.llm_max_tokens,
            # Duas frases a partir de dados dados: esforço baixo basta.
            output_config={"effort": "low"},
            betas=[_BETA_FALLBACK],
            fallbacks="default",
            system=_SYSTEM,
            messages=[{"role": "user", "content": _mensagem(contexto)}],
        )
        if resposta.stop_reason == "refusal":
            raise FalhaLLM("recusa sem fallback disponível")
        if resposta.stop_reason == "max_tokens":
            raise FalhaLLM("resposta truncada em max_tokens")

        texto = " ".join(
            b.text for b in resposta.content if getattr(b, "type", None) == "text"
        ).strip()
        if not texto:
            raise FalhaLLM("resposta sem texto")

        uso = resposta.usage
        tokens = (uso.input_tokens or 0) + (uso.output_tokens or 0)
        return Sintese(texto=texto, modo=self.modo, tokens=tokens)

    def _obter_cliente(self) -> Any:
        if self._cliente is None:
            import anthropic

            self._cliente = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        return self._cliente


def _mensagem(contexto: ContextoJustificativa) -> str:
    ev = contexto.evidencia
    comp = contexto.comparacao
    return "\n".join(
        [
            f"Tema: {contexto.tema}",
            f"[{MARCADOR_MATERIAL}] Referência mais recente do material: {comp.ano_material}",
            f"[{ev.marcador}] Evidência: {ev.titulo}",
            f"Fonte: {ev.fonte} ({ev.fonte_tipo.value})",
            f"Publicada em: {ev.publicado_em.isoformat()}",
            f"Nível de evidência: {ev.nivel_evidencia.value}",
            f"Practice-changing: {'sim' if comp.practice_changing else 'não'}",
            f"Meses entre a referência do material e a evidência: {comp.gap_meses}",
            f"Trecho da evidência: \"{ev.trecho}\"",
            "",
            f"Marcadores permitidos: [{MARCADOR_MATERIAL}] e [{ev.marcador}].",
        ]
    )


def criar_gerador(settings: Settings | None = None) -> GeradorJustificativa:
    """Extrativa sem chave; LLM com chave. Registra em que modo entrou."""
    s = settings or get_settings()
    gerador: GeradorJustificativa = (
        JustificativaLLM(s) if s.usa_llm else JustificativaExtrativa()
    )
    logger.info("Síntese da justificativa em modo %s", gerador.modo)
    return gerador

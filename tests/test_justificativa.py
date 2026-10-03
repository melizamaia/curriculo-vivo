"""Síntese da justificativa (core/justificativa.py).

O LLM é simulado: nenhum teste depende de rede ou de chave. O que se testa
é o contrato com o resto do fluxo — marcadores no texto extrativo, falha de
infraestrutura cai para a extrativa, texto ruim do LLM passa adiante para a
barreira 3 decidir.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.detector import comparar
from app.core.guardrail import Guardrail
from app.core.justificativa import (
    ContextoJustificativa,
    JustificativaExtrativa,
    JustificativaLLM,
    criar_gerador,
)
from app.models import Defasagem, EvidenciaCitada, FonteTipo, NivelEvidencia

ANO = 2019


def contexto(marcador: int = 2) -> ContextoJustificativa:
    evidencia = EvidenciaCitada(
        marcador=marcador,
        doc_id="ms-sepse-2024",
        trecho_id="ms-sepse-2024#t1",
        titulo="Reconhecimento precoce da sepse",
        fonte="Ministério da Saúde",
        fonte_tipo=FonteTipo.ORGAO_OFICIAL,
        publicado_em=date(2024, 5, 20),
        nivel_evidencia=NivelEvidencia.A,
        trecho="O rastreamento na porta de entrada reduz o tempo até o tratamento.",
        score=0.57,
    )
    return ContextoJustificativa(
        tema="sepse",
        comparacao=comparar(ANO, evidencia.publicado_em, True),
        evidencia=evidencia,
    )


def defasagem_com(texto: str, ctx: ContextoJustificativa) -> Defasagem:
    comp = ctx.comparacao
    return Defasagem(
        tema=ctx.tema,
        severidade=comp.severidade,
        gap_meses=comp.gap_meses,
        practice_changing=comp.practice_changing,
        justificativa=texto,
        evidencia=ctx.evidencia,
    )


class ClienteFalso:
    """Imita `client.beta.messages.create` e guarda os argumentos."""

    def __init__(self, texto="", stop_reason="end_turn", erro: Exception | None = None):
        self.chamadas: list[dict] = []
        self._texto, self._stop, self._erro = texto, stop_reason, erro
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        if self._erro:
            raise self._erro
        return SimpleNamespace(
            stop_reason=self._stop,
            content=[SimpleNamespace(type="text", text=self._texto)] if self._texto else [],
            usage=SimpleNamespace(input_tokens=120, output_tokens=40),
        )


SETTINGS_LLM = Settings(anthropic_api_key="chave-fake")


# --------------------------------------------------------------------------
# Extrativa
# --------------------------------------------------------------------------


def test_extrativa_usa_so_os_marcadores_permitidos_e_passa_na_barreira_3():
    ctx = contexto(marcador=2)
    sintese = JustificativaExtrativa().gerar(ctx)

    assert sintese.modo == "extrativa"
    assert sintese.tokens == 0
    assert "[0]" in sintese.texto and "[2]" in sintese.texto
    assert ctx.evidencia.trecho in sintese.texto
    validacao = Guardrail(Settings()).barreira_validacao([defasagem_com(sintese.texto, ctx)], ANO)
    assert len(validacao.validas) == 1


def test_criar_gerador_respeita_a_chave():
    assert criar_gerador(Settings(anthropic_api_key="")).modo == "extrativa"
    assert criar_gerador(SETTINGS_LLM).modo == "abstrativa"


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------


def test_llm_recebe_marcadores_e_devolve_texto_e_tokens():
    cliente = ClienteFalso("O material cita 2019 [0]; há diretriz de 2024 [2].")
    sintese = JustificativaLLM(SETTINGS_LLM, cliente=cliente).gerar(contexto(2))

    assert sintese.modo == "abstrativa"
    assert sintese.texto == "O material cita 2019 [0]; há diretriz de 2024 [2]."
    assert sintese.tokens == 160
    chamada = cliente.chamadas[0]
    assert chamada["model"] == SETTINGS_LLM.llm_model
    assert chamada["fallbacks"] == "default"
    assert "Marcadores permitidos: [0] e [2]." in chamada["messages"][0]["content"]


@pytest.mark.parametrize(
    "cliente",
    [
        ClienteFalso(erro=RuntimeError("conexão recusada")),
        ClienteFalso("texto parcial [0]", stop_reason="max_tokens"),
        ClienteFalso("", stop_reason="refusal"),
        ClienteFalso(""),
    ],
    ids=["erro_de_rede", "truncada", "recusa", "sem_texto"],
)
def test_falha_de_infraestrutura_cai_para_extrativa(cliente, caplog):
    ctx = contexto()
    sintese = JustificativaLLM(SETTINGS_LLM, cliente=cliente).gerar(ctx)
    assert sintese == JustificativaExtrativa().gerar(ctx)
    assert "usando extrativa" in caplog.text


def test_texto_ruim_do_llm_nao_e_corrigido_aqui():
    # Marcador errado não é falha de infraestrutura: o texto segue como veio
    # e a barreira 3 descarta. Mascarar aqui esconderia a regressão.
    ctx = contexto(marcador=1)
    cliente = ClienteFalso("Material [0], evidência [3].")
    sintese = JustificativaLLM(SETTINGS_LLM, cliente=cliente).gerar(ctx)

    assert sintese.modo == "abstrativa"
    assert sintese.texto == "Material [0], evidência [3]."
    validacao = Guardrail(SETTINGS_LLM).barreira_validacao([defasagem_com(sintese.texto, ctx)], ANO)
    assert validacao.todas_descartadas

"""Orquestração (core/servico.py) e invariantes da seção 5.5 ponta a ponta.

O retriever espião prova a ordem do fluxo: objeto inelegível não chega à
busca. Os casos do `eval/dataset.json` rodam aqui como regressão rápida; o
harness da seção 8 mede as taxas, este teste só exige que nada mude.
"""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from app.config import Settings
from app.core.justificativa import JustificativaExtrativa, Sintese
from app.core.retriever import Retriever
from app.core.servico import ServicoAnalise
from app.models import (
    MotivoAbstencao,
    ObjetoAprendizagem,
    Referencia,
    Severidade,
    StatusAnalise,
    Trecho,
)

SETTINGS = Settings()
HOJE = date(2026, 10, 3)


@pytest.fixture(scope="module")
def retriever() -> Retriever:
    return Retriever.carregar(SETTINGS.caminho_evidencias)


@pytest.fixture(scope="module")
def catalogo() -> dict[str, ObjetoAprendizagem]:
    bruto = json.loads(SETTINGS.caminho_material.read_text(encoding="utf-8"))
    return {o["objeto_id"]: ObjetoAprendizagem.model_validate(o) for o in bruto}


def servico(retriever, gerador=None) -> ServicoAnalise:
    return ServicoAnalise(
        retriever, SETTINGS, gerador=gerador or JustificativaExtrativa(), hoje=lambda: HOJE
    )


class RetrieverEspiao:
    """Delega ao retriever real e conta as chamadas de `buscar`."""

    def __init__(self, real: Retriever) -> None:
        self._real = real
        self.chamadas: list[str | None] = []

    @property
    def versao_indice(self) -> str:
        return self._real.versao_indice

    def buscar(self, consulta, tema=None, top_k=3):
        self.chamadas.append(tema)
        return self._real.buscar(consulta, tema=tema, top_k=top_k)


# --------------------------------------------------------------------------
# Barreira 1 antes de qualquer recuperação
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("objeto_id", "motivo"),
    [
        ("med-objeto-invalido-aula04", MotivoAbstencao.OBJETO_INVALIDO),
        ("med-sem-referencia-aula01", MotivoAbstencao.MATERIAL_SEM_REFERENCIA),
        ("med-referencia-sem-ano-aula02", MotivoAbstencao.MATERIAL_SEM_REFERENCIA),
        ("med-escopo-questao-aula03", MotivoAbstencao.FORA_DE_ESCOPO),
    ],
)
def test_inelegivel_nao_chama_buscar(retriever, catalogo, objeto_id, motivo):
    espiao = RetrieverEspiao(retriever)
    resposta = servico(espiao).analisar(catalogo[objeto_id])

    assert espiao.chamadas == []
    assert resposta.status is StatusAnalise.ABSTIDO
    assert resposta.motivo_abstencao is motivo


def test_elegivel_busca_uma_vez_por_tema(retriever, catalogo):
    objeto = catalogo["med-clin-sepse-aula07"]
    espiao = RetrieverEspiao(retriever)
    servico(espiao).analisar(objeto)
    assert espiao.chamadas == objeto.temas


# --------------------------------------------------------------------------
# Dataset de avaliação como regressão
# --------------------------------------------------------------------------

_DATASET = json.loads(
    (SETTINGS.caminho_material.parents[2] / "eval" / "dataset.json").read_text(
        encoding="utf-8"
    )
)["itens"]
_STATUS_POR_CLASSE = {
    "defasado": StatusAnalise.DEFASAGEM_DETECTADA,
    "atualizado": StatusAnalise.SEM_ACHADO,
    "sem_evidencia": StatusAnalise.ABSTIDO,
    "inelegivel": StatusAnalise.ABSTIDO,
}


@pytest.mark.parametrize("caso", _DATASET, ids=[c["id"] for c in _DATASET])
def test_caso_do_dataset(retriever, catalogo, caso):
    resposta = servico(retriever).analisar(catalogo[caso["objeto_id"]])

    assert resposta.status is _STATUS_POR_CLASSE[caso["classe"]]
    motivo = resposta.motivo_abstencao.value if resposta.motivo_abstencao else None
    assert motivo == caso["motivo_esperado"]
    if caso["evidencia_esperada"]:
        assert caso["evidencia_esperada"] in {d.evidencia.doc_id for d in resposta.defasagens}
    severidade = resposta.severidade_maxima.value if resposta.severidade_maxima else None
    assert severidade == caso["severidade_esperada"]


# --------------------------------------------------------------------------
# Invariantes da seção 5.5 sobre o catálogo inteiro
# --------------------------------------------------------------------------


def test_invariantes_em_todo_o_catalogo(retriever, catalogo):
    marcador = re.compile(r"\[(\d+)\]")
    for objeto in catalogo.values():
        r = servico(retriever).analisar(objeto)

        # 1. defasagem_detectada ⟹ ao menos uma defasagem, todas com evidência
        if r.status is StatusAnalise.DEFASAGEM_DETECTADA:
            assert r.defasagens and all(d.evidencia for d in r.defasagens)
        else:
            assert r.defasagens == []

        # 2. todo marcador citado existe entre as evidências da resposta, ou é [0]
        citados = {d.evidencia.marcador for d in r.defasagens} | {0}
        for d in r.defasagens:
            assert {int(m) for m in marcador.findall(d.justificativa)} <= citados

        # 3. evidência posterior a 31/12 do ano de referência do material
        for d in r.defasagens:
            assert d.evidencia.publicado_em > date(r.ano_referencia_material, 12, 31)

        # alerta_descartado nunca aparece em operação normal
        assert r.motivo_abstencao is not MotivoAbstencao.ALERTA_DESCARTADO


# --------------------------------------------------------------------------
# Invariante 4 ponta a ponta: gerador que regride
# --------------------------------------------------------------------------


class GeradorQueRegride:
    """Simula um LLM que passou a citar o marcador errado."""

    modo = "abstrativa"

    def gerar(self, contexto):
        return Sintese(
            texto=f"Material [0], evidência [{contexto.evidencia.marcador + 1}].",
            modo=self.modo,
        )


def test_gerador_que_regride_vira_alerta_descartado(retriever, catalogo, caplog):
    resposta = servico(retriever, GeradorQueRegride()).analisar(
        catalogo["med-clin-sepse-aula07"]
    )
    assert resposta.status is StatusAnalise.ABSTIDO
    assert resposta.motivo_abstencao is MotivoAbstencao.ALERTA_DESCARTADO
    assert resposta.defasagens == []
    assert resposta.modo_sintese == "abstrativa"
    assert "Barreira 3" in caplog.text


def test_atualizado_continua_sem_achado_com_gerador_que_regride(retriever, catalogo):
    # Sem defasagem candidata não há o que descartar: sem_achado legítimo
    # não pode virar alerta_descartado.
    resposta = servico(retriever, GeradorQueRegride()).analisar(
        catalogo["med-card-hipertensao-aula03"]
    )
    assert resposta.status is StatusAnalise.SEM_ACHADO


# --------------------------------------------------------------------------
# Marcadores e resposta
# --------------------------------------------------------------------------


def test_mesma_evidencia_em_dois_temas_reusa_o_marcador(retriever, catalogo):
    base = catalogo["med-clin-sepse-aula07"]
    objeto = base.model_copy(update={"temas": ["sepse", "sepse"]})
    resposta = servico(retriever).analisar(objeto)
    assert [d.evidencia.marcador for d in resposta.defasagens] == [1, 1]


def test_multitema_cita_cada_tema_e_severidade_maxima_vence(retriever, catalogo):
    r = servico(retriever).analisar(catalogo["med-clin-sepse-antibiotico-aula15"])
    assert [(d.tema, d.severidade, d.evidencia.doc_id, d.evidencia.marcador)
            for d in r.defasagens] == [
        ("sepse", Severidade.MEDIA, "ms-sepse-2024", 1),
        ("antibioticoterapia", Severidade.ALTA, "diretriz-antibiotico-duracao-2024", 2),
    ]
    assert r.severidade_maxima is Severidade.ALTA


def test_multitema_parcial_cita_so_o_tema_defasado(retriever, catalogo):
    r = servico(retriever).analisar(catalogo["med-angio-tev-antibiotico-aula16"])
    assert r.status is StatusAnalise.DEFASAGEM_DETECTADA
    assert [d.tema for d in r.defasagens] == ["antibioticoterapia"]


def test_objeto_sem_temas_abstem(retriever):
    objeto = ObjetoAprendizagem(
        objeto_id="sem-temas",
        titulo="Aula sem tema",
        referencias=[Referencia(titulo="Livro", ano=2019)],
        trechos=[Trecho(trecho_id="sem-temas#t1", texto="Conteúdo qualquer.")],
    )
    resposta = servico(retriever).analisar(objeto)
    assert resposta.status is StatusAnalise.ABSTIDO
    assert resposta.motivo_abstencao is MotivoAbstencao.EVIDENCIA_INSUFICIENTE


def test_resposta_de_defasagem_carrega_contrato(retriever, catalogo):
    r = servico(retriever).analisar(catalogo["med-clin-sepse-aula07"])
    assert r.ano_referencia_material == 2019
    assert r.severidade_maxima is Severidade.ALTA
    assert r.modo_sintese == "extrativa"
    assert r.confianca > SETTINGS.limiar_confianca
    assert r.aviso == SETTINGS.aviso_padrao
    assert any(a.startswith("Base de demonstração") for a in r.alertas)
    ev = r.defasagens[0].evidencia
    assert ev.trecho and ev.fonte and ev.publicado_em and ev.nivel_evidencia


# --------------------------------------------------------------------------
# Radar
# --------------------------------------------------------------------------


def test_radar_ordena_por_severidade_e_agrega(retriever, catalogo):
    radar = servico(retriever).radar(catalogo.values())

    assert radar.total_objetos == len(catalogo)
    assert radar.objetos_com_defasagem == 19
    assert radar.por_severidade == {"alta": 6, "media": 6, "baixa": 7}
    assert radar.versao_indice == retriever.versao_indice
    assert sum(radar.por_curso.values()) == 19
    assert set(radar.por_curso) == {"Medicina", "Enfermagem", "Farmacia"}

    pesos = [
        {"alta": 3, "media": 2, "baixa": 1}.get(
            i.severidade_maxima.value if i.severidade_maxima else "", 0
        )
        for i in radar.itens
    ]
    assert pesos == sorted(pesos, reverse=True)


def test_radar_filtra_severidade_e_limita(retriever, catalogo):
    radar = servico(retriever).radar(
        catalogo.values(), severidade=Severidade.ALTA, limite=2
    )
    assert radar.total_objetos == 6
    assert len(radar.itens) == 2
    assert all(i.severidade_maxima is Severidade.ALTA for i in radar.itens)


def test_radar_filtra_disciplina(retriever, catalogo):
    radar = servico(retriever).radar(catalogo.values(), disciplina="Neurologia")
    assert radar.total_objetos > 0
    assert all(i.disciplina == "Neurologia" for i in radar.itens)

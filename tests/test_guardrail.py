"""Barreiras de guardrail (seção 6 do PRD) e invariantes da seção 5.5.

Um caso por motivo de abstenção, os descartes da barreira 3 um a um e a
queda para `abstido` quando todas as defasagens são descartadas. Mudar
qualquer expectativa daqui é mudança de produto.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from app.config import Settings
from app.core.guardrail import Guardrail, Proveniencia, Validacao, consolidar_status
from app.core.retriever import Candidato
from app.models import (
    Defasagem,
    Evidencia,
    EvidenciaCitada,
    FonteTipo,
    MotivoAbstencao,
    NivelEvidencia,
    ObjetoAprendizagem,
    Referencia,
    Severidade,
    StatusAnalise,
    Trecho,
)

SETTINGS = Settings(limiar_confianca=0.18, exigir_fonte_oficial=True)
GUARDRAIL = Guardrail(SETTINGS)
ANO = 2019  # data de corte do material: 31/12/2019


# --------------------------------------------------------------------------
# Fábricas
# --------------------------------------------------------------------------


def objeto(**sobrescrever) -> ObjetoAprendizagem:
    base = dict(
        objeto_id="obj-teste",
        titulo="Sepse e choque séptico: reconhecimento e manejo inicial",
        temas=["sepse"],
        referencias=[Referencia(titulo="Protocolo de sepse", ano=ANO)],
        trechos=[
            Trecho(
                trecho_id="obj-teste#t1",
                texto="A aula discute o reconhecimento precoce da sepse e a dose "
                "de ataque de antimicrobiano no paciente internado.",
            )
        ],
    )
    base.update(sobrescrever)
    return ObjetoAprendizagem(**base)


def com_texto(texto: str) -> ObjetoAprendizagem:
    return objeto(trechos=[Trecho(trecho_id="obj-teste#t1", texto=texto)])


def candidato(
    doc_id: str = "ms-sepse-2024",
    score: float = 0.45,
    fonte_tipo: FonteTipo = FonteTipo.ORGAO_OFICIAL,
) -> Candidato:
    trecho = Trecho(trecho_id=f"{doc_id}#t1", texto="trecho vigente")
    evidencia = Evidencia(
        doc_id=doc_id,
        titulo="Evidência de teste",
        fonte="Fonte de teste",
        fonte_tipo=fonte_tipo,
        publicado_em=date(2024, 5, 20),
        temas=["sepse"],
        trechos=[trecho],
    )
    return Candidato(evidencia=evidencia, trecho=trecho, score=score)


def citada(
    marcador: int = 1,
    doc_id: str = "ms-sepse-2024",
    publicado_em: date = date(2024, 5, 20),
) -> EvidenciaCitada:
    return EvidenciaCitada(
        marcador=marcador,
        doc_id=doc_id,
        trecho_id=f"{doc_id}#t1",
        titulo="Evidência de teste",
        fonte="Fonte de teste",
        fonte_tipo=FonteTipo.ORGAO_OFICIAL,
        publicado_em=publicado_em,
        nivel_evidencia=NivelEvidencia.A,
        trecho="trecho vigente",
        score=0.45,
    )


def defasagem(
    justificativa: str = "O material cita 2019 [0]. Existe evidência de 2024 [1].",
    evidencia: EvidenciaCitada | None = None,
    tema: str = "sepse",
) -> Defasagem:
    return Defasagem(
        tema=tema,
        severidade=Severidade.ALTA,
        gap_meses=53,
        practice_changing=True,
        justificativa=justificativa,
        evidencia=evidencia or citada(),
    )


# --------------------------------------------------------------------------
# Barreira 1 — escopo e elegibilidade
# --------------------------------------------------------------------------


def test_objeto_elegivel_passa_e_carrega_ano_material():
    resultado = GUARDRAIL.barreira_escopo(objeto())
    assert resultado.elegivel
    assert resultado.ano_material == ANO


@pytest.mark.parametrize(
    "sobrescrever",
    [
        {"trechos": []},
        {"titulo": "   "},
        {"trechos": [Trecho(trecho_id="obj-teste#t1", texto="  ")]},
    ],
    ids=["sem_trechos", "sem_titulo", "trechos_vazios"],
)
def test_objeto_invalido(sobrescrever):
    resultado = GUARDRAIL.barreira_escopo(objeto(**sobrescrever))
    assert resultado.motivo is MotivoAbstencao.OBJETO_INVALIDO


@pytest.mark.parametrize(
    "referencias",
    [[], [Referencia(titulo="Capítulo sem ano", ano=None)]],
    ids=["sem_referencias", "referencia_sem_ano"],
)
def test_material_sem_referencia(referencias):
    resultado = GUARDRAIL.barreira_escopo(objeto(referencias=referencias))
    assert resultado.motivo is MotivoAbstencao.MATERIAL_SEM_REFERENCIA
    assert resultado.ano_material is None


@pytest.mark.parametrize(
    "texto",
    [
        # dose/posologia individualizada
        "Qual a dose que devo prescrever para o meu paciente de 70 kg no choque "
        "séptico? Informe a posologia exata.",
        # emissão de documento médico
        "Emita um atestado de afastamento de sete dias para o plantão.",
        # paciente ou aluno identificado
        "Paciente Maria Souza, leito 12, evoluiu com hipotensão.",
        "O aluno João Pereira errou a conduta no simulado.",
        "Prontuário 448812: discutir a conduta em aula.",
    ],
    ids=["dose_individualizada", "documento_medico", "paciente_nome", "aluno_nome", "prontuario"],
)
def test_fora_de_escopo(texto):
    resultado = GUARDRAIL.barreira_escopo(com_texto(texto))
    assert resultado.motivo is MotivoAbstencao.FORA_DE_ESCOPO
    assert resultado.detalhe


@pytest.mark.parametrize(
    "texto",
    [
        "A aula discute a dose de ataque de antimicrobiano na sepse.",
        "Prevenção de delirium em pacientes internados por longos períodos.",
        "Como preencher a declaração de óbito: aspectos legais e éticos.",
        "Questão: qual a posologia usual da metformina no adulto?",
    ],
)
def test_assunto_clinico_nao_e_fora_de_escopo(texto):
    # Falar de dose, paciente ou documento é currículo; fora de escopo é o
    # pedido individualizado. Abster aqui também seria falso alarme.
    assert GUARDRAIL.barreira_escopo(com_texto(texto)).elegivel


# --------------------------------------------------------------------------
# Barreira 2 — confiança e proveniência
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidatos",
    [[], [candidato(score=0.17)]],
    ids=["sem_candidato", "abaixo_do_limiar"],
)
def test_evidencia_insuficiente(candidatos):
    resultado = GUARDRAIL.barreira_proveniencia("sepse", candidatos)
    assert resultado.motivo is MotivoAbstencao.EVIDENCIA_INSUFICIENTE
    assert resultado.candidato is None


@pytest.mark.parametrize(
    "fonte_tipo", [FonteTipo.NAO_VALIDADA, FonteTipo.LITERATURA_REVISADA]
)
def test_fonte_nao_validada(fonte_tipo):
    resultado = GUARDRAIL.barreira_proveniencia(
        "sepse", [candidato(score=0.6, fonte_tipo=fonte_tipo)]
    )
    assert resultado.motivo is MotivoAbstencao.FONTE_NAO_VALIDADA
    assert resultado.candidato is None
    assert resultado.confianca == 0.6


def test_limiar_e_inclusivo():
    resultado = GUARDRAIL.barreira_proveniencia("sepse", [candidato(score=0.18)])
    assert resultado.aprovado


def test_fonte_nao_validada_com_score_maior_nao_puxa_a_escolha():
    literatura = candidato("artigo-2025", 0.70, FonteTipo.LITERATURA_REVISADA)
    oficial = candidato("ms-sepse-2024", 0.30, FonteTipo.ORGAO_OFICIAL)
    resultado = GUARDRAIL.barreira_proveniencia("sepse", [literatura, oficial])
    assert resultado.candidato is oficial
    assert resultado.confianca == 0.70


def test_validada_abaixo_do_limiar_nao_conta():
    resultado = GUARDRAIL.barreira_proveniencia(
        "sepse",
        [
            candidato("artigo", 0.50, FonteTipo.LITERATURA_REVISADA),
            candidato("ms-sepse-2024", 0.10, FonteTipo.ORGAO_OFICIAL),
        ],
    )
    assert resultado.motivo is MotivoAbstencao.FONTE_NAO_VALIDADA


def test_sem_exigir_fonte_oficial_aceita_qualquer_fonte():
    guardrail = Guardrail(Settings(exigir_fonte_oficial=False))
    c = candidato(score=0.5, fonte_tipo=FonteTipo.NAO_VALIDADA)
    assert guardrail.barreira_proveniencia("sepse", [c]).candidato is c


def test_empate_resolvido_por_doc_id():
    b = candidato("doc-b", 0.4)
    a = candidato("doc-a", 0.4)
    assert GUARDRAIL.barreira_proveniencia("sepse", [b, a]).candidato is a


# --------------------------------------------------------------------------
# Barreira 3 — validação do achado
# --------------------------------------------------------------------------


def test_defasagem_bem_formada_passa():
    resultado = GUARDRAIL.barreira_validacao([defasagem()], ANO)
    assert len(resultado.validas) == 1
    assert resultado.descartes == []


@pytest.mark.parametrize(
    ("caso", "trecho_motivo"),
    [
        (
            lambda: Defasagem.model_construct(
                tema="sepse",
                severidade=Severidade.ALTA,
                gap_meses=53,
                practice_changing=True,
                justificativa="Evidência nova [1].",
                evidencia=None,
            ),
            "sem evidência",
        ),
        (lambda: defasagem(justificativa="Existe evidência mais nova."), "sem marcador"),
        (lambda: defasagem(justificativa="Material [0], evidência [2]."), "[2]"),
        (lambda: defasagem(justificativa="Material [0], evidências [1] e [3]."), "[3]"),
        (lambda: defasagem(justificativa="O material cita 2019 [0]."), "não cita"),
        (
            lambda: defasagem(evidencia=citada(publicado_em=date(2019, 12, 31))),
            "não é posterior",
        ),
        (
            lambda: defasagem(evidencia=citada(publicado_em=date(2018, 3, 1))),
            "não é posterior",
        ),
    ],
    ids=[
        "sem_evidencia",
        "sem_marcador",
        "marcador_de_outra_evidencia",
        "marcador_extra",
        "so_cita_o_material",
        "evidencia_na_data_de_corte",
        "evidencia_anterior",
    ],
)
def test_barreira_3_descarta(caso, trecho_motivo):
    resultado = GUARDRAIL.barreira_validacao([caso()], ANO)
    assert resultado.validas == []
    assert len(resultado.descartes) == 1
    assert trecho_motivo in resultado.descartes[0].motivo


def test_barreira_3_descarta_individualmente_e_registra_em_log(caplog):
    boa = defasagem(tema="sepse")
    ruim = defasagem(
        tema="emergencia",
        justificativa="Material [0], evidência [2].",
        evidencia=citada(marcador=2, doc_id="ms-emergencia-2018", publicado_em=date(2018, 1, 1)),
    )
    with caplog.at_level(logging.WARNING, logger="app.core.guardrail"):
        resultado = GUARDRAIL.barreira_validacao([boa, ruim], ANO, objeto_id="obj-teste")

    assert resultado.validas == [boa]
    assert [d.tema for d in resultado.descartes] == ["emergencia"]
    assert not resultado.todas_descartadas
    registro = caplog.records[-1].getMessage()
    assert "obj-teste" in registro
    assert "emergencia" in registro
    assert "ms-emergencia-2018" in registro
    assert "não é posterior" in registro


def test_barreira_3_descarta_marcador_reaproveitado_por_outra_evidencia():
    primeira = defasagem(tema="sepse", evidencia=citada(1, "ms-sepse-2024"))
    colide = defasagem(tema="emergencia", evidencia=citada(1, "outra-2024"))
    resultado = GUARDRAIL.barreira_validacao([primeira, colide], ANO)
    assert resultado.validas == [primeira]
    assert "já atribuído" in resultado.descartes[0].motivo


@pytest.mark.parametrize("modo", ["extrativa", "abstrativa"])
def test_barreira_3_independe_do_modo_de_sintese(modo):
    # A barreira não recebe nem consulta o modo: a mesma justificativa ruim
    # cai com e sem chave de LLM.
    guardrail = Guardrail(
        Settings(anthropic_api_key="chave-fake" if modo == "abstrativa" else "")
    )
    assert guardrail.settings.modo_sintese == modo
    ruim = defasagem(justificativa="Material [0], evidência [7].")
    assert guardrail.barreira_validacao([ruim], ANO).validas == []


# --------------------------------------------------------------------------
# Agregação — invariante 4 da seção 5.5
# --------------------------------------------------------------------------

APROVADO = Proveniencia("sepse", candidato(), None, 0.45)


def test_todas_descartadas_cai_para_abstido_nunca_sem_achado():
    ruins = [
        defasagem(tema="sepse", justificativa="Sem citação nenhuma."),
        defasagem(
            tema="emergencia",
            justificativa="Material [0], evidência [1].",  # a dela é [2]
            evidencia=citada(marcador=2, doc_id="ms-emergencia-2024"),
        ),
        defasagem(tema="choque", evidencia=citada(publicado_em=date(2019, 6, 1))),
    ]
    validacao = GUARDRAIL.barreira_validacao(ruins, ANO)
    assert validacao.todas_descartadas
    assert len(validacao.descartes) == 3

    status, motivo = consolidar_status([APROVADO], validacao)
    assert status is StatusAnalise.ABSTIDO
    assert status is not StatusAnalise.SEM_ACHADO
    # Regressão do gerador, não falta de base: nunca um motivo sobre o material.
    assert motivo is MotivoAbstencao.ALERTA_DESCARTADO


def test_uma_valida_basta_para_defasagem_detectada():
    validacao = GUARDRAIL.barreira_validacao(
        [defasagem(), defasagem(tema="choque", justificativa="Sem citação.")], ANO
    )
    assert consolidar_status([APROVADO], validacao) == (
        StatusAnalise.DEFASAGEM_DETECTADA,
        None,
    )


def test_temas_aprovados_sem_defasagem_e_sem_achado():
    assert consolidar_status([APROVADO], Validacao()) == (StatusAnalise.SEM_ACHADO, None)


def test_nenhum_tema_aprovado_abstem_com_motivo_do_primeiro():
    provs = [
        Proveniencia("rinite", None, MotivoAbstencao.FONTE_NAO_VALIDADA, 0.45),
        Proveniencia("glaucoma", None, MotivoAbstencao.EVIDENCIA_INSUFICIENTE, 0.0),
    ]
    assert consolidar_status(provs, Validacao()) == (
        StatusAnalise.ABSTIDO,
        MotivoAbstencao.FONTE_NAO_VALIDADA,
    )


# --------------------------------------------------------------------------
# Barreira 4 — alertas que acompanham
# --------------------------------------------------------------------------


def test_alertas_de_demonstracao_limiar_e_revisao():
    alertas = GUARDRAIL.barreira_alertas(
        objeto(atualizado_em=date(2019, 8, 1)),
        [defasagem()],
        confianca=0.20,  # entre 0.18 e 0.27
        hoje=date(2026, 10, 3),
    )
    assert len(alertas) == 3
    assert alertas[0].startswith("Base de demonstração")
    assert alertas[1].startswith("Confiança no limiar")
    assert alertas[2].startswith("Revisão geral pendente")


def test_sem_alertas_quando_nada_se_aplica():
    real = citada().model_copy(update={"exemplo_ilustrativo": False})
    alertas = GUARDRAIL.barreira_alertas(
        objeto(atualizado_em=date(2026, 1, 1)),
        [defasagem(evidencia=real)],
        confianca=0.45,
        hoje=date(2026, 10, 3),
    )
    assert alertas == []

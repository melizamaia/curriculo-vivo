"""Tabela de severidade (seção 6 do PRD), fronteiras incluídas.

Mudar qualquer expectativa daqui é mudança de produto: a tabela é a regra
que o coordenador lê para entender por que um alerta é alto.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.detector import RegraSeveridade, comparar, gap_meses
from app.models import Severidade

REGRA = RegraSeveridade()
ANO = 2020  # data de corte do material: 31/12/2020


@pytest.mark.parametrize(
    ("publicado_em", "esperado"),
    [
        (date(2021, 1, 15), 1),
        (date(2021, 11, 30), 11),
        (date(2021, 12, 1), 12),
        (date(2021, 12, 31), 12),
        (date(2022, 1, 1), 13),
        (date(2022, 12, 1), 24),
        (date(2023, 12, 1), 36),
        # Meses de calendário, não dias: 2 dias depois do corte já é 1 mês.
        (date(2021, 1, 2), 1),
        (date(2020, 12, 31), 0),
        (date(2020, 6, 1), -6),
    ],
)
def test_gap_meses_e_diferenca_de_meses_de_calendario(publicado_em, esperado):
    assert gap_meses(ANO, publicado_em) == esperado


@pytest.mark.parametrize(
    ("gap", "practice_changing", "esperado"),
    [
        # practice_changing = true
        (60, True, Severidade.ALTA),
        (25, True, Severidade.ALTA),
        (24, True, Severidade.ALTA),  # fronteira: exatamente 24 sobe para alta
        (23, True, Severidade.MEDIA),
        (13, True, Severidade.MEDIA),
        (12, True, Severidade.MEDIA),  # fronteira: exatamente 12 sobe para media
        (11, True, Severidade.BAIXA),
        (1, True, Severidade.BAIXA),
        # practice_changing = false
        (60, False, Severidade.MEDIA),
        (36, False, Severidade.MEDIA),  # fronteira: exatamente 36 sobe para media
        (35, False, Severidade.BAIXA),
        (24, False, Severidade.BAIXA),
        (12, False, Severidade.BAIXA),  # fronteira: exatamente 12 vira baixa
        (11, False, None),
        (1, False, None),
    ],
)
def test_tabela_de_severidade(gap, practice_changing, esperado):
    assert REGRA.classificar(gap, practice_changing) is esperado


@pytest.mark.parametrize(
    ("publicado_em", "practice_changing", "gap", "esperado"),
    [
        (date(2021, 12, 3), True, 12, Severidade.MEDIA),
        (date(2021, 11, 28), True, 11, Severidade.BAIXA),
        (date(2022, 12, 3), True, 24, Severidade.ALTA),
        (date(2022, 11, 28), True, 23, Severidade.MEDIA),
        (date(2021, 12, 3), False, 12, Severidade.BAIXA),
        (date(2021, 11, 28), False, 11, None),
        (date(2023, 12, 3), False, 36, Severidade.MEDIA),
    ],
)
def test_comparar_nas_fronteiras(publicado_em, practice_changing, gap, esperado):
    resultado = comparar(ANO, publicado_em, practice_changing, REGRA)
    assert resultado.gap_meses == gap
    assert resultado.severidade is esperado
    assert resultado.defasado is (esperado is not None)


@pytest.mark.parametrize("practice_changing", [True, False])
@pytest.mark.parametrize(
    "publicado_em",
    [
        date(2018, 3, 1),  # anos antes da referência
        date(2020, 1, 1),  # mesmo ano da referência
        date(2020, 12, 31),  # exatamente na data de corte: não é posterior
    ],
)
def test_evidencia_nao_posterior_nunca_gera_achado(publicado_em, practice_changing):
    resultado = comparar(ANO, publicado_em, practice_changing, REGRA)
    assert resultado.gap_meses <= 0
    assert resultado.severidade is None
    assert not resultado.defasado


def test_regra_vem_de_settings():
    from app.config import Settings

    regra = RegraSeveridade.de_settings(Settings(gap_meses_alta=30))
    assert regra.classificar(24, True) is Severidade.MEDIA
    assert regra.classificar(30, True) is Severidade.ALTA

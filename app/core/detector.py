"""Comparação de datas e severidade (seção 6 do PRD, ADR-2 e ADR-3).

A pergunta que este módulo responde é estreita de propósito: dada a
referência mais nova do material e a evidência vigente sobre o mesmo tema,
a evidência é posterior? Quantos meses? Quão grave?

Nada aqui olha conteúdo semântico. "Sua aula cita 2019, existe 2024" é
verificável pelo coordenador; um score de divergência textual não é.
Recuperação, proveniência e limiar ficam no retriever e no guardrail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.config import Settings, get_settings
from app.models import ObjetoAprendizagem, Severidade

# O material só informa o ano da referência. A data de corte é o último dia
# desse ano: o critério conservador, que nunca antecipa a referência.
MES_CORTE_MATERIAL = 12


def ano_material(objeto: ObjetoAprendizagem) -> int | None:
    """Maior `ano` entre as referências; `None` torna o objeto inelegível."""
    return objeto.ano_referencia


def data_corte(ano: int) -> date:
    """31/12 do ano da referência do material."""
    return date(ano, MES_CORTE_MATERIAL, 31)


def evidencia_posterior(ano: int, publicado_em: date) -> bool:
    """A evidência saiu depois de 31/12 do ano da referência do material?

    É a invariante 3 da seção 5.5: alerta que não satisfaz isso é descartado.
    """
    return publicado_em > data_corte(ano)


def gap_meses(ano: int, publicado_em: date) -> int:
    """Meses de calendário entre dez/`ano` e o mês de `publicado_em`.

    Diferença de meses de calendário, não de dias: uma evidência de
    dezembro do ano seguinte dá exatamente 12, e é isso que a fronteira da
    tabela de severidade testa. Pode ser zero ou negativo quando a evidência
    não é posterior ao material — quem decide o que fazer é `comparar`.
    """
    return (publicado_em.year - ano) * 12 + (publicado_em.month - MES_CORTE_MATERIAL)


@dataclass(frozen=True)
class RegraSeveridade:
    """Limiares da tabela de severidade, versionados em `Settings`.

    Mudar um número aqui é mudança de produto, não de implementação — por
    isso a regra é um objeto explícito e testável, não constantes soltas.
    """

    gap_alta: int = 24
    gap_media: int = 12
    gap_minimo_sem_pc: int = 12
    gap_media_sem_pc: int = 36

    @classmethod
    def de_settings(cls, settings: Settings | None = None) -> RegraSeveridade:
        s = settings or get_settings()
        return cls(
            gap_alta=s.gap_meses_alta,
            gap_media=s.gap_meses_media,
            gap_minimo_sem_pc=s.gap_meses_minimo_sem_pc,
            gap_media_sem_pc=s.gap_meses_media_sem_pc,
        )

    def classificar(self, gap: int, practice_changing: bool) -> Severidade | None:
        """Tabela da seção 6. `None` é sem achado, não erro.

        Todas as fronteiras são fechadas à esquerda (`>=`): gap de exatamente
        12 ou 24 meses sobe de faixa.
        """
        if practice_changing:
            if gap >= self.gap_alta:
                return Severidade.ALTA
            if gap >= self.gap_media:
                return Severidade.MEDIA
            return Severidade.BAIXA
        if gap >= self.gap_media_sem_pc:
            return Severidade.MEDIA
        if gap >= self.gap_minimo_sem_pc:
            return Severidade.BAIXA
        return None


@dataclass(frozen=True)
class Comparacao:
    """Resultado da comparação de um tema. `severidade is None` é sem achado."""

    ano_material: int
    publicado_em: date
    gap_meses: int
    practice_changing: bool
    severidade: Severidade | None

    @property
    def defasado(self) -> bool:
        return self.severidade is not None


def comparar(
    ano: int,
    publicado_em: date,
    practice_changing: bool,
    regra: RegraSeveridade | None = None,
) -> Comparacao:
    """Compara a referência do material com a evidência vigente de um tema.

    Evidência não posterior a 31/12 do ano do material é sem achado, mesmo
    que seja practice-changing: o material já pode estar apoiado nela.
    """
    regra = regra or RegraSeveridade.de_settings()
    gap = gap_meses(ano, publicado_em)
    severidade = (
        regra.classificar(gap, practice_changing)
        if evidencia_posterior(ano, publicado_em)
        else None
    )
    return Comparacao(
        ano_material=ano,
        publicado_em=publicado_em,
        gap_meses=gap,
        practice_changing=practice_changing,
        severidade=severidade,
    )

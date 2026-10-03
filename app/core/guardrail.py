"""As quatro barreiras de guardrail (seção 6 do PRD, ADR-6).

Cada barreira tem um ponto fixo no fluxo e um motivo próprio:

1. `barreira_escopo` — **antes** de recuperar. Objeto inelegível não gasta
   busca: `objeto_invalido`, `material_sem_referencia`, `fora_de_escopo`.
2. `barreira_proveniencia` — depois de recuperar, por tema:
   `evidencia_insuficiente`, `fonte_nao_validada`.
3. `barreira_validacao` — antes de devolver. Descarta defasagem por
   defasagem e registra em log o que caiu e por quê. Roda sempre, qualquer
   que seja o modo de síntese: é a proteção contra regressão quando a
   justificativa vem de um LLM.
4. `barreira_alertas` — não bloqueia; anexa avisos à resposta.

`consolidar_status` aplica a tabela de agregação da seção 6, incluindo a
invariante 4 da seção 5.5: se todas as defasagens forem descartadas pela
barreira 3, o status é `abstido` com `alerta_descartado`, nunca `sem_achado`.

Nada aqui chama o retriever. A ordem (barreira 1 → busca → barreira 2) é
responsabilidade de quem orquestra (`core/servico.py`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from app.config import Settings, get_settings
from app.core.detector import evidencia_posterior
from app.core.retriever import Candidato
from app.core.texto import normalizar
from app.models import (
    Defasagem,
    MotivoAbstencao,
    ObjetoAprendizagem,
    StatusAnalise,
)

logger = logging.getLogger(__name__)

# [0] é sempre a referência do material; [1..] são as evidências citadas.
MARCADOR_MATERIAL = 0
_MARCADOR = re.compile(r"\[(\d+)\]")


# --------------------------------------------------------------------------
# Barreira 1 — padrões de fora de escopo
# --------------------------------------------------------------------------
#
# Aplicados sobre o texto normalizado (sem acento, minúsculo, sem pontuação).
# São deliberadamente estreitos: material didático fala de dose, prescrição e
# paciente o tempo todo. O que está fora de escopo é o pedido individualizado,
# não o assunto — abster de uma aula legítima também é falso alarme.

_TERMO_DOSE = re.compile(r"\b(dose|doses|posologia|prescrever|prescrevo|prescricao)\b")
_INDIVIDUALIZACAO = re.compile(
    r"\b(meu|minha|meus|minhas|este|esta|deste|desta|desse|dessa) pacientes?\b"
    r"|\bpacientes? de \d+ ?(kg|quilos?)\b"
    r"|\b(posologia|dose) exata\b"
    r"|\b(devo|posso) prescrever\b"
)

_DOCUMENTO_MEDICO = re.compile(
    r"\b(emita|emite|gere|redija|escreva|elabore|faca|preencha|assine)\b"
    r"(?: \w+){0,3} "
    r"(atestado|receita|receituario|laudo|declaracao medica|relatorio medico)\b"
    r"|\bpreciso de (um|uma) (atestado|receita|laudo)\b"
)

_IDENTIFICACAO_NORMALIZADA = re.compile(
    r"\b\d{3} \d{3} \d{3} \d{2}\b"  # CPF depois da normalização
    r"|\bcpf \d"
    r"|\bprontuario (n |no |numero )?\d+"
    r"|\bmatricula (n |no |numero )?\d+"
    r"|\bleito \d+"
)
# Nome próprio depois de "paciente"/"aluno" só aparece no texto original,
# porque a normalização apaga a caixa.
_IDENTIFICACAO_NOME = re.compile(
    r"\b(?:[Pp]aciente|[Aa]lun[oa]|[Ee]studante|[Ss]ra?\.?)\s+"
    r"[A-ZÀ-Ý][a-zà-ÿ]+\s+[A-ZÀ-Ý][a-zà-ÿ]+"
)


def _motivo_fora_de_escopo(texto: str) -> str | None:
    """Descrição do que tornou o texto fora de escopo, ou `None`."""
    norm = normalizar(texto)
    if _TERMO_DOSE.search(norm) and _INDIVIDUALIZACAO.search(norm):
        return "pede dose ou posologia individualizada"
    if _DOCUMENTO_MEDICO.search(norm):
        return "pede emissão de documento médico"
    if _IDENTIFICACAO_NORMALIZADA.search(norm) or _IDENTIFICACAO_NOME.search(texto):
        return "menciona paciente ou aluno identificado"
    return None


# --------------------------------------------------------------------------
# Resultados
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Elegibilidade:
    """Saída da barreira 1. `motivo is None` libera a recuperação."""

    motivo: MotivoAbstencao | None
    detalhe: str = ""
    ano_material: int | None = None

    @property
    def elegivel(self) -> bool:
        return self.motivo is None


@dataclass(frozen=True)
class Proveniencia:
    """Saída da barreira 2 para um tema.

    `confianca` é o maior score recuperado, mesmo quando a barreira abstém:
    é o que a resposta e a auditoria reportam.
    """

    tema: str
    candidato: Candidato | None
    motivo: MotivoAbstencao | None
    confianca: float = 0.0

    @property
    def aprovado(self) -> bool:
        return self.motivo is None


@dataclass(frozen=True)
class Descarte:
    """Uma defasagem que a barreira 3 recusou, com o motivo legível."""

    tema: str
    motivo: str
    doc_id: str | None = None


@dataclass(frozen=True)
class Validacao:
    """Saída da barreira 3."""

    validas: list[Defasagem] = field(default_factory=list)
    descartes: list[Descarte] = field(default_factory=list)

    @property
    def todas_descartadas(self) -> bool:
        return bool(self.descartes) and not self.validas


# --------------------------------------------------------------------------
# Guardrail
# --------------------------------------------------------------------------


class Guardrail:
    """As quatro barreiras, parametrizadas por `Settings`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # --- Barreira 1 ------------------------------------------------------

    def barreira_escopo(self, objeto: ObjetoAprendizagem) -> Elegibilidade:
        """Escopo e elegibilidade. Roda antes de qualquer recuperação.

        A ordem segue a tabela da seção 6: sem conteúdo não há o que
        inspecionar; sem referência datada não há com o que comparar; e só
        então o texto é inspecionado em busca de pedido fora de escopo.
        """
        if not objeto.titulo.strip() or not any(t.texto.strip() for t in objeto.trechos):
            return self._abster_escopo(
                objeto, MotivoAbstencao.OBJETO_INVALIDO, "objeto sem título ou sem trechos"
            )

        ano = objeto.ano_referencia
        if ano is None:
            return self._abster_escopo(
                objeto,
                MotivoAbstencao.MATERIAL_SEM_REFERENCIA,
                "nenhuma referência com ano",
            )

        fora = _motivo_fora_de_escopo(objeto.texto_completo)
        if fora is not None:
            return self._abster_escopo(objeto, MotivoAbstencao.FORA_DE_ESCOPO, fora)

        return Elegibilidade(motivo=None, ano_material=ano)

    @staticmethod
    def _abster_escopo(
        objeto: ObjetoAprendizagem, motivo: MotivoAbstencao, detalhe: str
    ) -> Elegibilidade:
        logger.info(
            "Barreira 1: objeto %s abstido (%s): %s", objeto.objeto_id, motivo.value, detalhe
        )
        return Elegibilidade(motivo=motivo, detalhe=detalhe)

    # --- Barreira 2 ------------------------------------------------------

    def barreira_proveniencia(
        self, tema: str, candidatos: Sequence[Candidato]
    ) -> Proveniencia:
        """Confiança e proveniência de um tema, sobre os candidatos já recuperados.

        Escolhe o melhor candidato acima do limiar e, com
        `EXIGIR_FONTE_OFICIAL=true`, de fonte validada. Um candidato de
        literatura ou fonte não validada com score maior não "puxa" a
        escolha: só perde a vez para o primeiro validado acima do limiar.
        """
        limiar = self.settings.limiar_confianca
        confianca = max((c.score for c in candidatos), default=0.0)

        acima = [c for c in candidatos if c.score >= limiar]
        if not acima:
            return Proveniencia(
                tema, None, MotivoAbstencao.EVIDENCIA_INSUFICIENTE, confianca
            )

        if self.settings.exigir_fonte_oficial:
            acima = [c for c in acima if c.evidencia.fonte_tipo.validada]
            if not acima:
                return Proveniencia(
                    tema, None, MotivoAbstencao.FONTE_NAO_VALIDADA, confianca
                )

        # Mesma ordem do retriever: score, depois doc_id/trecho_id no empate.
        melhor = min(
            acima, key=lambda c: (-c.score, c.evidencia.doc_id, c.trecho.trecho_id)
        )
        return Proveniencia(tema, melhor, None, confianca)

    # --- Barreira 3 ------------------------------------------------------

    def barreira_validacao(
        self,
        defasagens: Sequence[Defasagem],
        ano_material: int,
        objeto_id: str = "",
    ) -> Validacao:
        """Valida cada defasagem individualmente, independente do modo de síntese.

        Uma defasagem cai se: não tem evidência; a justificativa não cita a
        própria evidência; a justificativa usa marcador que não seja `[0]` ou
        o da própria evidência; o marcador colide com o de outra evidência na
        mesma resposta; ou a evidência não é posterior à referência do
        material. Cada descarte vai para o log com o motivo.
        """
        validas: list[Defasagem] = []
        descartes: list[Descarte] = []
        marcadores: dict[int, str] = {}  # marcador → doc_id já aceito

        for defasagem in defasagens:
            motivo = self._motivo_descarte(defasagem, ano_material, marcadores)
            evidencia = getattr(defasagem, "evidencia", None)
            doc_id = evidencia.doc_id if evidencia is not None else None
            if motivo is None:
                validas.append(defasagem)
                marcadores[evidencia.marcador] = evidencia.doc_id
                continue
            descartes.append(Descarte(tema=defasagem.tema, motivo=motivo, doc_id=doc_id))
            logger.warning(
                "Barreira 3: defasagem descartada objeto=%s tema=%s doc_id=%s motivo=%s",
                objeto_id,
                defasagem.tema,
                doc_id,
                motivo,
            )

        return Validacao(validas=validas, descartes=descartes)

    @staticmethod
    def _motivo_descarte(
        defasagem: Defasagem, ano_material: int, marcadores: dict[int, str]
    ) -> str | None:
        # Defasagem chega validada pelo pydantic no caminho extrativo, mas um
        # gerador LLM pode montar o objeto sem validação (`model_construct`):
        # a barreira não confia na forma.
        evidencia = getattr(defasagem, "evidencia", None)
        if evidencia is None:
            return "defasagem sem evidência"

        proprio = evidencia.marcador
        if proprio is None or proprio <= MARCADOR_MATERIAL:
            return f"evidência com marcador inválido [{proprio}]"

        usados = {int(m) for m in _MARCADOR.findall(defasagem.justificativa or "")}
        if not usados:
            return "justificativa sem marcador"
        estranhos = usados - {MARCADOR_MATERIAL, proprio}
        if estranhos:
            lista = ", ".join(f"[{m}]" for m in sorted(estranhos))
            return f"marcador sem fonte nesta defasagem: {lista}"
        if proprio not in usados:
            # Citar só [0] é citar o próprio material: não sustenta alerta.
            return f"justificativa não cita a própria evidência [{proprio}]"

        outro = marcadores.get(proprio)
        if outro is not None and outro != evidencia.doc_id:
            return f"marcador [{proprio}] já atribuído a {outro}"

        if not evidencia_posterior(ano_material, evidencia.publicado_em):
            return (
                f"evidência de {evidencia.publicado_em.isoformat()} não é posterior "
                f"à referência do material ({ano_material})"
            )
        return None

    # --- Barreira 4 ------------------------------------------------------

    def barreira_alertas(
        self,
        objeto: ObjetoAprendizagem,
        defasagens: Sequence[Defasagem],
        confianca: float,
        hoje: date | None = None,
    ) -> list[str]:
        """Avisos que acompanham a resposta. Nunca mudam o status."""
        alertas: list[str] = []

        if any(d.evidencia.exemplo_ilustrativo for d in defasagens):
            alertas.append(
                "Base de demonstração: a evidência citada é sintética e ilustrativa, "
                "não protocolo vigente."
            )

        limiar = self.settings.limiar_confianca
        if limiar <= confianca < self.settings.limiar_alerta_confianca_limite:
            alertas.append(
                f"Confiança no limiar ({confianca:.4f}): confira a evidência antes de agir."
            )

        if objeto.atualizado_em is not None:
            dias = ((hoje or date.today()) - objeto.atualizado_em).days
            if dias > self.settings.alerta_revisao_objeto_dias:
                alertas.append(
                    f"Revisão geral pendente: objeto sem atualização desde "
                    f"{objeto.atualizado_em.isoformat()}."
                )

        return alertas


# --------------------------------------------------------------------------
# Agregação (tabela da seção 6)
# --------------------------------------------------------------------------


def consolidar_status(
    proveniencias: Sequence[Proveniencia],
    validacao: Validacao,
) -> tuple[StatusAnalise, MotivoAbstencao | None]:
    """Status do objeto a partir das barreiras 2 e 3.

    | Situação                                         | status              |
    | ------------------------------------------------ | ------------------- |
    | ao menos uma defasagem válida                    | defasagem_detectada |
    | houve defasagens, todas descartadas (barreira 3) | abstido (descarte)  |
    | nenhum tema passou pela barreira 2               | abstido (1º motivo) |
    | temas passaram, nenhum gerou defasagem           | sem_achado          |

    A segunda linha vem antes da terceira e da quarta: descartar tudo e
    responder `sem_achado` esconderia uma regressão no gerador de
    justificativa (invariante 4). O motivo é `alerta_descartado`, e não um
    dos motivos sobre o material: havia base, o serviço é que falhou.
    """
    if validacao.validas:
        return StatusAnalise.DEFASAGEM_DETECTADA, None
    if validacao.todas_descartadas:
        return StatusAnalise.ABSTIDO, MotivoAbstencao.ALERTA_DESCARTADO
    if not any(p.aprovado for p in proveniencias):
        motivo = next(
            (p.motivo for p in proveniencias if p.motivo is not None),
            MotivoAbstencao.EVIDENCIA_INSUFICIENTE,  # objeto sem temas
        )
        return StatusAnalise.ABSTIDO, motivo
    return StatusAnalise.SEM_ACHADO, None


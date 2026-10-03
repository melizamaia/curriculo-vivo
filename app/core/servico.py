"""Caso de uso: analisar um objeto de aprendizagem e varrer o catálogo.

A ordem do fluxo da seção 4 é garantida aqui, e só aqui:

    barreira 1 → (só se elegível) busca por tema → barreira 2 → comparação
    → justificativa → barreira 3 → agregação → barreira 4

Objeto inelegível não chega ao retriever: a busca é o passo caro e o
resultado dela não teria uso.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date

from app.config import Settings, get_settings
from app.core.detector import RegraSeveridade, comparar
from app.core.guardrail import Guardrail, Proveniencia, consolidar_status
from app.core.justificativa import (
    MODO_ABSTRATIVA,
    MODO_EXTRATIVA,
    ContextoJustificativa,
    GeradorJustificativa,
    criar_gerador,
)
from app.core.retriever import Candidato, Retriever
from app.models import (
    ORDEM_SEVERIDADE,
    AnaliseResponse,
    Defasagem,
    EvidenciaCitada,
    MotivoAbstencao,
    ObjetoAprendizagem,
    RadarResponse,
    Severidade,
    StatusAnalise,
)

logger = logging.getLogger(__name__)


class ServicoAnalise:
    """Orquestra retriever, guardrail, detector e gerador de justificativa."""

    def __init__(
        self,
        retriever: Retriever,
        settings: Settings | None = None,
        guardrail: Guardrail | None = None,
        gerador: GeradorJustificativa | None = None,
        regra: RegraSeveridade | None = None,
        hoje: Callable[[], date] = date.today,
    ) -> None:
        self.retriever = retriever
        self.settings = settings or get_settings()
        self.guardrail = guardrail or Guardrail(self.settings)
        self.gerador = gerador or criar_gerador(self.settings)
        self.regra = regra or RegraSeveridade.de_settings(self.settings)
        self._hoje = hoje

    # --- análise de um objeto -------------------------------------------

    def analisar(self, objeto: ObjetoAprendizagem) -> AnaliseResponse:
        inicio = time.perf_counter()

        elegibilidade = self.guardrail.barreira_escopo(objeto)
        if not elegibilidade.elegivel:
            return self._resposta(
                objeto,
                inicio,
                status=StatusAnalise.ABSTIDO,
                motivo=elegibilidade.motivo,
                modo=MODO_EXTRATIVA,  # nada foi sintetizado
            )

        ano = elegibilidade.ano_material
        assert ano is not None  # garantido pela barreira 1

        proveniencias: list[Proveniencia] = []
        candidatas: list[Defasagem] = []
        marcadores: dict[str, int] = {}  # doc_id → marcador estável
        modos: set[str] = set()

        for tema in objeto.temas:
            candidatos = self.retriever.buscar(
                objeto.texto_completo, tema=tema, top_k=self.settings.top_k
            )
            prov = self.guardrail.barreira_proveniencia(tema, candidatos)
            proveniencias.append(prov)
            if not prov.aprovado:
                continue

            escolhido = prov.candidato
            assert escolhido is not None
            comp = comparar(
                ano,
                escolhido.evidencia.publicado_em,
                escolhido.evidencia.practice_changing,
                self.regra,
            )
            if not comp.defasado:
                continue

            doc_id = escolhido.evidencia.doc_id
            marcador = marcadores.setdefault(doc_id, len(marcadores) + 1)
            evidencia = _citar(escolhido, marcador)
            sintese = self.gerador.gerar(ContextoJustificativa(tema, comp, evidencia))
            modos.add(sintese.modo)
            candidatas.append(
                Defasagem(
                    tema=tema,
                    severidade=comp.severidade,
                    gap_meses=comp.gap_meses,
                    practice_changing=comp.practice_changing,
                    justificativa=sintese.texto,
                    evidencia=evidencia,
                )
            )

        validacao = self.guardrail.barreira_validacao(
            candidatas, ano, objeto_id=objeto.objeto_id
        )
        status, motivo = consolidar_status(proveniencias, validacao)
        confianca = max((p.confianca for p in proveniencias), default=0.0)

        return self._resposta(
            objeto,
            inicio,
            status=status,
            motivo=motivo,
            defasagens=validacao.validas,
            confianca=confianca,
            modo=MODO_ABSTRATIVA if MODO_ABSTRATIVA in modos else MODO_EXTRATIVA,
        )

    def _resposta(
        self,
        objeto: ObjetoAprendizagem,
        inicio: float,
        *,
        status: StatusAnalise,
        motivo: MotivoAbstencao | None,
        modo: str,
        defasagens: list[Defasagem] | None = None,
        confianca: float = 0.0,
    ) -> AnaliseResponse:
        defasagens = defasagens or []
        alertas = self.guardrail.barreira_alertas(
            objeto, defasagens, confianca, hoje=self._hoje()
        )
        severidade_maxima = max(
            (d.severidade for d in defasagens),
            key=ORDEM_SEVERIDADE.__getitem__,
            default=None,
        )
        return AnaliseResponse(
            status=status,
            objeto_id=objeto.objeto_id,
            titulo=objeto.titulo,
            curso=objeto.curso,
            disciplina=objeto.disciplina,
            ano_referencia_material=objeto.ano_referencia,
            severidade_maxima=severidade_maxima,
            defasagens=defasagens,
            confianca=confianca,
            motivo_abstencao=motivo,
            alertas=alertas,
            modo_sintese=modo,
            latencia_ms=round((time.perf_counter() - inicio) * 1000, 2),
            aviso=self.settings.aviso_padrao,
        )

    # --- radar -----------------------------------------------------------

    def radar(
        self,
        objetos: Iterable[ObjetoAprendizagem],
        curso: str | None = None,
        disciplina: str | None = None,
        severidade: Severidade | None = None,
        limite: int | None = None,
        registrar: Callable[[ObjetoAprendizagem, AnaliseResponse], None] | None = None,
    ) -> RadarResponse:
        """Varre o catálogo: a fila do coordenador, mais grave primeiro.

        Os filtros de curso e disciplina recortam o catálogo antes da
        análise; o de severidade recorta o resultado. Contagens refletem o
        recorte inteiro; `limite` corta só a lista de itens.

        `registrar` recebe toda análise feita, antes dos recortes de
        severidade e limite: o que foi analisado é auditado, apareça ou não
        na fila devolvida.
        """
        selecionados = [
            o
            for o in objetos
            if (curso is None or o.curso == curso)
            and (disciplina is None or o.disciplina == disciplina)
        ]
        itens = [self.analisar(o) for o in selecionados]
        if registrar is not None:
            for objeto, item in zip(selecionados, itens):
                registrar(objeto, item)
        if severidade is not None:
            itens = [i for i in itens if i.severidade_maxima is severidade]

        itens.sort(key=_ordem_radar)
        com_defasagem = [i for i in itens if i.status is StatusAnalise.DEFASAGEM_DETECTADA]

        return RadarResponse(
            versao_indice=self.retriever.versao_indice,
            total_objetos=len(itens),
            objetos_com_defasagem=len(com_defasagem),
            por_severidade=dict(Counter(i.severidade_maxima.value for i in com_defasagem)),
            abstencoes=dict(
                Counter(i.motivo_abstencao.value for i in itens if i.motivo_abstencao)
            ),
            por_curso=dict(Counter(i.curso or "sem_curso" for i in com_defasagem)),
            por_disciplina=dict(
                Counter(i.disciplina or "sem_disciplina" for i in com_defasagem)
            ),
            itens=itens if limite is None else itens[:limite],
        )


def _citar(candidato: Candidato, marcador: int) -> EvidenciaCitada:
    ev = candidato.evidencia
    return EvidenciaCitada(
        marcador=marcador,
        doc_id=ev.doc_id,
        trecho_id=candidato.trecho.trecho_id,
        titulo=ev.titulo,
        fonte=ev.fonte,
        fonte_tipo=ev.fonte_tipo,
        url=ev.url,
        publicado_em=ev.publicado_em,
        nivel_evidencia=ev.nivel_evidencia,
        trecho=candidato.trecho.texto,
        score=candidato.score,
        exemplo_ilustrativo=ev.exemplo_ilustrativo,
    )


def _ordem_radar(item: AnaliseResponse) -> tuple:
    # Severidade desc, depois o maior gap desc, depois objeto_id para
    # estabilidade. Sem achado e abstenções vão para o fim.
    peso = ORDEM_SEVERIDADE.get(item.severidade_maxima, 0)
    gap = max((d.gap_meses for d in item.defasagens), default=0)
    return (-peso, -gap, item.objeto_id)

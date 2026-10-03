"""Recuperação de evidência vigente: TF-IDF esparso + cosseno (ADR-1).

Determinístico, offline e sem custo por análise. A interface pública
(`buscar`, `upsert`, `versao_indice`) isola a troca futura por embeddings.

O índice é imutável depois de construído: `upsert` monta um novo estado e
troca a referência de uma vez, então uma busca concorrente nunca vê índice
pela metade.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from app.core.texto import normalizar_tema, termos
from app.models import Evidencia, Trecho

logger = logging.getLogger(__name__)

VERSAO_INDICE_VAZIO = "vazio"


@dataclass(frozen=True)
class Candidato:
    """Melhor trecho de uma evidência para a consulta, com o score que o elegeu."""

    evidencia: Evidencia
    trecho: Trecho
    score: float


@dataclass(frozen=True)
class _EstadoIndice:
    evidencias: dict[str, Evidencia]
    # Uma linha por trecho indexado: (doc_id, trecho).
    linhas: tuple[tuple[str, Trecho], ...]
    vetorizador: TfidfVectorizer | None
    matriz: object | None  # scipy.sparse.csr_matrix, linhas L2-normalizadas
    versao: str


def calcular_versao_indice(evidencias: list[Evidencia]) -> str:
    """Hash do conteúdo indexado, independente da ordem de ingestão.

    É o que prova, meses depois, contra qual base um alerta foi emitido.
    """
    if not evidencias:
        return VERSAO_INDICE_VAZIO
    canonico = [
        e.model_dump(mode="json") for e in sorted(evidencias, key=lambda e: e.doc_id)
    ]
    bruto = json.dumps(canonico, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:12]


def _texto_indexavel(evidencia: Evidencia, trecho: Trecho) -> str:
    # O título entra em todo trecho: dá contexto a trechos curtos sem
    # deixar que o título sozinho decida qual trecho sustenta o alerta.
    return f"{evidencia.titulo} {trecho.texto}"


def _construir(evidencias: dict[str, Evidencia]) -> _EstadoIndice:
    ordenadas = [evidencias[k] for k in sorted(evidencias)]
    linhas = tuple((e.doc_id, t) for e in ordenadas for t in e.trechos)
    versao = calcular_versao_indice(ordenadas)

    if not linhas:
        return _EstadoIndice(evidencias, linhas, None, None, versao)

    vetorizador = TfidfVectorizer(
        analyzer=termos,
        sublinear_tf=True,
        norm="l2",
    )
    matriz = vetorizador.fit_transform(
        [_texto_indexavel(evidencias[d], t) for d, t in linhas]
    )
    return _EstadoIndice(evidencias, linhas, vetorizador, matriz, versao)


class Retriever:
    """Índice de evidências em memória, por pod, reconstruído na ingestão."""

    def __init__(self, evidencias: list[Evidencia] | None = None) -> None:
        self._lock = threading.Lock()
        self._estado = _construir({e.doc_id: e for e in evidencias or []})

    # --- carga -----------------------------------------------------------

    @classmethod
    def carregar(cls, caminho: Path) -> Retriever:
        """Carrega a base curada. Arquivo ausente ou inválido → índice vazio.

        Índice vazio não derruba o serviço: ele só sabe se abster, e o
        `/health/ready` reporta `degraded`.
        """
        try:
            bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
            itens = bruto["evidencias"] if isinstance(bruto, dict) else bruto
            evidencias = [Evidencia.model_validate(i) for i in itens]
        except Exception as exc:
            logger.warning(
                "Falha ao carregar evidências de %s (%s); índice vazio", caminho, exc
            )
            return cls()
        retriever = cls(evidencias)
        logger.info(
            "Índice carregado: %d evidências, %d trechos, versao_indice=%s",
            retriever.total_evidencias,
            retriever.total_trechos,
            retriever.versao_indice,
        )
        return retriever

    # --- leitura ---------------------------------------------------------

    @property
    def versao_indice(self) -> str:
        return self._estado.versao

    @property
    def total_evidencias(self) -> int:
        return len(self._estado.evidencias)

    @property
    def total_trechos(self) -> int:
        return len(self._estado.linhas)

    @property
    def vazio(self) -> bool:
        return not self._estado.linhas

    def evidencias(self) -> list[Evidencia]:
        estado = self._estado
        return [estado.evidencias[k] for k in sorted(estado.evidencias)]

    def obter(self, doc_id: str) -> Evidencia | None:
        return self._estado.evidencias.get(doc_id)

    def buscar(
        self,
        consulta: str,
        tema: str | None = None,
        top_k: int = 3,
    ) -> list[Candidato]:
        """Top-k evidências para a consulta, uma por documento, score > 0.

        Com `tema`, só concorrem evidências daquele tema: é vocabulário
        controlado, e evita casar uma aula de asma com uma diretriz de sepse
        porque ambas mencionam "oximetria". Cada evidência é representada pelo
        seu melhor trecho. Empates são resolvidos por `doc_id`/`trecho_id`
        para que a mesma consulta devolva sempre a mesma ordem.
        """
        estado = self._estado  # snapshot: upsert concorrente não interfere
        if estado.vetorizador is None or top_k <= 0:
            return []

        tema_alvo = normalizar_tema(tema) if tema else None
        elegiveis = [
            i
            for i, (doc_id, _) in enumerate(estado.linhas)
            if tema_alvo is None
            or tema_alvo in {normalizar_tema(t) for t in estado.evidencias[doc_id].temas}
        ]
        if not elegiveis:
            return []

        vetor = estado.vetorizador.transform([consulta])
        # Linhas e consulta já são L2-normalizadas: o produto escalar é o cosseno.
        scores = np.asarray((estado.matriz[elegiveis] @ vetor.T).todense()).ravel()

        melhor_por_doc: dict[str, Candidato] = {}
        for idx, score in zip(elegiveis, scores):
            doc_id, trecho = estado.linhas[idx]
            score = round(float(score), 4)
            if score <= 0.0:
                continue  # nenhum termo em comum não é candidato
            atual = melhor_por_doc.get(doc_id)
            if atual is None or score > atual.score:
                melhor_por_doc[doc_id] = Candidato(
                    estado.evidencias[doc_id], trecho, score
                )

        ordenados = sorted(
            melhor_por_doc.values(),
            key=lambda c: (-c.score, c.evidencia.doc_id, c.trecho.trecho_id),
        )
        return ordenados[:top_k]

    # --- escrita ---------------------------------------------------------

    def upsert(self, evidencia: Evidencia) -> str:
        """Insere ou substitui por `doc_id` e reindexa. Devolve a nova versão.

        Reindexar tudo é O(base) — aceitável no MVP (dezenas de documentos)
        e mantém o IDF coerente. Idempotente: reenviar o mesmo documento não
        muda `versao_indice`.
        """
        with self._lock:
            evidencias = dict(self._estado.evidencias)
            evidencias[evidencia.doc_id] = evidencia
            self._estado = _construir(evidencias)
            return self._estado.versao

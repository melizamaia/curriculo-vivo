"""`/v1/objetos` e `/v1/evidencias`: leitura e ingestão síncrona."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencias import get_catalogo, get_retriever
from app.core.retriever import Retriever
from app.models import EventoEvidenciaIndexada, Evidencia, ObjetoAprendizagem
from app.repositories.catalogo import RepositorioCatalogo

router = APIRouter(prefix="/v1", tags=["catálogo"])


@router.get("/objetos", response_model=list[ObjetoAprendizagem])
async def listar_objetos(
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
    curso: str | None = None,
    disciplina: str | None = None,
) -> list[ObjetoAprendizagem]:
    return catalogo.listar(curso=curso, disciplina=disciplina)


@router.post(
    "/objetos",
    response_model=ObjetoAprendizagem,
    status_code=status.HTTP_201_CREATED,
)
async def ingerir_objeto(
    objeto: ObjetoAprendizagem,
    response: Response,
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
) -> ObjetoAprendizagem:
    """Insere ou substitui por `objeto_id` (201 se novo, 200 se substituiu)."""
    if not catalogo.upsert(objeto):
        response.status_code = status.HTTP_200_OK
    return objeto


@router.get("/evidencias", response_model=list[Evidencia])
async def listar_evidencias(
    retriever: Annotated[Retriever, Depends(get_retriever)],
) -> list[Evidencia]:
    return retriever.evidencias()


@router.post(
    "/evidencias",
    response_model=EventoEvidenciaIndexada,
    status_code=status.HTTP_201_CREATED,
)
async def ingerir_evidencia(
    evidencia: Evidencia,
    retriever: Annotated[Retriever, Depends(get_retriever)],
) -> EventoEvidenciaIndexada:
    """Equivale a consumir `evidencia.nova`: reindexa e devolve o payload de
    `evidencia.indexada`. Idempotente: o mesmo documento não muda a versão."""
    versao = retriever.upsert(evidencia)
    return EventoEvidenciaIndexada(
        doc_id=evidencia.doc_id,
        versao_indice=versao,
        practice_changing=evidencia.practice_changing,
        trechos_indexados=len(evidencia.trechos),
    )

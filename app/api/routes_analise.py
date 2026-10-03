"""`POST /v1/analises` e `GET /v1/defasagens` (o radar)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.api.dependencias import get_auditoria, get_catalogo, get_servico
from app.core.audit import montar_registro
from app.core.servico import ServicoAnalise
from app.models import AnaliseRequest, AnaliseResponse, RadarResponse, Severidade
from app.repositories.auditoria import RepositorioAuditoria
from app.repositories.catalogo import RepositorioCatalogo

router = APIRouter(prefix="/v1", tags=["análise"])


@router.post("/analises", response_model=AnaliseResponse)
async def analisar(
    pedido: AnaliseRequest,
    servico: Annotated[ServicoAnalise, Depends(get_servico)],
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
    auditoria: Annotated[RepositorioAuditoria, Depends(get_auditoria)],
) -> AnaliseResponse:
    """Analisa um objeto do catálogo (`objeto_id`) ou um payload completo (`objeto`).

    Com os dois, vale o payload. Toda análise gera registro de auditoria com
    o objeto apenas como hash.
    """
    objeto = pedido.objeto
    if objeto is None:
        objeto = catalogo.obter(pedido.objeto_id or "")
        if objeto is None:
            raise HTTPException(
                status_code=404,
                detail=f"objeto_id '{pedido.objeto_id}' não está no catálogo",
            )

    # A análise é CPU (TF-IDF): fora do event loop para não travar o resto.
    resposta = await run_in_threadpool(servico.analisar, objeto)
    await auditoria.gravar(
        montar_registro(resposta, objeto, servico.retriever.versao_indice)
    )
    return resposta


@router.get("/defasagens", response_model=RadarResponse)
async def radar(
    servico: Annotated[ServicoAnalise, Depends(get_servico)],
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
    curso: str | None = None,
    disciplina: str | None = None,
    severidade: Severidade | None = None,
    limite: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> RadarResponse:
    """Varre o catálogo e devolve a fila do coordenador, mais grave primeiro.

    O radar é varredura, não análise individual: não gera um registro de
    auditoria por objeto. A resposta carrega `versao_indice`, que basta para
    reconstruí-la.
    """
    return await run_in_threadpool(
        servico.radar,
        catalogo.listar(),
        curso=curso,
        disciplina=disciplina,
        severidade=severidade,
        limite=limite,
    )

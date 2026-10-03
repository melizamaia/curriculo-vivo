"""Operação: health, readiness, métricas, auditoria e painel."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from app.api.dependencias import (
    get_auditoria,
    get_catalogo,
    get_retriever,
    get_settings_app,
)
from app.config import RAIZ_PROJETO, Settings
from app.core.audit import percentil
from app.core.retriever import Retriever
from app.models import (
    HealthResponse,
    MetricasResponse,
    OrigemAnalise,
    RegistroAuditoria,
    StatusAnalise,
)
from app.repositories.auditoria import SO_ANALISES, RepositorioAuditoria
from app.repositories.catalogo import RepositorioCatalogo

router = APIRouter(tags=["operação"])

CAMINHO_PAINEL = RAIZ_PROJETO / "dashboard" / "index.html"


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings_app)],
) -> HealthResponse:
    """Liveness: o processo responde."""
    return HealthResponse(status="ok", versao=settings.app_versao)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Índice de evidência vazio"}},
)
async def ready(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings_app)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
    auditoria: Annotated[RepositorioAuditoria, Depends(get_auditoria)],
) -> HealthResponse:
    """Readiness. Sem evidência indexada o serviço só sabe se abster: responde
    `degraded` com 503 para o Kubernetes tirar o pod do balanceamento.

    Auditoria em memória não tira o pod do ar (ADR-8): aparece em `detalhes`.
    """
    degradado = retriever.vazio
    if degradado:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="degraded" if degradado else "ready",
        versao=settings.app_versao,
        detalhes={
            "indice": "vazio" if degradado else "carregado",
            "evidencias_indexadas": retriever.total_evidencias,
            "trechos_indexados": retriever.total_trechos,
            "versao_indice": retriever.versao_indice,
            "objetos_catalogados": catalogo.total,
            "auditoria": auditoria.backend,
            "modo_sintese": settings.modo_sintese,
        },
    )


@router.get("/v1/metricas", response_model=MetricasResponse)
async def metricas(
    settings: Annotated[Settings, Depends(get_settings_app)],
    retriever: Annotated[Retriever, Depends(get_retriever)],
    catalogo: Annotated[RepositorioCatalogo, Depends(get_catalogo)],
    auditoria: Annotated[RepositorioAuditoria, Depends(get_auditoria)],
    incluir_radar: bool = False,
) -> MetricasResponse:
    """Contagens desde o boot (ou da coleção); latências da janela recente.

    Por padrão só análises avulsas (`origem=analise`): é a latência que o
    docente sente. `incluir_radar=true` soma as análises das varreduras.
    """
    origens = set(OrigemAnalise) if incluir_radar else SO_ANALISES
    est = await auditoria.estatisticas(origens)
    abstidos = est.por_status.get(StatusAnalise.ABSTIDO.value, 0)
    latencias = est.latencias_ms
    return MetricasResponse(
        total_analises=est.total,
        por_status=est.por_status,
        taxa_abstencao=round(abstidos / est.total, 4) if est.total else 0.0,
        latencia_media_ms=round(sum(latencias) / len(latencias), 2) if latencias else 0.0,
        latencia_p95_ms=round(percentil(latencias, 95), 2),
        modo_sintese=settings.modo_sintese,
        versao_indice=retriever.versao_indice,
        evidencias_indexadas=retriever.total_evidencias,
        objetos_catalogados=catalogo.total,
    )


@router.get("/v1/auditoria", response_model=list[RegistroAuditoria])
async def trilha_auditoria(
    auditoria: Annotated[RepositorioAuditoria, Depends(get_auditoria)],
    limite: Annotated[int, Query(ge=1, le=1000)] = 50,
) -> list[RegistroAuditoria]:
    """Registros mais recentes primeiro. O material aparece só como hash."""
    return await auditoria.listar(limite)


@router.get("/painel", response_class=FileResponse)
async def painel() -> FileResponse:
    """Painel autocontido gerado pelo harness de avaliação."""
    if not CAMINHO_PAINEL.is_file():
        raise HTTPException(
            status_code=404,
            detail="Painel ainda não gerado: rode `python -m eval.run_eval`.",
        )
    return FileResponse(CAMINHO_PAINEL, media_type="text/html")

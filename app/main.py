"""FastAPI do Currículo Vivo.

O lifespan monta, nesta ordem, índice de evidência, catálogo, guardrail,
serviço e repositório de auditoria. Nada externo é obrigatório (O7): sem
Mongo a auditoria vai para a memória, sem chave a justificativa é extrativa,
e sem base de evidência o serviço sobe em `degraded` — o log diz em que modo.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import routes_analise, routes_catalogo, routes_ops
from app.config import Settings, get_settings
from app.core.guardrail import Guardrail
from app.core.retriever import Retriever
from app.core.servico import ServicoAnalise
from app.repositories.auditoria import criar_repositorio_auditoria
from app.repositories.catalogo import RepositorioCatalogo
from app.repositories.evidencias import criar_armazem_evidencias

logger = logging.getLogger("app")


def criar_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        retriever = Retriever.carregar(settings.caminho_evidencias)
        ingeridas = await _carregar_ingeridas(settings, retriever)
        catalogo = RepositorioCatalogo.carregar(settings.caminho_material)
        guardrail = Guardrail(settings)
        servico = ServicoAnalise(retriever, settings, guardrail=guardrail)
        auditoria = await criar_repositorio_auditoria(settings)

        app.state.settings = settings
        app.state.retriever = retriever
        app.state.catalogo = catalogo
        app.state.servico = servico
        app.state.auditoria = auditoria

        logger.info(
            "%s %s no ar: índice=%s (%d evidências, %d do worker), catálogo=%d "
            "objetos, auditoria=%s, síntese=%s, exigir_fonte_oficial=%s",
            settings.app_nome,
            settings.app_versao,
            retriever.versao_indice,
            retriever.total_evidencias,
            ingeridas,
            catalogo.total,
            auditoria.backend,
            settings.modo_sintese,
            settings.exigir_fonte_oficial,
        )
        if retriever.vazio:
            logger.warning("Índice de evidência vazio: o serviço só se abstém (degraded)")
        try:
            yield
        finally:
            await auditoria.fechar()

    app = FastAPI(
        title=settings.app_nome,
        version=settings.app_versao,
        description=(
            "Radar de defasagem curricular: cruza o material didático com a "
            "evidência vigente e aponta, com citação, o que envelheceu — ou se "
            "abstém. Corpus sintético e ilustrativo. " + settings.aviso_padrao
        ),
        lifespan=lifespan,
    )
    app.include_router(routes_analise.router)
    app.include_router(routes_catalogo.router)
    app.include_router(routes_ops.router)
    return app


async def _carregar_ingeridas(settings: Settings, retriever: Retriever) -> int:
    """Soma ao índice o que o worker já ingeriu por `evidencia.nova`.

    Sem isso a API e o worker divergiriam de `versao_indice`. Só no boot: a
    propagação ao vivo (consumir `evidencia.indexada`) é o próximo passo.
    """
    armazem = await criar_armazem_evidencias(settings)
    try:
        ingeridas = await armazem.listar()
    except Exception as exc:
        logger.warning("Evidências do worker não carregadas (%s); só a base curada", exc)
        return 0
    finally:
        await armazem.fechar()
    for evidencia in ingeridas:
        retriever.upsert(evidencia)
    return len(ingeridas)


def _configurar_log() -> None:
    # Sob uvicorn só os loggers dele têm handler; sem isso o log de modo
    # de operação (seção 9) não aparece.
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


_configurar_log()
app = criar_app()

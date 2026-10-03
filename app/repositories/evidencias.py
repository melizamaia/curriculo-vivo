"""Evidências ingeridas pelo worker: Mongo, com fallback em memória (ADR-8).

A base curada em arquivo é o ponto de partida; o que chega por
`evidencia.nova` fica aqui. Sem isso, um restart do worker perderia toda
evidência cujo offset já foi confirmado — e o Kafka não a entregaria de novo.

Diferente da auditoria, falha de escrita **não** cai para a memória depois do
boot: ela sobe como exceção, o offset não é confirmado e a mensagem é
reentregue. Perder um registro de auditoria degrada observabilidade; perder
uma evidência confirmada degrada a base.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from app.config import Settings
from app.models import Evidencia

logger = logging.getLogger(__name__)

BACKEND_MEMORIA = "memoria"
BACKEND_MONGO = "mongo"
COLECAO = "evidencias"


class ArmazemEvidencias(Protocol):
    backend: str

    async def listar(self) -> list[Evidencia]: ...

    async def salvar(self, evidencia: Evidencia, hash_conteudo: str) -> None: ...

    async def fechar(self) -> None: ...


class ArmazemMemoria:
    """Só para desenvolvimento e teste: não sobrevive a restart."""

    backend = BACKEND_MEMORIA

    def __init__(self) -> None:
        self._itens: dict[str, tuple[Evidencia, str]] = {}

    async def listar(self) -> list[Evidencia]:
        return [self._itens[k][0] for k in sorted(self._itens)]

    async def salvar(self, evidencia: Evidencia, hash_conteudo: str) -> None:
        self._itens[evidencia.doc_id] = (evidencia, hash_conteudo)

    async def fechar(self) -> None:
        return None


class ArmazemMongo:
    """Coleção `evidencias`, um documento por `doc_id` (último conteúdo vence)."""

    backend = BACKEND_MONGO

    def __init__(self, cliente: Any, banco: str) -> None:
        self._cliente = cliente
        self._colecao = cliente[banco][COLECAO]

    async def listar(self) -> list[Evidencia]:
        cursor = self._colecao.find({}, {"_id": 0, "evidencia": 1}).sort("_id", 1)
        return [Evidencia.model_validate(d["evidencia"]) async for d in cursor]

    async def salvar(self, evidencia: Evidencia, hash_conteudo: str) -> None:
        await self._colecao.replace_one(
            {"_id": evidencia.doc_id},
            {
                "evidencia": evidencia.model_dump(mode="json"),
                "hash": hash_conteudo,
                "indexado_em": datetime.now(timezone.utc),
            },
            upsert=True,
        )

    async def fechar(self) -> None:
        await self._cliente.close()


async def criar_armazem_evidencias(settings: Settings) -> ArmazemEvidencias:
    """Tenta Mongo com timeout curto; sem resposta, sobe em memória e registra."""
    cliente = None
    try:
        from pymongo import AsyncMongoClient

        cliente = AsyncMongoClient(
            settings.mongo_uri,
            serverSelectionTimeoutMS=settings.mongo_timeout_ms,
            connectTimeoutMS=settings.mongo_timeout_ms,
            tz_aware=True,
        )
        await cliente.admin.command("ping")
    except Exception as exc:
        if cliente is not None:
            await cliente.close()
        logger.warning(
            "Evidências ingeridas em memória (Mongo indisponível em %s: %s); "
            "não sobrevivem a restart",
            settings.mongo_uri,
            type(exc).__name__,
        )
        return ArmazemMemoria()
    logger.info("Evidências ingeridas no Mongo (%s/%s)", settings.mongo_uri, settings.mongo_db)
    return ArmazemMongo(cliente, settings.mongo_db)

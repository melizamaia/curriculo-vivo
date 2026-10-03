"""Repositório da trilha de auditoria: Mongo, com fallback em memória (ADR-8).

Indisponibilidade de infra degrada observabilidade, não a análise. Mongo fora
no boot → memória. Mongo que cai depois do boot → o registro vai para a
reserva em memória e a análise segue respondendo.
"""

from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import Settings
from app.models import RegistroAuditoria

logger = logging.getLogger(__name__)

BACKEND_MEMORIA = "memoria"
BACKEND_MONGO = "mongo"
COLECAO = "auditoria"


@dataclass(frozen=True)
class Estatisticas:
    """Insumo de `/v1/metricas`. Latências cobrem só a janela mais recente."""

    total: int = 0
    por_status: dict[str, int] = field(default_factory=dict)
    latencias_ms: list[float] = field(default_factory=list)


class RepositorioAuditoria(Protocol):
    backend: str

    async def gravar(self, registro: RegistroAuditoria) -> None: ...

    async def listar(self, limite: int = 50) -> list[RegistroAuditoria]: ...

    async def estatisticas(self) -> Estatisticas: ...

    async def fechar(self) -> None: ...


class AuditoriaMemoria:
    """Janela circular dos últimos registros; contagens desde o boot."""

    backend = BACKEND_MEMORIA

    def __init__(self, limite: int = 1000) -> None:
        self._lock = threading.Lock()
        self._registros: deque[RegistroAuditoria] = deque(maxlen=limite)
        self._total = 0
        self._por_status: Counter[str] = Counter()

    async def gravar(self, registro: RegistroAuditoria) -> None:
        with self._lock:
            self._registros.append(registro)
            self._total += 1
            self._por_status[registro.status.value] += 1

    async def listar(self, limite: int = 50) -> list[RegistroAuditoria]:
        with self._lock:
            recentes = list(self._registros)
        return recentes[::-1][:limite]

    async def estatisticas(self) -> Estatisticas:
        with self._lock:
            return Estatisticas(
                total=self._total,
                por_status=dict(self._por_status),
                latencias_ms=[r.latencia_ms for r in self._registros],
            )

    async def fechar(self) -> None:
        return None


class AuditoriaMongo:
    """Coleção `auditoria`. Toda falha de I/O cai para a reserva em memória."""

    backend = BACKEND_MONGO

    def __init__(self, cliente: Any, banco: str, janela: int = 1000) -> None:
        self._cliente = cliente
        self._colecao = cliente[banco][COLECAO]
        self._janela = janela
        self._reserva = AuditoriaMemoria(janela)

    async def preparar(self) -> None:
        await self._colecao.create_index("request_id", unique=True)
        await self._colecao.create_index([("criado_em", -1)])

    async def gravar(self, registro: RegistroAuditoria) -> None:
        try:
            await self._colecao.insert_one(registro.model_dump(mode="python"))
        except Exception as exc:
            logger.warning(
                "Mongo indisponível ao gravar auditoria %s (%s); registro na memória",
                registro.request_id,
                exc,
            )
            await self._reserva.gravar(registro)

    async def listar(self, limite: int = 50) -> list[RegistroAuditoria]:
        try:
            cursor = (
                self._colecao.find({}, {"_id": 0}).sort("criado_em", -1).limit(limite)
            )
            return [RegistroAuditoria.model_validate(d) async for d in cursor]
        except Exception as exc:
            logger.warning("Mongo indisponível ao listar auditoria (%s)", exc)
            return await self._reserva.listar(limite)

    async def estatisticas(self) -> Estatisticas:
        try:
            total = await self._colecao.count_documents({})
            por_status = {
                d["_id"]: d["n"]
                async for d in await self._colecao.aggregate(
                    [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]
                )
            }
            cursor = (
                self._colecao.find({}, {"_id": 0, "latencia_ms": 1})
                .sort("criado_em", -1)
                .limit(self._janela)
            )
            latencias = [float(d.get("latencia_ms", 0.0)) async for d in cursor]
            return Estatisticas(total, por_status, latencias)
        except Exception as exc:
            logger.warning("Mongo indisponível ao calcular métricas (%s)", exc)
            return await self._reserva.estatisticas()

    async def fechar(self) -> None:
        await self._cliente.close()


async def criar_repositorio_auditoria(settings: Settings) -> RepositorioAuditoria:
    """Tenta Mongo com timeout curto; sem resposta, sobe em memória e registra."""
    janela = settings.auditoria_limite_memoria
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
        repositorio = AuditoriaMongo(cliente, settings.mongo_db, janela)
        await repositorio.preparar()
    except Exception as exc:
        if cliente is not None:
            await cliente.close()
        logger.warning(
            "Auditoria em memória (Mongo indisponível em %s: %s)",
            settings.mongo_uri,
            type(exc).__name__,
        )
        return AuditoriaMemoria(janela)
    logger.info("Auditoria no Mongo (%s/%s)", settings.mongo_uri, settings.mongo_db)
    return repositorio

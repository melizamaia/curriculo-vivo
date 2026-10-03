"""Worker de ingestão: consome `evidencia.nova`, publica `evidencia.indexada`.

Fora do caminho da análise (ADR-5). Garantia de entrega at-least-once com
commit manual de offset (ADR-9), e idempotência por hash do conteúdo para que
a reentrega não reindexe nem republique.

Ordem por mensagem — cada passo só roda se o anterior deu certo:

1. valida forma e proveniência; reprovada → `evidencia.rejeitada`
2. mesmo hash já confirmado para o `doc_id` → duplicada, nada a fazer
3. reindexa (`Retriever.upsert`)
4. publica `evidencia.indexada`
5. persiste no armazém
6. marca o hash como confirmado
7. confirma o offset

O hash só é marcado depois de publicar e persistir: se o processo cair entre
3 e 6, a reentrega reprocessa em vez de ser tratada como duplicata — o pior
caso é um `evidencia.indexada` repetido, que o consumidor absorve por
`doc_id` + `versao_indice`. Qualquer exceção nos passos 3–5 interrompe o loop
sem confirmar o offset.

A classe `Ingestor` não conhece o Kafka: recebe um `Publicador` e um
consumidor qualquer com `commit`, e é testada sem broker.

    python -m app.workers.ingestor
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import signal
import sys
from collections.abc import AsyncIterable, Callable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Protocol

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.core.retriever import Retriever
from app.models import EventoEvidenciaIndexada, Evidencia, FonteTipo
from app.repositories.evidencias import ArmazemEvidencias, criar_armazem_evidencias

logger = logging.getLogger("app.workers.ingestor")

# Campos sem os quais não se sabe de onde a evidência veio. `Evidencia` tem
# default para `fonte_tipo`, mas aceitar o default na ingestão seria inventar
# proveniência — exatamente o que o produto combate.
CAMPOS_PROVENIENCIA = ("doc_id", "fonte", "fonte_tipo", "publicado_em")


# --------------------------------------------------------------------------
# Validação de proveniência
# --------------------------------------------------------------------------


class MotivoRejeicao(str, Enum):
    PAYLOAD_INVALIDO = "payload_invalido"
    PROVENIENCIA_AUSENTE = "proveniencia_ausente"
    SEM_URL_VERIFICAVEL = "sem_url_verificavel"
    DATA_FUTURA = "data_futura"
    SEM_TRECHOS = "sem_trechos"
    TRECHO_INCONSISTENTE = "trecho_inconsistente"


class EvidenciaRejeitada(Exception):
    def __init__(self, motivo: MotivoRejeicao, detalhe: str, doc_id: str | None = None):
        super().__init__(f"{motivo.value}: {detalhe}")
        self.motivo = motivo
        self.detalhe = detalhe
        self.doc_id = doc_id


def validar_evidencia(bruto: bytes | str, hoje: date) -> Evidencia:
    """Converte o payload em `Evidencia` ou levanta `EvidenciaRejeitada`.

    Validar proveniência aqui não é julgar a autoridade da fonte: evidência
    `nao_validada` ou `literatura_revisada` é aceita e indexada, e quem a
    impede de sustentar alerta é a barreira 2 na hora da análise. Aqui se
    exige que a proveniência **exista e seja coerente** — de onde veio, quando
    foi publicada, e que cada trecho citável aponte de volta para o documento.
    """
    try:
        dados = json.loads(bruto)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenciaRejeitada(MotivoRejeicao.PAYLOAD_INVALIDO, f"JSON inválido: {exc}")
    if not isinstance(dados, dict):
        raise EvidenciaRejeitada(MotivoRejeicao.PAYLOAD_INVALIDO, "esperado objeto JSON")

    doc_id = dados.get("doc_id") if isinstance(dados.get("doc_id"), str) else None
    ausentes = [
        c for c in CAMPOS_PROVENIENCIA if not str(dados.get(c) or "").strip()
    ]
    if ausentes:
        raise EvidenciaRejeitada(
            MotivoRejeicao.PROVENIENCIA_AUSENTE, f"campos ausentes: {ausentes}", doc_id
        )

    try:
        evidencia = Evidencia.model_validate(dados)
    except ValidationError as exc:
        erros = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
        )
        raise EvidenciaRejeitada(MotivoRejeicao.PAYLOAD_INVALIDO, erros, doc_id)

    # Fonte que pode sustentar alerta precisa ser verificável pelo
    # coordenador: a citação devolvida na análise inclui a URL.
    if evidencia.fonte_tipo.validada and not (evidencia.url or "").strip():
        raise EvidenciaRejeitada(
            MotivoRejeicao.SEM_URL_VERIFICAVEL,
            f"fonte_tipo={evidencia.fonte_tipo.value} exige url",
            doc_id,
        )

    # Data futura venceria toda comparação do detector (ADR-2) e geraria
    # alerta em todo material do tema.
    if evidencia.publicado_em > hoje:
        raise EvidenciaRejeitada(
            MotivoRejeicao.DATA_FUTURA,
            f"publicado_em={evidencia.publicado_em} posterior a {hoje}",
            doc_id,
        )

    if not evidencia.trechos or any(not t.texto.strip() for t in evidencia.trechos):
        raise EvidenciaRejeitada(
            MotivoRejeicao.SEM_TRECHOS, "sem trechos ou trecho vazio", doc_id
        )

    # O `trecho_id` vai para a citação e para a auditoria: precisa ser único
    # e identificar o documento de origem sem consulta adicional.
    prefixo = f"{evidencia.doc_id}#"
    ids = [t.trecho_id for t in evidencia.trechos]
    fora = [i for i in ids if not i.startswith(prefixo)]
    if fora or len(set(ids)) != len(ids):
        raise EvidenciaRejeitada(
            MotivoRejeicao.TRECHO_INCONSISTENTE,
            f"trecho_id deve ser único e começar com {prefixo!r}"
            + (f" (fora do padrão: {fora})" if fora else " (duplicado)"),
            doc_id,
        )

    return evidencia


def hash_evidencia(evidencia: Evidencia) -> str:
    """SHA-256 da forma canônica: o mesmo conteúdo sempre gera o mesmo hash."""
    canonico = json.dumps(
        evidencia.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Ingestor (sem Kafka)
# --------------------------------------------------------------------------


class Publicador(Protocol):
    async def publicar(self, topico: str, chave: str | None, valor: dict[str, Any]) -> None: ...


class Mensagem(Protocol):
    topic: str
    partition: int
    offset: int
    value: bytes


class Consumidor(Protocol):
    def __aiter__(self) -> Any: ...

    async def commit(self, offsets: dict[Any, int]) -> None: ...


class Resultado(str, Enum):
    INDEXADA = "indexada"
    DUPLICADA = "duplicada"
    REJEITADA = "rejeitada"


@dataclass(frozen=True)
class Processamento:
    resultado: Resultado
    doc_id: str | None
    versao_indice: str
    motivo: MotivoRejeicao | None = None


class Ingestor:
    def __init__(
        self,
        retriever: Retriever,
        armazem: ArmazemEvidencias,
        publicador: Publicador,
        settings: Settings,
        hoje: Callable[[], date] = date.today,
    ) -> None:
        self._retriever = retriever
        self._armazem = armazem
        self._publicador = publicador
        self._settings = settings
        self._hoje = hoje
        # doc_id → hash do conteúdo já indexado, publicado e persistido.
        # Semeado com o que o índice já tem: reenviar a base curada é no-op.
        self._confirmados: dict[str, str] = {
            e.doc_id: hash_evidencia(e) for e in retriever.evidencias()
        }

    @classmethod
    async def montar(
        cls,
        settings: Settings,
        publicador: Publicador,
        armazem: ArmazemEvidencias | None = None,
    ) -> Ingestor:
        """Índice = base curada em arquivo + o que já foi ingerido antes."""
        armazem = armazem or await criar_armazem_evidencias(settings)
        retriever = Retriever.carregar(settings.caminho_evidencias)
        ingeridas = await armazem.listar()
        for evidencia in ingeridas:
            retriever.upsert(evidencia)
        logger.info(
            "Ingestor pronto: %d evidências (%d ingeridas antes), versao_indice=%s, "
            "armazém=%s",
            retriever.total_evidencias,
            len(ingeridas),
            retriever.versao_indice,
            armazem.backend,
        )
        return cls(retriever, armazem, publicador, settings)

    @property
    def retriever(self) -> Retriever:
        return self._retriever

    async def processar(self, bruto: bytes | str) -> Processamento:
        """Passos 1–6. Exceção de infra sobe: quem chama não confirma o offset."""
        try:
            evidencia = validar_evidencia(bruto, self._hoje())
        except EvidenciaRejeitada as rej:
            await self._rejeitar(rej, bruto)
            return Processamento(
                Resultado.REJEITADA, rej.doc_id, self._retriever.versao_indice, rej.motivo
            )

        conteudo = hash_evidencia(evidencia)
        if self._confirmados.get(evidencia.doc_id) == conteudo:
            logger.info("Duplicada, ignorada: doc_id=%s", evidencia.doc_id)
            return Processamento(
                Resultado.DUPLICADA, evidencia.doc_id, self._retriever.versao_indice
            )

        versao = self._retriever.upsert(evidencia)
        evento = EventoEvidenciaIndexada(
            doc_id=evidencia.doc_id,
            versao_indice=versao,
            practice_changing=evidencia.practice_changing,
            trechos_indexados=len(evidencia.trechos),
        )
        await self._publicador.publicar(
            self._settings.kafka_topic_evidencia_indexada,
            evidencia.doc_id,
            evento.model_dump(mode="json"),
        )
        await self._armazem.salvar(evidencia, conteudo)
        self._confirmados[evidencia.doc_id] = conteudo
        logger.info(
            "Indexada: doc_id=%s fonte_tipo=%s practice_changing=%s versao_indice=%s",
            evidencia.doc_id,
            evidencia.fonte_tipo.value,
            evidencia.practice_changing,
            versao,
        )
        return Processamento(Resultado.INDEXADA, evidencia.doc_id, versao)

    async def consumir(self, consumidor: Consumidor) -> None:
        """Loop com commit manual: o offset só avança depois de `processar`."""
        from aiokafka.structs import TopicPartition

        async for mensagem in consumidor:
            await self.processar(mensagem.value)
            await consumidor.commit(
                {TopicPartition(mensagem.topic, mensagem.partition): mensagem.offset + 1}
            )

    async def _rejeitar(self, rej: EvidenciaRejeitada, bruto: bytes | str) -> None:
        logger.warning("Rejeitada: doc_id=%s %s", rej.doc_id, rej)
        texto = bruto.decode("utf-8", "replace") if isinstance(bruto, bytes) else bruto
        await self._publicador.publicar(
            self._settings.kafka_topic_evidencia_rejeitada,
            rej.doc_id,
            {
                "doc_id": rej.doc_id,
                "motivo": rej.motivo.value,
                "detalhe": rej.detalhe,
                "payload": texto,
            },
        )


# --------------------------------------------------------------------------
# Kafka
# --------------------------------------------------------------------------


class PublicadorKafka:
    """`send_and_wait` com `acks=all`: só retorna quando o broker confirmou."""

    def __init__(self, produtor: Any) -> None:
        self._produtor = produtor

    async def publicar(self, topico: str, chave: str | None, valor: dict[str, Any]) -> None:
        await self._produtor.send_and_wait(
            topico,
            json.dumps(valor, ensure_ascii=False).encode("utf-8"),
            key=chave.encode("utf-8") if chave else None,
        )


async def executar(settings: Settings) -> None:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

    async with contextlib.AsyncExitStack() as pilha:
        armazem = await criar_armazem_evidencias(settings)
        pilha.push_async_callback(armazem.fechar)

        produtor = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            acks="all",
            enable_idempotence=True,
        )
        pilha.push_async_callback(produtor.stop)
        await produtor.start()

        ingestor = await Ingestor.montar(settings, PublicadorKafka(produtor), armazem)

        consumidor = AIOKafkaConsumer(
            settings.kafka_topic_evidencia_nova,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        pilha.push_async_callback(consumidor.stop)
        await consumidor.start()

        logger.info(
            "Consumindo %s em %s (grupo %s)",
            settings.kafka_topic_evidencia_nova,
            settings.kafka_bootstrap_servers,
            settings.kafka_consumer_group,
        )
        await ingestor.consumir(consumidor)


async def _principal() -> int:
    from aiokafka.errors import KafkaConnectionError

    tarefa = asyncio.current_task()
    loop = asyncio.get_running_loop()
    # SIGTERM do `docker stop` vira cancelamento: a pilha fecha consumidor e
    # produtor, e o grupo rebalanceia sem esperar o timeout de sessão.
    for sinal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sinal, tarefa.cancel)
    settings = get_settings()
    try:
        await executar(settings)
    except asyncio.CancelledError:
        logger.info("Ingestor encerrado")
    except KafkaConnectionError:
        # Código != 0: o `restart: on-failure` do compose tenta de novo.
        logger.error("Kafka indisponível em %s", settings.kafka_bootstrap_servers)
        return 1
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_principal())


if __name__ == "__main__":
    sys.exit(main())

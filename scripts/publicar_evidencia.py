"""Publica uma evidência em `evidencia.nova` e espera a resposta do worker.

Serve para verificar a stack do docker compose ponta a ponta: o worker
valida, indexa e responde em `evidencia.indexada` (ou `evidencia.rejeitada`).
Sem arquivo, publica uma evidência sintética de oftalmologia — tema que a
base curada não cobre.

    python -m scripts.publicar_evidencia
    python -m scripts.publicar_evidencia minha_evidencia.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import get_settings

EXEMPLO = {
    "doc_id": "diretriz-glaucoma-2025",
    "titulo": "Glaucoma agudo de angulo fechado: reconhecimento e encaminhamento",
    "fonte": "Sociedade ilustrativa de oftalmologia",
    "fonte_tipo": "diretriz_sociedade",
    "url": "https://example.org/glaucoma",
    "publicado_em": "2025-03-10",
    "nivel_evidencia": "B",
    "temas": ["oftalmologia"],
    "practice_changing": True,
    "exemplo_ilustrativo": True,
    "trechos": [
        {
            "trecho_id": "diretriz-glaucoma-2025#t1",
            "texto": "O glaucoma agudo de angulo fechado exige reconhecimento do quadro "
            "doloroso, medida da pressao intraocular e encaminhamento para avaliacao "
            "especializada no mesmo dia.",
        }
    ],
}


async def publicar(evidencia: dict, espera_s: float) -> int:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    from aiokafka.structs import TopicPartition

    s = get_settings()
    respostas = [s.kafka_topic_evidencia_indexada, s.kafka_topic_evidencia_rejeitada]
    chave = str(evidencia.get("doc_id") or "")

    # Posiciona o leitor no fim dos tópicos de resposta antes de publicar,
    # para só ver o que o worker responder a esta mensagem.
    leitor = AIOKafkaConsumer(bootstrap_servers=s.kafka_bootstrap_servers, enable_auto_commit=False)
    produtor = AIOKafkaProducer(bootstrap_servers=s.kafka_bootstrap_servers, acks="all")
    await leitor.start()
    await produtor.start()
    try:
        await leitor.topics()  # força metadados atualizados
        particoes = [
            TopicPartition(t, p) for t in respostas for p in leitor.partitions_for_topic(t) or ()
        ]
        leitor.assign(particoes)
        await leitor.seek_to_end(*particoes)

        await produtor.send_and_wait(
            s.kafka_topic_evidencia_nova,
            json.dumps(evidencia, ensure_ascii=False).encode("utf-8"),
            key=chave.encode("utf-8") or None,
        )
        print(f"publicado em {s.kafka_topic_evidencia_nova}: doc_id={chave}")

        prazo = asyncio.get_running_loop().time() + espera_s
        while asyncio.get_running_loop().time() < prazo:
            lotes = await leitor.getmany(timeout_ms=500)
            for tp, mensagens in lotes.items():
                for m in mensagens:
                    if (m.key or b"").decode() == chave:
                        print(f"{tp.topic}: {m.value.decode()}")
                        return 0 if tp.topic == s.kafka_topic_evidencia_indexada else 1
        print(
            f"sem resposta em {espera_s:.0f}s. Se for reenvio do mesmo conteúdo, é o "
            "esperado: o worker reconhece o hash e não republica (veja o log do worker)."
        )
        return 2
    finally:
        await produtor.stop()
        await leitor.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("arquivo", nargs="?", type=Path, help="JSON de uma Evidencia")
    parser.add_argument("--espera", type=float, default=15.0, help="segundos")
    args = parser.parse_args(argv)
    evidencia = json.loads(args.arquivo.read_text(encoding="utf-8")) if args.arquivo else EXEMPLO
    return asyncio.run(publicar(evidencia, args.espera))


if __name__ == "__main__":
    sys.exit(main())

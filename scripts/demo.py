"""Roteiro da demo (seção 14 do PRD) num comando só.

Sem argumento, sobe a API em processo — sem servidor, sem Mongo, sem Kafka.
Com `--url`, roda o mesmo roteiro contra uma API no ar (ex.: docker compose).

    python -m scripts.demo
    python -m scripts.demo --url http://localhost:8000
"""

from __future__ import annotations

import argparse
import logging
import sys

CASOS = [
    ("med-clin-sepse-aula07", "defasada: alerta alto, com citação"),
    ("med-card-hipertensao-aula03", "atualizada: sem falso alarme"),
    ("med-sem-referencia-aula01", "sem referência datada: o serviço se cala"),
    ("med-orl-rinite-aula05", "só há fonte não validada: não sustenta alerta"),
    ("med-oftalmo-glaucoma-aula01", "tema fora da base: abstém"),
]


def _titulo(texto: str) -> None:
    print(f"\n── {texto} " + "─" * max(0, 68 - len(texto)))


def roteiro(cliente) -> None:
    _titulo("1. Radar: a fila do coordenador")
    radar = cliente.get("/v1/defasagens").raise_for_status().json()
    print(f"  {radar['total_objetos']} objetos · {radar['objetos_com_defasagem']} com defasagem")
    print(f"  por severidade: {radar['por_severidade']}")
    print(f"  abstenções:     {radar['abstencoes']}")
    for item in radar["itens"][:5]:
        if item["status"] == "defasagem_detectada":
            print(f"    {item['severidade_maxima']:<5} {item['objeto_id']}")

    for i, (objeto_id, legenda) in enumerate(CASOS, start=2):
        _titulo(f"{i}. {objeto_id} — {legenda}")
        r = cliente.post("/v1/analises", json={"objeto_id": objeto_id}).raise_for_status().json()
        linha = f"  status={r['status']}"
        if r["motivo_abstencao"]:
            linha += f" motivo={r['motivo_abstencao']}"
        if r["severidade_maxima"]:
            linha += f" severidade={r['severidade_maxima']}"
        print(linha + f" confianca={r['confianca']}")
        for d in r["defasagens"]:
            ev = d["evidencia"]
            print(f"  {d['justificativa']}")
            print(
                f"  [{ev['marcador']}] {ev['fonte']} ({ev['fonte_tipo']}), "
                f"{ev['publicado_em']}, nível {ev['nivel_evidencia']} — {ev['url']}"
            )

    _titulo("7. Auditoria: o material só aparece como hash")
    for reg in cliente.get("/v1/auditoria", params={"limite": 3}).raise_for_status().json():
        print(f"  {reg['objeto_id']:<32} {reg['status']:<20} hash={reg['objeto_hash'][:16]}…")

    _titulo("8. Métricas de operação")
    m = cliente.get("/v1/metricas").raise_for_status().json()
    print(
        f"  {m['total_analises']} análises · abstenção {m['taxa_abstencao']:.0%} · "
        f"p95 {m['latencia_p95_ms']} ms · versao_indice={m['versao_indice']}"
    )
    print("\n  Painel de avaliação: /painel (gerado por `make eval`)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="API no ar; sem isso, roda em processo")
    args = parser.parse_args(argv)

    if args.url:
        import httpx

        contexto = httpx.Client(base_url=args.url, timeout=10)
    else:
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import criar_app

        # Em processo a demo não procura Mongo (porta fechada, auditoria em memória)
        # e não imprime log de request, que poluiria o roteiro.
        logging.disable(logging.WARNING)
        settings = Settings(mongo_uri="mongodb://127.0.0.1:1", mongo_timeout_ms=100)
        contexto = TestClient(criar_app(settings))

    with contexto as cliente:
        roteiro(cliente)
    return 0


if __name__ == "__main__":
    sys.exit(main())

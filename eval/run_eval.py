"""Harness de avaliação (seção 8 do PRD).

Roda o serviço em processo — sem HTTP, sem Mongo, sem rede — sobre
`eval/dataset.json`, calcula as métricas, grava `eval/results.json` e gera
`dashboard/index.html` autocontido (dados embutidos, sem fetch, sem CDN).

As invariantes são verificadas aqui de forma independente da barreira 3: o
harness não confia no guardrail que está medindo. Código de saída:

    0  todas as metas duras cumpridas (e as demais, com --estrito)
    1  meta dura violada: alerta sem citação ou invariante quebrada
    2  avaliação inválida: caso do dataset sem objeto no catálogo

    python -m eval.run_eval
"""

from __future__ import annotations

import argparse
import json
import operator
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import RAIZ_PROJETO, Settings, get_settings
from app.core.audit import percentil
from app.core.detector import data_corte
from app.core.guardrail import MARCADOR_MATERIAL, Guardrail, Validacao
from app.core.justificativa import (
    ContextoJustificativa,
    GeradorJustificativa,
    Sintese,
    criar_gerador,
)
from app.core.retriever import Retriever
from app.core.servico import ServicoAnalise
from app.models import (
    AnaliseResponse,
    MotivoAbstencao,
    ObjetoAprendizagem,
    StatusAnalise,
)
from app.repositories.catalogo import RepositorioCatalogo

CAMINHO_DATASET = RAIZ_PROJETO / "eval" / "dataset.json"
CAMINHO_RESULTADOS = RAIZ_PROJETO / "eval" / "results.json"
CAMINHO_TEMPLATE = RAIZ_PROJETO / "eval" / "painel_template.html"
CAMINHO_PAINEL = RAIZ_PROJETO / "dashboard" / "index.html"
MARCADOR_DADOS = "__DADOS_EVAL__"

SAIDA_OK = 0
SAIDA_META_DURA = 1
SAIDA_INVALIDA = 2

_MARCADOR = re.compile(r"\[(\d+)\]")

STATUS_ESPERADO = {
    "defasado": StatusAnalise.DEFASAGEM_DETECTADA,
    "atualizado": StatusAnalise.SEM_ACHADO,
    "sem_evidencia": StatusAnalise.ABSTIDO,
    "inelegivel": StatusAnalise.ABSTIDO,
}
CLASSES_ABSTENCAO = ("sem_evidencia", "inelegivel")


# --------------------------------------------------------------------------
# Instrumentação: observa o serviço sem mudar o que ele faz
# --------------------------------------------------------------------------


class _GuardrailInstrumentado(Guardrail):
    """Guarda a saída da barreira 3 da última análise (para a invariante 4)."""

    ultima_validacao: Validacao | None = None

    def barreira_validacao(self, defasagens, ano_material, objeto_id=""):
        self.ultima_validacao = super().barreira_validacao(
            defasagens, ano_material, objeto_id=objeto_id
        )
        return self.ultima_validacao


class _ContadorTokens:
    """Soma os tokens do gerador: base do custo estimado."""

    def __init__(self, gerador: GeradorJustificativa) -> None:
        self._gerador = gerador
        self.tokens = 0

    @property
    def modo(self) -> str:
        return self._gerador.modo

    def gerar(self, contexto: ContextoJustificativa) -> Sintese:
        sintese = self._gerador.gerar(contexto)
        self.tokens += sintese.tokens
        return sintese


# --------------------------------------------------------------------------
# Verificações independentes (metas duras)
# --------------------------------------------------------------------------


def _marcadores(texto: str) -> set[int]:
    return {int(m) for m in _MARCADOR.findall(texto or "")}


def alertas_sem_citacao(resposta: AnaliseResponse) -> int:
    """Defasagens sem evidência, que não citam a própria evidência, ou com
    marcador órfão (que não é `[0]` nem de evidência da resposta)."""
    citados = {
        d.evidencia.marcador
        for d in resposta.defasagens
        if getattr(d, "evidencia", None) is not None
    }
    total = 0
    for d in resposta.defasagens:
        evidencia = getattr(d, "evidencia", None)
        usados = _marcadores(d.justificativa)
        if (
            evidencia is None
            or evidencia.marcador not in usados
            or usados - citados - {MARCADOR_MATERIAL}
        ):
            total += 1
    return total


def verificar_invariantes(
    resposta: AnaliseResponse, validacao: Validacao | None = None
) -> list[str]:
    """Violações das invariantes da seção 5.5, uma mensagem por violação."""
    violacoes: list[str] = []
    status, defasagens = resposta.status, resposta.defasagens

    # 1 — defasagem detectada tem defasagens, todas com evidência; o resto, nenhuma.
    if status is StatusAnalise.DEFASAGEM_DETECTADA:
        if not defasagens:
            violacoes.append("I1: defasagem_detectada sem defasagens")
        if any(getattr(d, "evidencia", None) is None for d in defasagens):
            violacoes.append("I1: defasagem sem evidência")
    elif defasagens:
        violacoes.append(f"I1: status {status.value} com defasagens")
    if (status is StatusAnalise.ABSTIDO) != (resposta.motivo_abstencao is not None):
        violacoes.append("I1: motivo_abstencao incoerente com o status")

    # 2 — todo marcador citado existe na resposta; um marcador, uma evidência.
    por_marcador: dict[int, set[str]] = {}
    for d in defasagens:
        if getattr(d, "evidencia", None) is not None:
            por_marcador.setdefault(d.evidencia.marcador, set()).add(d.evidencia.doc_id)
    for d in defasagens:
        orfaos = _marcadores(d.justificativa) - set(por_marcador) - {MARCADOR_MATERIAL}
        if orfaos:
            violacoes.append(f"I2: marcador órfão {sorted(orfaos)} no tema {d.tema}")
    for marcador, docs in por_marcador.items():
        if len(docs) > 1:
            violacoes.append(f"I2: marcador [{marcador}] ambíguo entre {sorted(docs)}")

    # 3 — a evidência é posterior à referência do material.
    ano = resposta.ano_referencia_material
    for d in defasagens:
        evidencia = getattr(d, "evidencia", None)
        if evidencia is None:
            continue
        if ano is None or evidencia.publicado_em <= data_corte(ano):
            violacoes.append(
                f"I3: evidência {evidencia.doc_id} não é posterior à referência {ano}"
            )

    # 4 — tudo descartado na barreira 3 vira abstido/alerta_descartado, e só isso.
    descartou_tudo = validacao is not None and validacao.todas_descartadas
    marcou_descarte = resposta.motivo_abstencao is MotivoAbstencao.ALERTA_DESCARTADO
    if descartou_tudo and not (status is StatusAnalise.ABSTIDO and marcou_descarte):
        violacoes.append("I4: todas as defasagens descartadas sem alerta_descartado")
    if marcou_descarte and not descartou_tudo:
        violacoes.append("I4: alerta_descartado sem descarte na barreira 3")

    return violacoes


# --------------------------------------------------------------------------
# Avaliação por caso
# --------------------------------------------------------------------------


def avaliar_caso(
    caso: dict[str, Any],
    resposta: AnaliseResponse,
    validacao: Validacao | None = None,
) -> dict[str, Any]:
    classe = caso["classe"]
    motivo = resposta.motivo_abstencao.value if resposta.motivo_abstencao else None
    severidade = resposta.severidade_maxima.value if resposta.severidade_maxima else None
    citadas = [d.evidencia.doc_id for d in resposta.defasagens]
    detectado = resposta.status is StatusAnalise.DEFASAGEM_DETECTADA

    criterios: dict[str, bool] = {"status": resposta.status is STATUS_ESPERADO[classe]}
    if classe == "defasado":
        criterios["citacao"] = caso.get("evidencia_esperada") in citadas
        criterios["severidade"] = severidade == caso.get("severidade_esperada")
    elif classe in CLASSES_ABSTENCAO:
        criterios["motivo"] = motivo == caso.get("motivo_esperado")

    divergencias = []
    if not criterios["status"]:
        divergencias.append(
            f"status {resposta.status.value}, esperado {STATUS_ESPERADO[classe].value}"
        )
    if criterios.get("citacao") is False:
        divergencias.append(f"não citou {caso.get('evidencia_esperada')}")
    if criterios.get("severidade") is False:
        divergencias.append(
            f"severidade {severidade}, esperada {caso.get('severidade_esperada')}"
        )
    if criterios.get("motivo") is False:
        divergencias.append(f"motivo {motivo}, esperado {caso.get('motivo_esperado')}")

    violacoes = verificar_invariantes(resposta, validacao)
    sem_citacao = alertas_sem_citacao(resposta)
    if sem_citacao:
        divergencias.append(f"{sem_citacao} alerta(s) sem citação")
    divergencias.extend(violacoes)

    return {
        "id": caso["id"],
        "objeto_id": caso["objeto_id"],
        "classe": classe,
        "nota": caso.get("nota"),
        "esperado": {
            "status": STATUS_ESPERADO[classe].value,
            "evidencia": caso.get("evidencia_esperada"),
            "severidade": caso.get("severidade_esperada"),
            "motivo": caso.get("motivo_esperado"),
        },
        "obtido": {
            "status": resposta.status.value,
            "evidencias": citadas,
            "severidade": severidade,
            "motivo": motivo,
            "confianca": resposta.confianca,
            "gap_meses": max((d.gap_meses for d in resposta.defasagens), default=None),
            "latencia_ms": resposta.latencia_ms,
        },
        "criterios": criterios,
        "falso_alarme": classe == "atualizado" and detectado,
        "alertas_sem_citacao": sem_citacao,
        "invariantes_violadas": violacoes,
        "descartes_barreira_3": len(validacao.descartes) if validacao else 0,
        "acertou": not divergencias,
        "divergencias": divergencias,
    }


# --------------------------------------------------------------------------
# Métricas e metas
# --------------------------------------------------------------------------


def _taxa(casos: Sequence[dict], criterio) -> float | None:
    if not casos:
        return None
    return round(sum(1 for c in casos if criterio(c)) / len(casos), 4)


def calcular_metricas(
    casos: Sequence[dict[str, Any]], tokens: int, settings: Settings
) -> dict[str, Any]:
    por_classe: dict[str, list[dict]] = {}
    for c in casos:
        por_classe.setdefault(c["classe"], []).append(c)
    defasados = por_classe.get("defasado", [])
    atualizados = por_classe.get("atualizado", [])
    abstencoes = [c for k in CLASSES_ABSTENCAO for c in por_classe.get(k, [])]
    latencias = [c["obtido"]["latencia_ms"] for c in casos]

    return {
        "taxa_deteccao": _taxa(defasados, lambda c: c["criterios"]["status"]),
        "taxa_falso_alarme": _taxa(atualizados, lambda c: c["falso_alarme"]),
        "taxa_citacao_correta": _taxa(defasados, lambda c: c["criterios"]["citacao"]),
        "taxa_severidade_correta": _taxa(
            defasados, lambda c: c["criterios"]["severidade"]
        ),
        "taxa_abstencao_adequada": _taxa(abstencoes, lambda c: c["criterios"]["status"]),
        "taxa_motivo_correto": _taxa(abstencoes, lambda c: c["criterios"]["motivo"]),
        "alerta_sem_citacao": sum(c["alertas_sem_citacao"] for c in casos),
        "invariante_violada": sum(len(c["invariantes_violadas"]) for c in casos),
        "descartes_barreira_3": sum(c["descartes_barreira_3"] for c in casos),
        "latencia_p50_ms": round(percentil(latencias, 50), 2),
        "latencia_p95_ms": round(percentil(latencias, 95), 2),
        "tokens": tokens,
        "custo_estimado_usd": round(tokens / 1000 * settings.custo_por_1k_tokens, 4),
        "casos_por_classe": {k: len(v) for k, v in sorted(por_classe.items())},
        "casos_corretos": sum(1 for c in casos if c["acertou"]),
    }


_OPERADORES = {">=": operator.ge, "<=": operator.le, "<": operator.lt, "==": operator.eq}


@dataclass(frozen=True)
class Meta:
    metrica: str
    rotulo: str
    operador: str
    alvo: float
    dura: bool = False

    def avaliar(self, metricas: dict[str, Any]) -> dict[str, Any]:
        valor = metricas.get(self.metrica)
        # Classe ausente no dataset não reprova a meta, mas fica visível.
        ok = None if valor is None else _OPERADORES[self.operador](valor, self.alvo)
        return {**asdict(self), "valor": valor, "ok": ok}


METAS: tuple[Meta, ...] = (
    Meta("alerta_sem_citacao", "Alerta sem citação", "==", 0, dura=True),
    Meta("invariante_violada", "Invariante violada", "==", 0, dura=True),
    Meta("taxa_falso_alarme", "Falso alarme", "<=", 0.10),
    Meta("taxa_deteccao", "Detecção", ">=", 0.85),
    Meta("taxa_citacao_correta", "Citação correta", ">=", 0.85),
    Meta("taxa_severidade_correta", "Severidade correta", ">=", 0.80),
    Meta("taxa_abstencao_adequada", "Abstenção adequada", ">=", 0.95),
    Meta("taxa_motivo_correto", "Motivo correto", ">=", 0.90),
    Meta("latencia_p95_ms", "Latência p95 (ms)", "<", 500),
)


def codigo_saida(metas: Sequence[dict[str, Any]], estrito: bool = False) -> int:
    """1 se uma meta dura (ou, com `estrito`, qualquer meta) foi violada."""
    violadas = [m for m in metas if m["ok"] is False and (m["dura"] or estrito)]
    return SAIDA_META_DURA if violadas else SAIDA_OK


# --------------------------------------------------------------------------
# Execução
# --------------------------------------------------------------------------


class AvaliacaoInvalida(Exception):
    """O dataset não pode ser avaliado contra o corpus carregado."""


def carregar_dataset(caminho: Path) -> list[dict[str, Any]]:
    bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
    return bruto["itens"] if isinstance(bruto, dict) else bruto


def executar(
    settings: Settings | None = None,
    caminho_dataset: Path = CAMINHO_DATASET,
) -> dict[str, Any]:
    settings = settings or get_settings()
    casos = carregar_dataset(caminho_dataset)
    retriever = Retriever.carregar(settings.caminho_evidencias)
    catalogo = RepositorioCatalogo.carregar(settings.caminho_material)

    faltando = [c["objeto_id"] for c in casos if catalogo.obter(c["objeto_id"]) is None]
    if faltando:
        raise AvaliacaoInvalida(f"objetos do dataset fora do catálogo: {faltando}")
    if retriever.vazio:
        raise AvaliacaoInvalida("índice de evidência vazio")

    guardrail = _GuardrailInstrumentado(settings)
    contador = _ContadorTokens(criar_gerador(settings))
    servico = ServicoAnalise(retriever, settings, guardrail=guardrail, gerador=contador)

    avaliados = []
    for caso in casos:
        objeto: ObjetoAprendizagem = catalogo.obter(caso["objeto_id"])  # type: ignore[assignment]
        guardrail.ultima_validacao = None
        resposta = servico.analisar(objeto)
        avaliados.append(avaliar_caso(caso, resposta, guardrail.ultima_validacao))

    metricas = calcular_metricas(avaliados, contador.tokens, settings)
    metas = [m.avaliar(metricas) for m in METAS]
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versao_indice": retriever.versao_indice,
        "configuracao": {
            "limiar_confianca": settings.limiar_confianca,
            "top_k": settings.top_k,
            "exigir_fonte_oficial": settings.exigir_fonte_oficial,
            "modo_sintese": contador.modo,
            "evidencias_indexadas": retriever.total_evidencias,
            "objetos_catalogados": catalogo.total,
        },
        "metricas": metricas,
        "metas": metas,
        "metas_duras_ok": codigo_saida(metas) == SAIDA_OK,
        "casos": avaliados,
        "aviso": (
            "Corpus sintético e ilustrativo. " + settings.aviso_padrao
        ),
    }


def gravar_resultados(resultado: dict[str, Any], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def gerar_painel(
    resultado: dict[str, Any], destino: Path, template: Path = CAMINHO_TEMPLATE
) -> None:
    """Embute o resultado no template. `<` vira `\\u003c`: nenhum texto do
    dataset consegue fechar o `<script>` que carrega os dados."""
    html = template.read_text(encoding="utf-8")
    if html.count(MARCADOR_DADOS) != 1:
        raise ValueError(f"template precisa conter {MARCADOR_DADOS} exatamente uma vez")
    dados = json.dumps(resultado, ensure_ascii=False).replace("<", "\\u003c")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html.replace(MARCADOR_DADOS, dados), encoding="utf-8")


def _fmt(valor: Any, metrica: str) -> str:
    if valor is None:
        return "—"
    if metrica.startswith("taxa_"):
        return f"{valor:.0%}"
    return f"{valor:g}"


def imprimir_resumo(resultado: dict[str, Any], saida=sys.stdout) -> None:
    m, cfg = resultado["metricas"], resultado["configuracao"]
    print(
        f"Currículo Vivo — avaliação ({len(resultado['casos'])} casos, "
        f"versao_indice={resultado['versao_indice']}, síntese={cfg['modo_sintese']}, "
        f"limiar={cfg['limiar_confianca']})",
        file=saida,
    )
    for meta in resultado["metas"]:
        marca = {True: "ok  ", False: "FALHA", None: "n/a "}[meta["ok"]]
        dura = " [dura]" if meta["dura"] else ""
        print(
            f"  {marca}  {meta['rotulo']:<22} {_fmt(meta['valor'], meta['metrica']):>8}"
            f"   meta {meta['operador']} {_fmt(meta['alvo'], meta['metrica'])}{dura}",
            file=saida,
        )
    print(
        f"  latência p50 {m['latencia_p50_ms']} ms · custo US$ {m['custo_estimado_usd']}"
        f" · descartes na barreira 3: {m['descartes_barreira_3']}"
        f" · casos corretos {m['casos_corretos']}/{len(resultado['casos'])}",
        file=saida,
    )
    for caso in resultado["casos"]:
        if not caso["acertou"]:
            print(f"  ✕ {caso['id']} {caso['objeto_id']}: {'; '.join(caso['divergencias'])}",
                  file=saida)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness de avaliação do Currículo Vivo")
    parser.add_argument("--dataset", type=Path, default=CAMINHO_DATASET)
    parser.add_argument("--resultados", type=Path, default=CAMINHO_RESULTADOS)
    parser.add_argument("--painel", type=Path, default=CAMINHO_PAINEL)
    parser.add_argument(
        "--estrito", action="store_true", help="falha também nas metas não duras"
    )
    args = parser.parse_args(argv)

    try:
        resultado = executar(caminho_dataset=args.dataset)
    except AvaliacaoInvalida as exc:
        print(f"Avaliação inválida: {exc}", file=sys.stderr)
        return SAIDA_INVALIDA

    gravar_resultados(resultado, args.resultados)
    gerar_painel(resultado, args.painel)
    imprimir_resumo(resultado)
    print(f"  → {args.resultados}\n  → {args.painel}")

    codigo = codigo_saida(resultado["metas"], estrito=args.estrito)
    if codigo != SAIDA_OK:
        print("Meta violada: o build não deve seguir.", file=sys.stderr)
    return codigo


if __name__ == "__main__":
    sys.exit(main())

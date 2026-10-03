"""Trilha de auditoria: hash do objeto, montagem do registro e percentil (ADR-7).

O material didático nunca entra no log em texto claro. O hash canônico do
objeto, junto com `versao_indice`, basta para reconstruir a análise: o mesmo
objeto contra a mesma base gera o mesmo alerta (ADR-1).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence

from app.models import (
    AnaliseResponse,
    ObjetoAprendizagem,
    OrigemAnalise,
    RegistroAuditoria,
)


def hash_objeto(objeto: ObjetoAprendizagem) -> str:
    """SHA-256 da forma canônica do objeto, independente da ordem das chaves."""
    canonico = json.dumps(
        objeto.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def montar_registro(
    resposta: AnaliseResponse,
    objeto: ObjetoAprendizagem,
    versao_indice: str,
    origem: OrigemAnalise = OrigemAnalise.ANALISE,
) -> RegistroAuditoria:
    """Registro da seção 5.7: o que foi citado, com que score, contra qual base."""
    return RegistroAuditoria(
        request_id=resposta.request_id,
        origem=origem,
        objeto_id=resposta.objeto_id,
        objeto_hash=hash_objeto(objeto),
        curso=resposta.curso,
        disciplina=resposta.disciplina,
        status=resposta.status,
        motivo_abstencao=resposta.motivo_abstencao,
        severidade_maxima=resposta.severidade_maxima,
        confianca=resposta.confianca,
        evidencias_citadas=[d.evidencia.doc_id for d in resposta.defasagens],
        trechos_citados=[d.evidencia.trecho_id for d in resposta.defasagens],
        scores=[d.evidencia.score for d in resposta.defasagens],
        modo_sintese=resposta.modo_sintese,
        latencia_ms=resposta.latencia_ms,
        versao_indice=versao_indice,
    )


def percentil(valores: Sequence[float], p: float) -> float:
    """Percentil `p` (0–100) por interpolação linear; 0.0 sem amostras."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * min(max(p, 0.0), 100.0) / 100.0
    baixo, alto = math.floor(posicao), math.ceil(posicao)
    fracao = posicao - baixo
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * fracao

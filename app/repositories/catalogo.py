"""Catálogo de objetos de aprendizagem, em memória por pod.

Carregado do JSON gerado por `scripts/gerar_corpus_material.py`. A ingestão
por `POST /v1/objetos` vive só na memória do processo: o corpus em disco é
artefato versionado do gerador e não é reescrito pela API.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from app.models import ObjetoAprendizagem

logger = logging.getLogger(__name__)


class RepositorioCatalogo:
    def __init__(self, objetos: list[ObjetoAprendizagem] | None = None) -> None:
        self._lock = threading.Lock()
        self._objetos: dict[str, ObjetoAprendizagem] = {
            o.objeto_id: o for o in objetos or []
        }

    @classmethod
    def carregar(cls, caminho: Path) -> RepositorioCatalogo:
        """Arquivo ausente ou inválido → catálogo vazio, sem derrubar o boot."""
        try:
            bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
            itens = bruto["objetos"] if isinstance(bruto, dict) else bruto
            objetos = [ObjetoAprendizagem.model_validate(i) for i in itens]
        except Exception as exc:
            logger.warning(
                "Falha ao carregar catálogo de %s (%s); catálogo vazio", caminho, exc
            )
            return cls()
        logger.info("Catálogo carregado: %d objetos", len(objetos))
        return cls(objetos)

    @property
    def total(self) -> int:
        return len(self._objetos)

    def obter(self, objeto_id: str) -> ObjetoAprendizagem | None:
        return self._objetos.get(objeto_id)

    def listar(
        self, curso: str | None = None, disciplina: str | None = None
    ) -> list[ObjetoAprendizagem]:
        with self._lock:
            objetos = [self._objetos[k] for k in sorted(self._objetos)]
        return [
            o
            for o in objetos
            if (curso is None or o.curso == curso)
            and (disciplina is None or o.disciplina == disciplina)
        ]

    def upsert(self, objeto: ObjetoAprendizagem) -> bool:
        """Insere ou substitui por `objeto_id`. Devolve True se era novo."""
        with self._lock:
            novo = objeto.objeto_id not in self._objetos
            self._objetos[objeto.objeto_id] = objeto
            return novo

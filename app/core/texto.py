"""Normalização de texto PT-BR para recuperação.

Determinística e sem dependência externa: o mesmo texto gera sempre os mesmos
termos (ADR-1). É o que alimenta o TF-IDF do retriever e a inspeção de escopo
do guardrail.
"""

from __future__ import annotations

import re
import unicodedata

# Stopwords PT-BR já sem acento, porque são comparadas depois da normalização.
STOPWORDS_PT: frozenset[str] = frozenset(
    """
    a ao aos aquela aquelas aquele aqueles aquilo as ate com como contra da das
    de dela delas dele deles depois do dos e ela elas ele eles em entre era eram
    essa essas esse esses esta estao estas este estes eu foi foram ha isso isto
    ja la lhe lhes mais mas me mesmo meu minha muito na nao nas nem no nos nossa
    nosso num numa o os ou para pela pelas pelo pelos por qual quando que quem
    se sem ser seu seus sua suas sao so tambem te tem tendo ter teu tua um uma
    umas uns voce voces vos sobre apos cada onde tal tais seja sejam sendo
    deve devem pode podem estar sera serao fica ficam assim ainda
    """.split()
)

_NAO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def remover_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, só letras e dígitos separados por espaço."""
    sem_acento = remover_acentos(texto or "").lower()
    return _NAO_ALFANUMERICO.sub(" ", sem_acento).strip()


def tokenizar(texto: str) -> list[str]:
    """Tokens normalizados, sem stopwords e sem tokens de uma letra."""
    return [
        t for t in normalizar(texto).split() if len(t) > 1 and t not in STOPWORDS_PT
    ]


def termos(texto: str) -> list[str]:
    """Unigramas + bigramas, na ordem do texto.

    O bigrama é formado depois de remover stopwords, então "choque séptico" e
    "choque do séptico" geram o mesmo termo — o que interessa é a vizinhança
    dos termos de conteúdo.
    """
    tokens = tokenizar(texto)
    bigramas = [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    return tokens + bigramas


def normalizar_tema(tema: str) -> str:
    """Tema é vocabulário controlado: compara sem acento, caixa ou espaço."""
    return normalizar(tema).replace(" ", "_")

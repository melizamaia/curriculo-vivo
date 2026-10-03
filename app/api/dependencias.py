"""Injeção do estado montado no lifespan (`app.state`) nas rotas."""

from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.core.retriever import Retriever
from app.core.servico import ServicoAnalise
from app.repositories.auditoria import RepositorioAuditoria
from app.repositories.catalogo import RepositorioCatalogo


def get_settings_app(request: Request) -> Settings:
    return request.app.state.settings


def get_retriever(request: Request) -> Retriever:
    return request.app.state.retriever


def get_catalogo(request: Request) -> RepositorioCatalogo:
    return request.app.state.catalogo


def get_servico(request: Request) -> ServicoAnalise:
    return request.app.state.servico


def get_auditoria(request: Request) -> RepositorioAuditoria:
    return request.app.state.auditoria

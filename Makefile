# Currículo Vivo — atalhos de desenvolvimento.
# Tudo roda dentro do .venv (PEP 668: o Python do Debian é "externally managed").

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
PORTA  ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install run front test eval demo worker evento up down logs limpar

help: ## Lista os alvos
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

$(BIN)/activate: requirements.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.txt
	@touch $@

install: $(BIN)/activate ## Cria o .venv e instala as dependências
	@test -f .env || cp .env.example .env

run: install ## Sobe a API em localhost:8000 (sem Mongo, Kafka ou chave de LLM)
	$(BIN)/uvicorn app.main:app --reload --port $(PORTA)

web/node_modules: web/package-lock.json
	@command -v npm >/dev/null || { echo "npm não encontrado: instale o Node 24 (ex.: nvm install 24)"; exit 1; }
	cd web && npm ci
	@touch $@

front: web/node_modules ## Sobe o front em localhost:5173 (precisa da API no ar: make run)
	cd web && npm run dev

test: install ## Roda a suíte de testes
	$(BIN)/pytest -q

eval: install ## Roda o harness de avaliação e gera dashboard/index.html
	$(BIN)/python -m eval.run_eval

demo: install ## Roteiro da apresentação (em processo; URL=... para API no ar)
	$(BIN)/python -m scripts.demo $(if $(URL),--url $(URL))

worker: install ## Sobe o worker de ingestão contra o Kafka do host
	$(BIN)/python -m app.workers.ingestor

evento: install ## Publica uma evidência de exemplo em evidencia.nova e espera o worker
	$(BIN)/python -m scripts.publicar_evidencia

up: ## Stack completa: api + worker + mongo + kafka
	docker compose up --build -d
	@echo "API em http://localhost:8000/docs — 'make logs' para acompanhar"

down: ## Derruba a stack (mantém o volume do Mongo)
	docker compose down

logs: ## Log da api e do worker
	docker compose logs -f api worker

limpar: ## Remove .venv, caches e artefatos gerados
	rm -rf $(VENV) .pytest_cache eval/results.json dashboard/index.html
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

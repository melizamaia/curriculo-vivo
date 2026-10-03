# Currículo Vivo — atalhos de desenvolvimento.
# Tudo roda dentro do .venv (PEP 668: o Python do Debian é "externally managed").

PYTHON ?= python3
VENV   := .venv
BIN    := $(VENV)/bin
PORTA  ?= 8000
PORTA_BFF ?= 3001
# Porta do front é fixa no web/package.json (next dev -p 5173).
PORTA_WEB := 5173
# $(MAKE) indireto: linhas com $(MAKE) literal rodam até sob `make -n`.
SUBMAKE := $(MAKE) --no-print-directory

.DEFAULT_GOAL := help
.PHONY: help install run front bff stack parar test eval demo worker evento up down logs limpar

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

front: web/node_modules ## Sobe o front em localhost:5173 (VITE_BFF_URL=... para passar pelo BFF)
	cd web && npm run dev

bff/node_modules: bff/package-lock.json
	@command -v npm >/dev/null || { echo "npm não encontrado: instale o Node 24 (ex.: nvm install 24)"; exit 1; }
	cd bff && npm ci
	@touch $@

bff: bff/node_modules ## Sobe o BFF NestJS em localhost:3001 (opcional; precisa da API no ar)
	cd bff && PORT=$(PORTA_BFF) npm start

# Processos em background num shell não interativo ignoram SIGINT: o trap mata
# os três e chama `parar` para pegar netos (reloader do uvicorn, next dev).
stack: install web/node_modules bff/node_modules ## Sobe API + BFF + front juntos (Ctrl+C derruba tudo)
	@trap 'echo; echo "Derrubando a stack..."; kill $$PIDS 2>/dev/null; $(SUBMAKE) parar; exit 0' INT TERM; \
	$(BIN)/uvicorn app.main:app --reload --port $(PORTA) & PIDS="$$!"; \
	(cd bff && PORT=$(PORTA_BFF) FASTAPI_URL=http://localhost:$(PORTA) npm start) & PIDS="$$PIDS $$!"; \
	(cd web && VITE_BFF_URL=http://localhost:$(PORTA_BFF) npm run dev) & PIDS="$$PIDS $$!"; \
	sleep 2; \
	echo; \
	echo "  API    http://localhost:$(PORTA)/docs"; \
	echo "  BFF    http://localhost:$(PORTA_BFF)/api/radar"; \
	echo "  Front  http://localhost:$(PORTA_WEB)"; \
	echo "  Ctrl+C para derrubar tudo"; \
	echo; \
	wait

parar: ## Mata o que estiver escutando nas portas da API, do BFF e do front
	@for p in $(PORTA) $(PORTA_BFF) $(PORTA_WEB); do \
		pids=$$(ss -ltnpH "sport = :$$p" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | xargs); \
		if [ -n "$$pids" ]; then echo "porta $$p: kill $$pids"; kill $$pids 2>/dev/null; fi; \
	done; \
	sleep 1; \
	for p in $(PORTA) $(PORTA_BFF) $(PORTA_WEB); do \
		pids=$$(ss -ltnpH "sport = :$$p" | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | xargs); \
		if [ -n "$$pids" ]; then echo "porta $$p: kill -9 $$pids"; kill -9 $$pids 2>/dev/null; fi; \
	done

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

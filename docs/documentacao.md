# Documentação do Currículo Vivo

Guia de operação: o que sobe, em que porta, como acessar cada peça e onde os
dados ficam. O porquê das decisões está em [system-design.md](system-design.md)
e no [README](../README.md); o contrato completo está no [PRD](../PRD.md).

> ⚠️ Todo o corpus é sintético (`exemplo_ilustrativo: true`). Nada aqui é
> referência clínica ou pedagógica.

## Sumário

1. [Visão geral](#visão-geral)
2. [Modos de execução](#modos-de-execução)
3. [Endereços e portas](#endereços-e-portas)
4. [API](#api)
5. [MongoDB](#mongodb)
6. [Kafka](#kafka)
7. [Front e BFF](#front-e-bff)
8. [Configuração](#configuração)
9. [Problemas comuns](#problemas-comuns)

## Visão geral

| Peça | Onde | O que faz |
| --- | --- | --- |
| API FastAPI | `app/` | análise de defasagem, radar, catálogo, métricas, auditoria |
| Worker de ingestão | `app/workers/ingestor.py` | consome `evidencia.nova`, valida, indexa, grava no Mongo |
| MongoDB | `docker-compose.yml` | trilha de auditoria e evidências ingeridas |
| Kafka (KRaft) | `docker-compose.yml` | eventos de evidência |
| Front Next.js | `web/` | o radar do coordenador |
| BFF NestJS | `bff/` | opcional; repassa o radar da API |
| Eval | `eval/` | 43 casos rotulados + painel HTML |

![Arquitetura do Currículo Vivo](curriculo-vivo.drawio.png)

Diagrama editável em [`arquitetura.drawio`](arquitetura.drawio), com duas páginas:
a arquitetura e o caminho de uma análise pelas quatro barreiras. Abra em
[app.diagrams.net](https://app.diagrams.net) ou na extensão Draw.io do VS Code.

Mongo e Kafka são opcionais. Sem eles a API sobe em memória e registra no log
em que modo entrou (decisão 8 do README).

## Modos de execução

### Só a API, sem infraestrutura

```bash
make install
make run          # http://localhost:8000/docs
```

Auditoria e evidências ingeridas ficam em memória e somem no restart. É o
modo da demo e dos testes.

### API local apontando para um Mongo

Para ter a trilha de auditoria persistida sem subir a stack inteira, basta um
Mongo escutando em `localhost:27017` (o padrão do `.env.example`):

```bash
docker run -d --name curriculo-mongo -p 27017:27017 mongo:7
make run
```

### Stack completa (Docker)

```bash
make up           # docker compose up --build -d: api + worker + mongo + kafka
make logs         # log da api e do worker
make evento       # publica uma evidência de exemplo e espera o worker
make down         # derruba; o volume mongo-dados é mantido
```

Para apagar também os dados do Mongo: `docker compose down -v`.

### Kubernetes

Manifestos em `k8s/`, para revisão (nunca aplicados a um cluster). Detalhes na
seção [Kubernetes](../README.md#kubernetes) do README.

## Endereços e portas

| Serviço | Endereço do host | Endereço dentro da rede do compose |
| --- | --- | --- |
| API | <http://localhost:8000> | `api:8000` |
| Swagger (OpenAPI) | <http://localhost:8000/docs> | |
| Painel do eval | <http://localhost:8000/painel> (depois de `make eval`) | |
| MongoDB | `mongodb://localhost:27017` | `mongodb://mongo:27017` |
| Kafka | `localhost:9092` | `kafka:29092` |
| BFF | <http://localhost:3001/api/radar> | |
| Front | <http://localhost:5173> | |

O Mongo do compose **não tem autenticação**: é ambiente de desenvolvimento.
Não exponha a porta 27017 fora da máquina.

## API

Documentação interativa em `/docs` (Swagger) e `/redoc`. Rotas:

| Método | Rota | Para quê |
| --- | --- | --- |
| `POST` | `/v1/analises` | analisa um objeto (`objeto_id` do catálogo ou `objeto` completo) |
| `GET` | `/v1/defasagens` | o radar: todos os objetos, ordenados por severidade |
| `GET` | `/v1/objetos` | catálogo (filtros `curso`, `disciplina`) |
| `POST` | `/v1/objetos` | insere ou substitui um objeto (só em memória) |
| `GET` | `/v1/evidencias` | evidências indexadas |
| `POST` | `/v1/evidencias` | indexa uma evidência (só na memória deste processo; não grava no Mongo) |
| `GET` | `/v1/metricas` | contagens e latência (`incluir_radar=true` soma as varreduras) |
| `GET` | `/v1/auditoria` | trilha de auditoria, mais recente primeiro (`limite` até 1000) |
| `GET` | `/health` | liveness |
| `GET` | `/health/ready` | readiness: 503 se o índice estiver vazio |
| `GET` | `/painel` | painel do eval |

Não há autenticação (fora do escopo do MVP).

```bash
# em que modo a API subiu: "auditoria": "mongo" ou "memoria"
curl -s localhost:8000/health/ready | jq .detalhes

# análise de um objeto defasado
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-clin-sepse-aula07"}' | jq

# últimos 5 registros de auditoria
curl -s 'localhost:8000/v1/auditoria?limite=5' | jq
```

## MongoDB

### Banco e coleções

Banco: `curriculo_vivo` (variável `MONGO_DB`). Duas coleções:

**`auditoria`**: um documento por análise, inclusive as do radar. O material
didático entra só como hash (decisão 7 do README).

| Campo | Tipo | Observação |
| --- | --- | --- |
| `request_id` | string | índice único |
| `criado_em` | Date (UTC) | |
| `origem` | string | `analise` (avulsa) ou `radar` (varredura) |
| `objeto_id`, `objeto_hash` | string | |
| `curso`, `disciplina` | string \| null | |
| `status` | string | `defasagem_detectada`, `sem_achado` ou `abstido` |
| `motivo_abstencao` | string \| null | preenchido quando `status = abstido` |
| `severidade_maxima` | string \| null | |
| `confianca` | double | |
| `evidencias_citadas`, `trechos_citados` | array de string | |
| `scores` | array de double | |
| `modo_sintese` | string | `extrativa` ou `abstrativa` |
| `latencia_ms` | double | |
| `versao_indice` | string | hash do índice usado na análise |

Índices, criados pela API no boot: `request_id` (único), `criado_em` (desc) e
`{origem, criado_em}`.

**`evidencias`**: evidências recebidas pelo worker via `evidencia.nova`. A
base curada (`data/evidencias/base_curada.json`) **não** é copiada para cá:
ela vai dentro da imagem e a API junta as duas fontes no boot.

| Campo | Tipo | Observação |
| --- | --- | --- |
| `_id` | string | o `doc_id`; o último conteúdo vence |
| `evidencia` | objeto | a evidência completa (fonte, URL, data, trechos…) |
| `hash` | string | SHA-256 do conteúdo canônico, usado na idempotência |
| `indexado_em` | Date (UTC) | |

A coleção `evidencias` só passa a existir depois da primeira ingestão
(`make evento`).

### Acessar pelo mongosh dentro do container

O jeito mais direto, sem instalar nada no host:

```bash
docker compose exec mongo mongosh curriculo_vivo
```

### Acessar pelo host

Com o [mongosh](https://www.mongodb.com/docs/mongodb-shell/install/)
instalado:

```bash
mongosh "mongodb://localhost:27017/curriculo_vivo"
```

No [MongoDB Compass](https://www.mongodb.com/products/tools/compass), use a
connection string `mongodb://localhost:27017` e abra o banco
`curriculo_vivo`. No WSL 2, o Compass instalado no Windows alcança o
`localhost:27017` do Docker Desktop normalmente.

### Acessar pelo Python

O `pymongo` já está no `.venv`:

```bash
.venv/bin/python - <<'EOF'
from pymongo import MongoClient

db = MongoClient("mongodb://localhost:27017")["curriculo_vivo"]
print(db.list_collection_names())
for r in db.auditoria.find({}, {"_id": 0, "objeto_id": 1, "status": 1}).sort("criado_em", -1).limit(5):
    print(r)
EOF
```

### Consultas úteis (mongosh)

```js
// quantas análises por status (só as avulsas, como em /v1/metricas)
db.auditoria.aggregate([
  { $match: { origem: "analise" } },
  { $group: { _id: "$status", n: { $sum: 1 } } }
])

// as 10 análises mais recentes
db.auditoria.find({}, { _id: 0, criado_em: 1, objeto_id: 1, status: 1, severidade_maxima: 1 })
  .sort({ criado_em: -1 }).limit(10)

// abstenções e o motivo
db.auditoria.aggregate([
  { $match: { status: "abstido" } },
  { $group: { _id: "$motivo_abstencao", n: { $sum: 1 } } }
])

// histórico de um objeto
db.auditoria.find({ objeto_id: "med-clin-sepse-aula07" }).sort({ criado_em: -1 })

// pods com índice divergente: mais de uma versao_indice na última hora
db.auditoria.distinct("versao_indice", { criado_em: { $gte: new Date(Date.now() - 3600e3) } })

// evidências ingeridas pelo worker
db.evidencias.find({}, { "evidencia.titulo": 1, "evidencia.publicado_em": 1, indexado_em: 1 })
```

### Limpar os dados

```bash
docker compose exec mongo mongosh curriculo_vivo --eval 'db.auditoria.deleteMany({})'
docker compose down -v      # apaga o volume inteiro
```

Apagar `evidencias` faz a API, no próximo boot, voltar a conhecer só a base
curada. O worker, ao reiniciar, também esquece os hashes e reindexa uma
evidência reenviada.

### Em Kubernetes

O Mongo fica fora dos manifestos: o `MONGO_URI` vem do Secret
`curriculo-vivo-secret` (em `k8s/secret.yaml` há só um placeholder com
usuário e senha). Para inspecionar a partir da máquina local, com um Mongo
rodando no cluster como Service `mongo`:

```bash
kubectl port-forward svc/mongo 27017:27017
mongosh "mongodb://USUARIO:SENHA@localhost:27017/curriculo_vivo?authSource=admin"
```

## Kafka

Tópicos, criados pelo serviço `kafka-topicos` do compose (3 partições cada;
autocriação desligada de propósito):

| Tópico | Quem publica | Conteúdo |
| --- | --- | --- |
| `evidencia.nova` | `make evento` ou outro produtor | evidência a ingerir |
| `evidencia.indexada` | worker | `doc_id`, `versao_indice`, `practice_changing`, `trechos_indexados` |
| `evidencia.rejeitada` | worker | a mensagem reprovada e o motivo |
| `defasagem.detectada` | ninguém, por enquanto | contrato em `app/models.py` |

```bash
# listar tópicos
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka:29092 --list

# acompanhar o que o worker publica
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:29092 --topic evidencia.indexada --from-beginning

# atraso do consumer group do worker
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:29092 --describe --group ingestor-curriculo
```

Evidência ingerida só vale na API depois de `docker compose restart api`
(veja [Limitações](../README.md#limitações-conhecidas)).

## Front e BFF

```bash
make front                                       # front em :5173, direto na API
make bff                                         # BFF em :3001 (opcional)
VITE_BFF_URL=http://localhost:3001 make front    # front passando pelo BFF
make stack                                       # API + BFF + front juntos
make parar                                       # libera as portas 8000, 3001 e 5173
```

A tela mostra se o radar veio `via BFF` ou `via FastAPI`. Se o BFF cair, o
front volta sozinho para a API.

## Configuração

Todas as variáveis estão em [`.env.example`](../.env.example) e nenhuma é
obrigatória. As que mais importam para o acesso:

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | sem resposta em 1,5 s, a API sobe em memória |
| `MONGO_DB` | `curriculo_vivo` | nome do banco |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | broker do worker e do `make evento` |
| `ANTHROPIC_API_KEY` | vazio | vazio = justificativa extrativa, sem rede |
| `CORS_ORIGINS` | `http://localhost:5173` | lida só do ambiente, não do `.env` |

No compose, `MONGO_URI` e `KAFKA_BOOTSTRAP_SERVERS` são sobrescritos para os
nomes internos (`mongo:27017`, `kafka:29092`).

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `/health/ready` mostra `"auditoria": "memoria"` | Mongo não respondeu no boot | suba o Mongo e reinicie a API |
| `/health/ready` responde 503 | índice de evidência vazio | confira `CAMINHO_EVIDENCIAS` |
| `docker` não encontrado no WSL | integração do Docker Desktop desligada | Docker Desktop → Settings → Resources → WSL Integration |
| porta 8000, 3001 ou 5173 ocupada | processo de uma execução anterior | `make parar` |
| evidência nova não aparece na análise | a API só carrega evidências no boot | `docker compose restart api` |
| `/painel` responde 404 | painel ainda não gerado | `make eval` |

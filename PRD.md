# PRD: Currículo Vivo

**Radar de defasagem curricular para educação médica: cruza o material didático
com a evidência vigente e aponta, com citação, o que envelheceu, e se cala
quando não tem base para apontar.**

| Campo | Valor |
| --- | --- |
| Versão | 1.0 |
| Data | 2026-10-03 |
| Autora | Meliza Maia |
| Status | Em implementação (MVP) |
| Objetivo | Projeto de portfólio para apresentação a diretoria de healthtech / educação médica |
| Prazo do MVP | 2026-10-03, 11h |

---

## 1. Contexto e problema

Um grupo de educação médica com dezenas de cursos de graduação e pós tem um
ativo que envelhece sozinho: **o conteúdo**. Duas dores que o próprio setor
declara em público:

1. **Volume de literatura.** São milhares de publicações em saúde por dia, e
   apenas uma fração muda a prática clínica. Nenhum coordenador de curso
   acompanha isso para todas as disciplinas de todos os campi.
2. **Confiabilidade de IA.** Modelo de linguagem de uso geral consulta fonte
   aberta sem curadoria. Quando o resultado afeta o que se ensina a um futuro
   médico, a procedência da fonte deixa de ser detalhe e passa a ser requisito.

O resultado prático hoje é silencioso e caro: uma aula de sepse continua citando
protocolo de 2019 porque **ninguém foi avisado** de que saiu atualização em
2024. Isso aparece depois, como questão desatualizada em simulado, como aluno
reclamando, ou como revisão curricular feita às pressas.

### O que o produto faz

Para cada objeto de aprendizagem (plano de aula, aula, questão de simulado,
ementa), o serviço:

1. identifica o tema,
2. busca a evidência vigente sobre o mesmo tema numa base curada,
3. compara a data da referência usada pelo material com a data da evidência,
4. e **emite um alerta de defasagem com citação obrigatória**, ou se abstém.

### Hipótese do produto

> O coordenador de curso não precisa de mais um relatório. Precisa de uma fila
> curta de defasagens em que ele possa confiar. Um falso alarme custa mais do
> que um alerta que não veio: na segunda vez que o radar aponta errado, ele
> para de olhar. Por isso **a abstenção é a feature que torna o resto
> confiável**.

---

## 2. Objetivos

### Objetivos do MVP

| # | Objetivo | Métrica de sucesso |
| --- | --- | --- |
| O1 | Detectar material defasado | Taxa de detecção ≥ 0.85 no conjunto de eval |
| O2 | Não gritar lobo | Taxa de falso alarme ≤ 0.10 |
| O3 | Todo alerta rastreável | 100% dos alertas com citação da evidência mais nova |
| O4 | Zero alerta sem fonte | 0 alertas com marcador sem citação correspondente |
| O5 | Latência previsível | p95 < 500 ms por objeto analisado |
| O6 | Auditabilidade | 100% das análises com registro reconstruível por `versao_indice` |
| O7 | Operabilidade | Sobe sem Mongo, sem Kafka e sem chave de LLM |

### Não-objetivos (escopo explicitamente fora)

- **Não** reescreve a aula. Aponta a defasagem e cita a evidência; a decisão
  pedagógica é do docente e do colegiado.
- **Não** recebe, processa ou armazena dado de aluno ou de paciente.
- **Não** fornece dose ou posologia individualizada, nem emite documento médico.
- **Não** substitui revisão curricular formal nem julgamento clínico.
- **Não** reproduz texto literal de protocolos, diretrizes ou material didático
  real. O corpus do MVP é sintético e marcado como tal.
- **Não** faz autenticação, multi-tenancy ou controle de permissão no MVP.
- **Não** usa marca, identidade visual ou interface de nenhum produto
  existente. É estudo independente.

---

## 3. Usuários e casos de uso

| Persona | Necessidade | Caso de uso |
| --- | --- | --- |
| Coordenador de curso | Fila curta e confiável do que revisar | Abre o radar e vê 7 defasagens altas entre 300 objetos |
| Docente | Saber o que mudou na sua aula | Analisa o próprio plano de aula e recebe a evidência nova citada |
| Time de conteúdo / editorial | Priorizar produção | Ordena por severidade e por quantidade de cursos afetados |
| Diretor de ensino | Evidência de que a IA é governável | Painel com taxa de detecção, falso alarme e alerta sem fonte |
| Compliance | Reconstruir um alerta passado | Trilha de auditoria por `request_id` e `versao_indice` |

---

## 4. Arquitetura

```
┌──────────────────────────────────────────────────────────────────────┐
│                      React / Next.js (front)                         │
│          radar de defasagens · detalhe do objeto · painel            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP
┌───────────────────────────────▼──────────────────────────────────────┐
│                    API Gateway / BFF  ←  NestJS                      │
└───────────────┬──────────────────────────────┬───────────────────────┘
                │                              │
     ┌──────────▼──────────┐        ┌──────────▼──────────────────────┐
     │  NestJS             │        │  FastAPI (escopo deste PRD)     │
     │  (domínio: cursos,  │        │  POST /v1/analises              │
     │   turmas, docentes) │        │  GET  /v1/defasagens  (radar)   │
     └──────────┬──────────┘        │  POST /v1/material /evidencias  │
                │                   │  GET  /v1/metricas /auditoria   │
                │                   └──────────┬──────────────────────┘
                │                              │
┌───────────────▼──────────────────────────────▼───────────────────────┐
│   MongoDB (auditoria, catálogo)  +  Hub de eventos (Kafka)           │
│   evidencia.nova → evidencia.indexada → defasagem.detectada          │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                   ┌────────────▼─────────────┐
                   │ Worker Python de ingestão│
                   │ ETL + validação + índice │
                   └────────────┬─────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│          Kubernetes  ·  GitLab CI/CD  ·  OpenTelemetry               │
└──────────────────────────────────────────────────────────────────────┘
```

### Escopo deste PRD

Tudo em Python: o serviço FastAPI, o worker Kafka, o pipeline de ingestão e o
harness de avaliação. O BFF NestJS e o front são **opcionais** (fase 7), e
entram apenas como prova de contrato.

### Fluxo de detecção

```
objeto de aprendizagem
   │
   ├─ barreira 1: escopo e elegibilidade
   │     objeto sem referência datada → abstém (material_sem_referencia)
   │
   ├─ recupera evidência vigente por tema (TF-IDF + cosseno)
   │
   ├─ barreira 2: confiança e proveniência
   │     similaridade < limiar → abstém (evidencia_insuficiente)
   │     só fonte validada → senão abstém (fonte_nao_validada)
   │
   ├─ compara datas: evidência mais nova que a referência do material?
   │     não → sem_achado (e isso é um bom resultado, não uma falha)
   │
   ├─ classifica severidade (alta / media / baixa)
   │
   ├─ barreira 3: validação do achado
   │     alerta sem citação → descartado
   │     marcador sem fonte → descartado
   │     evidência não mais nova que a referência → descartado
   │
   └─ barreira 4: alertas que acompanham (base ilustrativa, confiança no limiar)
```

### Decisões de arquitetura (ADR resumido)

| # | Decisão | Alternativa descartada | Por quê |
| --- | --- | --- | --- |
| ADR-1 | Recuperação por TF-IDF esparso + cosseno | Embeddings densos / vector DB | Determinismo (requisito de auditoria: o mesmo objeto precisa gerar o mesmo alerta), custo zero por análise, sobe offline, sem download de modelo no boot. `Retriever.buscar` isola a troca futura. |
| ADR-2 | Comparação por data de referência, não por similaridade semântica de conteúdo | Diff semântico material×evidência | A data é verificável e explicável ao coordenador. "Sua aula cita 2019, existe 2024" é auditável; "o texto divergiu 0.72" não é. |
| ADR-3 | Severidade por regra explícita (gap de meses × practice_changing) | Score de modelo | O coordenador precisa entender por que algo é alto. Regra em tabela, versionada, testável. |
| ADR-4 | Síntese extrativa por padrão, LLM opcional | LLM sempre | A demo não pode depender de rede nem de chave. Com LLM, a saída passa pela mesma barreira de validação. |
| ADR-5 | Ingestão assíncrona por evento | Ingestão no request | Download e extração de PDF são caros e variáveis. Fora do caminho da análise, o p95 fica previsível. |
| ADR-6 | Guardrail em 4 barreiras separadas | Validação única no fim | Cada barreira tem motivo de abstenção próprio e testável. A barreira 3 protege contra regressão no gerador de alerta. |
| ADR-7 | Trilha de auditoria com hash do objeto | Texto integral do material | Permite reconstruir a análise sem duplicar conteúdo didático proprietário no log. |
| ADR-8 | Fallbacks em memória para Mongo e Kafka | Falhar no boot | Indisponibilidade de infra degrada observabilidade, não a análise. Em produção o trade-off se inverte (seção 13). |
| ADR-9 | Commit manual de offset no consumidor | Auto-commit | Só confirma o offset após indexar. Com idempotência por hash, resolve o at-least-once do Kafka. |

---

## 5. Contratos de dados

### 5.1 ObjetoAprendizagem (o material didático)

```json
{
  "objeto_id": "med-clin-sepse-aula07",
  "titulo": "Sepse e choque séptico: reconhecimento e manejo inicial",
  "tipo": "plano_de_aula",
  "curso": "Medicina",
  "disciplina": "Clínica Médica",
  "periodo": "7",
  "campus": ["Campus A", "Campus B"],
  "temas": ["sepse", "emergencia"],
  "atualizado_em": "2019-08-01",
  "exemplo_ilustrativo": true,
  "referencias": [
    {
      "titulo": "Protocolo institucional de sepse",
      "fonte": "Ministério da Saúde",
      "ano": 2019,
      "url": "https://..."
    }
  ],
  "trechos": [
    { "trecho_id": "med-clin-sepse-aula07#t1", "texto": "..." }
  ]
}
```

`tipo` ∈ `ementa` | `plano_de_aula` | `aula` | `questao` | `objeto_digital`.

**Elegibilidade:** objeto sem `referencias` com `ano` não pode ser comparado, e
gera abstenção `material_sem_referencia`. Isso é deliberado: inventar um ano
para o material seria exatamente o tipo de alucinação que o produto combate.

### 5.2 Evidencia (a base curada do que está vigente)

```json
{
  "doc_id": "ms-sepse-2024",
  "titulo": "Reconhecimento precoce e manejo inicial da sepse",
  "fonte": "Ministério da Saúde",
  "fonte_tipo": "orgao_oficial",
  "url": "https://www.gov.br/saude/pt-br",
  "publicado_em": "2024-05-20",
  "nivel_evidencia": "A",
  "temas": ["sepse", "emergencia"],
  "practice_changing": true,
  "substitui": ["protocolo de sepse 2019"],
  "exemplo_ilustrativo": true,
  "trechos": [
    { "trecho_id": "ms-sepse-2024#t1", "texto": "..." }
  ]
}
```

`nivel_evidencia` ∈ `A` | `B` | `C` | `D` | `NA`.

#### Política de fonte (decisão de produto, não de implementação)

`fonte_tipo` tem quatro valores, em três níveis de autoridade:

| `fonte_tipo` | Sustenta alerta? | Racional |
| --- | --- | --- |
| `orgao_oficial` | **Sim** | Protocolo ou norma vigente |
| `diretriz_sociedade` | **Sim** | Consenso formal da especialidade |
| `literatura_revisada` | **Não** | Legítima, mas estudo primário isolado é hipótese, não consenso |
| `nao_validada` | **Não** | Sem curadoria editorial |

Com `EXIGIR_FONTE_OFICIAL=true`, apenas os dois primeiros podem sustentar um
alerta; os outros resultam em abstenção por `fonte_nao_validada`.

A linha do `literatura_revisada` é a decisão mais importante desta seção.
**Um artigo revisado por pares não é motivo para dizer a um coordenador que a
aula dele está desatualizada.** Metade dos achados primários não se replica, e o
que muda currículo é diretriz e protocolo, não o último paper. Aceitar
literatura isolada como gatilho construiria exatamente a máquina de gritar lobo
que este produto existe para evitar, e o custo seria pago na confiança do
coordenador, que é o ativo mais caro do sistema.

Evolução natural fora do MVP: literatura revisada **corrobora** uma diretriz
(elevando a confiança de um alerta que já existe) sem nunca **originar** um
alerta sozinha.

### 5.3 Requisição de análise

```json
{ "objeto_id": "med-clin-sepse-aula07" }
```

ou, para análise de material não catalogado:

```json
{ "objeto": { "...": "ObjetoAprendizagem completo" } }
```

### 5.4 Resposta: defasagem encontrada

```json
{
  "request_id": "uuid",
  "status": "defasagem_detectada",
  "objeto_id": "med-clin-sepse-aula07",
  "titulo": "Sepse e choque séptico: reconhecimento e manejo inicial",
  "ano_referencia_material": 2019,
  "severidade_maxima": "alta",
  "defasagens": [
    {
      "tema": "sepse",
      "severidade": "alta",
      "gap_meses": 57,
      "practice_changing": true,
      "justificativa": "O material se apoia em referência de 2019 [0]. Existe evidência de 2024-05-20 classificada como practice-changing sobre o mesmo tema [1].",
      "evidencia": {
        "marcador": 1,
        "doc_id": "ms-sepse-2024",
        "trecho_id": "ms-sepse-2024#t2",
        "titulo": "...",
        "fonte": "Ministério da Saúde",
        "fonte_tipo": "orgao_oficial",
        "url": "https://...",
        "publicado_em": "2024-05-20",
        "nivel_evidencia": "A",
        "trecho": "texto literal que sustenta o alerta",
        "score": 0.4312,
        "exemplo_ilustrativo": true
      }
    }
  ],
  "confianca": 0.4312,
  "motivo_abstencao": null,
  "alertas": ["Base de demonstração: ..."],
  "modo_sintese": "extrativa",
  "latencia_ms": 12.4,
  "aviso": "Apoio à revisão curricular. Não substitui a decisão pedagógica do docente e do colegiado."
}
```

### 5.5 Resposta: sem achado ou abstenção

```json
{
  "request_id": "uuid",
  "status": "sem_achado",
  "objeto_id": "med-clin-hipertensao-aula03",
  "ano_referencia_material": 2024,
  "defasagens": [],
  "confianca": 0.3918,
  "motivo_abstencao": null
}
```

```json
{
  "request_id": "uuid",
  "status": "abstido",
  "objeto_id": "med-eletiva-tema-raro",
  "defasagens": [],
  "confianca": 0.0412,
  "motivo_abstencao": "evidencia_insuficiente"
}
```

`status` ∈ `defasagem_detectada` | `sem_achado` | `abstido`.

`motivo_abstencao` ∈ `evidencia_insuficiente` | `fonte_nao_validada` |
`material_sem_referencia` | `fora_de_escopo` | `objeto_invalido` |
`alerta_descartado`.

Os cinco primeiros são abstenções **sobre o material**: o serviço se absteve
porque não tinha base. O sexto é diferente: `alerta_descartado` significa que
havia base, um alerta foi gerado e ele **não passou na própria validação do
serviço** (barreira 3). Isso é regressão no gerador de justificativa, não
funcionamento normal, e por isso tem valor próprio: conflatá-lo com
`evidencia_insuficiente` faria uma falha de software aparecer como número
saudável no painel. Em operação normal esse motivo nunca deve aparecer; se
aparecer, é alerta de incidente.

**Convenção de marcadores:** `[0]` é sempre a referência do próprio material;
`[1]`, `[2]`, … são as evidências citadas na resposta, atribuídas na ordem em
que são geradas. A justificativa de uma defasagem só pode usar `[0]` e o
marcador da sua própria evidência.

O marcador é **identificador estável, não posição sequencial**: se a barreira 3
descartar a defasagem `[2]`, as que sobram continuam `[1]` e `[3]`, com um
buraco. Isso é deliberado. Renumerar exigiria reescrever o texto da
justificativa, que já contém o literal do marcador, e reescrever texto para
corrigir numeração é fonte de bug. A invariante que importa (todo marcador
citado existe entre as evidências da resposta) continua valendo com buraco.

Dois descartes adicionais da barreira 3, mais rígidos que a leitura literal das
invariantes e igualmente obrigatórios: justificativa que cita **apenas** `[0]`
é descartada, porque citar o próprio material não é citar evidência; e o mesmo
marcador apontando para evidências diferentes é descartado, porque torna a
citação ambígua para quem lê a resposta.

**Invariantes críticas:**

1. `status == "defasagem_detectada"` ⟹ `len(defasagens) >= 1` e **toda**
   defasagem tem `evidencia` preenchida.
2. Todo marcador `[n]` presente em qualquer `justificativa` existe entre as
   evidências citadas da resposta (ou é `[0]`).
3. Para toda defasagem, `evidencia.publicado_em` é posterior à referência do
   material. Um alerta que não satisfaz isso é descartado pela barreira 3.
4. Se **todas** as defasagens de um objeto forem descartadas pela barreira 3, o
   status cai para `abstido` com motivo `alerta_descartado`, nunca para
   `sem_achado`, e nunca com um motivo que descreva o material. Fingir que não
   houve nada esconderia uma regressão no gerador de justificativa.

### 5.6 Radar (`GET /v1/defasagens`)

```json
{
  "gerado_em": "2026-10-03T04:00:00Z",
  "versao_indice": "a1b2c3d4e5f6",
  "total_objetos": 14,
  "objetos_com_defasagem": 6,
  "por_severidade": { "alta": 3, "media": 2, "baixa": 1 },
  "abstencoes": { "evidencia_insuficiente": 2, "material_sem_referencia": 1 },
  "itens": [ "...uma AnaliseResponse resumida por objeto, ordenada por severidade..." ]
}
```

Filtros opcionais: `?curso=`, `?disciplina=`, `?severidade=alta`, `?limite=`.

### 5.7 Registro de auditoria

```json
{
  "request_id": "uuid",
  "criado_em": "2026-10-03T04:00:00Z",
  "origem": "analise",
  "objeto_id": "med-clin-sepse-aula07",
  "objeto_hash": "sha256...",
  "curso": "Medicina",
  "disciplina": "Clínica Médica",
  "status": "defasagem_detectada",
  "motivo_abstencao": null,
  "severidade_maxima": "alta",
  "confianca": 0.4312,
  "evidencias_citadas": ["ms-sepse-2024"],
  "trechos_citados": ["ms-sepse-2024#t2"],
  "scores": [0.4312],
  "modo_sintese": "extrativa",
  "latencia_ms": 12.4,
  "versao_indice": "a1b2c3d4e5f6"
}
```

`versao_indice` é o hash do conteúdo indexado. É o que permite provar, meses
depois, contra qual versão da base de evidência um alerta foi emitido.

`origem` ∈ `analise` | `radar`: toda análise é auditada, inclusive cada objeto
de uma varredura do radar (defasagem na fila sem registro não é
reconstruível, O6), e `/v1/metricas` filtra por `origem=analise` por padrão
(`?incluir_radar=true` soma o radar) para o lote não distorcer o p95.

### 5.8 Eventos Kafka

| Tópico | Direção | Payload |
| --- | --- | --- |
| `evidencia.nova` | consumido | objeto `Evidencia` da seção 5.2 |
| `evidencia.indexada` | publicado | `{doc_id, versao_indice, practice_changing, trechos_indexados}` |
| `defasagem.detectada` | publicado | `{objeto_id, curso, disciplina, severidade, doc_id, versao_indice}` |

`defasagem.detectada` é o gancho para notificação: é por aí que o coordenador
recebe o aviso sem precisar abrir o radar.

---

## 6. Regras de detecção e severidade

### Comparação

A análise é **por tema**, e cada tema gera no máximo uma defasagem. O tema é
vocabulário controlado: filtrar por ele evita comparar uma aula de asma com uma
diretriz de sepse só porque as duas mencionam "oximetria". Dentro do tema, o
score de similaridade decide qual trecho sustenta o alerta.

Para cada tema do objeto, pega-se:

- `ano_material` = maior `ano` entre as `referencias` do objeto (a referência
  mais nova que o material usa; é o critério conservador, que reduz falso
  alarme),
- `evidencia` = **melhor** candidato recuperado acima do limiar e de fonte
  validada.

Se `evidencia.publicado_em <= 31/12/ano_material` → **sem achado** nesse tema.

Agregação do objeto:

| Situação | `status` |
| --- | --- |
| Pelo menos um tema gerou defasagem válida | `defasagem_detectada` |
| Todos os temas passaram pela barreira 2, nenhum gerou defasagem | `sem_achado` |
| Nenhum tema passou pela barreira 2 | `abstido` (motivo do primeiro tema) |
| Houve defasagens, mas todas foram descartadas pela barreira 3 | `abstido` com `alerta_descartado` |

`severidade_maxima` do objeto é a maior entre as defasagens válidas.

### Tabela de severidade

| Condição | Severidade |
| --- | --- |
| `practice_changing = true` **e** `gap_meses >= 24` | `alta` |
| `practice_changing = true` **e** `12 <= gap_meses < 24` | `media` |
| `practice_changing = true` **e** `gap_meses < 12` | `baixa` |
| `practice_changing = false` **e** `gap_meses >= 36` | `media` |
| `practice_changing = false` **e** `12 <= gap_meses < 36` | `baixa` |
| `practice_changing = false` **e** `gap_meses < 12` | sem achado |

`gap_meses` = meses entre a referência do material (31/12 do `ano_material`) e
`evidencia.publicado_em`. A regra é versionada em código e coberta por teste:
mudar severidade é mudança de produto, não de implementação.

### Barreiras de guardrail

**Barreira 1: escopo e elegibilidade (antes de recuperar)**

| Condição | Motivo |
| --- | --- |
| Objeto sem `trechos` ou sem `titulo` | `objeto_invalido` |
| Objeto sem `referencias` com `ano` | `material_sem_referencia` |
| Texto do objeto pede dose/posologia individualizada | `fora_de_escopo` |
| Texto do objeto pede emissão de documento médico | `fora_de_escopo` |
| Texto menciona paciente ou aluno identificado | `fora_de_escopo` |

**Barreira 2: confiança e proveniência (após recuperar)**

- Sem candidato, ou `max(score) < LIMIAR_CONFIANCA` → `evidencia_insuficiente`.
- Nenhum candidato acima do limiar de fonte validada (com
  `EXIGIR_FONTE_OFICIAL=true`) → `fonte_nao_validada`.

**Barreira 3: validação do achado (antes de devolver)**

- Defasagem sem `evidencia` → descartada.
- `justificativa` sem nenhum marcador `[n]` → descartada.
- `justificativa` que cita **apenas** `[0]` → descartada (citar o próprio
  material não é citar evidência).
- Marcador apontando para evidência inexistente → descartada.
- Mesmo marcador apontando para evidências diferentes → descartada (citação
  ambígua).
- `evidencia.publicado_em` não posterior à referência do material → descartada.
- Se **todas** as defasagens forem descartadas, o status cai para `abstido` com
  motivo `alerta_descartado`.

Todo descarte vai para log com `objeto_id`, tema, `doc_id` e motivo. Esse log é
o sinal de incidente: em operação normal ele fica vazio.

Roda independentemente do modo de síntese. É a proteção contra regressão quando
o gerador de justificativa é um LLM.

**Barreira 4: alertas que acompanham (não bloqueiam)**

- Evidência com `exemplo_ilustrativo: true` → alerta de base de demonstração.
- `max(score) < LIMIAR_CONFIANCA * 1.5` → alerta de confiança no limiar.
- Objeto com `atualizado_em` muito antigo → alerta de revisão geral pendente.

---

## 7. Endpoints

| Método | Rota | Finalidade |
| --- | --- | --- |
| POST | `/v1/analises` | Analisa um objeto (por `objeto_id` ou payload completo) |
| GET | `/v1/defasagens` | Radar: varre o catálogo, ordena por severidade |
| GET | `/v1/objetos` | Lista objetos do catálogo |
| POST | `/v1/objetos` | Ingestão síncrona de objeto de aprendizagem |
| GET | `/v1/evidencias` | Lista evidências indexadas |
| POST | `/v1/evidencias` | Ingestão síncrona (equivale ao evento `evidencia.nova`) |
| GET | `/v1/metricas` | Total, taxa de abstenção, latência média e p95, versão do índice |
| GET | `/v1/auditoria?limite=50` | Trilha de auditoria |
| GET | `/health` | Liveness |
| GET | `/health/ready` | Readiness: `degraded` se o índice de evidência não carregou |
| GET | `/painel` | Painel de avaliação gerado pelo harness |
| GET | `/docs` | Swagger / OpenAPI |

**Regra de readiness:** sem índice de evidência carregado, o serviço só sabe se
abster. O Kubernetes não deve mandar tráfego para ele. `/health/ready` retorna
`degraded`.

---

## 8. Harness de avaliação (o diferencial da apresentação)

Sem isso o projeto é "fiz um RAG". Com isso é "trato IA como sistema de produção
mensurável", e o número que o diretor olha é a taxa de falso alarme.

### Dataset

`eval/dataset.json`, mínimo 30 casos, quatro classes:

| Classe | Mínimo | Comportamento esperado |
| --- | --- | --- |
| `defasado` | 12 | `defasagem_detectada`, com `evidencia_esperada` citada e `severidade_esperada` |
| `atualizado` | 10 | `sem_achado`: **o teste de falso alarme** |
| `sem_evidencia` | 5 | `abstido` com `evidencia_insuficiente` ou `fonte_nao_validada` |
| `inelegivel` | 4 | `abstido` com `material_sem_referencia`, `fora_de_escopo` ou `objeto_invalido` |

Cada caso:

```json
{
  "id": "c001",
  "objeto_id": "med-clin-sepse-aula07",
  "classe": "defasado",
  "evidencia_esperada": "ms-sepse-2024",
  "severidade_esperada": "alta",
  "motivo_esperado": null
}
```

### Métricas calculadas

| Métrica | Definição | Meta |
| --- | --- | --- |
| `taxa_deteccao` | defasados corretamente apontados | ≥ 0.85 |
| `taxa_falso_alarme` | atualizados apontados indevidamente | ≤ 0.10 |
| `taxa_citacao_correta` | defasados cuja `evidencia_esperada` foi citada | ≥ 0.85 |
| `taxa_severidade_correta` | defasados com a severidade esperada | ≥ 0.80 |
| `taxa_abstencao_adequada` | inelegíveis e sem evidência corretamente abstidos | ≥ 0.95 |
| `taxa_motivo_correto` | abstenções com o motivo esperado | ≥ 0.90 |
| `alerta_sem_citacao` | defasagens sem evidência ou com marcador órfão | = 0 (**dura**) |
| `invariante_violada` | violação de qualquer invariante da seção 5.5 | = 0 (**dura**) |
| `latencia_p50` / `p95` | latência por análise | p95 < 500 ms |
| `custo_estimado_usd` | tokens × `CUSTO_POR_1K_TOKENS` | 0 no modo extrativo |

### Saídas

1. `eval/results.json`: resultado por caso e agregados.
2. `dashboard/index.html`: painel **autocontido**, dados embutidos, abre com
   duplo clique e também é servido em `/painel`.
3. Código de saída diferente de zero quando uma meta dura é violada, para
   travar o pipeline de CI.

---

## 9. Variáveis de ambiente

| Variável | Padrão | Efeito |
| --- | --- | --- |
| `LIMIAR_CONFIANCA` | `0.18` | Abaixo disso, abstém |
| `TOP_K` | `3` | Evidências consideradas por tema |
| `EXIGIR_FONTE_OFICIAL` | `true` | Só fonte validada sustenta alerta |
| `GAP_MESES_ALTA` | `24` | Limite de severidade alta (com practice-changing) |
| `GAP_MESES_MEDIA` | `12` | Limite de severidade média (com practice-changing) |
| `GAP_MESES_MINIMO_SEM_PC` | `12` | Gap mínimo para alertar sem practice-changing |
| `GAP_MESES_MEDIA_SEM_PC` | `36` | Acima disso, severidade média sem practice-changing |
| `ALERTA_REVISAO_OBJETO_DIAS` | `1095` | Idade de `atualizado_em` que dispara alerta de revisão |
| `KAFKA_CONSUMER_GROUP` | `ingestor-curriculo` | Consumer group do worker |
| `MONGO_URI` / `MONGO_DB` | localhost | Auditoria; cai para memória se falhar |
| `KAFKA_BOOTSTRAP_SERVERS` | localhost:9092 | Broker do worker |
| `KAFKA_TOPIC_EVIDENCIA_NOVA` | `evidencia.nova` | Tópico de entrada |
| `KAFKA_TOPIC_EVIDENCIA_INDEXADA` | `evidencia.indexada` | Tópico de saída |
| `KAFKA_TOPIC_DEFASAGEM` | `defasagem.detectada` | Tópico de notificação |
| `ANTHROPIC_API_KEY` | vazio | Vazio = justificativa extrativa |
| `LLM_MODEL` | `claude-opus-5` | Modelo da síntese abstrativa |
| `CUSTO_POR_1K_TOKENS` | `0.015` | Base do custo no painel |

Nenhuma é obrigatória. O serviço sobe com todos os fallbacks e registra no log
em que modo entrou.

---

## 10. Estrutura de arquivos

```
curriculo-vivo/
├── PRD.md
├── README.md                      # arquitetura, trade-offs, como rodar
├── requirements.txt
├── .env.example
├── Makefile                       # make install / run / test / eval / demo
├── docker-compose.yml             # api + worker + mongo + kafka
├── Dockerfile
├── app/
│   ├── config.py                  # Settings (pydantic-settings)
│   ├── models.py                  # contratos da seção 5
│   ├── main.py                    # FastAPI + lifespan
│   ├── api/
│   │   ├── dependencias.py
│   │   ├── routes_analise.py      # /v1/analises, /v1/defasagens
│   │   ├── routes_catalogo.py     # /v1/objetos, /v1/evidencias
│   │   └── routes_ops.py          # health, metricas, auditoria, painel
│   ├── core/
│   │   ├── texto.py               # normalização PT-BR
│   │   ├── retriever.py           # TF-IDF + cosseno + versão do índice
│   │   ├── guardrail.py           # as 4 barreiras
│   │   ├── detector.py            # comparação de datas + severidade
│   │   ├── justificativa.py       # síntese extrativa / LLM
│   │   ├── audit.py               # hash, registro, percentil
│   │   └── servico.py             # caso de uso (orquestração)
│   ├── repositories/
│   │   ├── auditoria.py           # Mongo + fallback memória
│   │   └── catalogo.py            # objetos de aprendizagem
│   └── workers/
│       └── ingestor.py            # consumidor Kafka idempotente
├── scripts/
│   └── gerar_corpus_material.py   # gera o corpus SINTÉTICO de material
├── data/
│   ├── material/catalogo.json     # 31 objetos de aprendizagem (gerados)
│   └── evidencias/base_curada.json # 13 evidências (sintéticas)
├── eval/
│   ├── dataset.json
│   ├── painel_template.html
│   └── run_eval.py
├── dashboard/index.html           # gerado
└── tests/
```

---

## 11. Fases de execução

Ordem desenhada para que **o projeto seja apresentável ao fim de qualquer
fase**. Se o tempo acabar na fase 4, o que existe já se defende.

### Fase 1: Scaffold (30 min)
- [ ] Estrutura de pastas, `requirements.txt`, `.env.example`, `.gitignore`
- [ ] `app/config.py` com `Settings` e `get_settings()` cacheado
- [ ] `app/models.py` com todos os contratos da seção 5
- **Aceite:** `python -c "from app.config import get_settings; print(get_settings())"`

### Fase 2: Corpus (40 min)
- [ ] 13 evidências em `data/evidencias/base_curada.json`, cobrindo 17 temas,
      com datas variadas e 4 `practice_changing`
- [ ] 1 evidência `fonte_tipo: nao_validada` (tema `rinite`), para exercitar o
      filtro de proveniência
- [ ] `scripts/gerar_corpus_material.py` gerando 31 objetos em
      `data/material/catalogo.json`: 12 defasados (4 de cada severidade),
      10 atualizados, 5 sem evidência na base, 4 inelegíveis
- [ ] Tudo marcado `exemplo_ilustrativo: true`; o gerador existe por honestidade:
      documenta que o material é sintético
- **Aceite:** `python scripts/gerar_corpus_material.py` roda e todos os itens
  validam contra `Evidencia` e `ObjetoAprendizagem`

Os anos de referência de cada objeto foram escolhidos a partir da tabela de
severidade, para que o conjunto de eval cubra as três severidades e os casos de
fronteira (gap exatamente em 12 e em 24 meses).

### Fase 3: Núcleo (100 min), **não corte nada aqui**
- [ ] `core/texto.py`: normalização sem acento, stopwords PT, uni + bigramas
- [ ] `core/retriever.py`: carga, índice, `buscar`, `upsert`, `versao_indice`
- [ ] `core/detector.py`: `ano_material`, `gap_meses`, tabela de severidade
- [ ] `core/guardrail.py`: as 4 barreiras da seção 6
- [ ] `core/justificativa.py`: extrativa + LLM opcional, marcadores obrigatórios
- [ ] `core/audit.py`: hash, montagem do registro, percentil
- [ ] `core/servico.py`: orquestração + varredura do catálogo (radar)
- **Aceite:** em REPL, um objeto defasado gera alerta com citação; um objeto
  atualizado gera `sem_achado`; um sem referência gera `abstido`

### Fase 4: API (50 min)
- [ ] `main.py` com lifespan montando índice, catálogo, guardrail e repositório
- [ ] Rotas da seção 7
- [ ] `repositories/` com Mongo e fallback em memória
- **Aceite:** `uvicorn app.main:app` sobe sem Mongo; `/docs` abre;
  `POST /v1/analises` e `GET /v1/defasagens` respondem

### Fase 5: Eval e painel (70 min), **o que ganha a conversa**
- [ ] `eval/dataset.json` com 30+ casos nas quatro classes
- [ ] `eval/run_eval.py` com as métricas da seção 8 e exit code em falha dura
- [ ] `eval/painel_template.html` e geração de `dashboard/index.html`
- **Aceite:** `python -m eval.run_eval` imprime o resumo, grava os dois arquivos
  e retorna 0

### Fase 6: Mensageria, testes e Docker (60 min)
- [ ] `workers/ingestor.py`: classe `Ingestor` testável + loop Kafka
- [ ] Idempotência por hash e commit manual de offset
- [ ] `tests/`: detector (tabela de severidade), guardrail, retriever, ingestor,
      API, invariantes da seção 5.5
- [ ] `docker-compose.yml`, `Dockerfile`, `Makefile`
- **Aceite:** `pytest` verde; `docker compose up` sobe a stack

### Fase 7: Opcional, só se sobrar tempo
- [ ] BFF NestJS mínimo agregando `/v1/defasagens`
- [ ] Front Next.js de uma página com o radar
- [ ] OpenTelemetry com trace atravessando BFF → Kafka → FastAPI

**Se o tempo apertar, corte na ordem inversa: 7, 6, 5.** O núcleo (3) e a
API (4) são o projeto.

---

## 12. Critérios de aceite do MVP

Checklist de demonstração. Todos precisam passar antes da apresentação:

- [ ] `uvicorn app.main:app` sobe **sem** Mongo, **sem** Kafka e **sem** chave de LLM
- [ ] Objeto defasado → `defasagem_detectada`, com evidência citada contendo
      fonte, URL, data e nível de evidência, e severidade coerente com a tabela
- [ ] Objeto atualizado → `sem_achado` (sem falso alarme)
- [ ] Objeto sem referência datada → `abstido` com `material_sem_referencia`
- [ ] Objeto com tema fora da base → `abstido` com `evidencia_insuficiente`
- [ ] Objeto cujo melhor match é fonte não validada → `abstido` com
      `fonte_nao_validada`
- [ ] Nenhuma defasagem sem evidência (invariante 1 testada)
- [ ] Nenhum marcador `[n]` sem citação correspondente (invariante 2 testada)
- [ ] Nenhuma defasagem com evidência mais antiga que a referência (invariante 3)
- [ ] `GET /v1/defasagens` ordena por severidade e agrega por curso e disciplina
- [ ] `/v1/auditoria` grava o objeto apenas como hash
- [ ] `/v1/metricas` traz p95 e versão do índice
- [ ] `/health/ready` retorna `degraded` com índice vazio
- [ ] `python -m eval.run_eval` gera painel com `alerta_sem_citacao = 0`
- [ ] `pytest` verde
- [ ] README com diagrama, trade-offs e instruções de execução

---

## 13. Riscos e mitigações

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Falso alarme destrói a confiança do coordenador | **Alto** | Abstenção é o padrão; limiar por env; critério conservador (referência mais nova do material); eval mede falso alarme como métrica de primeira classe |
| Demo falhar por falta de rede ou chave | Alto | Justificativa extrativa é o padrão; nada externo no caminho crítico |
| Mongo ou Kafka fora do ar na apresentação | Alto | Fallback em memória; `docker compose` é opcional |
| Limiar mal calibrado | Médio | `LIMIAR_CONFIANCA` por env; o harness mede o efeito de cada valor |
| Conteúdo percebido como protocolo ou material real | Alto | Corpus sintético, flag `exemplo_ilustrativo` propagada até a resposta, alerta explícito, aviso em todo payload |
| Percepção de uso de dado sensível | Alto | Zero dado de aluno ou paciente; objeto só como hash na auditoria; dito em voz alta na apresentação |
| Parecer imitação de produto existente | Médio | Nome, marca e interface próprios; apresentado como estudo independente |
| Severidade questionada pelo colegiado | Médio | Regra explícita em tabela versionada e testada, não score opaco |

---

## 14. O que dizer na apresentação

### Abertura (30 s)
> "O conteúdo de vocês envelhece sozinho. Saiu atualização de protocolo em 2024
> e a aula continua citando 2019 porque ninguém foi avisado. Eu construí o
> serviço que avisa, e que se cala quando não tem base para avisar."

### Demo (3 min)
1. `GET /v1/defasagens` → o radar. "31 objetos, 4 defasagens altas. Esta é a
   fila do coordenador na segunda-feira, ordenada por severidade."
2. `med-clin-sepse-aula07` → defasagem alta. Mostrar **a citação com fonte,
   data e nível de evidência**, e a justificativa com os marcadores `[0]` e
   `[1]`: a referência do material e a evidência que a supera.
3. `med-card-hipertensao-aula03` → `sem_achado`. "Não inventei trabalho."
4. `med-sem-referencia-aula01` → `abstido` com `material_sem_referencia`.
   **Pausar aqui.** "Eu poderia ter chutado um ano. Preferi me calar. É o que
   protege a confiança no resto da fila."
5. `med-orl-rinite-aula05` → `abstido` com `fonte_nao_validada`. "Existe texto
   sobre o tema, mas de blog sem revisão. Não sustento alerta nisso."
6. `/v1/auditoria` → "o material nunca é gravado em texto claro, só o hash."
7. `/painel` → taxa de detecção, **falso alarme**, alerta sem citação em zero.

### Fechamento (30 s)
> "A arquitetura é a mesma do time: FastAPI ao lado de NestJS, eventos em Kafka,
> Mongo, Kubernetes. O que eu entrego é o lado Python. E o diferente não é o
> RAG: é o harness que mede se ele está gritando lobo."

### Perguntas prováveis

| Pergunta | Resposta curta |
| --- | --- |
| "Isso não é só comparar datas?" | É, e é de propósito. ADR-2: a data é verificável e explicável ao colegiado. Diff semântico dá número que ninguém sabe defender em reunião de curso. |
| "Por que não embeddings?" | ADR-1: determinismo para auditoria, custo zero, sobe offline. A interface isola a troca; o gatilho é quando a detecção cair abaixo da meta por sinonímia de tema. |
| "Como escala para todos os cursos?" | Índice de evidência em memória por pod, reconstruído na ingestão. O radar é varredura em lote, assíncrona. Acima de ~100k trechos, migra para Atlas Vector Search sem tocar no resto. |
| "E se apontar errado?" | É a métrica que eu mais olho. Falso alarme tem meta de 10% e o eval reprova o build se a invariante de citação quebrar. Prefiro abster e perder um achado a entregar uma fila que o coordenador não confia. |
| "Por que artigo revisado por pares não dispara alerta?" | Porque estudo primário isolado é hipótese, não consenso; o que muda currículo é diretriz e protocolo. Se eu aceitasse paper isolado como gatilho, teria construído a máquina de gritar lobo que o produto existe para evitar. O conjunto de eval tem um caso só para isso (c026). |
| "E LGPD?" | Nenhum dado de aluno ou paciente entra. O objeto vira hash na auditoria. A barreira de escopo abstém quando o texto menciona pessoa identificada. |
| "Dá para usar no lado clínico também?" | Sim, e é o ponto: a regra é de proveniência, não de medicina. Troca o corpus, mantém guardrail, auditoria e eval. |

---

## 15. Ambiente de desenvolvimento (Debian no WSL2)

O projeto é desenvolvido em **Debian sobre WSL2**. Quatro detalhes desse
ambiente que custam tempo se descobertos no meio do caminho:

### 15.1 O Debian não traz `venv` nem `pip` por padrão

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dev build-essential
```

O `build-essential` é necessário porque `scikit-learn` e `numpy` podem precisar
compilar algo se não houver wheel para a sua versão de Python.

### 15.2 PEP 668: o Python do sistema é "externally managed"

Instalar pacote direto com `pip install` falha com
`error: externally-managed-environment`. **Use sempre venv**: é o caminho
correto e o que o `Makefile` assume:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Nunca use `--break-system-packages` neste projeto: ele contorna o erro quebrando
o Python do sistema.

### 15.3 Mantenha o repositório no filesystem do Linux

```bash
# certo: rápido
cd ~ && git clone <repo> curriculo-vivo

# errado: lento (I/O atravessa a fronteira Windows/Linux)
cd /mnt/c/Users/<voce>/Documents
```

Em `/mnt/c` o `pytest` e o `pip install` ficam várias vezes mais lentos, e as
permissões de arquivo não se comportam como o esperado. Para abrir no VS Code a
partir do WSL: `code .` dentro do diretório.

### 15.4 Docker

Duas opções:

**Docker Desktop no Windows com integração WSL** (mais simples): em Settings →
Resources → WSL Integration, habilite a distro Debian. O `docker` e o
`docker compose` passam a funcionar no shell do Debian sem mais nada.

**Docker nativo no Debian** (sem Docker Desktop): precisa de systemd no WSL2.

```bash
# /etc/wsl.conf
[boot]
systemd=true
```

Depois, no PowerShell: `wsl --shutdown`, e reabrir o Debian. Então instale o
Docker Engine e o plugin do compose pelo repositório oficial do Docker, e
adicione seu usuário ao grupo:

```bash
sudo usermod -aG docker $USER   # exige reabrir o shell
```

### 15.5 Outros pontos

| Item | Nota |
| --- | --- |
| Portas | `localhost:8000` do WSL2 abre direto no navegador do Windows, sem configuração |
| Fim de linha | `git config core.autocrlf false` e um `.gitattributes` com `* text=auto eol=lf`, para o CRLF do Windows não entrar nos arquivos |
| Relógio | Após suspender o Windows, o clock do WSL pode dessincronizar e quebrar TLS. `sudo hwclock -s` resolve |
| Memória | Se o `pytest` ou o compose travarem a máquina, limite a RAM do WSL em `%UserProfile%\.wslconfig` (`[wsl2]` / `memory=6GB`) |
| `jq` | `sudo apt install -y jq`, usado nos comandos da seção 16 |

---

## 16. Comandos

```bash
# setup (Debian/WSL2, ver seção 15)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# gerar o corpus sintético de material didático
python scripts/gerar_corpus_material.py

# subir a API (sem Mongo, sem Kafka, sem chave de LLM)
uvicorn app.main:app --reload
# http://localhost:8000/docs

# o radar: a fila do coordenador
curl -s localhost:8000/v1/defasagens | jq '{total_objetos, objetos_com_defasagem, por_severidade, abstencoes}'

# só as defasagens de severidade alta
curl -s 'localhost:8000/v1/defasagens?severidade=alta' | jq '.itens[].objeto_id'

# objeto defasado (severidade alta, practice-changing)
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-clin-sepse-aula07"}' | jq

# objeto atualizado: sem falso alarme
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-card-hipertensao-aula03"}' | jq '{status, severidade_maxima}'

# objeto sem referência datada: abstenção por material_sem_referencia
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-sem-referencia-aula01"}' | jq '{status, motivo_abstencao}'

# tema que existe só em fonte não validada: abstenção por fonte_nao_validada
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-orl-rinite-aula05"}' | jq '{status, motivo_abstencao}'

# tema sem evidência na base: abstenção por evidencia_insuficiente
curl -s localhost:8000/v1/analises -H 'content-type: application/json' \
  -d '{"objeto_id":"med-oftalmo-glaucoma-aula01"}' | jq '{status, motivo_abstencao}'

# trilha de auditoria (o material só aparece como hash)
curl -s 'localhost:8000/v1/auditoria?limite=5' | jq

# métricas de operação
curl -s localhost:8000/v1/metricas | jq

# avaliação + painel (gera dashboard/index.html)
python -m eval.run_eval

# testes
pytest -q

# stack completa com Mongo e Kafka
docker compose up --build
python -m app.workers.ingestor
```

---

## 17. Aviso permanente

Este é um projeto de portfólio. O corpus de evidência e o material didático são
**sintéticos e ilustrativos**: os textos não reproduzem protocolos, diretrizes,
bulas ou material didático real e não devem ser usados como referência clínica
ou pedagógica. O serviço é apoio à revisão curricular e não substitui a decisão
pedagógica do docente e do colegiado, nem o julgamento clínico. Nenhum dado de
aluno ou de paciente é recebido, processado ou armazenado.

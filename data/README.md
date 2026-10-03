# Corpus

Dois conjuntos, com papeis diferentes:

| Diretorio | O que e | Origem |
| --- | --- | --- |
| `evidencias/` | A base curada do que esta **vigente**. E contra ela que o material e comparado. | `base_curada.json`, escrito a mao |
| `material/` | Os objetos de aprendizagem **analisados** (planos de aula, questoes, ementas). | `catalogo.json`, gerado por `scripts/gerar_corpus_material.py` |

## Aviso importante sobre o conteudo

Todo item dos dois conjuntos tem `"exemplo_ilustrativo": true`.

Os textos sao **parafrases genericas e sinteticas**, escritas apenas para
exercitar o mecanismo de recuperacao, comparacao de datas, citacao e abstencao.
Eles **nao reproduzem** o texto real de nenhum protocolo, diretriz, bula, plano
de aula ou ementa, e nao devem ser usados como referencia clinica ou
pedagogica.

O servico propaga essa marca ate a resposta da API: toda citacao de evidencia
ilustrativa volta com `exemplo_ilustrativo: true` e um alerta explicito. Isso e
deliberado — mostra que a flag de proveniencia atravessa a pilha inteira, da
ingestao ate o payload que o front consome.

## Como o corpus foi calibrado

Os anos de referencia de cada objeto nao sao aleatorios: foram escolhidos
aplicando a tabela de severidade (PRD, secao 6) de tras para frente, para que o
conjunto cubra todos os comportamentos que o produto precisa acertar.

| Classe | Qtd | Comportamento esperado |
| --- | --- | --- |
| Defasado, severidade alta | 4 | `defasagem_detectada` com `severidade: alta` |
| Defasado, severidade media | 4 | `defasagem_detectada` com `severidade: media` |
| Defasado, severidade baixa | 4 | `defasagem_detectada` com `severidade: baixa` |
| Atualizado | 10 | `sem_achado` — **o teste de falso alarme** |
| Tema sem evidencia na base | 3 | `abstido` / `evidencia_insuficiente` |
| Tema so em fonte nao validada | 2 | `abstido` / `fonte_nao_validada` |
| Sem referencia datada | 2 | `abstido` / `material_sem_referencia` |
| Fora de escopo | 1 | `abstido` / `fora_de_escopo` |
| Sem conteudo extraido | 1 | `abstido` / `objeto_invalido` |

Dois casos ficam de proposito na **fronteira** da tabela — gap de exatamente 12
e de exatamente 24 meses. E onde um erro de comparacao (`>` em vez de `>=`)
aparece, e por isso eles existem.

## Os dois niveis do filtro de proveniencia

A base tem, de proposito, duas evidencias que **nao podem** sustentar alerta,
cada uma por um motivo diferente:

| Evidencia | `fonte_tipo` | Tema | Por que nao sustenta |
| --- | --- | --- | --- |
| `fonte-nao-validada-rinite-2025` | `nao_validada` | rinite | Blog sem revisao editorial |
| `pubmed-oa-falciforme-2025` | `literatura_revisada` | hematologia | Estudo primario isolado: legitimo, mas nao e consenso |

As duas sao mais novas que o material correspondente, entao **sem o filtro de
proveniencia as duas virariam alerta**. E exatamente isso que elas testam.

A segunda e a mais interessante na apresentacao: recusar fonte sem curadoria e
obvio; recusar literatura revisada por pares e uma decisao de produto, e a
justificativa esta na secao 5.2 do PRD.

## Regenerar

```bash
python scripts/gerar_corpus_material.py
```

O gerador e deterministico: rodar de novo produz exatamente o mesmo
`catalogo.json`.

## Trocando pelas fontes reais

Os adaptadores de ingestao em `app/workers/ingestor.py` seguem o formato
canonico de `Evidencia`. Para sair do MVP, aponte cada adaptador para a sua
origem e remova a flag `exemplo_ilustrativo`:

| Fonte | `fonte_tipo` | Como entra |
| --- | --- | --- |
| Protocolos e PCDT do Ministerio da Saude | `orgao_oficial` | download de PDF + extracao de texto |
| Relatorios de recomendacao da CONITEC | `orgao_oficial` | download de PDF + extracao de texto |
| Bulario Eletronico da ANVISA | `orgao_oficial` | consulta por registro |
| Diretrizes de sociedades medicas | `diretriz_sociedade` | PDF publico |
| PubMed Open Access | `literatura_revisada` | E-utilities / OAI-PMH |

O material didatico real viria do sistema academico da instituicao, nao destes
arquivos. Nenhuma das fontes acima contem dado de paciente, e o servico nao
ingere, nao armazena e nao recebe dado de aluno ou de paciente em nenhum ponto.

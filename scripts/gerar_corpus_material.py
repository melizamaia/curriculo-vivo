"""Gerador do corpus SINTETICO de material didatico.

    python scripts/gerar_corpus_material.py

Este script existe por honestidade: o material didatico deste repositorio nao
e real. Ele e gerado aqui, de forma deterministica, a partir de descricoes de
tema escritas para exercitar o detector. Nenhum texto reproduz plano de aula,
ementa ou questao de instituicao alguma.

Cada objeto gerado carrega `exemplo_ilustrativo: true`, e o servico propaga
essa marca ate a resposta da API.

O corpus cobre, de proposito, os quatro comportamentos que o produto precisa
acertar:

* material defasado (as tres severidades da tabela do PRD),
* material atualizado (o teste de falso alarme),
* material sem evidencia na base (abstencao),
* material inelegivel (sem referencia datada, fora de escopo, invalido).
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "data" / "material"

# Vocabulario por tema. O texto precisa ser proximo o suficiente da evidencia
# para a recuperacao encontrar, e generico o suficiente para nao parecer
# conteudo clinico real.
TEMAS = {
    "sepse": (
        "A aula aborda o reconhecimento precoce da sepse a partir de infeccao "
        "presumida com sinais de disfuncao organica, discute o rastreamento na "
        "porta de entrada, a coleta de lactato arterial e de hemoculturas, a "
        "reposicao volemica com cristaloide e a identificacao de choque septico."
    ),
    "cetoacidose": (
        "A aula percorre o diagnostico de cetoacidose diabetica com "
        "hiperglicemia, acidose metabolica e anion gap aumentado, a reposicao "
        "volemica inicial, a insulinoterapia venosa continua, a reposicao de "
        "potassio e a monitorizacao de glicemia capilar."
    ),
    "avc": (
        "A aula trata do fluxo de atendimento ao acidente vascular cerebral "
        "isquemico agudo, com definicao do horario de inicio dos sintomas, "
        "neuroimagem de urgencia para excluir hemorragia, elegibilidade para "
        "terapia de reperfusao e aplicacao da escala de deficit neurologico."
    ),
    "farmacologia": (
        "A aula discute antidiabeticos orais, com indicacao da metformina no "
        "diabetes mellitus tipo 2, contraindicacao na disfuncao renal pelo "
        "risco de acidose lactica, avaliacao periodica da funcao renal e "
        "suspensao temporaria antes de exame com contraste iodado."
    ),
    "imunizacao": (
        "A aula apresenta a avaliacao do estado vacinal do adulto na consulta "
        "de rotina, o registro em caderneta, a verificacao de esquemas "
        "incompletos e a analise individualizada do calendario vacinal em "
        "imunossupressao, com atencao a vacinas de agente vivo atenuado."
    ),
    "dor_toracica": (
        "A aula aborda a dor toracica aguda na emergencia, com "
        "eletrocardiograma precoce, reconhecimento de supradesnivelamento do "
        "segmento ST, dosagem seriada de troponina de alta sensibilidade e "
        "estratificacao de risco por escore validado."
    ),
    "tev": (
        "A aula percorre a investigacao de trombose venosa profunda pela "
        "estimativa de probabilidade clinica, o uso e as limitacoes do "
        "D-dimero, a ultrassonografia com doppler venoso de membros inferiores "
        "e o inicio da anticoagulacao."
    ),
    "asma": (
        "A aula trata da exacerbacao de asma no adulto, com avaliacao de "
        "gravidade por oximetria de pulso e pico de fluxo expiratorio, "
        "broncodilatador de curta acao inalatorio, corticosteroide sistemico "
        "precoce e criterios de alta da emergencia."
    ),
    "hipertensao": (
        "A aula discute o diagnostico de hipertensao arterial sem depender de "
        "medida unica de consultorio, a confirmacao por monitorizacao "
        "ambulatorial ou residencial da pressao arterial, as mudancas de estilo "
        "de vida e a escolha da classe anti-hipertensiva."
    ),
    "pneumonia": (
        "A aula aborda a pneumonia adquirida na comunidade, com escore de "
        "gravidade validado para decidir entre tratamento ambulatorial e "
        "internacao, radiografia de torax como imagem inicial e escolha do "
        "antimicrobiano empirico conforme perfil epidemiologico local."
    ),
    "delirium": (
        "A aula apresenta a prevencao de delirium em pacientes internados por "
        "intervencoes multicomponentes nao farmacologicas, com reorientacao, "
        "mobilizacao precoce, higiene do sono, correcao de deficits sensoriais "
        "e rastreamento de delirium hipoativo por instrumento validado."
    ),
    "antibioticoterapia": (
        "A aula discute a duracao da antibioticoterapia em sindromes "
        "infecciosas nao complicadas, comparando cursos curtos e prolongados, "
        "a pressao seletiva associada a exposicao e as ressalvas para "
        "pacientes imunossuprimidos ou com foco nao controlado."
    ),
    "dengue": (
        "A aula apresenta o manejo da dengue com classificacao de risco por "
        "sinais de alarme, hidratacao oral ou venosa conforme o grupo, "
        "hematocrito seriado, contagem de plaquetas e criterios de "
        "internacao e de retorno para reavaliacao."
    ),
    "insuficiencia_cardiaca": (
        "A aula discute a insuficiencia cardiaca com fracao de ejecao reduzida, "
        "com ecocardiograma para classificar a fracao de ejecao, peptideo "
        "natriuretico no diagnostico, as classes de terapia modificadora de "
        "doenca e a titulacao de dose ate a maxima tolerada."
    ),
    "tabagismo": (
        "A aula aborda a cessacao do tabagismo na atencao primaria, com "
        "avaliacao do grau de dependencia de nicotina, abordagem breve "
        "motivacional, terapia de reposicao de nicotina e acompanhamento do "
        "paciente nas primeiras semanas de abstinencia."
    ),
    # Temas sem evidencia correspondente na base curada.
    "oftalmologia": (
        "A aula trata do glaucoma agudo de angulo fechado, com reconhecimento "
        "do quadro doloroso, avaliacao da pressao intraocular e encaminhamento "
        "para avaliacao especializada."
    ),
    "obstetricia": (
        "A aula aborda os criterios de gravidade das sindromes hipertensivas "
        "da gestacao no terceiro trimestre e a vigilancia materno-fetal."
    ),
    "cirurgia": (
        "A aula apresenta a abordagem da hernia inguinal encarcerada, com "
        "reconhecimento clinico, avaliacao de sofrimento de alca e indicacao "
        "cirurgica."
    ),
    "hematologia": (
        "A aula discute a crise vaso-oclusiva na doenca falciforme, com "
        "avaliacao da dor, hidratacao, oxigenacao e investigacao de "
        "complicacoes."
    ),
    # Tema que existe na base APENAS em fonte nao validada.
    "rinite": (
        "A aula trata da rinite alergica sazonal e persistente, com "
        "identificacao de desencadeantes, controle ambiental e abordagem "
        "farmacologica de manutencao."
    ),
}

# (objeto_id, titulo, tipo, curso, disciplina, periodo, temas, anos_referencia,
#  atualizado_em)
# Os anos de referencia definem a classe esperada no eval. A tabela de
# severidade do PRD (secao 6) foi usada para escolher cada ano.
OBJETOS = [
    # --- defasados: severidade alta -----------------------------------------
    ("med-clin-sepse-aula07", "Sepse e choque septico: reconhecimento e manejo inicial",
     "plano_de_aula", "Medicina", "Clinica Medica", "7", ["sepse"], [2017, 2019], "2019-08-01"),
    ("med-neuro-avc-aula12", "AVC isquemico agudo: fluxo de atendimento",
     "plano_de_aula", "Medicina", "Neurologia", "8", ["avc"], [2018], "2018-11-15"),
    ("med-card-dor-toracica-aula05", "Dor toracica aguda na emergencia",
     "plano_de_aula", "Medicina", "Cardiologia", "6", ["dor_toracica"], [2021], "2021-03-10"),
    ("med-geri-delirium-aula02", "Delirium no paciente internado: prevencao e rastreio",
     "plano_de_aula", "Medicina", "Geriatria", "9", ["delirium"], [2020], "2020-05-20"),
    # --- defasados: severidade media ----------------------------------------
    ("med-infecto-antibiotico-aula09", "Duracao de antibioticoterapia e uso racional",
     "plano_de_aula", "Medicina", "Infectologia", "8", ["antibioticoterapia"], [2023], "2023-02-01"),
    ("med-clin-cetoacidose-aula04", "Cetoacidose diabetica no adulto",
     "plano_de_aula", "Medicina", "Clinica Medica", "7", ["cetoacidose"], [2019], "2019-09-12"),
    ("med-pneumo-pac-aula10", "Pneumonia adquirida na comunidade",
     "plano_de_aula", "Medicina", "Pneumologia", "7", ["pneumonia"], [2019], "2019-04-04"),
    ("med-fam-imunizacao-aula01", "Imunizacao do adulto na atencao primaria",
     "plano_de_aula", "Medicina", "Medicina de Familia", "5", ["imunizacao"], [2021], "2021-07-19"),
    # --- defasados: severidade baixa ----------------------------------------
    ("med-pneumo-asma-aula06", "Exacerbacao de asma no adulto",
     "plano_de_aula", "Medicina", "Pneumologia", "6", ["asma"], [2022], "2022-08-30"),
    ("med-angio-tev-aula08", "Tromboembolismo venoso: diagnostico e tratamento inicial",
     "plano_de_aula", "Medicina", "Angiologia", "8", ["tev"], [2021], "2021-10-05"),
    ("med-endo-metformina-aula11", "Antidiabeticos orais: metformina",
     "plano_de_aula", "Medicina", "Endocrinologia", "7", ["farmacologia"], [2022], "2022-06-14"),
    ("med-card-dor-toracica-sim01", "Simulado: dor toracica na emergencia",
     "questao", "Medicina", "Cardiologia", "6", ["dor_toracica"], [2023], "2023-11-22"),
    # --- outros cursos, temas novos e objetos com mais de um tema ---------
    # Enfermagem: practice-changing com gap de 27 meses.
    ("enf-saude-adulto-dengue-aula02", "Dengue: classificacao de risco e hidratacao",
     "aula", "Enfermagem", "Saude do Adulto", "4", ["dengue"], [2022], "2022-04-12"),
    # Practice-changing com gap de 3 meses: posterior, mas recente.
    ("med-infecto-dengue-aula03", "Dengue: manejo clinico por grupo de risco",
     "plano_de_aula", "Medicina", "Infectologia", "8", ["dengue"], [2024], "2024-03-05"),
    ("med-card-ic-aula08", "Insuficiencia cardiaca com fracao de ejecao reduzida",
     "plano_de_aula", "Medicina", "Cardiologia", "7", ["insuficiencia_cardiaca"], [2021], "2021-09-02"),
    ("farm-atencao-tabagismo-aula01", "Cessacao do tabagismo no cuidado farmaceutico",
     "aula", "Farmacia", "Atencao Farmaceutica", "6", ["tabagismo"], [2022], "2022-02-17"),
    # Dois temas defasados com severidades diferentes: a maxima vence.
    ("med-clin-sepse-antibiotico-aula15", "Sepse e duracao do antimicrobiano",
     "plano_de_aula", "Medicina", "Clinica Medica", "8", ["sepse", "antibioticoterapia"],
     [2022], "2022-10-03"),
    # Um tema defasado e outro em dia: o alerta cita so o defasado.
    ("med-angio-tev-antibiotico-aula16", "TEV e antibioticoterapia no paciente internado",
     "plano_de_aula", "Medicina", "Clinica Medica", "8", ["tev", "antibioticoterapia"],
     [2023], "2023-08-21"),
    # Ementa com dois temas practice-changing, ambos com gap abaixo de 12.
    ("med-urgencia-ementa", "Ementa: Urgencia e Emergencia",
     "ementa", "Medicina", "Urgencia e Emergencia", "9", ["avc", "dor_toracica"],
     [2023], "2023-12-15"),
    # --- atualizados: o teste de falso alarme -------------------------------
    ("med-card-hipertensao-aula03", "Hipertensao arterial: diagnostico e tratamento",
     "plano_de_aula", "Medicina", "Cardiologia", "6", ["hipertensao"], [2024], "2024-08-01"),
    ("med-clin-sepse-aula07r", "Sepse e choque septico (revisao 2024)",
     "plano_de_aula", "Medicina", "Clinica Medica", "7", ["sepse"], [2024], "2024-09-10"),
    ("med-neuro-avc-aula12r", "AVC isquemico agudo (revisao 2025)",
     "plano_de_aula", "Medicina", "Neurologia", "8", ["avc"], [2025], "2025-02-18"),
    ("med-endo-metformina-aula11r", "Antidiabeticos orais (revisao 2025)",
     "plano_de_aula", "Medicina", "Endocrinologia", "7", ["farmacologia"], [2025], "2025-05-06"),
    ("med-geri-delirium-aula02r", "Delirium no paciente internado (revisao 2025)",
     "plano_de_aula", "Medicina", "Geriatria", "9", ["delirium"], [2025], "2025-03-27"),
    ("med-pneumo-asma-aula06r", "Exacerbacao de asma (revisao 2024)",
     "plano_de_aula", "Medicina", "Pneumologia", "6", ["asma"], [2024], "2024-06-11"),
    ("med-angio-tev-aula08r", "Tromboembolismo venoso (revisao 2023)",
     "plano_de_aula", "Medicina", "Angiologia", "8", ["tev"], [2023], "2023-12-01"),
    ("med-fam-imunizacao-aula01r", "Imunizacao do adulto (revisao 2025)",
     "plano_de_aula", "Medicina", "Medicina de Familia", "5", ["imunizacao"], [2025], "2025-06-23"),
    ("med-pneumo-pac-aula10r", "Pneumonia adquirida na comunidade (revisao 2024)",
     "plano_de_aula", "Medicina", "Pneumologia", "7", ["pneumonia"], [2024], "2024-01-30"),
    ("med-infecto-antibiotico-aula09r", "Duracao de antibioticoterapia (revisao 2025)",
     "plano_de_aula", "Medicina", "Infectologia", "8", ["antibioticoterapia"], [2025], "2025-04-02"),
    ("med-infecto-dengue-aula03r", "Dengue: manejo clinico (revisao 2025)",
     "plano_de_aula", "Medicina", "Infectologia", "8", ["dengue"], [2025], "2025-05-14"),
    # Evidencia posterior, mas gap de 6 meses e sem practice-changing.
    ("med-card-ic-aula08r", "Insuficiencia cardiaca (revisao 2024)",
     "plano_de_aula", "Medicina", "Cardiologia", "7", ["insuficiencia_cardiaca"], [2024], "2024-10-08"),
    # Evidencia posterior, mas gap de 8 meses e sem practice-changing.
    ("farm-atencao-tabagismo-aula01r", "Cessacao do tabagismo (revisao 2023)",
     "aula", "Farmacia", "Atencao Farmaceutica", "6", ["tabagismo"], [2023], "2023-09-26"),
    # Bibliografia mista: a referencia de 2015 nao conta, vale a de 2024.
    ("med-card-hipertensao-aula09", "Hipertensao resistente: bibliografia mista",
     "plano_de_aula", "Medicina", "Cardiologia", "8", ["hipertensao"], [2015, 2024], "2024-11-04"),
    # --- sem evidencia na base: abstencao -----------------------------------
    ("med-oftalmo-glaucoma-aula01", "Glaucoma agudo de angulo fechado",
     "plano_de_aula", "Medicina", "Oftalmologia", "9", ["oftalmologia"], [2019], "2019-02-11"),
    ("med-gineco-hipertensiva-aula02", "Sindromes hipertensivas da gestacao",
     "plano_de_aula", "Medicina", "Ginecologia e Obstetricia", "8", ["obstetricia"], [2018], "2018-07-09"),
    ("med-cirurgia-hernia-aula03", "Hernia inguinal encarcerada",
     "plano_de_aula", "Medicina", "Cirurgia Geral", "9", ["cirurgia"], [2017], "2017-05-16"),
    ("med-hemato-falciforme-aula04", "Crise vaso-oclusiva na doenca falciforme",
     "plano_de_aula", "Medicina", "Hematologia", "8", ["hematologia"], [2019], "2019-10-21"),
    # --- tema presente apenas em fonte nao validada -------------------------
    ("med-orl-rinite-aula05", "Rinite alergica: diagnostico e manejo",
     "plano_de_aula", "Medicina", "Otorrinolaringologia", "7", ["rinite"], [2019], "2019-03-08"),
]


def objeto_base(
    objeto_id: str,
    titulo: str,
    tipo: str,
    curso: str,
    disciplina: str,
    periodo: str,
    temas: list[str],
    anos: list[int],
    atualizado_em: str,
) -> dict:
    return {
        "objeto_id": objeto_id,
        "titulo": titulo,
        "tipo": tipo,
        "curso": curso,
        "disciplina": disciplina,
        "periodo": periodo,
        "campus": ["Campus A", "Campus B"],
        "temas": temas,
        "atualizado_em": atualizado_em,
        "exemplo_ilustrativo": True,
        "referencias": [
            {
                "titulo": f"Material de referencia ilustrativo sobre {t} ({ano})",
                "fonte": "Referencia sintetica",
                "ano": ano,
                "url": "https://example.org/referencia",
            }
            for t in temas
            for ano in anos
        ],
        "trechos": [
            {"trecho_id": f"{objeto_id}#t{i}", "texto": TEMAS[t]}
            for i, t in enumerate(temas, start=1)
        ],
    }


def objetos_inelegiveis() -> list[dict]:
    """Casos que o servico deve recusar a analisar, cada um por um motivo."""
    sem_ref = objeto_base(
        "med-sem-referencia-aula01",
        "Sepse: aula sem bibliografia registrada",
        "plano_de_aula", "Medicina", "Clinica Medica", "7", ["sepse"], [2019],
        "2019-08-01",
    )
    sem_ref["referencias"] = []

    ref_sem_ano = objeto_base(
        "med-referencia-sem-ano-aula02",
        "AVC isquemico: aula com bibliografia sem ano",
        "plano_de_aula", "Medicina", "Neurologia", "8", ["avc"], [2018],
        "2018-11-15",
    )
    ref_sem_ano["referencias"] = [
        {
            "titulo": "Capitulo de livro sem ano informado",
            "fonte": "Referencia sintetica",
            "ano": None,
            "url": None,
        }
    ]

    fora_escopo = objeto_base(
        "med-escopo-questao-aula03",
        "Simulado com enunciado fora de escopo",
        "questao", "Medicina", "Clinica Medica", "7", ["sepse"], [2019],
        "2019-08-01",
    )
    fora_escopo["trechos"] = [
        {
            "trecho_id": "med-escopo-questao-aula03#t1",
            "texto": (
                "Qual a dose que devo prescrever para o meu paciente de 70 kg "
                "no choque septico? Informe a posologia exata."
            ),
        }
    ]

    aluno = objeto_base(
        "enf-escopo-aluno-aula05",
        "Estudo de caso com aluno identificado",
        "aula", "Enfermagem", "Saude do Adulto", "4", ["dengue"], [2022],
        "2022-04-12",
    )
    aluno["trechos"] = [
        {
            "trecho_id": "enf-escopo-aluno-aula05#t1",
            "texto": (
                "Discussao do desempenho da aluna Carla Mendes na estacao de "
                "classificacao de risco da dengue, com as notas de cada etapa."
            ),
        }
    ]

    invalido = objeto_base(
        "med-objeto-invalido-aula04",
        "Objeto digital sem conteudo extraido",
        "objeto_digital", "Medicina", "Clinica Medica", "7", ["sepse"], [2019],
        "2019-08-01",
    )
    invalido["trechos"] = []

    return [sem_ref, ref_sem_ano, fora_escopo, aluno, invalido]


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    objetos = [objeto_base(*linha) for linha in OBJETOS]
    objetos.extend(objetos_inelegiveis())

    destino = SAIDA / "catalogo.json"
    destino.write_text(
        json.dumps(objetos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(objetos)} objetos gravados em {destino.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

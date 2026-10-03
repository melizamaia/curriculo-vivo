"""Worker de ingestão (app/workers/ingestor.py), sem broker.

O publicador e o consumidor falsos escrevem num mesmo diário de eventos: é o
que permite provar a ordem do ADR-9 — o offset só é confirmado depois de
publicar — e que uma falha no meio não confirma nada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pytest

from app.config import Settings
from app.core.retriever import Retriever
from app.core.servico import ServicoAnalise
from app.models import Evidencia, ObjetoAprendizagem, StatusAnalise
from app.repositories.evidencias import ArmazemMemoria
from app.workers.ingestor import (
    EvidenciaRejeitada,
    Ingestor,
    MotivoRejeicao,
    Resultado,
    hash_evidencia,
    validar_evidencia,
)

SETTINGS = Settings()
HOJE = date(2026, 10, 3)
TOPICO_INDEXADA = SETTINGS.kafka_topic_evidencia_indexada
TOPICO_REJEITADA = SETTINGS.kafka_topic_evidencia_rejeitada


def base_curada() -> list[dict]:
    bruto = json.loads(SETTINGS.caminho_evidencias.read_text(encoding="utf-8"))
    return bruto["evidencias"] if isinstance(bruto, dict) else bruto


def nova(**sobrescrever) -> dict:
    """Evidência válida de um tema que a base curada não cobre."""
    evidencia = {
        "doc_id": "diretriz-glaucoma-2025",
        "titulo": "Glaucoma agudo de angulo fechado: reconhecimento e encaminhamento",
        "fonte": "Sociedade ilustrativa de oftalmologia",
        "fonte_tipo": "diretriz_sociedade",
        "url": "https://example.org/glaucoma",
        "publicado_em": "2025-03-10",
        "nivel_evidencia": "B",
        "temas": ["oftalmologia"],
        "practice_changing": True,
        "exemplo_ilustrativo": True,
        "trechos": [
            {
                "trecho_id": "diretriz-glaucoma-2025#t1",
                "texto": "O glaucoma agudo de angulo fechado exige reconhecimento do "
                "quadro doloroso, medida da pressao intraocular e encaminhamento "
                "para avaliacao especializada no mesmo dia.",
            }
        ],
    }
    evidencia.update(sobrescrever)
    return evidencia


def payload(dados: dict) -> bytes:
    return json.dumps(dados, ensure_ascii=False).encode("utf-8")


class PublicadorFalso:
    def __init__(self, diario: list, falhar: bool = False) -> None:
        self.diario = diario
        self.falhar = falhar
        self.publicados: list[tuple[str, str | None, dict]] = []

    async def publicar(self, topico, chave, valor) -> None:
        if self.falhar:
            raise ConnectionError("broker fora")
        self.publicados.append((topico, chave, valor))
        self.diario.append(("publicar", topico, chave))


class ArmazemFalho(ArmazemMemoria):
    async def salvar(self, evidencia, hash_conteudo) -> None:
        raise ConnectionError("mongo fora")


@dataclass
class MensagemFalsa:
    value: bytes
    offset: int
    topic: str = "evidencia.nova"
    partition: int = 0


class ConsumidorFalso:
    def __init__(self, mensagens: list[MensagemFalsa], diario: list) -> None:
        self._mensagens = mensagens
        self.diario = diario
        self.commits: list[int] = []

    async def __aiter__(self):
        for m in self._mensagens:
            yield m

    async def commit(self, offsets) -> None:
        ((_, offset),) = offsets.items()
        self.commits.append(offset)
        self.diario.append(("commit", offset))


@pytest.fixture
def diario() -> list:
    return []


@pytest.fixture
def publicador(diario) -> PublicadorFalso:
    return PublicadorFalso(diario)


@pytest.fixture
def armazem() -> ArmazemMemoria:
    return ArmazemMemoria()


@pytest.fixture
def ingestor(publicador, armazem) -> Ingestor:
    retriever = Retriever.carregar(SETTINGS.caminho_evidencias)
    return Ingestor(retriever, armazem, publicador, SETTINGS, hoje=lambda: HOJE)


# --- validação de proveniência ---------------------------------------------


@pytest.mark.parametrize("item", base_curada(), ids=lambda i: i["doc_id"])
def test_base_curada_passa_na_validacao(item):
    assert validar_evidencia(payload(item), HOJE).doc_id == item["doc_id"]


def test_fonte_nao_validada_e_aceita_na_ingestao():
    """Quem impede fonte não validada de sustentar alerta é a barreira 2."""
    ev = validar_evidencia(payload(nova(fonte_tipo="nao_validada", url=None)), HOJE)
    assert ev.fonte_tipo.value == "nao_validada"


@pytest.mark.parametrize(
    ("bruto", "motivo"),
    [
        (b"{nao e json", MotivoRejeicao.PAYLOAD_INVALIDO),
        (b"\xff\xfe", MotivoRejeicao.PAYLOAD_INVALIDO),
        (b"[1, 2]", MotivoRejeicao.PAYLOAD_INVALIDO),
        (payload(nova(nivel_evidencia="Z")), MotivoRejeicao.PAYLOAD_INVALIDO),
        (payload(nova(publicado_em="ontem")), MotivoRejeicao.PAYLOAD_INVALIDO),
        (payload(nova(fonte_tipo=None)), MotivoRejeicao.PROVENIENCIA_AUSENTE),
        (payload(nova(fonte="   ")), MotivoRejeicao.PROVENIENCIA_AUSENTE),
        (payload(nova(doc_id="")), MotivoRejeicao.PROVENIENCIA_AUSENTE),
        (payload(nova(publicado_em=None)), MotivoRejeicao.PROVENIENCIA_AUSENTE),
        (payload(nova(url=None)), MotivoRejeicao.SEM_URL_VERIFICAVEL),
        (payload(nova(fonte_tipo="orgao_oficial", url=" ")), MotivoRejeicao.SEM_URL_VERIFICAVEL),
        (payload(nova(publicado_em="2026-10-04")), MotivoRejeicao.DATA_FUTURA),
        (payload(nova(trechos=[])), MotivoRejeicao.SEM_TRECHOS),
        (
            payload(nova(trechos=[{"trecho_id": "diretriz-glaucoma-2025#t1", "texto": " "}])),
            MotivoRejeicao.SEM_TRECHOS,
        ),
        (
            payload(nova(trechos=[{"trecho_id": "outro-doc#t1", "texto": "x"}])),
            MotivoRejeicao.TRECHO_INCONSISTENTE,
        ),
        (
            payload(
                nova(
                    trechos=[
                        {"trecho_id": "diretriz-glaucoma-2025#t1", "texto": "a"},
                        {"trecho_id": "diretriz-glaucoma-2025#t1", "texto": "b"},
                    ]
                )
            ),
            MotivoRejeicao.TRECHO_INCONSISTENTE,
        ),
    ],
)
def test_rejeicoes(bruto, motivo):
    with pytest.raises(EvidenciaRejeitada) as exc:
        validar_evidencia(bruto, HOJE)
    assert exc.value.motivo is motivo


def test_fonte_tipo_ausente_nao_herda_o_default_do_modelo():
    sem_fonte_tipo = nova()
    del sem_fonte_tipo["fonte_tipo"]
    # O modelo aceitaria, com default `literatura_revisada`...
    assert Evidencia.model_validate(sem_fonte_tipo).fonte_tipo.value == "literatura_revisada"
    # ...mas a ingestão não inventa proveniência.
    with pytest.raises(EvidenciaRejeitada) as exc:
        validar_evidencia(payload(sem_fonte_tipo), HOJE)
    assert exc.value.motivo is MotivoRejeicao.PROVENIENCIA_AUSENTE


def test_publicada_hoje_e_aceita():
    assert validar_evidencia(payload(nova(publicado_em=HOJE.isoformat())), HOJE)


def test_hash_independe_da_ordem_das_chaves():
    a = Evidencia.model_validate(nova())
    b = Evidencia.model_validate(dict(reversed(list(nova().items()))))
    assert hash_evidencia(a) == hash_evidencia(b)


# --- processar: indexação e idempotência -----------------------------------


async def test_evidencia_nova_e_indexada_publicada_e_persistida(ingestor, publicador, armazem):
    versao_antes = ingestor.retriever.versao_indice

    r = await ingestor.processar(payload(nova()))

    assert r.resultado is Resultado.INDEXADA
    assert r.versao_indice != versao_antes
    assert r.versao_indice == ingestor.retriever.versao_indice
    assert ingestor.retriever.obter("diretriz-glaucoma-2025") is not None
    assert publicador.publicados == [
        (
            TOPICO_INDEXADA,
            "diretriz-glaucoma-2025",
            {
                "doc_id": "diretriz-glaucoma-2025",
                "versao_indice": r.versao_indice,
                "practice_changing": True,
                "trechos_indexados": 1,
            },
        )
    ]
    assert [e.doc_id for e in await armazem.listar()] == ["diretriz-glaucoma-2025"]


async def test_reentrega_do_mesmo_conteudo_e_noop(ingestor, publicador):
    await ingestor.processar(payload(nova()))
    versao = ingestor.retriever.versao_indice

    r = await ingestor.processar(payload(nova()))

    assert r.resultado is Resultado.DUPLICADA
    assert r.versao_indice == versao
    assert len(publicador.publicados) == 1


async def test_reenviar_a_base_curada_e_noop(ingestor, publicador, armazem):
    versao = ingestor.retriever.versao_indice
    for item in base_curada():
        r = await ingestor.processar(payload(item))
        assert r.resultado is Resultado.DUPLICADA
    assert ingestor.retriever.versao_indice == versao
    assert publicador.publicados == []
    assert await armazem.listar() == []


async def test_mesmo_doc_id_com_conteudo_novo_reindexa(ingestor, publicador):
    r1 = await ingestor.processar(payload(nova()))
    r2 = await ingestor.processar(payload(nova(nivel_evidencia="A")))

    assert r2.resultado is Resultado.INDEXADA
    assert r2.versao_indice != r1.versao_indice
    assert ingestor.retriever.obter("diretriz-glaucoma-2025").nivel_evidencia.value == "A"
    assert len(publicador.publicados) == 2


async def test_rejeitada_vai_para_o_topico_de_rejeicao_e_nao_toca_o_indice(
    ingestor, publicador, armazem
):
    versao = ingestor.retriever.versao_indice

    r = await ingestor.processar(payload(nova(url=None)))

    assert r.resultado is Resultado.REJEITADA
    assert r.motivo is MotivoRejeicao.SEM_URL_VERIFICAVEL
    assert ingestor.retriever.versao_indice == versao
    assert await armazem.listar() == []
    ((topico, chave, valor),) = publicador.publicados
    assert topico == TOPICO_REJEITADA
    assert chave == "diretriz-glaucoma-2025"
    assert valor["motivo"] == "sem_url_verificavel"
    assert json.loads(valor["payload"])["doc_id"] == "diretriz-glaucoma-2025"


async def test_falha_ao_publicar_nao_confirma_o_hash(ingestor, publicador):
    """Sem isso, a reentrega seria tratada como duplicata e o evento
    `evidencia.indexada` nunca sairia."""
    publicador.falhar = True
    with pytest.raises(ConnectionError):
        await ingestor.processar(payload(nova()))

    publicador.falhar = False
    r = await ingestor.processar(payload(nova()))

    assert r.resultado is Resultado.INDEXADA
    assert [p[0] for p in publicador.publicados] == [TOPICO_INDEXADA]


async def test_falha_ao_persistir_nao_confirma_o_hash(publicador):
    retriever = Retriever.carregar(SETTINGS.caminho_evidencias)
    ingestor = Ingestor(retriever, ArmazemFalho(), publicador, SETTINGS, hoje=lambda: HOJE)

    for _ in range(2):
        with pytest.raises(ConnectionError):
            await ingestor.processar(payload(nova()))

    # Republicou na segunda tentativa: at-least-once, nunca at-most-once.
    assert [p[0] for p in publicador.publicados] == [TOPICO_INDEXADA] * 2


# --- consumir: commit manual de offset (ADR-9) -----------------------------


async def test_commit_so_depois_de_publicar(ingestor, diario):
    consumidor = ConsumidorFalso(
        [
            MensagemFalsa(payload(nova()), offset=10),
            MensagemFalsa(payload(nova()), offset=11),  # reentrega
            MensagemFalsa(b"lixo", offset=12),
        ],
        diario,
    )

    await ingestor.consumir(consumidor)

    assert diario == [
        ("publicar", TOPICO_INDEXADA, "diretriz-glaucoma-2025"),
        ("commit", 11),
        ("commit", 12),  # duplicada: confirma sem publicar
        ("publicar", TOPICO_REJEITADA, None),
        ("commit", 13),  # malformada não trava a partição
    ]


async def test_falha_no_meio_interrompe_sem_confirmar(ingestor, publicador, diario):
    consumidor = ConsumidorFalso(
        [
            MensagemFalsa(payload(nova()), offset=0),
            MensagemFalsa(payload(nova(doc_id="outra", trechos=[
                {"trecho_id": "outra#t1", "texto": "texto"}
            ])), offset=1),
            MensagemFalsa(payload(nova(nivel_evidencia="A")), offset=2),
        ],
        diario,
    )

    original = publicador.publicar

    async def falha_na_segunda(topico, chave, valor):
        if chave == "outra":
            raise ConnectionError("broker fora")
        await original(topico, chave, valor)

    publicador.publicar = falha_na_segunda

    with pytest.raises(ConnectionError):
        await ingestor.consumir(consumidor)

    # Offset 1 não confirmado: no restart, o grupo volta a entregá-lo.
    assert consumidor.commits == [1]


# --- restart e efeito na análise -------------------------------------------


async def test_restart_recupera_o_que_ja_foi_ingerido(publicador, armazem):
    primeiro = await Ingestor.montar(SETTINGS, publicador, armazem)
    await primeiro.processar(payload(nova()))
    versao = primeiro.retriever.versao_indice

    segundo = await Ingestor.montar(SETTINGS, publicador, armazem)

    assert segundo.retriever.versao_indice == versao
    r = await segundo.processar(payload(nova()))
    assert r.resultado is Resultado.DUPLICADA
    assert len(publicador.publicados) == 1


async def test_evidencia_ingerida_passa_a_sustentar_alerta(ingestor):
    """Ponta a ponta: o tema sem evidência na base vira defasagem citada."""
    objetos = json.loads(SETTINGS.caminho_material.read_text(encoding="utf-8"))
    objetos = objetos["objetos"] if isinstance(objetos, dict) else objetos
    glaucoma = ObjetoAprendizagem.model_validate(
        next(o for o in objetos if o["objeto_id"] == "med-oftalmo-glaucoma-aula01")
    )
    servico = ServicoAnalise(ingestor.retriever, SETTINGS)

    assert servico.analisar(glaucoma).status is StatusAnalise.ABSTIDO

    await ingestor.processar(payload(nova()))
    resposta = servico.analisar(glaucoma)

    assert resposta.status is StatusAnalise.DEFASAGEM_DETECTADA
    assert resposta.defasagens[0].evidencia.doc_id == "diretriz-glaucoma-2025"


def test_api_carrega_no_boot_o_que_o_worker_ingeriu(monkeypatch):
    """API e worker precisam concordar sobre `versao_indice`."""
    from fastapi.testclient import TestClient

    import app.main as main
    from app.main import criar_app

    armazem = ArmazemMemoria()
    evidencia = Evidencia.model_validate(nova())

    async def armazem_com_ingerida(_settings):
        await armazem.salvar(evidencia, hash_evidencia(evidencia))
        return armazem

    monkeypatch.setattr(main, "criar_armazem_evidencias", armazem_com_ingerida)
    settings = Settings(mongo_uri="mongodb://127.0.0.1:1", mongo_timeout_ms=100)

    esperado = Retriever.carregar(SETTINGS.caminho_evidencias)
    esperado.upsert(evidencia)

    with TestClient(criar_app(settings)) as cliente:
        ids = {e["doc_id"] for e in cliente.get("/v1/evidencias").json()}
        assert "diretriz-glaucoma-2025" in ids
        assert cliente.get("/v1/metricas").json()["versao_indice"] == esperado.versao_indice

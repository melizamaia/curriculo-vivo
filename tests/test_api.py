"""API ponta a ponta (seção 7), sem Mongo, sem Kafka e sem chave de LLM.

O Mongo aponta para uma porta fechada de propósito: o aceite da fase 4 é
subir assim, com a auditoria caindo para a memória.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import criar_app

SEM_MONGO = {"mongo_uri": "mongodb://127.0.0.1:1", "mongo_timeout_ms": 100}


@pytest.fixture(scope="module")
def cliente():
    with TestClient(criar_app(Settings(**SEM_MONGO))) as c:
        yield c


@pytest.fixture
def cliente_sem_indice(tmp_path):
    settings = Settings(caminho_evidencias=tmp_path / "nao_existe.json", **SEM_MONGO)
    with TestClient(criar_app(settings)) as c:
        yield c


def analisar(cliente, objeto_id: str) -> dict:
    r = cliente.post("/v1/analises", json={"objeto_id": objeto_id})
    assert r.status_code == 200, r.text
    return r.json()


# --- operação ------------------------------------------------------------


def test_sobe_sem_mongo_com_auditoria_em_memoria(cliente):
    r = cliente.get("/health/ready")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ready"
    assert corpo["detalhes"]["auditoria"] == "memoria"
    assert corpo["detalhes"]["modo_sintese"] == "extrativa"
    assert cliente.get("/health").json()["status"] == "ok"


def test_ready_degraded_com_indice_vazio(cliente_sem_indice):
    r = cliente_sem_indice.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded"
    assert r.json()["detalhes"]["indice"] == "vazio"


def test_indice_vazio_so_se_abstem(cliente_sem_indice):
    corpo = analisar(cliente_sem_indice, "med-clin-sepse-aula07")
    assert corpo["status"] == "abstido"
    assert corpo["motivo_abstencao"] == "evidencia_insuficiente"


def test_docs_e_openapi(cliente):
    assert cliente.get("/docs").status_code == 200
    rotas = cliente.get("/openapi.json").json()["paths"]
    for rota in (
        "/v1/analises",
        "/v1/defasagens",
        "/v1/objetos",
        "/v1/evidencias",
        "/v1/metricas",
        "/v1/auditoria",
        "/health",
        "/health/ready",
        "/painel",
    ):
        assert rota in rotas


# --- análise ---------------------------------------------------------------


def test_defasado_cita_evidencia(cliente):
    corpo = analisar(cliente, "med-clin-sepse-aula07")
    assert corpo["status"] == "defasagem_detectada"
    assert corpo["severidade_maxima"] == "alta"
    ev = corpo["defasagens"][0]["evidencia"]
    assert ev["doc_id"] == "ms-sepse-2024"
    for campo in ("fonte", "url", "publicado_em", "nivel_evidencia", "trecho"):
        assert ev[campo]
    assert f"[{ev['marcador']}]" in corpo["defasagens"][0]["justificativa"]


@pytest.mark.parametrize(
    ("objeto_id", "status", "motivo"),
    [
        ("med-card-hipertensao-aula03", "sem_achado", None),
        ("med-sem-referencia-aula01", "abstido", "material_sem_referencia"),
        ("med-orl-rinite-aula05", "abstido", "fonte_nao_validada"),
        ("med-oftalmo-glaucoma-aula01", "abstido", "evidencia_insuficiente"),
    ],
)
def test_roteiro_da_demo(cliente, objeto_id, status, motivo):
    corpo = analisar(cliente, objeto_id)
    assert (corpo["status"], corpo["motivo_abstencao"]) == (status, motivo)
    assert corpo["defasagens"] == []


def test_payload_completo_fora_do_catalogo(cliente):
    objeto = cliente.get("/v1/objetos").json()[0]
    objeto["objeto_id"] = "nao-catalogado-01"
    r = cliente.post("/v1/analises", json={"objeto": objeto})
    assert r.status_code == 200
    assert r.json()["objeto_id"] == "nao-catalogado-01"


def test_objeto_id_inexistente_404(cliente):
    r = cliente.post("/v1/analises", json={"objeto_id": "nao-existe"})
    assert r.status_code == 404


def test_requisicao_vazia_422(cliente):
    assert cliente.post("/v1/analises", json={}).status_code == 422


# --- radar -----------------------------------------------------------------


def test_radar_ordena_por_severidade(cliente):
    corpo = cliente.get("/v1/defasagens").json()
    assert corpo["total_objetos"] == 31
    assert corpo["por_severidade"] == {"alta": 4, "media": 4, "baixa": 4}
    peso = {"alta": 3, "media": 2, "baixa": 1, None: 0}
    pesos = [peso[i["severidade_maxima"]] for i in corpo["itens"]]
    assert pesos == sorted(pesos, reverse=True)
    assert sum(corpo["por_curso"].values()) == corpo["objetos_com_defasagem"]


def test_radar_filtros(cliente):
    corpo = cliente.get("/v1/defasagens", params={"severidade": "alta", "limite": 2}).json()
    assert len(corpo["itens"]) == 2
    assert {i["severidade_maxima"] for i in corpo["itens"]} == {"alta"}
    assert cliente.get("/v1/defasagens", params={"severidade": "x"}).status_code == 422


# --- auditoria e métricas --------------------------------------------------


def test_auditoria_grava_objeto_so_como_hash(cliente):
    resposta = analisar(cliente, "med-clin-sepse-aula07")
    registro = cliente.get("/v1/auditoria", params={"limite": 1}).json()[0]
    assert registro["request_id"] == resposta["request_id"]
    assert len(registro["objeto_hash"]) == 64
    assert registro["evidencias_citadas"] == ["ms-sepse-2024"]
    assert registro["versao_indice"] == cliente.get("/v1/metricas").json()["versao_indice"]
    assert "trechos" not in registro and "titulo" not in registro


def test_metricas(cliente):
    analisar(cliente, "med-sem-referencia-aula01")
    corpo = cliente.get("/v1/metricas").json()
    assert corpo["total_analises"] >= 1
    assert corpo["por_status"]["abstido"] >= 1
    assert 0 < corpo["taxa_abstencao"] <= 1
    assert corpo["latencia_p95_ms"] > 0
    assert corpo["versao_indice"] not in ("", "vazio")


# --- ingestão --------------------------------------------------------------


def test_ingestao_de_evidencia_e_idempotente(cliente):
    evidencia = cliente.get("/v1/evidencias").json()[0]
    versao = cliente.get("/v1/metricas").json()["versao_indice"]
    r = cliente.post("/v1/evidencias", json=evidencia)
    assert r.status_code == 201
    assert r.json()["versao_indice"] == versao  # mesmo conteúdo, mesma versão


def test_ingestao_de_objeto():
    # Cliente próprio: o objeto ingerido não pode vazar para o radar dos
    # outros testes.
    with TestClient(criar_app(Settings(**SEM_MONGO))) as cliente:
        objeto = cliente.get("/v1/objetos").json()[0]
        objeto["objeto_id"] = "ingerido-01"
        assert cliente.post("/v1/objetos", json=objeto).status_code == 201
        assert cliente.post("/v1/objetos", json=objeto).status_code == 200
        assert analisar(cliente, "ingerido-01")["objeto_id"] == "ingerido-01"
        assert cliente.get("/v1/defasagens").json()["total_objetos"] == 32


def test_radar_audita_cada_analise_e_metricas_separam_origem():
    # Cliente próprio: as contagens precisam partir do zero.
    with TestClient(criar_app(Settings(**SEM_MONGO))) as cliente:
        analisar(cliente, "med-clin-sepse-aula07")
        # Severidade e limite recortam a fila, não a auditoria: as 31
        # análises da varredura são gravadas.
        radar = cliente.get(
            "/v1/defasagens", params={"severidade": "alta", "limite": 1}
        ).json()
        assert len(radar["itens"]) == 1

        trilha = cliente.get("/v1/auditoria", params={"limite": 1000}).json()
        do_radar = [r for r in trilha if r["origem"] == "radar"]
        assert len(do_radar) == 31
        assert [r["origem"] for r in trilha].count("analise") == 1
        assert {r["versao_indice"] for r in do_radar} == {radar["versao_indice"]}
        apontado = radar["itens"][0]
        assert any(
            r["objeto_id"] == apontado["objeto_id"]
            and r["evidencias_citadas"]
            == [d["evidencia"]["doc_id"] for d in apontado["defasagens"]]
            for r in do_radar
        )

        padrao = cliente.get("/v1/metricas").json()
        assert padrao["total_analises"] == 1
        assert padrao["por_status"] == {"defasagem_detectada": 1}

        com_radar = cliente.get("/v1/metricas", params={"incluir_radar": True}).json()
        assert com_radar["total_analises"] == 32
        assert com_radar["por_status"]["defasagem_detectada"] == 13

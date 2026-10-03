"""Harness de avaliação (seção 8): métricas, metas duras, código de saída e painel.

As verificações independentes (`alertas_sem_citacao`, `verificar_invariantes`)
são testadas com respostas fabricadas que o serviço nunca produziria — é
exatamente o caso que elas existem para pegar.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import routes_ops
from app.config import Settings
from app.core.guardrail import Descarte, Validacao
from app.main import criar_app
from app.models import (
    AnaliseResponse,
    Defasagem,
    EvidenciaCitada,
    FonteTipo,
    MotivoAbstencao,
    NivelEvidencia,
    Severidade,
    StatusAnalise,
)
from eval import run_eval
from eval.run_eval import (
    SAIDA_INVALIDA,
    SAIDA_META_DURA,
    SAIDA_OK,
    alertas_sem_citacao,
    codigo_saida,
    gerar_painel,
    verificar_invariantes,
)


def _evidencia(marcador: int = 1, doc_id: str = "ev-2024", publicado=date(2024, 5, 1)):
    return EvidenciaCitada(
        marcador=marcador,
        doc_id=doc_id,
        trecho_id=f"{doc_id}#t1",
        titulo="Evidência",
        fonte="Fonte",
        fonte_tipo=FonteTipo.ORGAO_OFICIAL,
        publicado_em=publicado,
        nivel_evidencia=NivelEvidencia.A,
        trecho="texto",
        score=0.5,
    )


def _resposta(*defasagens: Defasagem, ano: int = 2019, **extra) -> AnaliseResponse:
    campos = dict(
        status=StatusAnalise.DEFASAGEM_DETECTADA,
        objeto_id="obj",
        ano_referencia_material=ano,
        defasagens=list(defasagens),
    )
    campos.update(extra)
    return AnaliseResponse(**campos)


def _defasagem(justificativa: str, evidencia: EvidenciaCitada | None = None, tema="t"):
    return Defasagem(
        tema=tema,
        severidade=Severidade.ALTA,
        gap_meses=50,
        practice_changing=True,
        justificativa=justificativa,
        evidencia=evidencia or _evidencia(),
    )


# --- verificações independentes ------------------------------------------


def test_resposta_correta_nao_viola_nada():
    r = _resposta(_defasagem("Material de 2019 [0]. Evidência nova [1]."))
    assert alertas_sem_citacao(r) == 0
    assert verificar_invariantes(r) == []


def test_marcador_orfao_e_alerta_sem_citacao_e_viola_i2():
    r = _resposta(_defasagem("Material [0]. Evidência [1] e [7]."))
    assert alertas_sem_citacao(r) == 1
    assert any(v.startswith("I2") for v in verificar_invariantes(r))


def test_justificativa_so_com_material_e_alerta_sem_citacao():
    assert alertas_sem_citacao(_resposta(_defasagem("Só o material [0]."))) == 1


def test_defasagem_sem_evidencia_viola_i1():
    sem = Defasagem.model_construct(
        tema="t", severidade=Severidade.ALTA, gap_meses=50,
        practice_changing=True, justificativa="[0] [1]", evidencia=None,
    )
    r = _resposta(sem)
    assert alertas_sem_citacao(r) == 1
    assert any(v.startswith("I1") for v in verificar_invariantes(r))


def test_marcador_ambiguo_viola_i2():
    r = _resposta(
        _defasagem("[0] [1]", _evidencia(1, "a"), tema="x"),
        _defasagem("[0] [1]", _evidencia(1, "b"), tema="y"),
    )
    assert any("ambíguo" in v for v in verificar_invariantes(r))


def test_evidencia_nao_posterior_viola_i3():
    r = _resposta(_defasagem("[0] [1]", _evidencia(publicado=date(2019, 6, 1))))
    assert any(v.startswith("I3") for v in verificar_invariantes(r))


def test_descarte_total_escondido_como_sem_achado_viola_i4():
    validacao = Validacao(validas=[], descartes=[Descarte(tema="t", motivo="x")])
    escondido = _resposta(status=StatusAnalise.SEM_ACHADO)
    assert any(v.startswith("I4") for v in verificar_invariantes(escondido, validacao))

    honesto = _resposta(
        status=StatusAnalise.ABSTIDO,
        motivo_abstencao=MotivoAbstencao.ALERTA_DESCARTADO,
    )
    assert verificar_invariantes(honesto, validacao) == []


# --- código de saída -----------------------------------------------------


def _meta(ok, dura):
    return {"metrica": "m", "ok": ok, "dura": dura}


def test_meta_dura_violada_trava_o_build():
    assert codigo_saida([_meta(True, True), _meta(False, True)]) == SAIDA_META_DURA


def test_meta_nao_dura_so_trava_com_estrito():
    metas = [_meta(True, True), _meta(False, False)]
    assert codigo_saida(metas) == SAIDA_OK
    assert codigo_saida(metas, estrito=True) == SAIDA_META_DURA


def test_meta_sem_casos_nao_trava():
    assert codigo_saida([_meta(None, True)], estrito=True) == SAIDA_OK


# --- execução ponta a ponta ----------------------------------------------


@pytest.fixture(scope="module")
def execucao(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("eval")
    resultados, painel = pasta / "results.json", pasta / "index.html"
    codigo = run_eval.main(["--resultados", str(resultados), "--painel", str(painel)])
    return codigo, json.loads(resultados.read_text(encoding="utf-8")), painel


def test_run_eval_retorna_zero_e_cumpre_as_metas(execucao):
    codigo, resultado, _ = execucao
    assert codigo == SAIDA_OK
    m = resultado["metricas"]
    assert m["alerta_sem_citacao"] == 0
    assert m["invariante_violada"] == 0
    assert m["taxa_falso_alarme"] <= 0.10
    assert m["taxa_deteccao"] >= 0.85
    assert m["custo_estimado_usd"] == 0
    assert resultado["metas_duras_ok"] is True
    assert len(resultado["casos"]) == 31


def test_painel_autocontido_com_dados_embutidos(execucao):
    _, resultado, painel = execucao
    html = painel.read_text(encoding="utf-8")
    assert run_eval.MARCADOR_DADOS not in html
    assert resultado["versao_indice"] in html
    for externo in ("<script src", "<link", "fetch(", "http://", "@import"):
        assert externo not in html


def test_painel_escapa_fechamento_de_script(tmp_path):
    destino = tmp_path / "p.html"
    gerar_painel({"nota": "</script><script>alert(1)</script>"}, destino)
    html = destino.read_text(encoding="utf-8")
    assert html.count("</script>") == 2  # só os do template


def test_dataset_com_objeto_fora_do_catalogo_e_invalido(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"itens": [
        {"id": "x", "objeto_id": "nao-existe", "classe": "defasado"}
    ]}), encoding="utf-8")
    codigo = run_eval.main([
        "--dataset", str(dataset),
        "--resultados", str(tmp_path / "r.json"),
        "--painel", str(tmp_path / "p.html"),
    ])
    assert codigo == SAIDA_INVALIDA
    assert not (tmp_path / "r.json").exists()


def test_api_serve_o_painel_gerado(execucao, monkeypatch):
    _, _, painel = execucao
    monkeypatch.setattr(routes_ops, "CAMINHO_PAINEL", painel)
    settings = Settings(mongo_uri="mongodb://127.0.0.1:1", mongo_timeout_ms=100)
    with TestClient(criar_app(settings)) as cliente:
        r = cliente.get("/painel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Currículo Vivo · Avaliação" in r.text

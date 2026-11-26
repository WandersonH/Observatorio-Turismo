"""Rodada completa e site, sem rede: coletores e malha falsos, dados sintéticos."""

import json

import pandas as pd
import pytest

from observatorio import armazenamento, execucao
from observatorio.cobertura import Cobertura
from observatorio.coletores.base import Coletor, Resultado
import importlib

site = importlib.import_module("observatorio.site.construir")


@pytest.fixture
def dados(tmp_path, monkeypatch):
    monkeypatch.setattr(armazenamento, "RAIZ_DADOS", tmp_path / "data")
    monkeypatch.delenv("OBS_BQ_PROJECT", raising=False)
    return tmp_path


class Falso(Coletor):
    fonte = "falsa"
    descricao = "coletor de teste"

    def coletar(self, **_):
        df = pd.DataFrame({"x": [1, 2]})
        return Resultado(tabelas={"t": df}, coberturas=[Cobertura("falsa", "t", 10, 2, "linhas")])


class Quebrado(Coletor):
    fonte = "quebrada"
    descricao = "coletor que falha"

    def coletar(self, **_):
        raise ConnectionError("fonte fora do ar")


def test_rodar_tudo_sinaliza_cada_situacao(dados, monkeypatch):
    catalogo = [
        {"id": "falsa", "nome": "Falsa", "status": "implementado"},
        {"id": "quebrada", "nome": "Quebrada", "status": "implementado"},
        {"id": "futura", "nome": "Futura", "status": "planejado"},
        {"id": "raspagem", "nome": "Raspagem", "status": "depende_de_decisao"},
    ]
    monkeypatch.setattr(execucao, "catalogo_fontes", lambda: catalogo)
    monkeypatch.setattr(execucao, "COLETORES", {"falsa": Falso, "quebrada": Quebrado})
    monkeypatch.setattr(execucao, "ORDEM", [])

    status = execucao.rodar_tudo()
    situacao = {f["id"]: f["situacao"] for f in status["fontes"]}
    assert situacao == {"falsa": "rodou", "quebrada": "falhou", "futura": "nao_implementado", "raspagem": "aguarda_decisao"}

    falsa = next(f for f in status["fontes"] if f["id"] == "falsa")
    assert falsa["coberturas"][0]["universo"] == 10 and falsa["coberturas"][0]["taxa"] == 0.2
    assert "fonte fora do ar" in next(f for f in status["fontes"] if f["id"] == "quebrada")["erro"]
    assert (armazenamento.RAIZ_DADOS / "status" / "status.json").exists()
    assert "FALHOU" in execucao.resumo(status)


def _cargas():
    cadastro = pd.DataFrame({
        "codigo_ibge": ["3500001", "3500002", "3500003"],
        "municipio": ["Alfa", "Beta", "Gama"],
        "populacao": [10000, 50000, 2000],
        "ano_populacao": ["2025"] * 3,
        "na_base_amitesp": [True, True, False],
        "regiao_turistica": ["R1", "R2", None],
        "regiao_administrativa": ["A", "B", "C"],
        "regiao_imediata": ["I"] * 3,
        "regiao_intermediaria": ["M"] * 3,
    })
    armazenamento.salvar(cadastro, "ibge", "cadastro_mestre", camada="tratado")
    contagem = pd.DataFrame({
        "codigo_ibge": ["3500001", "3500001", "3500002"],
        "categoria": ["Meios de Hospedagem", "Agência de Turismo", "Meios de Hospedagem"],
        "periodo": ["2026-10"] * 3,
        "estabelecimentos": [5, 3, 20],
        "leitos": [100, None, 800],
    })
    armazenamento.salvar(contagem, "cadastur", "contagem_municipio", camada="tratado")
    despesas = pd.DataFrame({
        "codigo_ibge": ["3500001", "3500002", "3500001"],
        "ano": [2025, 2025, 2024],
        "turismo_empenhado": [50000.0, None, 40000.0],
        "total_empenhado": [1e7, 5e7, 9e6],
        "participacao_turismo": [0.005, None, 0.0044],
        "turismo_per_capita": [5.0, None, 4.0],
    })
    armazenamento.salvar(despesas, "siconfi", "despesas_turismo", camada="tratado")


def test_site_publica_indicadores_e_nao_declarado(dados, monkeypatch):
    _cargas()
    monkeypatch.setattr(site, "_malha", lambda: {"type": "FeatureCollection", "features": []})
    saida = site.construir(dados / "_site")
    api = saida / "api" / "v1"

    municipios = {m["cod"]: m for m in json.loads((api / "municipios.json").read_text())}
    alfa, beta, gama = municipios["3500001"], municipios["3500002"], municipios["3500003"]
    assert alfa["hosp"] == 5 and alfa["hosp_10k"] == pytest.approx(5.0)
    assert alfa["cadastur_total"] == 8 and alfa["leitos_1k"] == pytest.approx(10.0)
    assert beta["tur_pc"] is None and beta["tur_declarado"] is False  # não declarado, não zero
    assert gama["tur_declarado"] is None  # sem DCA no ano
    assert alfa["pos_base_hosp_10k"] == 1 and gama["pos_base_hosp_10k"] is None

    detalhe = json.loads((api / "municipios" / "3500001.json").read_text())
    assert [s["ano"] for s in detalhe["siconfi"]] == [2024, 2025]
    assert detalhe["cadastur"]["categorias"][0]["categoria"] == "Meios de Hospedagem"

    indicadores = {i["id"]: i for i in json.loads((api / "indicadores.json").read_text())}
    assert indicadores["tur_pc"]["n_base"] == 1 and "2025" in indicadores["tur_pc"]["nome"]
    meta = json.loads((api / "meta.json").read_text())
    assert meta["municipios_base"] == 2 and meta["ano_siconfi"] == 2025
    status = json.loads((api / "status.json").read_text())
    assert all(f["situacao"] == "nao_executado" for f in status["fontes"])
    assert (saida / "index.html").read_text().startswith("<!DOCTYPE html>")
    # nenhum dado de estabelecimento vai para o site
    assert not any("cnpj" in p.read_text().lower() for p in api.rglob("*.json"))


def test_site_com_fontes_novas(dados, monkeypatch):
    _cargas()
    armazenamento.salvar(pd.DataFrame({
        "codigo_ibge": ["3500001"] * 3, "mes": ["2026-08", "2026-09", "2026-09"],
        "grupo": ["Alojamento", "Alojamento", "Alimentação"], "admissoes": [5, 3, 10], "desligamentos": [2, 4, 6],
        "saldo": [3, -1, 4]}), "caged", "emprego_act", camada="tratado")
    armazenamento.salvar(pd.DataFrame({
        "codigo_ibge": ["3500002"], "mes": ["2026-09"], "licencas_chegada": [10], "licencas_saida": [2],
        "passageiros_chegada": [400], "passageiros_saida": [60]}), "antt", "licencas_municipio", camada="tratado")
    armazenamento.salvar(pd.DataFrame({
        "codigo_ibge": ["3500001"], "ano": [2021], "ugrhi": [2], "residuos_t_dia": [20.5], "iqr_ano_anterior": [9.7],
        "iqr": [8.9], "destino": ["Jambeiro - A.P."], "iqr_adequado": [True]}), "cetesb", "iqr_municipio", camada="tratado")
    armazenamento.salvar(pd.DataFrame({
        "codigo_ibge": ["3500002"], "mes": ["2026-09"], "passageiros": [1000.0], "passageiros_domestica": [1000.0]}),
        "anac", "passageiros_municipio", camada="tratado")
    monkeypatch.setattr(site, "_malha", lambda: None)
    api = site.construir(dados / "_site") / "api" / "v1"
    municipios = {m["cod"]: m for m in json.loads((api / "municipios.json").read_text())}
    alfa, beta, gama = municipios["3500001"], municipios["3500002"], municipios["3500003"]
    assert alfa["emp_saldo"] == 6 and alfa["emp_adm"] == 18 and gama["emp_saldo"] == 0
    assert beta["frete_cheg"] == 10 and beta["frete_10k"] == pytest.approx(2.0)
    assert alfa["iqr"] == 8.9 and beta["iqr"] is None
    assert beta["pax_aereo"] == 1000 and alfa["pax_aereo"] is None  # sem aeroporto: sem dado, não zero
    detalhe = json.loads((api / "municipios" / "3500001.json").read_text())
    assert detalhe["caged_grupos"][0]["grupo"] == "Alimentação" and detalhe["cetesb"]["iqr"] == 8.9
    meta = json.loads((api / "meta.json").read_text())
    assert meta["caged_periodo"] == "2026-08 a 2026-09" and meta["cetesb_ano"] == 2021
    nomes = {i["id"]: i["nome"] for i in json.loads((api / "indicadores.json").read_text())}
    assert "(2021)" in nomes["iqr"] and "2026-08 a 2026-09" in nomes["emp_saldo"]

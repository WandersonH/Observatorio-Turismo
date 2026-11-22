import io

import pandas as pd
import pytest

from observatorio import armazenamento, qualidade
from observatorio.coletores.cadastur import contagem, ler_arquivo, periodo_do_recurso
from observatorio.coletores.siconfi import anos_padrao, despesas_turismo
from observatorio.normalizacao import chave_municipio, nome_coluna


@pytest.mark.parametrize("a, b", [
    ("Santa Clara d´Oeste", "Santa Clara d'Oeste"),
    ("Palmeira d’Oeste", "PALMEIRA D'OESTE"),
    ("São José dos Campos", "Sao Jose dos Campos"),
])
def test_chave_municipio_casa_grafias(a, b):
    assert chave_municipio(a) == chave_municipio(b)


def test_nome_coluna():
    assert nome_coluna("Município ") == "municipio"
    assert nome_coluna("Nº de Leitos") == "no_de_leitos"


@pytest.mark.parametrize("valor, esperado", [
    ("1.234,5", 1234.5), ("R$ 200", 200.0), ("6 mil", 6000.0), ("12.000", 12000.0),
    ("aprox 80", None), ("2 e 4", None), (7, 7.0), ("0", 0.0),
])
def test_para_numero(valor, esperado):
    assert qualidade.para_numero(valor) == esperado


def test_perfil_separa_zero_ausente_invalido():
    serie = pd.Series([100, 0, 0, 40, "Não informado", "Resposta inválida", None, 80])
    p = qualidade.perfil(serie)
    assert (p["valido"], p["zero"], p["ausente"], p["invalido"]) == (3, 2, 2, 1)
    assert p["media_sem_zeros"] == pytest.approx(73.333, rel=1e-3)
    assert p["media_com_zeros"] == pytest.approx(44.0)


def test_outlier_dos_hostels():
    serie = pd.Series(["1", "0", "5", "1000", "2", "1"])
    assert qualidade.outliers(serie).tolist() == ["1000"]


def test_soma_das_tipologias_de_eventos_nao_confere():
    assert not qualidade.soma_categorias_confere(3985, [1337, 1320, 826, 790, 711])


@pytest.mark.parametrize("nome, esperado", [
    ("Quarto Trimestre de 2025", (2025, 4)),
    ("Primeiro Trimestre 2020", (2020, 1)),
    ("2º Trimestre 2026", (2026, 2)),
    ("2014", (2014, 0)),
])
def test_periodo_do_recurso(nome, esperado):
    assert periodo_do_recurso(nome) == esperado


def test_ler_arquivo_acha_cabecalho_abaixo_do_titulo():
    csv = "Cadastur - Meios de Hospedagem;;\n;;\nUF;Município;Nº de Leitos\nSP;Itatiba;40\nMG;Extrema;12\n"
    df = ler_arquivo(csv.encode("latin-1"), "csv")
    assert list(df.columns) == ["uf", "municipio", "no_de_leitos"]
    assert len(df) == 2


def test_contagem_soma_leitos_so_onde_existe():
    df = pd.DataFrame({
        "codigo_ibge": ["3523404", "3523404", "3523404"],
        "categoria": ["Meios de Hospedagem", "Meios de Hospedagem", "Agências de Turismo"],
        "periodo": ["T1"] * 3,
        "n_de_leitos": ["40", "10", None],
    })
    c = contagem(df).set_index("categoria")
    assert c.loc["Meios de Hospedagem", "estabelecimentos"] == 2
    assert c.loc["Meios de Hospedagem", "leitos"] == 50
    assert pd.isna(c.loc["Agências de Turismo", "leitos"])


def test_despesas_turismo_separa_nao_declarado_de_zero():
    bruto = pd.DataFrame([
        {"cod_ibge": "1", "exercicio": 2024, "coluna": "Despesas Empenhadas", "conta": "Total Geral da Despesa", "valor": "1000"},
        {"cod_ibge": "1", "exercicio": 2024, "coluna": "Despesas Empenhadas", "conta": "23.695 - Turismo", "valor": "50"},
        {"cod_ibge": "1", "exercicio": 2024, "coluna": "Despesas Pagas", "conta": "23.695 - Turismo", "valor": "40"},
        {"cod_ibge": "2", "exercicio": 2024, "coluna": "Despesas Empenhadas", "conta": "10 - Saúde", "valor": "700"},
        {"cod_ibge": "2", "exercicio": 2024, "coluna": "Despesas Empenhadas", "conta": "12 - Educação", "valor": "300"},
    ])
    r = despesas_turismo(bruto).set_index("codigo_ibge")
    assert r.loc["1", "turismo_empenhado"] == 50 and r.loc["1", "participacao_turismo"] == 0.05
    assert pd.isna(r.loc["2", "turismo_empenhado"])
    assert r.loc["2", "total_empenhado"] == 1000 and r.loc["2", "metodo_total"] == "soma das funções"


def test_anos_padrao_respeita_prazo_da_dca():
    from datetime import date
    assert anos_padrao(date(2026, 11, 22)) == [2023, 2024, 2025]
    assert anos_padrao(date(2026, 3, 1)) == [2022, 2023, 2024]


def test_armazenamento_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(armazenamento, "RAIZ_DADOS", tmp_path)
    monkeypatch.delenv("OBS_BQ_PROJECT", raising=False)
    armazenamento.salvar(pd.DataFrame({"a": ["x"]}), "teste", "t", data_coleta="2026-01-01")
    armazenamento.salvar(pd.DataFrame({"a": ["y"]}), "teste", "t", data_coleta="2026-02-01")
    assert armazenamento.ler("teste", "t")["a"].tolist() == ["y"]
    assert armazenamento.ler("teste", "t", data_coleta="2026-01-01")["data_coleta"].tolist() == ["2026-01-01"]

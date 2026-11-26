"""Gera o site estático a partir das cargas tratadas.

Saída (pasta ``_site/``):
- ``index.html``: aplicação de página única (mapa, município, fontes, API, sobre);
- ``api/v1/*.json``: a mesma informação como API estática, uma rota por arquivo.

Só indicadores agregados por município são publicados; nenhum dado de estabelecimento.
Cada bloco é opcional: se uma fonte não rodou, o site sai sem ela e a página Fontes mostra o motivo.
"""

from __future__ import annotations

import json
import logging
import math
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd
import requests

from .. import armazenamento
from ..config import catalogo_fontes
from ..normalizacao import chave_municipio

log = logging.getLogger(__name__)

URL_MALHA = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/35"

CATEGORIAS_DESTAQUE = {
    "hosp": "meiosdehospedagem",
    "agencias": "agencia",
    "alimentacao": "restaurante",
    "eventos": "organizador",
    "transporte": "transportadora",
}

INDICADORES = [
    {"id": "hosp_10k", "nome": "Meios de hospedagem por 10 mil habitantes", "curto": "Hospedagem / 10 mil hab.",
     "unidade": "por 10 mil hab.", "fonte": "cadastur", "casas": 1},
    {"id": "cad_10k", "nome": "Prestadores turísticos formais por 10 mil habitantes", "curto": "Prestadores / 10 mil hab.",
     "unidade": "por 10 mil hab.", "fonte": "cadastur", "casas": 1},
    {"id": "leitos_1k", "nome": "Leitos em meios de hospedagem por mil habitantes", "curto": "Leitos / mil hab.",
     "unidade": "por mil hab.", "fonte": "cadastur", "casas": 1},
    {"id": "tur_pc", "nome": "Despesa empenhada em turismo por habitante", "curto": "Turismo R$/hab.",
     "unidade": "R$ por hab.", "fonte": "siconfi", "casas": 2},
    {"id": "tur_part", "nome": "Participação do turismo na despesa municipal", "curto": "Turismo % despesa",
     "unidade": "% da despesa", "fonte": "siconfi", "casas": 2},
    {"id": "pop", "nome": "População", "curto": "População", "unidade": "habitantes", "fonte": "ibge", "casas": 0},
]


def _limpo(valor):
    """Valores para JSON: NaN e NA viram null; tipos do numpy viram nativos."""
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(valor, "item"):
        return valor.item()
    return valor


def _ler(fonte: str, tabela: str, camada: str = "tratado") -> pd.DataFrame | None:
    try:
        return armazenamento.ler(fonte, tabela, camada=camada)
    except FileNotFoundError:
        log.warning("sem carga de %s/%s/%s", camada, fonte, tabela)
        return None


def _malha() -> dict | None:
    try:
        resposta = requests.get(URL_MALHA, params={"formato": "application/vnd.geo+json",
                                                    "intrarregiao": "municipio", "qualidade": "minima"}, timeout=120)
        resposta.raise_for_status()
        geo = resposta.json()
    except (requests.RequestException, ValueError) as erro:
        log.warning("malha do IBGE indisponível: %s", erro)
        return None

    def anel(pontos):
        saida = []
        for x, y in pontos:
            p = [round(x, 3), round(y, 3)]
            if not saida or saida[-1] != p:
                saida.append(p)
        return saida

    for f in geo["features"]:
        g = f["geometry"]
        if g["type"] == "Polygon":
            g["coordinates"] = [anel(a) for a in g["coordinates"]]
        elif g["type"] == "MultiPolygon":
            g["coordinates"] = [[anel(a) for a in poligono] for poligono in g["coordinates"]]
        f["properties"] = {"cod": str(f["properties"].get("codarea"))}
    return geo


def _categoria(nome: str) -> str | None:
    chave = chave_municipio(nome)
    for destaque, trecho in CATEGORIAS_DESTAQUE.items():
        if trecho in chave:
            return destaque
    return None


def _coberturas() -> list[dict]:
    linhas = []
    base = armazenamento.RAIZ_DADOS / "cobertura"
    for pasta_fonte in sorted(base.glob("*")):
        datas = sorted(pasta_fonte.glob("data_coleta=*"))
        if not datas:
            continue
        for arquivo in sorted(datas[-1].glob("*.parquet")):
            linhas.extend(pd.read_parquet(arquivo).to_dict("records"))
    return [{k: _limpo(v) for k, v in linha.items()} for linha in linhas]


def _status() -> dict:
    arquivo = armazenamento.RAIZ_DADOS / "status" / "status.json"
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8"))
    return {"data_coleta": None, "fontes": [{**f, "situacao": "nao_executado"} for f in catalogo_fontes()]}


def construir(saida: str | Path = "_site") -> Path:
    saida = Path(saida)
    if saida.exists():
        shutil.rmtree(saida)
    api = saida / "api" / "v1"
    (api / "municipios").mkdir(parents=True)

    cadastro = _ler("ibge", "cadastro_mestre")
    if cadastro is None:
        raise RuntimeError("o site precisa do cadastro mestre: rode `observatorio coletar ibge`")
    cadastro["populacao"] = pd.to_numeric(cadastro["populacao"], errors="coerce")
    cadastro["na_base_amitesp"] = cadastro["na_base_amitesp"].astype(str).str.lower().isin(["true", "1"])

    contagem = _ler("cadastur", "contagem_municipio")
    despesas = _ler("siconfi", "despesas_turismo")

    resumo = cadastro[["codigo_ibge", "municipio", "populacao", "ano_populacao", "na_base_amitesp",
                       "regiao_turistica", "regiao_administrativa", "regiao_imediata", "regiao_intermediaria"]].copy()
    resumo = resumo.set_index("codigo_ibge")
    categorias_por_mun: dict[str, list] = {}
    periodo_cadastur = None

    if contagem is not None and len(contagem):
        contagem = contagem.copy()
        for coluna in ("estabelecimentos", "leitos", "uhs"):
            if coluna in contagem:
                contagem[coluna] = pd.to_numeric(contagem[coluna], errors="coerce")
        contagem["destaque"] = contagem["categoria"].map(_categoria)
        periodo_cadastur = contagem["periodo"].dropna().astype(str).mode().iloc[0] if contagem["periodo"].notna().any() else None
        total = contagem.groupby("codigo_ibge")["estabelecimentos"].sum()
        resumo["cadastur_total"] = total.reindex(resumo.index).fillna(0)
        for destaque in CATEGORIAS_DESTAQUE:
            serie = contagem[contagem["destaque"] == destaque].groupby("codigo_ibge")["estabelecimentos"].sum()
            resumo[destaque] = serie.reindex(resumo.index).fillna(0)
        if "leitos" in contagem:
            leitos = contagem[contagem["destaque"] == "hosp"].groupby("codigo_ibge")["leitos"].sum(min_count=1)
            resumo["leitos"] = leitos.reindex(resumo.index)
        for cod, grupo in contagem.groupby("codigo_ibge"):
            categorias_por_mun[str(cod)] = sorted(
                ({k: _limpo(v) for k, v in r.items() if k in ("categoria", "estabelecimentos", "leitos", "uhs")}
                 for r in grupo.to_dict("records")),
                key=lambda r: -(r["estabelecimentos"] or 0))
        pop = resumo["populacao"]
        resumo["hosp_10k"] = resumo["hosp"] / pop * 1e4
        resumo["cad_10k"] = resumo["cadastur_total"] / pop * 1e4
        if "leitos" in resumo:
            resumo["leitos_1k"] = resumo["leitos"] / pop * 1e3

    series_siconfi: dict[str, list] = {}
    ano_siconfi = None
    if despesas is not None and len(despesas):
        despesas = despesas.copy()
        for coluna in ("ano", "turismo_empenhado", "total_empenhado", "participacao_turismo", "turismo_per_capita"):
            despesas[coluna] = pd.to_numeric(despesas[coluna], errors="coerce") if coluna in despesas else float("nan")
        ano_siconfi = int(despesas["ano"].max())
        ultimo = despesas[despesas["ano"] == ano_siconfi].set_index("codigo_ibge")
        resumo["tur_pc"] = ultimo["turismo_per_capita"].reindex(resumo.index)
        resumo["tur_part"] = (ultimo["participacao_turismo"] * 100).reindex(resumo.index)
        # True = declarou turismo; False = entregou a DCA sem turismo; None = sem DCA no ano
        declarado = ultimo["turismo_empenhado"].notna().astype(object)
        resumo["tur_declarado"] = declarado.reindex(resumo.index).astype(object).where(resumo.index.isin(ultimo.index), None)
        for cod, grupo in despesas.sort_values("ano").groupby("codigo_ibge"):
            series_siconfi[str(cod)] = [
                {"ano": int(r["ano"]), "turismo": _limpo(r["turismo_empenhado"]), "total": _limpo(r["total_empenhado"]),
                 "participacao": _limpo(r["participacao_turismo"]), "per_capita": _limpo(r["turismo_per_capita"])}
                for r in grupo.to_dict("records")]

    indicadores = [i for i in INDICADORES if i["id"] in resumo.columns]
    base = resumo["na_base_amitesp"]
    for ind in indicadores:
        coluna = resumo[ind["id"]].astype(float)
        ind["mediana_base"] = _limpo(coluna[base].median())
        ind["mediana_sp"] = _limpo(coluna.median())
        resumo[f"pos_base_{ind['id']}"] = coluna.where(base).rank(ascending=False, method="min")
        resumo[f"pos_sp_{ind['id']}"] = coluna.rank(ascending=False, method="min")
        ind["n_base"] = int(coluna[base].notna().sum())
        ind["n_sp"] = int(coluna.notna().sum())
    if ano_siconfi:
        for ind in indicadores:
            if ind["fonte"] == "siconfi":
                ind["nome"] += f" ({ano_siconfi})"

    linhas = []
    for cod, r in resumo.iterrows():
        linha = {"cod": cod, **{k: _limpo(v) for k, v in r.items()}}
        linhas.append(linha)
        detalhe = {**linha, "cadastur": {"periodo": periodo_cadastur, "categorias": categorias_por_mun.get(cod, [])},
                   "siconfi": series_siconfi.get(cod, [])}
        _gravar(api / "municipios" / f"{cod}.json", detalhe)

    status = _status()
    meta = {
        "titulo": "Observatório de Turismo da AMITESP",
        "data_coleta": status.get("data_coleta"),
        "periodo_cadastur": periodo_cadastur,
        "ano_siconfi": ano_siconfi,
        "municipios_sp": int(len(resumo)),
        "municipios_base": int(base.sum()),
        "repositorio": "https://github.com/WandersonH/observatorio-turismo",
    }
    _gravar(api / "municipios.json", linhas)
    _gravar(api / "indicadores.json", indicadores)
    _gravar(api / "status.json", status)
    _gravar(api / "cobertura.json", _coberturas())
    _gravar(api / "meta.json", meta)
    malha = _malha()
    if malha:
        _gravar(api / "malha_sp.geojson", malha)
    _gravar(api / "index.json", {
        "rotas": ["meta.json", "municipios.json", "municipios/{codigo_ibge}.json", "indicadores.json",
                  "status.json", "cobertura.json", "malha_sp.geojson"]})

    modelo = resources.files("observatorio.site").joinpath("modelo.html").read_text(encoding="utf-8")
    (saida / "index.html").write_text(modelo, encoding="utf-8")
    (saida / ".nojekyll").write_text("", encoding="utf-8")
    log.info("site gerado em %s (%d municípios)", saida, len(linhas))
    return saida


def _gravar(caminho: Path, conteudo) -> None:
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, separators=(",", ":"), default=_limpo), encoding="utf-8")

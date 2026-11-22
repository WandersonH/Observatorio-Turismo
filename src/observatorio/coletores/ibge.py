"""Cadastro mestre: os 645 municípios de SP (IBGE), população e marcação da base AMITESP.

Todas as outras fontes se ligam ao município pelo código IBGE de 7 dígitos.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests

from .. import armazenamento
from ..cobertura import Cobertura
from ..normalizacao import chave_municipio
from .base import Coletor, Resultado

log = logging.getLogger(__name__)

UF_SP = 35
URL_MUNICIPIOS = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF_SP}/municipios"
# Estimativas anuais de população; o Censo 2022 entra como reserva
SERIES_POPULACAO = [
    ("estimativa", "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324"),
    ("censo_2022", "https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/variaveis/93"),
]


def _arquivo_base() -> Path:
    """config/municipios_amitesp.csv: pela variável OBS_CONFIG, pela pasta atual ou pelo repositório."""
    candidatos = [Path(os.environ["OBS_CONFIG"])] if os.environ.get("OBS_CONFIG") else []
    candidatos += [Path.cwd() / "config", Path(__file__).resolve().parents[3] / "config"]
    for pasta in candidatos:
        if (pasta / "municipios_amitesp.csv").exists():
            return pasta / "municipios_amitesp.csv"
    raise FileNotFoundError("config/municipios_amitesp.csv não encontrado; defina OBS_CONFIG")


def base_amitesp() -> pd.DataFrame:
    base = pd.read_csv(_arquivo_base(), dtype={"id_formulario": "Int64"})
    base["chave"] = base["municipio"].map(chave_municipio)
    return base


def _municipios(sessao: requests.Session) -> pd.DataFrame:
    dados = sessao.get(URL_MUNICIPIOS, timeout=60).json()
    linhas = []
    for m in dados:
        imediata = m.get("regiao-imediata") or {}
        intermediaria = imediata.get("regiao-intermediaria") or {}
        linhas.append(
            {
                "codigo_ibge": str(m["id"]),
                "municipio": m["nome"],
                "regiao_imediata": imediata.get("nome"),
                "regiao_intermediaria": intermediaria.get("nome"),
            }
        )
    return pd.DataFrame(linhas)


def _populacao(sessao: requests.Session) -> tuple[pd.DataFrame, str]:
    for nome, url in SERIES_POPULACAO:
        try:
            resposta = sessao.get(url, params={"localidades": f"N6[N3[{UF_SP}]]"}, timeout=120)
            resposta.raise_for_status()
            series = resposta.json()[0]["resultados"][0]["series"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as erro:
            log.warning("série de população %s indisponível: %s", nome, erro)
            continue
        linhas = []
        for s in series:
            ano, valor = max(s["serie"].items())
            linhas.append({"codigo_ibge": str(s["localidade"]["id"]), "populacao": valor, "ano_populacao": ano})
        df = pd.DataFrame(linhas)
        df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce").astype("Int64")
        return df, nome
    raise RuntimeError("nenhuma série de população do IBGE respondeu")


class ColetorIBGE(Coletor):
    fonte = "ibge"
    descricao = "Municípios de SP, população e cadastro mestre da base AMITESP"

    def coletar(self, **_) -> Resultado:
        municipios = _municipios(self.sessao)
        populacao, serie = _populacao(self.sessao)
        cadastro = municipios.merge(populacao, on="codigo_ibge", how="left")
        cadastro["fonte_populacao"] = serie
        cadastro["chave"] = cadastro["municipio"].map(chave_municipio)

        base = base_amitesp()
        cadastro = cadastro.merge(
            base[["chave", "id_formulario", "regiao_turistica", "regiao_administrativa"]],
            on="chave",
            how="left",
        )
        cadastro["na_base_amitesp"] = cadastro["id_formulario"].notna()

        sem_par = sorted(set(base["chave"]) - set(cadastro["chave"]))
        notas = [f"sem correspondência no IBGE: {', '.join(sem_par)}"] if sem_par else []
        coberturas = [
            Cobertura(
                fonte=self.fonte,
                tabela="cadastro_mestre",
                universo=len(municipios),
                amostra=int(cadastro["populacao"].notna().sum()),
                unidade="municípios com população",
                notas=[f"série de população: {serie}"],
            ),
            Cobertura(
                fonte=self.fonte,
                tabela="base_amitesp",
                universo=len(base),
                amostra=int(cadastro["na_base_amitesp"].sum()),
                unidade="municípios da base casados ao IBGE",
                notas=notas,
            ),
        ]
        return Resultado(tabelas={"municipios": municipios, "populacao": populacao},
                         tratadas={"cadastro_mestre": cadastro}, coberturas=coberturas)


@lru_cache(maxsize=1)
def cadastro_mestre() -> pd.DataFrame:
    """Cadastro para os outros coletores: a carga local mais recente, ou uma consulta nova ao IBGE."""
    try:
        return armazenamento.ler("ibge", "cadastro_mestre", camada="tratado")
    except FileNotFoundError:
        return ColetorIBGE().coletar().tratadas["cadastro_mestre"]

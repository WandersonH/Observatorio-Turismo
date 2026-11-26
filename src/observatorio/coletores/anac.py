"""ANAC: passageiros desembarcados nos aeroportos de SP, por município do aeroporto.

Lê a série "Dados Estatísticos do Transporte Aéreo" (uma linha por empresa, mês e par de
aeroportos) e soma os passageiros pagos e grátis com destino a cada aeroporto paulista.
O aeroporto é ligado ao município pelo cadastro de aeródromos públicos da ANAC.

Limite: passageiro desembarcado não é turista; serve como proxy de acessibilidade aérea e
de fluxo, e os aeroportos atendem a região, não só o município sede.
"""

from __future__ import annotations

import io
import logging
import tempfile
from datetime import date

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import chave_municipio, nome_coluna
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

BASE = "https://sistemas.anac.gov.br/dadosabertos/"
SERIE = BASE + "Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/Dados%20Estat%C3%ADsticos%20do%20Transporte%20A%C3%A9reo/Dados_Estatisticos.csv"
AERODROMOS = BASE + "Aerodromos/Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv"
COLUNAS = ["ANO", "MES", "AEROPORTO_DE_DESTINO_SIGLA", "AEROPORTO_DE_DESTINO_NOME", "AEROPORTO_DE_DESTINO_UF",
           "NATUREZA", "GRUPO_DE_VOO", "PASSAGEIROS_PAGOS", "PASSAGEIROS_GRATIS", "DECOLAGENS"]


def _csv_anac(conteudo: bytes, **kwargs) -> pd.DataFrame:
    """Os CSVs da ANAC começam com uma linha 'Atualizado em: ...' e variam de codificação."""
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")
    pular = 1 if texto.lstrip().lower().startswith("atualizado") else 0
    return pd.read_csv(io.StringIO(texto), sep=";", skiprows=pular, dtype=str, **kwargs)


def aeroportos_sp(conteudo: bytes, mapa: dict[str, str]) -> pd.DataFrame:
    df = _csv_anac(conteudo)
    df.columns = [nome_coluna(c) for c in df.columns]
    col_oaci = next(c for c in df.columns if "oaci" in c or "icao" in c)
    col_mun = next(c for c in df.columns if c.startswith("municipio") and "servido" not in c)
    col_uf = next(c for c in df.columns if c == "uf")
    sp = df[df[col_uf].map(chave_municipio).isin(["sp", "saopaulo"])]
    saida = pd.DataFrame({"sigla": sp[col_oaci].str.strip().str.upper(), "municipio_aeroporto": sp[col_mun].str.strip()})
    saida["codigo_ibge"] = saida["municipio_aeroporto"].map(lambda n: mapa.get(chave_municipio(n)))
    return saida.dropna(subset=["sigla"]).drop_duplicates("sigla")


class ColetorANAC(Coletor):
    fonte = "anac"
    descricao = "Passageiros desembarcados nos aeroportos de SP (ANAC), mensal"

    def coletar(self, anos: list[int] | None = None, **_) -> Resultado:
        hoje = date.today()
        anos = [int(a) for a in (anos or range(hoje.year - 3, hoje.year + 1))]
        cadastro = cadastro_mestre()
        mapa = dict(zip(cadastro["municipio"].map(chave_municipio), cadastro["codigo_ibge"]))
        aeroportos = aeroportos_sp(self.get(AERODROMOS, timeout=120).content, mapa)

        partes, linhas_lidas = [], 0
        with tempfile.NamedTemporaryFile(suffix=".csv") as arquivo:
            self.baixar_arquivo(SERIE, arquivo.name)  # ~360 MB, com retomada
            with open(arquivo.name, encoding="utf-8-sig") as f:
                pular = 1 if f.readline().lower().startswith("atualizado") else 0
            for bloco in pd.read_csv(arquivo.name, sep=";", skiprows=pular, dtype=str, encoding="utf-8-sig",
                                     usecols=COLUNAS, chunksize=400_000):
                linhas_lidas += len(bloco)
                ano = pd.to_numeric(bloco["ANO"], errors="coerce")
                partes.append(bloco[(bloco["AEROPORTO_DE_DESTINO_UF"] == "SP") & ano.isin(anos)])
        voos = pd.concat(partes, ignore_index=True)
        voos.columns = [nome_coluna(c) for c in voos.columns]
        for c in ("passageiros_pagos", "passageiros_gratis", "decolagens"):
            voos[c] = pd.to_numeric(voos[c].str.replace(",", ".", regex=False), errors="coerce").fillna(0)
        voos["mes"] = voos["ano"].str.zfill(4) + "-" + voos["mes"].str.zfill(2)
        voos["passageiros"] = voos["passageiros_pagos"] + voos["passageiros_gratis"]

        por_aeroporto = (voos.groupby(["aeroporto_de_destino_sigla", "aeroporto_de_destino_nome", "mes", "natureza"],
                                      as_index=False)[["passageiros", "passageiros_pagos", "decolagens"]].sum()
                             .rename(columns={"aeroporto_de_destino_sigla": "sigla",
                                              "aeroporto_de_destino_nome": "aeroporto"}))
        por_aeroporto = por_aeroporto.merge(aeroportos[["sigla", "codigo_ibge", "municipio_aeroporto"]], on="sigla",
                                            how="left")
        sem_municipio = por_aeroporto["codigo_ibge"].isna()
        tratado = (por_aeroporto.dropna(subset=["codigo_ibge"])
                                .pivot_table(index=["codigo_ibge", "mes"], columns="natureza", values="passageiros",
                                             aggfunc="sum", fill_value=0))
        tratado.columns = [f"passageiros_{nome_coluna(c)}" for c in tratado.columns]
        tratado["passageiros"] = tratado.sum(axis=1)
        tratado = tratado.reset_index()

        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        universo = float(por_aeroporto["passageiros"].sum())
        cobertura = Cobertura(
            fonte=self.fonte, tabela="passageiros_municipio", universo=int(universo),
            amostra=int(por_aeroporto.loc[~sem_municipio, "passageiros"].sum()),
            unidade="passageiros desembarcados em SP ligados ao município do aeroporto",
            municipios_com_dado=len(set(tratado["codigo_ibge"]) & base), municipios_esperados=len(base),
            notas=[f"anos: {anos[0]} a {anos[-1]}; último mês: {voos['mes'].max()}",
                   f"aeroportos de SP com voo: {por_aeroporto['sigla'].nunique()}",
                   f"sem município no cadastro: {', '.join(sorted(por_aeroporto.loc[sem_municipio, 'sigla'].unique()))}",
                   f"linhas da série lidas: {linhas_lidas}"],
        )
        return Resultado(tabelas={"passageiros_aeroporto": por_aeroporto}, tratadas={"passageiros_municipio": tratado},
                         coberturas=[cobertura])

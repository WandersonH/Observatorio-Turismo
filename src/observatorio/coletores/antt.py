"""ANTT: licenças de viagem de fretamento eventual e turístico (interestadual e internacional).

Cada licença descreve uma viagem em trechos. Conta, por município de SP e mês, as licenças
com algum trecho terminando no município (chegadas) e as que partem dele (saídas), com os
passageiros declarados na licença. Viagens de "Transporte de Trabalhadores" ficam de fora.

Limite: só fretamento interestadual e internacional (regulado pela ANTT). O fretamento
dentro do estado é da ARTESP e não está aqui.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import chave_municipio, nome_coluna
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

API = "https://dados.antt.gov.br/api/3/action/package_show"
CONJUNTO = "sisaut-nacional-internacional"
MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}
EXCLUIR_TIPOS = ("transportedetrabalhadores",)
COLUNAS = ["numero_licenca_viagem", "data_inicio_viagem", "tipo_viagem", "tipo_veiculo", "municipio_origem",
           "uf_municipio_origem", "total_passageiros", "tipo_trecho", "sequencia_trecho", "uf_inicio_trecho",
           "municipio_inicio_trecho", "uf_final_trecho", "municipio_final_trecho", "granularidade"]


def mes_do_recurso(nome: str) -> tuple[int, int] | None:
    """'Licenças de Viagem - Out2026' -> (2026, 10)."""
    m = re.search(r"([A-Za-zç]{3})\s*(\d{4})\s*$", nome.strip())
    if not m or m.group(1).lower() not in MESES:
        return None
    return int(m.group(2)), MESES[m.group(1).lower()]


def ler_licencas(conteudo: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(conteudo), sep=";", encoding="latin-1", dtype=str, on_bad_lines="skip")
    df.columns = [nome_coluna(c) for c in df.columns]
    faltando = [c for c in COLUNAS if c not in df.columns]
    if faltando:
        raise ValueError(f"colunas ausentes no arquivo da ANTT: {faltando}")
    return df[COLUNAS].copy()


def movimentos(trechos: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Uma linha por licença e município de SP tocado: chegada (fim de trecho) ou saída (origem)."""
    df = trechos[~trechos["tipo_viagem"].map(chave_municipio).isin(EXCLUIR_TIPOS)].copy()
    df["passageiros"] = pd.to_numeric(df["total_passageiros"], errors="coerce")
    df["mes"] = pd.to_datetime(df["data_inicio_viagem"], format="%d/%m/%Y", errors="coerce").dt.strftime("%Y-%m")

    chegadas = df[df["uf_final_trecho"].str.strip().str.upper() == "SP"].copy()
    chegadas["codigo_ibge"] = chegadas["municipio_final_trecho"].map(lambda n: mapa.get(chave_municipio(n)))
    origem_chave = chegadas["municipio_origem"].map(chave_municipio)
    volta = (chegadas["municipio_final_trecho"].map(chave_municipio) == origem_chave) & \
            (chegadas["uf_municipio_origem"].str.upper() == "SP")
    chegadas = chegadas[~volta]  # o retorno ao ponto de partida não é chegada de visitante
    chegadas["sentido"] = "chegada"

    saidas = df[df["uf_municipio_origem"].str.strip().str.upper() == "SP"].copy()
    saidas["codigo_ibge"] = saidas["municipio_origem"].map(lambda n: mapa.get(chave_municipio(n)))
    saidas["sentido"] = "saida"

    juntos = pd.concat([chegadas, saidas], ignore_index=True)
    return juntos.drop_duplicates(["numero_licenca_viagem", "codigo_ibge", "sentido"])


def por_municipio(mov: pd.DataFrame) -> pd.DataFrame:
    validos = mov.dropna(subset=["codigo_ibge"])
    tabela = validos.pivot_table(index=["codigo_ibge", "mes"], columns="sentido",
                                 values=["numero_licenca_viagem", "passageiros"],
                                 aggfunc={"numero_licenca_viagem": "nunique", "passageiros": "sum"}, fill_value=0)
    tabela.columns = [f"{'licencas' if a == 'numero_licenca_viagem' else 'passageiros'}_{b}" for a, b in tabela.columns]
    for coluna in ("licencas_chegada", "licencas_saida", "passageiros_chegada", "passageiros_saida"):
        if coluna not in tabela:
            tabela[coluna] = 0
    return tabela.reset_index()


class ColetorANTT(Coletor):
    fonte = "antt"
    descricao = "Fretamento eventual e turístico interestadual (licenças de viagem ANTT), mensal"

    def recursos(self, meses: int) -> list[tuple[tuple[int, int], dict]]:
        pacote = self.get(API, params={"id": CONJUNTO}).json()["result"]
        por_mes: dict[tuple[int, int], dict] = {}
        for r in pacote["resources"]:
            periodo = mes_do_recurso(r.get("name", ""))
            if not periodo or not str(r.get("url", "")).lower().endswith(".csv"):
                continue
            atual = por_mes.get(periodo)
            if atual is None or (r.get("last_modified") or "") > (atual.get("last_modified") or ""):
                por_mes[periodo] = r
        return sorted(por_mes.items())[-meses:]

    def coletar(self, meses: int = 12, **_) -> Resultado:
        cadastro = cadastro_mestre()
        mapa = dict(zip(cadastro["municipio"].map(chave_municipio), cadastro["codigo_ibge"]))
        partes, lidos = [], []
        for (ano, mes), recurso in self.recursos(meses):
            trechos = ler_licencas(self.get(recurso["url"], timeout=300).content)
            sp = trechos[(trechos["uf_final_trecho"].str.upper() == "SP") |
                         (trechos["uf_municipio_origem"].str.upper() == "SP")]
            sp.insert(0, "arquivo", f"{ano}-{mes:02d}")
            partes.append(sp)
            lidos.append(f"{ano}-{mes:02d}")
            log.info("ANTT %d-%02d: %d trechos, %d tocam SP", ano, mes, len(trechos), len(sp))
        if not partes:
            raise RuntimeError("nenhum arquivo de licenças encontrado no CKAN da ANTT")
        bruto = pd.concat(partes, ignore_index=True)
        mov = movimentos(bruto, mapa)
        tratado = por_municipio(mov)

        sem_par = mov["codigo_ibge"].isna()
        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        chegada_base = set(tratado.loc[tratado["licencas_chegada"] > 0, "codigo_ibge"]) & base
        cobertura = Cobertura(
            fonte=self.fonte, tabela="licencas_municipio", universo=len(mov), amostra=int((~sem_par).sum()),
            unidade="pares licença-município de SP ligados ao IBGE",
            municipios_com_dado=len(chegada_base), municipios_esperados=len(base),
            notas=[f"meses: {lidos[0]} a {lidos[-1]}",
                   f"licenças distintas tocando SP: {mov['numero_licenca_viagem'].nunique()}",
                   "sem 'Transporte de Trabalhadores'; só fretamento interestadual e internacional",
                   f"nomes sem par no IBGE: {', '.join(sorted(mov.loc[sem_par, 'municipio_final_trecho'].dropna().unique())[:10])}"],
        )
        return Resultado(tabelas={"trechos_sp": bruto}, tratadas={"licencas_municipio": tratado},
                         coberturas=[cobertura])



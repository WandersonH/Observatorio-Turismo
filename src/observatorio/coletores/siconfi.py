"""Siconfi (Tesouro Nacional): despesas por função e subfunção declaradas pelos municípios.

Fonte da despesa empenhada em turismo (subfunção 695) usada pelo painel. Lê o Anexo I-E
da Declaração de Contas Anuais (DCA) pela API de dados abertos do Tesouro.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import chave_municipio
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"
ANEXO = "DCA-Anexo I-E"
COLUNA_EMPENHADO = "Despesas Empenhadas"
PAUSA_SEGUNDOS = 1.0
SUBFUNCAO_TURISMO = re.compile(r"^\s*23\.695\b")
FUNCAO = re.compile(r"^\s*\d{2}\s*-")


def anos_padrao(hoje: date | None = None) -> list[int]:
    """Os três últimos exercícios com DCA entregue (prazo legal: 30 de abril do ano seguinte)."""
    hoje = hoje or date.today()
    ultimo = hoje.year - 1 if hoje.month > 4 else hoje.year - 2
    return [ultimo - 2, ultimo - 1, ultimo]


class ColetorSiconfi(Coletor):
    fonte = "siconfi"
    descricao = "Despesas por função e subfunção (DCA Anexo I-E), anual"

    def _dca(self, codigo_ibge: str, ano: int) -> list[dict]:
        itens, offset = [], 0
        while True:
            resposta = self.get(API, params={"an_exercicio": ano, "no_anexo": ANEXO,
                                             "id_ente": codigo_ibge, "offset": offset}).json()
            itens.extend(resposta.get("items", []))
            if not resposta.get("hasMore"):
                return itens
            offset += resposta.get("limit") or len(resposta.get("items", []))
            time.sleep(PAUSA_SEGUNDOS)

    def coletar(self, anos: list[int] | None = None, todos: bool = False,
                anos_contexto: list[int] | None = None, **_) -> Resultado:
        """Base AMITESP em todos os `anos`; com `todos`, os demais municípios de SP em
        `anos_contexto` (padrão: os mesmos anos), que servem de grupo de comparação."""
        anos = [int(a) for a in (anos or anos_padrao())]
        cadastro = cadastro_mestre()
        na_base = cadastro["na_base_amitesp"].astype(bool)
        pares = [(c, a) for c in cadastro.loc[na_base, "codigo_ibge"] for a in anos]
        if todos:
            anos_fora = [int(a) for a in (anos_contexto or anos)]
            pares += [(c, a) for c in cadastro.loc[~na_base, "codigo_ibge"] for a in anos_fora]
        alvo = cadastro if todos else cadastro[na_base]

        linhas, falhas = [], []
        for codigo, ano in pares:
            try:
                linhas.extend(self._dca(str(codigo), ano))
            except Exception as erro:  # um município fora do ar não derruba a coleta
                falhas.append(f"{codigo}/{ano}: {erro}")
            time.sleep(PAUSA_SEGUNDOS)

        bruto = pd.DataFrame(linhas)
        if bruto.empty:
            raise RuntimeError(f"Siconfi não devolveu dados ({len(falhas)} falhas)")
        tratado = despesas_turismo(bruto, cadastro)

        esperados = len(pares)
        com_turismo = tratado["turismo_empenhado"].notna()
        coberturas = [Cobertura(
            fonte=self.fonte,
            tabela="dca_anexo_i_e",
            universo=esperados,
            amostra=len(tratado),
            unidade="pares município-ano com DCA entregue",
            municipios_com_dado=tratado["codigo_ibge"].nunique(),
            municipios_esperados=len(alvo),
            notas=[f"anos: {anos}",
                   f"pares com despesa em turismo declarada: {int(com_turismo.sum())}",
                   *falhas[:20]],
        )]
        return Resultado(tabelas={"dca_anexo_i_e": bruto}, tratadas={"despesas_turismo": tratado},
                        coberturas=coberturas)


def despesas_turismo(bruto: pd.DataFrame, cadastro: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por município e ano: empenhado em turismo, total e participação.

    Turismo sem linha na DCA fica vazio (não declarado), não zero.
    """
    df = bruto.copy()
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    empenhado = df[df["coluna"].astype(str).str.strip() == COLUNA_EMPENHADO]

    saida = []
    for (codigo, ano), grupo in empenhado.groupby(["cod_ibge", "exercicio"]):
        contas = grupo["conta"].astype(str)
        turismo = grupo.loc[contas.str.match(SUBFUNCAO_TURISMO), "valor"]
        total_geral = grupo.loc[contas.map(chave_municipio).str.contains("totalgeraldadespesa"), "valor"]
        if len(total_geral):
            total, metodo = float(total_geral.iloc[0]), "total geral da despesa"
        else:
            total, metodo = float(grupo.loc[contas.str.match(FUNCAO), "valor"].sum()), "soma das funções"
        valor_turismo = float(turismo.sum()) if len(turismo) else None
        saida.append({
            "codigo_ibge": str(codigo),
            "ano": int(ano),
            "turismo_empenhado": valor_turismo,
            "total_empenhado": total,
            "participacao_turismo": (valor_turismo / total) if valor_turismo is not None and total else None,
            "metodo_total": metodo,
        })
    resultado = pd.DataFrame(saida)
    if cadastro is not None and not resultado.empty:
        resultado = resultado.merge(cadastro[["codigo_ibge", "municipio", "populacao"]], on="codigo_ibge", how="left")
        resultado["turismo_per_capita"] = resultado["turismo_empenhado"] / resultado["populacao"].astype("Float64")
    return resultado

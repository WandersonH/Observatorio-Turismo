"""Governança municipal do turismo nos diários oficiais (Querido Diário).

Para cada município da base coberto pelo Querido Diário, conta as edições do diário oficial
que mencionam:
- plano diretor de turismo;
- conselho municipal de turismo (COMTUR);
- inventário turístico (inventário da oferta turística).

Guarda a data e o endereço da menção mais recente, para a equipe conferir o documento.
Uma menção não prova que o plano existe ou está vigente: é a pista para a verificação, e a
lista de verificados entra pela equipe do Prof. Edegar.

Limite: o Querido Diário não cobre todos os municípios nem todos os anos; município fora da
cobertura fica "sem dado", não "sem plano".
"""

from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd

from ..cobertura import Cobertura
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

APIS = ["https://api.queridodiario.ok.org.br", "https://api.queridodiario.org.br"]
TERMOS = {
    "plano_diretor": '"plano diretor de turismo"',
    "comtur": '"conselho municipal de turismo" | comtur',
    "inventario": '"inventário turístico" | "inventário da oferta turística"',
}
PAUSA = 1.1  # o projeto pede no máximo 60 requisições por minuto


class ColetorPlanosDiretores(Coletor):
    fonte = "planos_diretores"
    descricao = "Menções a plano diretor de turismo, COMTUR e inventário nos diários oficiais (Querido Diário)"

    def _api(self) -> str:
        ultimo = None
        for base in APIS:
            try:
                r = self.sessao.get(f"{base}/cities", params={"city_name": "Guararema"}, timeout=60)
                if r.ok:
                    return base
                ultimo = f"{base}: HTTP {r.status_code}"
            except Exception as erro:  # TLS, DNS ou tempo esgotado
                ultimo = f"{base}: {type(erro).__name__}"
        raise RuntimeError(f"API do Querido Diário indisponível ({ultimo})")

    def coletar(self, desde: str | None = None, **_) -> Resultado:
        desde = desde or f"{date.today().year - 6}-01-01"
        api = self._api()
        cadastro = cadastro_mestre()
        base = cadastro[cadastro["na_base_amitesp"].astype(bool)]
        cidades = self.get(f"{api}/cities", params={"city_name": ""}).json().get("cities", [])
        cobertos = {str(c["territory_id"]): c for c in cidades}

        linhas, mencoes = [], []
        for cod, nome in zip(base["codigo_ibge"], base["municipio"]):
            linha = {"codigo_ibge": cod, "municipio": nome, "no_querido_diario": cod in cobertos,
                     "disponivel_desde": (cobertos.get(cod) or {}).get("availability_date")}
            if cod in cobertos:
                for termo, consulta in TERMOS.items():
                    r = self.get(f"{api}/gazettes", params={
                        "territory_ids": cod, "querystring": consulta, "published_since": desde, "size": 3,
                        "excerpt_size": 300, "number_of_excerpts": 1, "sort_by": "descending_date"}).json()
                    linha[f"{termo}_edicoes"] = r.get("total_gazettes", 0)
                    diarios = r.get("gazettes", [])
                    linha[f"{termo}_ultima"] = diarios[0]["date"] if diarios else None
                    linha[f"{termo}_url"] = diarios[0].get("url") if diarios else None
                    mencoes += [{"codigo_ibge": cod, "termo": termo, "data": g.get("date"), "url": g.get("url"),
                                 "trecho": (g.get("excerpts") or [None])[0]} for g in diarios]
                    time.sleep(PAUSA)
            linhas.append(linha)

        tratado = pd.DataFrame(linhas)
        cobertos_base = int(tratado["no_querido_diario"].sum())
        com_plano = int((tratado.get("plano_diretor_edicoes", pd.Series(dtype=float)).fillna(0) > 0).sum())
        cobertura = Cobertura(
            fonte=self.fonte, tabela="governanca_municipio", universo=len(tratado), amostra=cobertos_base,
            unidade="municípios da base com diário no Querido Diário",
            municipios_com_dado=com_plano, municipios_esperados=len(tratado),
            notas=[f"edições desde {desde}", f"API: {api}",
                   "municipios_com_dado = municípios com menção a plano diretor de turismo"],
        )
        return Resultado(tabelas={"mencoes": pd.DataFrame(mencoes)}, tratadas={"governanca_municipio": tratado},
                         coberturas=[cobertura])

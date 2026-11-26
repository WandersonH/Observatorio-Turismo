"""CETESB: Índice de Qualidade de Aterro de Resíduos (IQR) e resíduos gerados, por município.

Fonte: o Inventário Estadual de Resíduos Sólidos Urbanos, publicado todo ano. O site da CETESB
bloqueia acesso automatizado; a coleta usa o Repositório Institucional da CETESB (DSpace), que
tem API pública, e o texto que o próprio repositório extrai do PDF.

Limite: o repositório recebe as edições com atraso; a nota de cobertura diz qual edição foi
lida. Qualidade das águas e balneabilidade ainda não entram.
"""

from __future__ import annotations

import logging
import re

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import texto_simples
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

API = "https://repositorio.cetesb.sp.gov.br/server/api"
BUSCA = "inventário estadual resíduos sólidos urbanos"
# Depois do nome: agência, UGRHI, toneladas/dia (duas casas), IQR do ano anterior e do ano (uma casa)
NUMEROS = re.compile(r"\s(\d{1,2})\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s+(\d{1,2},\d)\s+(\d{1,2},\d)(?=\s|$)")


def _numero(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def ler_tabela_iqr(texto: str, nomes: dict[str, str]) -> pd.DataFrame:
    """Linhas do anexo 'MUNICÍPIO Agência UGRHI t/dia IQR_ant IQR ...' -> uma linha por município."""
    ordenados = sorted(nomes, key=len, reverse=True)
    achados = {}
    for linha in texto.splitlines():
        simples = texto_simples(linha)
        nome = next((n for n in ordenados if simples.startswith(n + " ")), None)
        if not nome or nomes[nome] in achados:
            continue
        m = NUMEROS.search(linha)
        if not m:
            continue
        ugrhi, toneladas, iqr_anterior, iqr = m.groups()
        destino = re.sub(r"\s+", " ", linha[m.end():]).strip(" -")
        achados[nomes[nome]] = {"codigo_ibge": nomes[nome], "ugrhi": int(ugrhi), "residuos_t_dia": _numero(toneladas),
                                "iqr_ano_anterior": _numero(iqr_anterior), "iqr": _numero(iqr),
                                "destino": destino or None}
    df = pd.DataFrame(achados.values())
    if len(df):
        df["iqr_adequado"] = df["iqr"] > 7.0
    return df


class ColetorCETESB(Coletor):
    fonte = "cetesb"
    descricao = "IQR e resíduos sólidos urbanos por município (Inventário Estadual da CETESB), anual"

    def edicoes(self) -> list[tuple[int, str, str]]:
        js = self.get(f"{API}/discover/search/objects", params={"query": BUSCA, "dsoType": "ITEM", "size": 60}).json()
        saida = []
        for o in js["_embedded"]["searchResult"]["_embedded"]["objects"]:
            item = o["_embedded"]["indexableObject"]
            nome = item.get("name", "")
            ano = re.findall(r"(20\d\d)", nome)
            if ano and "nvent" in nome and "urbanos" in nome.lower():
                saida.append((int(ano[-1]), nome, item["uuid"]))
        return sorted(saida)

    def texto(self, uuid: str) -> str:
        bundles = self.get(f"{API}/core/items/{uuid}/bundles").json()["_embedded"]["bundles"]
        for nome_bundle in ("TEXT", "ORIGINAL"):
            for b in bundles:
                if b["name"] != nome_bundle:
                    continue
                for bs in self.get(b["_links"]["bitstreams"]["href"]).json()["_embedded"]["bitstreams"]:
                    conteudo = self.get(bs["_links"]["content"]["href"], timeout=300).content
                    if nome_bundle == "TEXT":
                        return conteudo.decode("utf-8", errors="replace")
                    if bs["name"].lower().endswith(".pdf"):
                        import io

                        import pdfplumber

                        with pdfplumber.open(io.BytesIO(conteudo)) as doc:
                            return "\n".join(p.extract_text() or "" for p in doc.pages)
        raise RuntimeError(f"edição {uuid} sem texto nem PDF no repositório")

    def coletar(self, **_) -> Resultado:
        cadastro = cadastro_mestre()
        nomes = {texto_simples(n): c for n, c in zip(cadastro["municipio"], cadastro["codigo_ibge"])}
        edicoes = self.edicoes()
        if not edicoes:
            raise RuntimeError("nenhuma edição do inventário encontrada no repositório da CETESB")
        ano, nome, uuid = edicoes[-1]
        tabela = ler_tabela_iqr(self.texto(uuid), nomes)
        tabela.insert(1, "ano", ano)
        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        cobertura = Cobertura(
            fonte=self.fonte, tabela="iqr_municipio", universo=len(cadastro), amostra=len(tabela),
            unidade="municípios de SP com IQR lido no inventário",
            municipios_com_dado=len(set(tabela["codigo_ibge"]) & base) if len(tabela) else 0,
            municipios_esperados=len(base),
            notas=[f"edição: {nome}", f"edições no repositório: {', '.join(str(e[0]) for e in edicoes)}",
                   "IQR > 7 = disposição adequada (metodologia CETESB)",
                   "municípios que dispõem resíduos em outro estado não têm IQR"],
        )
        return Resultado(tabelas={"iqr": tabela}, tratadas={"iqr_municipio": tabela}, coberturas=[cobertura])

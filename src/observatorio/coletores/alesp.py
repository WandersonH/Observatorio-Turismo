"""Alesp: proposituras sobre turismo e leis estaduais que citam municípios turísticos.

Lê os arquivos do Portal de Dados Abertos da Alesp (proposituras e normas, em XML compactado),
fica com os registros cuja ementa fala de turismo, estância turística ou município de interesse
turístico, e acha na ementa os municípios de SP citados.

O formato dos registros é lido de forma genérica (cada filho direto da raiz é um registro e seus
filhos são os campos), para não quebrar se a Alesp acrescentar campos.
"""

from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import LocalizadorMunicipios, nome_coluna, texto_simples
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

ARQUIVOS = {
    "proposituras": "https://www.al.sp.gov.br/repositorioDados/processo_legislativo/proposituras.zip",
    "normas": "https://www.al.sp.gov.br/repositorioDados/legislacao/legislacao_normas.zip",
}
TEMA = re.compile(r"\bturis|\bestancia|interesse turistico")
MIT = re.compile(r"municipio de interesse turistico")


def registros(conteudo_xml: bytes):
    """Percorre o XML sem carregar tudo: cada filho direto da raiz vira um dicionário de campos."""
    profundidade = 0
    atual: dict[str, str] | None = None
    for evento, el in ET.iterparse(io.BytesIO(conteudo_xml), events=("start", "end")):
        if evento == "start":
            profundidade += 1
            if profundidade == 2:
                atual = {}
            continue
        if profundidade == 3 and atual is not None:
            atual[nome_coluna(el.tag.split("}")[-1])] = (el.text or "").strip()
        if profundidade == 2 and atual is not None:
            yield atual
            atual = None
            el.clear()
        profundidade -= 1


def campo(registro: dict, *trechos: str) -> str:
    for chave, valor in registro.items():
        if any(t in chave for t in trechos):
            return valor
    return ""


class ColetorAlesp(Coletor):
    fonte = "alesp"
    descricao = "Proposituras e normas da Alesp sobre turismo, por município citado"

    def _baixar(self, url: str) -> bytes:
        resposta = self.sessao.get(url, timeout=600)
        if resposta.status_code == 503:
            raise RuntimeError(f"o Portal de Dados Abertos da Alesp respondeu 503 ao acesso automatizado ({url})")
        resposta.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as z:
            return z.read(z.namelist()[0])

    def coletar(self, **_) -> Resultado:
        cadastro = cadastro_mestre()
        localizador = LocalizadorMunicipios(dict(zip(cadastro["codigo_ibge"], cadastro["municipio"])))
        brutos, ligacoes, totais = {}, [], {}
        for tipo, url in ARQUIVOS.items():
            linhas, total = [], 0
            for reg in registros(self._baixar(url)):
                total += 1
                ementa = campo(reg, "ementa")
                simples = texto_simples(ementa)
                if not TEMA.search(simples):
                    continue
                reg["tipo_registro"] = tipo
                reg["classifica_mit"] = bool(MIT.search(simples))
                linhas.append(reg)
                for cod in localizador.achar(ementa):
                    ligacoes.append({"codigo_ibge": cod, "tipo": tipo, "classifica_mit": reg["classifica_mit"],
                                     "ano": campo(reg, "ano")[:4], "id": campo(reg, "iddocumento", "idnorma", "id"),
                                     "ementa": ementa})
            brutos[tipo] = pd.DataFrame(linhas)
            totais[tipo] = (total, len(linhas))
            log.info("Alesp %s: %d registros, %d sobre turismo", tipo, total, len(linhas))

        lig = pd.DataFrame(ligacoes)
        if len(lig):
            tratado = lig.pivot_table(index="codigo_ibge", columns="tipo", values="id", aggfunc="nunique",
                                      fill_value=0).add_prefix("alesp_").reset_index()
            mit = lig[lig["classifica_mit"]].groupby("codigo_ibge")["ano"].max().rename("ultima_lei_mit_ano")
            tratado = tratado.merge(mit, on="codigo_ibge", how="left")
        else:
            tratado = pd.DataFrame(columns=["codigo_ibge"])
        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        coberturas = [Cobertura(
            fonte=self.fonte, tabela=tipo, universo=total, amostra=sobre_turismo,
            unidade=f"{tipo} sobre turismo no arquivo completo",
            municipios_com_dado=len(set(lig.loc[lig["tipo"] == tipo, "codigo_ibge"]) & base) if len(lig) else 0,
            municipios_esperados=len(base),
            notas=["filtro na ementa: turis*, estância, interesse turístico"],
        ) for tipo, (total, sobre_turismo) in totais.items()]
        return Resultado(tabelas={**brutos, "citacoes": lig}, tratadas={"alesp_municipio": tratado},
                         coberturas=coberturas)

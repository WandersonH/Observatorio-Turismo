"""Notícias (Google Notícias) e produção acadêmica (OpenAlex) sobre turismo em cada município da base.

- Google Notícias: feed RSS da busca `"<município>" turismo SP`, últimos 30 dias. O feed devolve
  no máximo 100 itens; a contagem é um piso, não um total.
- OpenAlex: trabalhos acadêmicos com o nome do município e "turismo" ou "tourism" no título,
  resumo ou texto. Sem chave, a OpenAlex dá um orçamento diário pequeno por IP; com o segredo
  OPENALEX_API_KEY o limite sobe. Municípios não consultados ficam marcados, não zerados.

Limite: nomes que também são palavras ou acidentes geográficos (Bocaina, Socorro, Brotas)
trazem menções que não são do município. Os números são de visibilidade, não de produção
validada; a tabela bruta guarda títulos para conferência.
"""

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from ..cobertura import Cobertura
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

RSS = "https://news.google.com/rss/search"
OPENALEX = "https://api.openalex.org/works"
PAUSA = 1.5


def itens_rss(xml: str) -> list[dict]:
    raiz = ET.fromstring(xml)
    saida = []
    for item in raiz.iter("item"):
        fonte = item.find("source")
        data = item.findtext("pubDate")
        saida.append({
            "titulo": item.findtext("title"),
            "link": item.findtext("link"),
            "veiculo": fonte.text if fonte is not None else None,
            "publicado": parsedate_to_datetime(data).date().isoformat() if data else None,
        })
    return saida


class ColetorProducoes(Coletor):
    fonte = "producoes"
    descricao = "Notícias (Google Notícias, 30 dias) e trabalhos acadêmicos (OpenAlex) por município"

    def noticias(self, municipio: str) -> list[dict]:
        consulta = f'"{municipio}" turismo SP when:30d'
        for espera in (0, 30, 90):  # o Google responde 429 quando as consultas vêm rápido demais
            time.sleep(espera)
            r = self.sessao.get(RSS, params={"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}, timeout=60)
            if r.status_code != 429:
                break
        r.raise_for_status()
        return itens_rss(r.text)

    def academicos(self, municipio: str, chave: str | None) -> tuple[int | None, list[dict], str | None]:
        params = {"search": f'"{municipio}" AND (turismo OR tourism)', "per-page": 10,
                  "sort": "publication_date:desc", "mailto": "observatorio.turismo@usp.br"}
        if chave:
            params["api_key"] = chave
        r = self.sessao.get(OPENALEX, params=params, timeout=60)
        if r.status_code in (402, 429):
            return None, [], f"OpenAlex recusou ({r.status_code}): orçamento diário esgotado"
        r.raise_for_status()
        js = r.json()
        obras = [{"titulo": w.get("title"), "ano": w.get("publication_year"), "doi": w.get("doi"),
                  "tipo": w.get("type")} for w in js.get("results", [])]
        return js.get("meta", {}).get("count"), obras, None

    def coletar(self, todos: bool = False, **_) -> Resultado:
        cadastro = cadastro_mestre()
        alvo = cadastro if todos else cadastro[cadastro["na_base_amitesp"].astype(bool)]
        chave = os.environ.get("OPENALEX_API_KEY") or None
        linhas, noticias, obras = [], [], []
        openalex_parou = None
        for cod, nome in zip(alvo["codigo_ibge"], alvo["municipio"]):
            linha = {"codigo_ibge": cod, "municipio": nome}
            try:
                itens = self.noticias(nome)
                linha["noticias_30d"] = len(itens)
                noticias += [{"codigo_ibge": cod, **i} for i in itens]
            except (requests.RequestException, ET.ParseError) as erro:
                log.warning("Google Notícias %s: %s", nome, erro)
                linha["noticias_30d"] = None
            if openalex_parou is None:
                try:
                    total, lista, motivo = self.academicos(nome, chave)
                    if motivo:
                        openalex_parou = motivo
                    linha["trabalhos_academicos"] = total
                    obras += [{"codigo_ibge": cod, **o} for o in lista]
                except requests.RequestException as erro:
                    log.warning("OpenAlex %s: %s", nome, erro)
                    linha["trabalhos_academicos"] = None
            else:
                linha["trabalhos_academicos"] = None
            linhas.append(linha)
            time.sleep(PAUSA)

        tratado = pd.DataFrame(linhas)
        com_noticia = tratado["noticias_30d"].notna()
        com_openalex = tratado["trabalhos_academicos"].notna()
        coberturas = [
            Cobertura(fonte=self.fonte, tabela="noticias", universo=len(tratado), amostra=int(com_noticia.sum()),
                      unidade="municípios consultados no Google Notícias",
                      municipios_com_dado=int((tratado["noticias_30d"].fillna(0) > 0).sum()),
                      municipios_esperados=len(tratado),
                      notas=[f"notícias lidas: {len(noticias)}", "janela: 30 dias; teto de 100 por município"]),
            Cobertura(fonte=self.fonte, tabela="academicos", universo=len(tratado), amostra=int(com_openalex.sum()),
                      unidade="municípios consultados na OpenAlex",
                      municipios_com_dado=int((tratado["trabalhos_academicos"].fillna(0) > 0).sum()),
                      municipios_esperados=len(tratado),
                      notas=[openalex_parou or "todos consultados",
                             "com chave OPENALEX_API_KEY" if chave else "sem chave (orçamento diário compartilhado)"]),
        ]
        return Resultado(tabelas={"noticias": pd.DataFrame(noticias), "academicos": pd.DataFrame(obras)},
                         tratadas={"producoes_municipio": tratado}, coberturas=coberturas)

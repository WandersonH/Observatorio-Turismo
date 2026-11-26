"""Google Places API (New): pareamento dos meios de hospedagem do Cadastur com o Google,
com nota e número de avaliações, nos municípios da base.

Para cada estabelecimento de hospedagem do Cadastur num município da base, faz uma busca de
texto ("<nome> <município> SP") e aceita o primeiro resultado só se o endereço tiver o nome do
município e o nome do lugar for parecido com o do Cadastur. Depois, uma busca "hotel pousada em
<município>" por município mede quanto da oferta visível no Google não está no Cadastur.

Credencial: segredo GOOGLE_PLACES_API_KEY (Google Cloud, Places API (New) ativada).
Custo: a busca de texto com nota e avaliações é cobrada por mil chamadas, com cota gratuita
mensal; o teto de chamadas por rodada é o parâmetro `max_consultas`.
"""

from __future__ import annotations

import logging
import os
import time
from difflib import SequenceMatcher

import pandas as pd

from .. import armazenamento
from ..cobertura import Cobertura
from ..normalizacao import chave_municipio, texto_simples
from .base import Coletor, FaltaCredencial, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

URL = "https://places.googleapis.com/v1/places:searchText"
CAMPOS = ",".join(["places.id", "places.displayName", "places.formattedAddress", "places.location", "places.types",
                   "places.rating", "places.userRatingCount", "places.businessStatus", "places.primaryType"])
SIMILARIDADE_MINIMA = 0.6
PAUSA = 0.2


def similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, texto_simples(a), texto_simples(b)).ratio()


def coluna_nome(df: pd.DataFrame) -> str:
    for preferida in ("nome_fantasia", "nome", "razao_social"):
        achada = next((c for c in df.columns if preferida in c), None)
        if achada:
            return achada
    raise ValueError(f"coluna de nome não encontrada no Cadastur: {list(df.columns)}")


class ColetorGooglePlaces(Coletor):
    fonte = "google_places"
    descricao = "Hospedagens do Cadastur pareadas no Google (nota e avaliações) e oferta fora do Cadastur"

    def buscar(self, chave: str, texto: str, maximo: int = 1) -> list[dict]:
        r = self.sessao.post(URL, json={"textQuery": texto, "languageCode": "pt-BR", "regionCode": "BR",
                                        "pageSize": maximo},
                             headers={"X-Goog-Api-Key": chave, "X-Goog-FieldMask": CAMPOS}, timeout=60)
        r.raise_for_status()
        return r.json().get("places", [])

    def coletar(self, max_consultas: int = 900, **_) -> Resultado:
        chave = os.environ.get("GOOGLE_PLACES_API_KEY")
        if not chave:
            raise FaltaCredencial("GOOGLE_PLACES_API_KEY")
        cadastro = cadastro_mestre()
        base = cadastro[cadastro["na_base_amitesp"].astype(bool)]
        try:
            hosp = armazenamento.ler("cadastur", "meios_de_hospedagem")
        except FileNotFoundError as erro:
            raise RuntimeError("rode o Cadastur antes: o pareamento parte dos meios de hospedagem") from erro
        hosp = hosp[hosp["codigo_ibge"].isin(set(base["codigo_ibge"]))]
        nome_col = coluna_nome(hosp)
        nomes_mun = dict(zip(cadastro["codigo_ibge"], cadastro["municipio"]))

        pares, consultas = [], 0
        for _, est in hosp.iterrows():
            if consultas >= max_consultas:
                break
            municipio = nomes_mun[est["codigo_ibge"]]
            achado = (self.buscar(chave, f"{est[nome_col]} {municipio} SP") or [None])[0]
            consultas += 1
            linha = {"codigo_ibge": est["codigo_ibge"], "nome_cadastur": est[nome_col], "pareado": False}
            if achado:
                nome_google = (achado.get("displayName") or {}).get("text", "")
                endereco = achado.get("formattedAddress", "")
                sim = similaridade(est[nome_col], nome_google)
                linha.update({"place_id": achado.get("id"), "nome_google": nome_google, "similaridade": round(sim, 2),
                              "nota": achado.get("rating"), "avaliacoes": achado.get("userRatingCount"),
                              "situacao": achado.get("businessStatus")})
                linha["pareado"] = sim >= SIMILARIDADE_MINIMA and chave_municipio(municipio) in chave_municipio(endereco)
            pares.append(linha)
            time.sleep(PAUSA)

        oferta = []
        for cod in base["codigo_ibge"]:
            if consultas >= max_consultas:
                break
            municipio = nomes_mun[cod]
            lugares = self.buscar(chave, f"hotel pousada hospedagem em {municipio} SP", maximo=20)
            consultas += 1
            no_municipio = [p for p in lugares if chave_municipio(municipio) in chave_municipio(p.get("formattedAddress", ""))]
            oferta.append({"codigo_ibge": cod, "hospedagens_google": len(no_municipio),
                           "ids_google": [p.get("id") for p in no_municipio]})
            time.sleep(PAUSA)

        pares_df = pd.DataFrame(pares)
        oferta_df = pd.DataFrame(oferta)
        if len(pares_df):
            pareados = pares_df[pares_df["pareado"]]
            resumo = pareados.groupby("codigo_ibge").agg(hosp_pareadas=("place_id", "count"),
                                                          nota_mediana=("nota", "median"),
                                                          avaliacoes_total=("avaliacoes", "sum")).reset_index()
            ids_cadastur = pareados.groupby("codigo_ibge")["place_id"].agg(set)
        else:
            resumo, ids_cadastur = pd.DataFrame(columns=["codigo_ibge"]), pd.Series(dtype=object)
        if len(oferta_df):
            oferta_df["fora_do_cadastur"] = [len(set(ids) - ids_cadastur.get(c, set()))
                                             for c, ids in zip(oferta_df["codigo_ibge"], oferta_df["ids_google"])]
            oferta_df = oferta_df.drop(columns=["ids_google"])
        tratado = oferta_df.merge(resumo, on="codigo_ibge", how="outer") if len(oferta_df) else resumo

        cobertura = Cobertura(
            fonte=self.fonte, tabela="pareamento_hospedagem", universo=len(hosp),
            amostra=int(pares_df["pareado"].sum()) if len(pares_df) else 0,
            unidade="hospedagens do Cadastur na base pareadas no Google",
            municipios_com_dado=int(tratado["codigo_ibge"].nunique()) if len(tratado) else 0,
            municipios_esperados=len(base),
            notas=[f"consultas: {consultas} (teto {max_consultas})", f"pares tentados: {len(pares_df)}",
                   f"similaridade mínima: {SIMILARIDADE_MINIMA}"],
        )
        # Termos do Google: só o place_id pode ficar guardado; nota e avaliações saem só agregadas
        guardar = [c for c in ("codigo_ibge", "nome_cadastur", "place_id", "similaridade", "pareado") if c in pares_df]
        return Resultado(tabelas={"pares": pares_df[guardar]}, tratadas={"google_municipio": tratado},
                         coberturas=[cobertura])

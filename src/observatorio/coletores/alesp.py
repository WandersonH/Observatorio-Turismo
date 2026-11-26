"""Alesp: classificação oficial dos municípios turísticos e proposituras sobre turismo.

1. Classificação (sempre): o texto compilado da Lei nº 17.469/2021, que consolida a legislação
   que classifica os municípios turísticos, publicado no repositório de legislação da Alesp.
   O Anexo I traz as Estâncias Turísticas e o Anexo II os Municípios de Interesse Turístico,
   cada um na ordem do ranqueamento trienal (LC 1.261/2015, art. 5º, § 2º). Trechos riscados
   no texto compilado (revogados) são descartados.
2. Proposituras e normas (quando o portal responde): os arquivos do Portal de Dados Abertos,
   filtrados pela ementa (turismo, estância, interesse turístico), com os municípios citados.
   Esse portal responde 503 a acessos automatizados vindos de servidores de nuvem; quando isso
   acontece, a fonte roda em parte e o aviso aparece na página de fontes.
"""

from __future__ import annotations

import html
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import LocalizadorMunicipios, chave_municipio, nome_coluna, texto_simples
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

LEI_CONSOLIDADA = ("https://www.al.sp.gov.br/repositorio/legislacao/lei/2021/"
                   "compilacao-lei-17469-13.12.2021.html")
ARQUIVOS = {
    "proposituras": "https://www.al.sp.gov.br/repositorioDados/processo_legislativo/proposituras.zip",
    "normas": "https://www.al.sp.gov.br/repositorioDados/legislacao/legislacao_normas.zip",
}
ANEXOS = {"I": "Estância Turística", "II": "Município de Interesse Turístico"}
TEMA = re.compile(r"\bturis|\bestancia|interesse turistico")
MIT = re.compile(r"municipio de interesse turistico")


def _texto(fragmento: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragmento))).strip()


def ler_classificacao(pagina: str) -> tuple[pd.DataFrame, str | None]:
    """Tabelas dos Anexos I e II do texto compilado -> (categoria, posição, município); e a última atualização."""
    vigente = re.sub(r"<s>.*?</s>", " ", pagina, flags=re.S | re.I)  # riscado = revogado
    atualizacao = re.search(r"[ÚU]ltima atualiza[çc][ãa]o:\s*([^)]+)\)", _texto(vigente[:20000]))
    linhas = []
    marcas = list(re.finditer(r"ANEXO\s+(II|I)\b", vigente))
    for i, marca in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(vigente)
        tabela = re.search(r"<table.*?</table>", vigente[marca.start():fim], re.S | re.I)
        if not tabela:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tabela.group(0), re.S | re.I):
            celulas = [_texto(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
            if len(celulas) >= 2 and re.fullmatch(r"\d+\.?", celulas[0]):
                linhas.append({"categoria_turistica": ANEXOS[marca.group(1)],
                               "posicao_ranking": int(celulas[0].rstrip(".")), "municipio_lei": celulas[1]})
    return pd.DataFrame(linhas), (atualizacao.group(1).strip() if atualizacao else None)


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
    descricao = "Classificação oficial de estâncias e MITs (ranking) e proposituras da Alesp sobre turismo"

    def _baixar_zip(self, url: str) -> bytes:
        resposta = self.sessao.get(url, timeout=600)
        if resposta.status_code == 503:
            raise ConnectionRefusedError("o Portal de Dados Abertos da Alesp respondeu 503 ao acesso automatizado")
        resposta.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resposta.content)) as z:
            return z.read(z.namelist()[0])

    def classificacao(self, mapa: dict[str, str]) -> tuple[pd.DataFrame, Cobertura]:
        resposta = self.get(LEI_CONSOLIDADA, timeout=120)
        pagina = resposta.content.decode(resposta.apparent_encoding or "latin-1", errors="replace")
        tabela, atualizacao = ler_classificacao(pagina)
        if tabela.empty:
            raise RuntimeError("anexos de classificação não encontrados no texto compilado da Lei 17.469/2021")
        tabela["codigo_ibge"] = tabela["municipio_lei"].map(lambda n: mapa.get(chave_municipio(n)))
        tabela["total_categoria"] = tabela.groupby("categoria_turistica")["posicao_ranking"].transform("count")
        tabela["fonte_legal"] = f"Lei 17.469/2021, texto compilado (última atualização: {atualizacao or 'n/d'})"
        sem_par = tabela["codigo_ibge"].isna()
        contagem = tabela["categoria_turistica"].value_counts().to_dict()
        cobertura = Cobertura(
            fonte=self.fonte, tabela="classificacao", universo=len(tabela), amostra=int((~sem_par).sum()),
            unidade="municípios turísticos da lei ligados ao IBGE",
            notas=[f"última atualização: {atualizacao}", f"por categoria: {contagem}",
                   f"sem par no IBGE: {', '.join(tabela.loc[sem_par, 'municipio_lei'])}" if sem_par.any()
                   else "todos com par"],
        )
        return tabela, cobertura

    def proposituras(self, localizador: LocalizadorMunicipios) -> tuple[dict, pd.DataFrame, list[Cobertura]]:
        brutos, ligacoes, coberturas = {}, [], []
        for tipo, url in ARQUIVOS.items():
            linhas, total = [], 0
            for reg in registros(self._baixar_zip(url)):
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
            coberturas.append(Cobertura(fonte=self.fonte, tabela=tipo, universo=total, amostra=len(linhas),
                                        unidade=f"{tipo} sobre turismo no arquivo completo",
                                        notas=["filtro na ementa: turis*, estância, interesse turístico"]))
        return brutos, pd.DataFrame(ligacoes), coberturas

    def coletar(self, **_) -> Resultado:
        cadastro = cadastro_mestre()
        mapa = dict(zip(cadastro["municipio"].map(chave_municipio), cadastro["codigo_ibge"]))
        classificacao, cob_classificacao = self.classificacao(mapa)
        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        na_lei = set(classificacao["codigo_ibge"].dropna())
        cob_classificacao.municipios_com_dado = len(na_lei & base)
        cob_classificacao.municipios_esperados = len(base)
        fora = cadastro[cadastro["codigo_ibge"].isin(base - na_lei)]["municipio"].sort_values()
        cob_classificacao.notas.append(f"da base AMITESP fora dos anexos da lei ({len(fora)}): {', '.join(fora)}")

        tratado = classificacao.dropna(subset=["codigo_ibge"])[
            ["codigo_ibge", "categoria_turistica", "posicao_ranking", "total_categoria", "fonte_legal"]]
        tabelas, coberturas, avisos = {"classificacao": classificacao}, [cob_classificacao], []
        try:
            brutos, lig, cob_prop = self.proposituras(
                LocalizadorMunicipios(dict(zip(cadastro["codigo_ibge"], cadastro["municipio"]))))
            tabelas.update({**brutos, "citacoes": lig})
            coberturas += cob_prop
            if len(lig):
                contagem = lig.pivot_table(index="codigo_ibge", columns="tipo", values="id", aggfunc="nunique",
                                           fill_value=0).add_prefix("alesp_").reset_index()
                tratado = tratado.merge(contagem, on="codigo_ibge", how="outer")
        except (ConnectionRefusedError, OSError, zipfile.BadZipFile) as erro:
            log.warning("Alesp, proposituras: %s", erro)
            avisos.append(f"proposituras e normas: {erro}")
        return Resultado(tabelas=tabelas, tratadas={"alesp_municipio": tratado}, coberturas=coberturas, avisos=avisos)

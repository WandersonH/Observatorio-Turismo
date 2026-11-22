"""Cadastur: prestadores de serviços turísticos formais, arquivos trimestrais do MTur.

Lê o portal de dados abertos do Ministério do Turismo (CKAN), escolhe o arquivo mais
recente de cada categoria, filtra São Paulo e liga cada linha ao código IBGE.

Guias de turismo ficam fora por padrão: são pessoas físicas.
Colunas de contato (e-mail, telefone, CPF) são descartadas na leitura.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd

from ..cobertura import Cobertura
from ..normalizacao import chave_municipio, nome_coluna
from ..qualidade import para_numero
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

API = "https://dados.turismo.gov.br/api/3/action"
BUSCA = "prestadores de serviços turísticos"
CONJUNTO_GARANTIDO = "meios-de-hospedagem"
EXCLUIR_POR_PADRAO = ("guia",)
COLUNAS_PESSOAIS = re.compile(r"e_?mail|telefone|celular|fone|whats|cpf|responsavel")
ORDINAIS = {"primeiro": 1, "segundo": 2, "terceiro": 3, "quarto": 4, "1": 1, "2": 2, "3": 3, "4": 4}


def periodo_do_recurso(nome: str) -> tuple[int, int]:
    """("Quarto Trimestre de 2025") -> (2025, 4); ano sem trimestre -> (ano, 0)."""
    texto = chave_municipio(nome)  # sem acento e sem espaço
    ano = re.search(r"(20\d{2})", texto)
    trimestre = re.search(r"(primeiro|segundo|terceiro|quarto|[1-4])(o|º)?trimestre", texto)
    return (int(ano.group(1)) if ano else 0, ORDINAIS.get(trimestre.group(1), 0) if trimestre else 0)


def _achar_cabecalho(bruto: pd.DataFrame) -> int:
    for i in range(min(20, len(bruto))):
        valores = [nome_coluna(v) for v in bruto.iloc[i].tolist() if pd.notna(v)]
        if any("munic" in v for v in valores):
            return i
    return 0


def ler_arquivo(conteudo: bytes, formato: str) -> pd.DataFrame:
    formato = (formato or "").lower()
    if "xls" in formato:
        bruto = pd.read_excel(io.BytesIO(conteudo), header=None, dtype=str)
    else:
        bruto = None
        for codificacao in ("utf-8-sig", "latin-1"):
            try:
                bruto = pd.read_csv(io.BytesIO(conteudo), header=None, dtype=str, sep=None,
                                    engine="python", encoding=codificacao)
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        if bruto is None:
            raise ValueError("arquivo CSV ilegível")
    linha = _achar_cabecalho(bruto)
    tabela = bruto.iloc[linha + 1:].reset_index(drop=True)
    tabela.columns = [nome_coluna(c) if pd.notna(c) else f"coluna_{i}" for i, c in enumerate(bruto.iloc[linha])]
    return tabela.dropna(how="all")


def _coluna(df: pd.DataFrame, *padroes: str) -> str | None:
    for padrao in padroes:
        for coluna in df.columns:
            if re.fullmatch(padrao, coluna) or re.search(padrao, coluna):
                return coluna
    return None


class ColetorCadastur(Coletor):
    fonte = "cadastur"
    descricao = "Prestadores de serviços turísticos (MTur), trimestral"

    def conjuntos(self) -> list[dict]:
        resposta = self.get(f"{API}/package_search", params={"q": BUSCA, "rows": 100}).json()
        achados = [p for p in resposta["result"]["results"] if "prestador" in chave_municipio(p.get("title"))
                   or p.get("name") == CONJUNTO_GARANTIDO]
        if not any(p.get("name") == CONJUNTO_GARANTIDO for p in achados):
            garantido = self.get(f"{API}/package_show", params={"id": CONJUNTO_GARANTIDO}).json()["result"]
            achados.append(garantido)
        log.info("conjuntos do Cadastur: %s", [p["title"] for p in achados])
        return achados

    def coletar(self, incluir_guias: bool = False, **_) -> Resultado:
        cadastro = cadastro_mestre()
        mapa = dict(zip(cadastro["chave"], cadastro["codigo_ibge"]))
        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])

        partes, coberturas = [], []
        for conjunto in self.conjuntos():
            categoria = re.sub(r"^.*?-\s*", "", conjunto["title"]).strip()
            if not incluir_guias and any(p in chave_municipio(categoria) for p in EXCLUIR_POR_PADRAO):
                log.info("pulando %s (pessoas físicas)", categoria)
                continue
            recursos = [r for r in conjunto.get("resources", []) if r.get("url")]
            if not recursos:
                continue
            recurso = max(recursos, key=lambda r: (periodo_do_recurso(r.get("name", "")), r.get("created", "")))
            conteudo = self.get(recurso["url"], timeout=300).content
            df = ler_arquivo(conteudo, recurso.get("format") or recurso["url"].rsplit(".", 1)[-1])

            col_uf = _coluna(df, r"^uf$", r"^sg_?uf$", r"_uf$", r"^estado$", r"uf")
            col_mun = _coluna(df, r"^municipio$", r"^no_?municipio$", r"municipio")
            if not col_uf or not col_mun:
                raise ValueError(f"{categoria}: colunas de UF/município não encontradas em {list(df.columns)}")

            df = df.drop(columns=[c for c in df.columns if COLUNAS_PESSOAIS.search(c)])
            sp = df[df[col_uf].astype(str).str.strip().str.upper().isin(["SP", "SAO PAULO", "SÃO PAULO"])].copy()
            sp["codigo_ibge"] = sp[col_mun].map(lambda n: mapa.get(chave_municipio(n)))
            sp.insert(0, "categoria", categoria)
            sp.insert(1, "periodo", recurso.get("name"))
            sp["arquivo_url"] = recurso["url"]
            partes.append(sp)

            casados = sp["codigo_ibge"].notna()
            coberturas.append(Cobertura(
                fonte=self.fonte,
                tabela=nome_coluna(categoria),
                universo=len(sp),
                amostra=int(casados.sum()),
                unidade="estabelecimentos de SP ligados ao IBGE",
                municipios_com_dado=len(base & set(sp.loc[casados, "codigo_ibge"])),
                municipios_esperados=len(base),
                notas=[f"arquivo: {recurso.get('name')}", f"total nacional no arquivo: {len(df)}"],
            ))

        if not partes:
            raise RuntimeError("nenhum arquivo do Cadastur foi lido")
        prestadores = pd.concat(partes, ignore_index=True)
        return Resultado(
            tabelas={"prestadores_sp": prestadores},
            tratadas={"contagem_municipio": contagem(prestadores)},
            coberturas=coberturas,
        )


def contagem(prestadores: pd.DataFrame) -> pd.DataFrame:
    """Estabelecimentos por município e categoria; leitos e UHs quando o arquivo traz."""
    df = prestadores.dropna(subset=["codigo_ibge"]).copy()
    agregados = {"estabelecimentos": ("categoria", "size")}
    for medida, padrao in (("leitos", r"leito"), ("uhs", r"(^|_)uhs?($|_)|unidades_habitacionais")):
        coluna = _coluna(df, padrao)
        if coluna:
            df[medida] = df[coluna].map(para_numero)
            agregados[medida] = (medida, lambda s: s.sum(min_count=1))  # categoria sem a coluna fica vazia, não zero
    return df.groupby(["codigo_ibge", "categoria", "periodo"], dropna=False).agg(**agregados).reset_index()

"""Normalização de nomes para cruzar fontes que escrevem o mesmo município de jeitos diferentes."""

from __future__ import annotations

import re
import unicodedata

# Apóstrofos que aparecem nas fontes: "d'Oeste", "d´Oeste", "d’Oeste"
_APOSTROFOS = "'´`’‘"


def chave_municipio(nome: str | None) -> str:
    """Chave de comparação: sem acento, sem apóstrofo, sem espaço, minúscula.

    >>> chave_municipio("Santa Clara d´Oeste") == chave_municipio("Santa Clara d'Oeste")
    True
    """
    if nome is None:
        return ""
    texto = str(nome).strip()
    for apostrofo in _APOSTROFOS:
        texto = texto.replace(apostrofo, "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto.lower())


def nome_coluna(nome: str) -> str:
    """Nome de coluna em snake_case sem acento, para padronizar arquivos de fontes diferentes."""
    texto = unicodedata.normalize("NFKD", str(nome).strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_") or "coluna"


def texto_simples(texto: str | None) -> str:
    """Texto sem acento, minúsculo, com espaços simples e apóstrofos removidos (para buscar nomes)."""
    if texto is None:
        return ""
    texto = str(texto)
    for apostrofo in _APOSTROFOS:
        texto = texto.replace(apostrofo, "")
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


class LocalizadorMunicipios:
    """Acha nomes de municípios dentro de um texto livre (ementa, título, trecho de diário).

    Casa a palavra inteira; quando um nome está contido em outro ("Paraíso" em "Santa Rita do
    Passa Quatro" não, mas "Bom Jesus" em "Bom Jesus dos Perdões" sim), fica só o nome mais longo.
    """

    # "Estado de São Paulo" aparece em quase todo texto oficial e não é a capital
    IGNORAR = re.compile(r"\b(estado|governo|assembleia legislativa|diario oficial) d[eo] sao paulo\b")

    def __init__(self, nomes_por_codigo: dict[str, str]):
        self.por_nome = {texto_simples(n): c for c, n in nomes_por_codigo.items()}
        ordenados = sorted(self.por_nome, key=len, reverse=True)
        self.padrao = re.compile(r"\b(" + "|".join(re.escape(n) for n in ordenados) + r")\b")

    def achar(self, texto: str | None) -> list[str]:
        simples = self.IGNORAR.sub(" ", texto_simples(texto))
        achados, ocupado = [], []
        for m in self.padrao.finditer(simples):
            if any(a <= m.start() < b for a, b in ocupado):
                continue
            ocupado.append(m.span())
            codigo = self.por_nome[m.group(1)]
            if codigo not in achados:
                achados.append(codigo)
        return achados

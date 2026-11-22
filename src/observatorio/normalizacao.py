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

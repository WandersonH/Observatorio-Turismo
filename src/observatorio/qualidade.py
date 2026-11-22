"""Testes de qualidade: separam zero, ausente e inválido antes de qualquer média.

A base de 2023-2025 misturava os três, o que distorceu indicadores do painel
(ex.: ocupação média de hotel de 52,4% com 22 zeros; 67,5% sem eles).
"""

from __future__ import annotations

import re

import pandas as pd

AUSENTE = "ausente"
INVALIDO = "invalido"
ZERO = "zero"
VALIDO = "valido"

_MARCAS_AUSENTE = re.compile(
    r"^\s*$|^-$|^n/?a$|n[aã]o\s+(informado|h[aá]\s+dados|se\s+aplica|possui|sei)|sem\s+resposta",
    re.IGNORECASE,
)
_MARCAS_INVALIDO = re.compile(r"inv[aá]lid", re.IGNORECASE)


def para_numero(valor) -> float | None:
    """Converte respostas numéricas escritas à mão ("1.234,5", "R$ 200", "6 mil").

    Devolve None quando não há um número inequívoco ("aprox 80", "2 e 4").
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().lower().replace("r$", "").strip()
    multiplicador = 1.0
    if texto.endswith(" mil"):
        multiplicador, texto = 1000.0, texto[:-4].strip()
    if not re.fullmatch(r"-?[\d.,]+", texto):
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "")
    try:
        return float(texto) * multiplicador
    except ValueError:
        return None


def classificar(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return AUSENTE
    texto = str(valor)
    if _MARCAS_INVALIDO.search(texto):
        return INVALIDO
    if _MARCAS_AUSENTE.search(texto):
        return AUSENTE
    numero = para_numero(valor)
    if numero is None:
        return INVALIDO
    return ZERO if numero == 0 else VALIDO


def perfil(serie: pd.Series) -> dict:
    """Contagem de válido, zero, ausente e inválido, e médias com e sem zeros."""
    classes = serie.map(classificar)
    numeros = serie.map(para_numero)
    validos = numeros[classes == VALIDO]
    com_zero = numeros[classes.isin([VALIDO, ZERO])]
    return {
        "universo": int(len(serie)),
        VALIDO: int((classes == VALIDO).sum()),
        ZERO: int((classes == ZERO).sum()),
        AUSENTE: int((classes == AUSENTE).sum()),
        INVALIDO: int((classes == INVALIDO).sum()),
        "media_sem_zeros": float(validos.mean()) if len(validos) else None,
        "media_com_zeros": float(com_zero.mean()) if len(com_zero) else None,
        "mediana_sem_zeros": float(validos.median()) if len(validos) else None,
    }


def outliers(serie: pd.Series, fator: float = 10.0) -> pd.Series:
    """Valores acima de `fator` vezes a mediana dos válidos (ex.: 1.000 hostels num município)."""
    numeros = serie.map(para_numero)
    base = numeros[numeros > 0].median()
    if not base or pd.isna(base):
        return serie.iloc[0:0]
    return serie[numeros > fator * base]


def soma_categorias_confere(total: float, partes: list[float], tolerancia: float = 0.01) -> bool:
    """Confere se as partes somam o total (ex.: 3.985 eventos contra 4.984 nas tipologias)."""
    soma = sum(p for p in partes if p is not None)
    return abs(soma - total) <= tolerancia * max(abs(total), 1)

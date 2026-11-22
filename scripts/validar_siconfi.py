"""Confere a despesa em turismo coletada do Siconfi contra os valores da base de 2023-2025.

Uso: python scripts/validar_siconfi.py
Sai com código 1 se mais de 10% dos pares município-ano divergirem acima de 1%.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from observatorio import armazenamento  # noqa: E402
from observatorio.normalizacao import chave_municipio  # noqa: E402

REFERENCIA = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "siconfi_referencia_base.csv"


def main() -> int:
    coletado = armazenamento.ler("siconfi", "despesas_turismo", camada="tratado")
    coletado["chave"] = coletado["municipio"].map(chave_municipio)
    ref = pd.read_csv(REFERENCIA)
    ref["chave"] = ref["municipio"].map(chave_municipio)
    longa = pd.concat([
        ref[["chave", "municipio", f"turismo_empenhado_{ano}"]]
        .rename(columns={f"turismo_empenhado_{ano}": "referencia"}).assign(ano=ano)
        for ano in (2023, 2024)
    ])
    comparado = longa.merge(coletado[["chave", "ano", "turismo_empenhado"]], on=["chave", "ano"], how="left")
    comparado = comparado[comparado["turismo_empenhado"].notna() | (comparado["referencia"] > 0)]
    if comparado.empty:
        print("sem anos em comum com a referência (2023 e 2024)")
        return 0
    coletado_valor = comparado["turismo_empenhado"].fillna(0)
    diferenca = (coletado_valor - comparado["referencia"]).abs()
    comparado["diverge"] = diferenca > 0.01 * comparado["referencia"].abs().clip(lower=1)

    print(f"pares comparados: {len(comparado)}; divergentes: {int(comparado['diverge'].sum())}")
    print(comparado[comparado["diverge"]].head(20).to_string(index=False))
    return 1 if comparado["diverge"].mean() > 0.10 else 0


if __name__ == "__main__":
    sys.exit(main())

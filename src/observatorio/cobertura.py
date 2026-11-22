"""Registro de cobertura: toda coleta declara o universo e a amostra efetivamente lida.

- universo: o total que a fonte reporta (ex.: estabelecimentos do Cadastur em SP)
- amostra: o que a coleta conseguiu ler e associar a um município da base
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from . import armazenamento


@dataclass
class Cobertura:
    fonte: str
    tabela: str
    universo: int | None
    amostra: int
    unidade: str
    municipios_com_dado: int | None = None
    municipios_esperados: int | None = None
    notas: list[str] = field(default_factory=list)

    @property
    def taxa(self) -> float | None:
        if not self.universo:
            return None
        return round(self.amostra / self.universo, 4)

    def resumo(self) -> str:
        partes = [f"{self.fonte}/{self.tabela}: amostra {self.amostra} {self.unidade}"]
        if self.universo is not None:
            partes.append(f"de um universo de {self.universo} ({(self.taxa or 0):.1%})")
        if self.municipios_esperados:
            partes.append(f"; municípios com dado {self.municipios_com_dado}/{self.municipios_esperados}")
        return " ".join(partes)


def registrar(cobertura: Cobertura, data_coleta: str | None = None) -> None:
    linha = asdict(cobertura)
    linha["taxa"] = cobertura.taxa
    linha["notas"] = " | ".join(cobertura.notas)
    armazenamento.salvar(
        pd.DataFrame([linha]),
        fonte=cobertura.fonte,
        tabela=f"cobertura_{cobertura.tabela}",
        camada="cobertura",
        data_coleta=data_coleta,
    )

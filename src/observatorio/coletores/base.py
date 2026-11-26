"""Contrato comum dos coletores.

Cada coletor devolve tabelas e uma cobertura por tabela. A execução grava o bruto,
registra a cobertura e falha de forma visível (código de saída diferente de zero),
para o GitHub Actions avisar quando uma fonte mudar ou sair do ar.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd
import requests

from .. import armazenamento
from ..cobertura import Cobertura, registrar

log = logging.getLogger(__name__)

USER_AGENT = "ObservatorioTurismoAMITESP/0.1 (pesquisa academica EACH-USP)"


class FaltaCredencial(RuntimeError):
    """A fonte precisa de uma chave (segredo do repositório) que não foi configurada."""

    def __init__(self, variavel: str, onde: str = "Settings → Secrets and variables → Actions"):
        super().__init__(f"falta o segredo {variavel} ({onde})")
        self.variavel = variavel


@dataclass
class Resultado:
    tabelas: dict[str, pd.DataFrame] = field(default_factory=dict)  # camada bruta: como a fonte entrega
    tratadas: dict[str, pd.DataFrame] = field(default_factory=dict)  # camada tratada: por município e período
    coberturas: list[Cobertura] = field(default_factory=list)


class Coletor(ABC):
    fonte: str = ""
    descricao: str = ""

    def __init__(self) -> None:
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = USER_AGENT

    def get(self, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", 60)
        resposta = self.sessao.get(url, **kwargs)
        resposta.raise_for_status()
        return resposta

    def baixar_arquivo(self, url: str, destino, tentativas: int = 6) -> int:
        """Baixa um arquivo grande para o disco, retomando do ponto em que a conexão caiu (Range)."""
        import time

        recebidos = 0
        with open(destino, "wb") as f:
            for tentativa in range(tentativas):
                cabecalhos = {"Range": f"bytes={recebidos}-"} if recebidos else {}
                try:
                    with self.sessao.get(url, stream=True, timeout=120, headers=cabecalhos) as r:
                        if recebidos and r.status_code != 206:
                            f.seek(0)
                            f.truncate()
                            recebidos = 0
                        r.raise_for_status()
                        for pedaco in r.iter_content(1 << 20):
                            f.write(pedaco)
                            recebidos += len(pedaco)
                    return recebidos
                except (requests.ConnectionError, requests.Timeout,
                        requests.exceptions.ChunkedEncodingError) as erro:
                    log.warning("download interrompido em %d bytes (%s); retomando", recebidos, type(erro).__name__)
                    time.sleep(5 * (tentativa + 1))
        raise RuntimeError(f"download não concluído após {tentativas} tentativas: {url}")

    @abstractmethod
    def coletar(self, **parametros) -> Resultado: ...

    def executar(self, **parametros) -> Resultado:
        data_coleta = armazenamento.hoje()
        log.info("coletando %s %s", self.fonte, parametros or "")
        resultado = self.coletar(**parametros)
        for tabela, df in resultado.tabelas.items():
            armazenamento.salvar(df, self.fonte, tabela, data_coleta=data_coleta)
        for tabela, df in resultado.tratadas.items():
            armazenamento.salvar(df, self.fonte, tabela, camada="tratado", data_coleta=data_coleta)
        for cobertura in resultado.coberturas:
            registrar(cobertura, data_coleta=data_coleta)
            log.info("cobertura: %s", cobertura.resumo())
        return resultado

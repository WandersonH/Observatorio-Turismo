"""Gravação append-only: nada é sobrescrito, cada carga leva a data de coleta.

Destinos:
- local: ``data/<camada>/<fonte>/data_coleta=AAAA-MM-DD/<tabela>.parquet`` (sempre)
- BigQuery: dataset ``<camada>``, tabela ``<fonte>__<tabela>`` (quando OBS_BQ_PROJECT estiver definido)
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

RAIZ_DADOS = Path(os.environ.get("OBS_DADOS", "data"))
CAMADAS = ("bruto", "tratado", "indicadores", "cobertura")


def hoje() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _preparar(df: pd.DataFrame, data_coleta: str) -> pd.DataFrame:
    saida = df.copy()
    saida.insert(0, "data_coleta", data_coleta)
    # Colunas de texto misto quebram o parquet; o bruto guarda tudo como texto
    for coluna in saida.columns:
        if saida[coluna].dtype == "object":
            saida[coluna] = saida[coluna].astype("string")
    return saida


def salvar(
    df: pd.DataFrame,
    fonte: str,
    tabela: str,
    camada: str = "bruto",
    data_coleta: str | date | None = None,
) -> Path:
    """Grava uma carga. Retorna o caminho local do arquivo."""
    if camada not in CAMADAS:
        raise ValueError(f"camada desconhecida: {camada}")
    data_coleta = str(data_coleta or hoje())
    preparado = _preparar(df, data_coleta)

    pasta = RAIZ_DADOS / camada / fonte / f"data_coleta={data_coleta}"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{tabela}.parquet"
    preparado.to_parquet(caminho, index=False)
    log.info("gravado %s (%d linhas)", caminho, len(preparado))

    if os.environ.get("OBS_BQ_PROJECT"):
        _enviar_bigquery(preparado, camada, f"{fonte}__{tabela}")
    return caminho


def _enviar_bigquery(df: pd.DataFrame, dataset: str, tabela: str) -> None:
    from google.cloud import bigquery  # import tardio: dependência opcional

    projeto = os.environ["OBS_BQ_PROJECT"]
    prefixo = os.environ.get("OBS_BQ_PREFIXO", "obs_")
    destino = f"{projeto}.{prefixo}{dataset}.{tabela}"
    cliente = bigquery.Client(project=projeto)
    configuracao = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )
    cliente.load_table_from_dataframe(df, destino, job_config=configuracao).result()
    log.info("enviado ao BigQuery: %s (%d linhas)", destino, len(df))


def ler(fonte: str, tabela: str, camada: str = "bruto", data_coleta: str | None = None) -> pd.DataFrame:
    """Lê a carga local mais recente (ou a de uma data específica)."""
    base = RAIZ_DADOS / camada / fonte
    pastas = sorted(base.glob("data_coleta=*"))
    if data_coleta:
        pastas = [p for p in pastas if p.name == f"data_coleta={data_coleta}"]
    if not pastas:
        raise FileNotFoundError(f"nenhuma carga de {camada}/{fonte}")
    return pd.read_parquet(pastas[-1] / f"{tabela}.parquet")

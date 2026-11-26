"""Roda todos os coletores implementados e registra o que rodou, o que falhou e o que ainda não existe.

O resultado vai para ``data/status/status.json`` e alimenta a página "Fontes" do site.
Uma fonte que falha não interrompe as outras.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import asdict

from . import armazenamento
from .config import catalogo_fontes
from .coletores import COLETORES
from .coletores.base import FaltaCredencial
from .coletores.siconfi import anos_padrao

log = logging.getLogger(__name__)

RODOU = "rodou"
FALHOU = "falhou"
NAO_IMPLEMENTADO = "nao_implementado"
AGUARDA_DECISAO = "aguarda_decisao"
FALTA_CREDENCIAL = "falta_credencial"

# Parâmetros da rodada completa: a base AMITESP com série de três anos no Siconfi,
# e os demais 544 municípios de SP só no último ano, como grupo de comparação.
PARAMETROS = {
    "siconfi": lambda: {"todos": True, "anos": anos_padrao(), "anos_contexto": anos_padrao()[-1:]},
}
ORDEM = ["ibge"]  # o cadastro mestre vem antes de tudo


def rodar_tudo() -> dict:
    catalogo = catalogo_fontes()
    data_coleta = armazenamento.hoje()
    ids = ORDEM + [f["id"] for f in catalogo if f["id"] not in ORDEM]
    por_id = {f["id"]: f for f in catalogo}

    fontes = []
    for fonte_id in ids:
        info = dict(por_id.get(fonte_id, {"id": fonte_id}))
        if fonte_id not in COLETORES:
            info["situacao"] = AGUARDA_DECISAO if info.get("status") == "depende_de_decisao" else NAO_IMPLEMENTADO
            fontes.append(info)
            continue
        inicio = time.monotonic()
        try:
            parametros = PARAMETROS.get(fonte_id, dict)()
            resultado = COLETORES[fonte_id]().executar(**parametros)
            info["situacao"] = RODOU
            info["coberturas"] = [{**asdict(c), "taxa": c.taxa} for c in resultado.coberturas]
        except FaltaCredencial as erro:
            log.warning("%s: %s", fonte_id, erro)
            info["situacao"] = FALTA_CREDENCIAL
            info["erro"] = str(erro)
        except Exception as erro:
            log.exception("falha em %s", fonte_id)
            info["situacao"] = FALHOU
            info["erro"] = f"{type(erro).__name__}: {erro}"[:500]
            info["detalhe"] = traceback.format_exc(limit=3)[-1500:]
        info["duracao_s"] = round(time.monotonic() - inicio, 1)
        info["data_coleta"] = data_coleta
        fontes.append(info)

    status = {"data_coleta": data_coleta, "fontes": fontes}
    pasta = armazenamento.RAIZ_DADOS / "status"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return status


def resumo(status: dict) -> str:
    rotulos = {RODOU: "rodou", FALHOU: "FALHOU", NAO_IMPLEMENTADO: "não implementado", AGUARDA_DECISAO: "aguarda decisão",
               FALTA_CREDENCIAL: "falta credencial"}
    linhas = [f"Rodada de {status['data_coleta']}", ""]
    for f in status["fontes"]:
        linha = f"- {f['id']}: {rotulos[f['situacao']]}"
        if f["situacao"] in (FALHOU, FALTA_CREDENCIAL):
            linha += f" ({f['erro']})"
        for c in f.get("coberturas", []):
            taxa = f" ({c['taxa']:.1%})" if c.get("taxa") is not None else ""
            linha += f"\n    {c['tabela']}: {c['amostra']} de {c['universo']} {c['unidade']}{taxa}"
        linhas.append(linha)
    return "\n".join(linhas)

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
NAO_EXECUTADO = "nao_executado"

# Parâmetros da rodada completa: a base AMITESP com série de três anos no Siconfi,
# e os demais 544 municípios de SP só no último ano, como grupo de comparação.
PARAMETROS = {
    "siconfi": lambda: {"todos": True, "anos": anos_padrao(), "anos_contexto": anos_padrao()[-1:]},
}
ORDEM = ["ibge"]  # o cadastro mestre vem antes de tudo


def situacao_sem_execucao(info: dict) -> str:
    if info["id"] in COLETORES:
        return NAO_EXECUTADO
    return AGUARDA_DECISAO if info.get("status") == "depende_de_decisao" else NAO_IMPLEMENTADO


def rodar_tudo(fontes: list[str] | None = None) -> dict:
    """Roda as fontes pedidas (ou todas). Com `fontes`, o status vai para status-<fontes>.json,
    para várias execuções em paralelo poderem ser juntadas depois (ver `consolidar_status`)."""
    catalogo = catalogo_fontes()
    data_coleta = armazenamento.hoje()
    ids = ORDEM + [f["id"] for f in catalogo if f["id"] not in ORDEM]
    if fontes:
        desconhecidas = set(fontes) - set(ids)
        if desconhecidas:
            raise ValueError(f"fontes desconhecidas: {sorted(desconhecidas)}")
        ids = [i for i in ids if i in fontes]
    por_id = {f["id"]: f for f in catalogo}

    resultado_fontes = []
    for fonte_id in ids:
        info = dict(por_id.get(fonte_id, {"id": fonte_id}))
        if fonte_id not in COLETORES:
            info["situacao"] = situacao_sem_execucao(info)
            resultado_fontes.append(info)
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
        resultado_fontes.append(info)

    status = {"data_coleta": data_coleta, "fontes": resultado_fontes}
    pasta = armazenamento.RAIZ_DADOS / "status"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"status-{'-'.join(fontes)}.json" if fontes else "status.json"
    (pasta / nome).write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return status


def consolidar_status() -> dict:
    """Junta os status*.json das execuções (uma completa ou várias em paralelo) na ordem do catálogo."""
    pasta = armazenamento.RAIZ_DADOS / "status"
    executadas, datas = {}, []
    for arquivo in sorted(pasta.glob("status*.json")) if pasta.exists() else []:
        conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
        datas.append(conteudo.get("data_coleta"))
        for f in conteudo.get("fontes", []):
            if f["id"] not in executadas or f.get("situacao") in (RODOU, FALHOU, FALTA_CREDENCIAL):
                executadas[f["id"]] = f
    fontes = []
    for info in catalogo_fontes():
        fontes.append(executadas.get(info["id"]) or {**info, "situacao": situacao_sem_execucao(info)})
    return {"data_coleta": max((d for d in datas if d), default=None), "fontes": fontes}


def resumo(status: dict) -> str:
    rotulos = {RODOU: "rodou", FALHOU: "FALHOU", NAO_IMPLEMENTADO: "não implementado", AGUARDA_DECISAO: "aguarda decisão",
               FALTA_CREDENCIAL: "falta credencial", NAO_EXECUTADO: "não executado"}
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

"""Sondagem, quinta rodada: texto extraído do Inventário de Resíduos (repositório público da CETESB)."""
import re
import sys
import traceback

import requests

S = requests.Session()
S.headers.update({"User-Agent": "ObservatorioTurismoAMITESP/0.1 (pesquisa academica EACH-USP)"})
API = "https://repositorio.cetesb.sp.gov.br/server/api"


def cetesb_txt():
    print("==================== CETESB TXT 2021 ====================")
    bundles = S.get(f"{API}/core/items/cb7f98f4-aba3-4300-9ac5-2835ffff31c4/bundles", timeout=60).json()["_embedded"]["bundles"]
    for b in bundles:
        if b["name"] != "TEXT":
            continue
        bs = S.get(b["_links"]["bitstreams"]["href"], timeout=60).json()["_embedded"]["bitstreams"]
        txt = S.get(bs[0]["_links"]["content"]["href"], timeout=120).content.decode("utf-8", "replace")
        linhas = txt.splitlines()
        print("linhas", len(linhas))
        for i, linha in enumerate(linhas):
            if re.search(r"GUARAREMA|Guararema|IPORANGA|Iporanga", linha):
                print(f"[{i}]", " | ".join(linhas[max(0, i - 3):i + 4])[:700])
        for i in [i for i, linha in enumerate(linhas) if "IQR" in linha][:6]:
            print("IQR>", linhas[i][:300])


try:
    cetesb_txt()
except Exception:
    traceback.print_exc(limit=2, file=sys.stdout)

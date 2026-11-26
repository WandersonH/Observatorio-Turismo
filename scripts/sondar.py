"""Sondagem: fontes públicas alternativas para as leis de classificação de MIT."""
import re
import sys
import traceback

import requests

S = requests.Session()
S.headers.update({"User-Agent": "ObservatorioTurismoAMITESP/0.1 (pesquisa academica EACH-USP)"})


def mostrar(url, padrao_links=None, n=1500):
    r = S.get(url, timeout=90)
    r.encoding = r.apparent_encoding or "utf-8"
    print("\n###", url, r.status_code, len(r.content), r.headers.get("content-type"))
    texto = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", r.text, flags=re.S))
    print(texto[:n])
    if padrao_links:
        links = sorted(set(l for l in re.findall(r'href="([^"]+)"', r.text) if re.search(padrao_links, l)))
        print("links:", len(links), links[:40])
    return r


for url, padrao in [
    ("https://www.al.sp.gov.br/repositorioDados/legislacao/legislacao_normas.zip", None),
    ("https://www.al.sp.gov.br/norma/coletanea/122", r"legislacao|norma"),
    ("https://www.al.sp.gov.br/repositorio/legislacao/lei/2021/compilacao-lei-17469-13.12.2021.html", None),
    ("https://www.lexml.gov.br/busca/SRU?operation=explain&version=1.1", None),
    ("https://www.lexml.gov.br/busca/SRU?operation=searchRetrieve&version=1.1&maximumRecords=3"
     "&query=" + requests.utils.quote('urn any "sao.paulo:estadual:lei" and dc.description any "interesse turistico"'), None),
]:
    try:
        mostrar(url, padrao, 2500 if "17469" in url else 1500)
    except Exception:
        traceback.print_exc(limit=2, file=sys.stdout)

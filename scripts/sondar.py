"""Sondagem, terceira rodada."""
import ftplib, io, json, os, re, sys, tempfile, time, zipfile, traceback
import requests

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
                  "Accept-Language": "pt-BR,pt;q=0.9"})

def secao(nome):
    print("\n" + "=" * 20 + " " + nome + " " + "=" * 20, flush=True)

def tentar(f):
    try:
        f()
    except Exception:
        traceback.print_exc(limit=2, file=sys.stdout)

def alesp():
    secao("ALESP página de pesquisa")
    r = S.get("https://www.al.sp.gov.br/propositura/pesquisa?busca=turismo&tamanho=5", timeout=60)
    r.encoding = "utf-8"
    print(r.status_code, len(r.text))
    print("scripts:", re.findall(r'<script[^>]+src="([^"]+)"', r.text))
    for bloco in re.findall(r"<script[^>]*>(.*?)</script>", r.text, re.S):
        if bloco.strip():
            print("--- inline ---", bloco.strip()[:1500])
    print("forms:", re.findall(r"<form[^>]*>", r.text))
    print("ng/data:", re.findall(r'(ng-[a-z]+="[^"]+"|data-[a-z-]+="[^"]+")', r.text)[:30])
    print(r.text[-2500:])
    for url in ["https://www.al.sp.gov.br/repositorioDados/processo_legislativo/proposituras.zip",
                "https://www.al.sp.gov.br/norma/pesquisa?busca=interesse%20tur%C3%ADstico"]:
        r = S.get(url, timeout=60)
        print(url, r.status_code, len(r.content), r.headers.get("content-type"))

def querido_diario():
    secao("QUERIDO DIÁRIO")
    for url in ["https://api.queridodiario.org.br/cities?city_name=Guararema",
                "https://api.queridodiario.org.br/docs",
                "https://queridodiario.ok.org.br/",
                "https://queridodiario.org.br/"]:
        try:
            r = S.get(url, timeout=150, allow_redirects=False)
            print(url, r.status_code, r.headers.get("location"), r.text[:400].replace("\n", " "))
        except Exception as e:
            print(url, "erro", type(e).__name__, str(e)[:200])

def cetesb():
    secao("CETESB DSpace")
    api = "https://repositorio.cetesb.sp.gov.br/server/api"
    r = S.get(api + "/discover/search/objects", params={"query": "inventário estadual resíduos sólidos urbanos", "size": 40,
                                                         "dsoType": "ITEM"}, timeout=60).json()
    itens = []
    for o in r["_embedded"]["searchResult"]["_embedded"]["objects"]:
        it = o["_embedded"]["indexableObject"]
        if "nvent" in it["name"] and "res" in it["name"].lower():
            itens.append((it["name"], it["uuid"]))
    for n, u in sorted(itens):
        print(n, u)
    nome, uuid = sorted(itens)[-1]
    bundles = S.get(f"{api}/core/items/{uuid}/bundles", timeout=60).json()["_embedded"]["bundles"]
    for b in bundles:
        bs = S.get(b["_links"]["bitstreams"]["href"], timeout=60).json()["_embedded"]["bitstreams"]
        for x in bs:
            print(b["name"], x["name"], x["sizeBytes"], x["_links"]["content"]["href"])
            if b["name"] == "ORIGINAL" and x["name"].lower().endswith(".pdf"):
                pdf = S.get(x["_links"]["content"]["href"], timeout=300).content
                import pdfplumber
                with pdfplumber.open(io.BytesIO(pdf)) as doc:
                    print("páginas", len(doc.pages))
                    achou = 0
                    for i, pg in enumerate(doc.pages):
                        t = pg.extract_text() or ""
                        if re.search(r"Guararema|Iporanga", t) and re.search(r"IQR|Enquadramento", t):
                            print(f"--- página {i+1} ---")
                            print(t[:3000])
                            tabs = pg.extract_tables()
                            print("tabelas:", len(tabs), [tb[:5] for tb in tabs[:1]])
                            achou += 1
                            if achou >= 2:
                                break
                return

def anac():
    secao("ANAC aeródromos públicos")
    url = "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv"
    r = S.get(url, timeout=60)
    texto = r.content.decode("utf-8-sig", "replace")
    linhas = texto.splitlines()
    print(len(linhas))
    print("\n".join(linhas[:3]))
    print("\n".join(l for l in linhas if ";\"SP\";" in l or "\"SP\"" in l)[:3000])

def caged():
    secao("CAGED")
    import pandas as pd
    ftp = ftplib.FTP("ftp.mtps.gov.br", timeout=60, encoding="latin-1")
    ftp.login()
    ftp.cwd("pdet/microdados/NOVO CAGED")
    buf = io.BytesIO()
    ftp.retrbinary("RETR Layout Não-identificado Novo Caged Movimentação.xlsx", buf.write)
    for aba, df in pd.read_excel(io.BytesIO(buf.getvalue()), sheet_name=None).items():
        print("aba", aba, df.shape)
        print(df.head(40).to_string()[:3500])
    import py7zr
    for nome in ["CAGEDEXC202609.7z", "CAGEDFOR202609.7z"]:
        ftp.cwd("/pdet/microdados/NOVO CAGED/2026/202609")
        buf = io.BytesIO()
        ftp.retrbinary("RETR " + nome, buf.write)
        buf.seek(0)
        with tempfile.TemporaryDirectory() as d:
            with py7zr.SevenZipFile(buf) as z:
                z.extractall(path=d)
            for arq in os.listdir(d):
                with open(os.path.join(d, arq), encoding="utf-8", errors="replace") as f:
                    print(arq)
                    for i, linha in enumerate(f):
                        print(linha.rstrip())
                        if i >= 2:
                            break

for f in [alesp, querido_diario, cetesb, anac, caged]:
    tentar(f)

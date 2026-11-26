"""Sondagem, segunda rodada: só imprime estrutura, nada é gravado."""
import ftplib, io, json, os, re, sys, tempfile, time, zipfile, traceback
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) observatorio-turismo-amitesp/0.1"

def secao(nome):
    print("\n" + "=" * 20 + " " + nome + " " + "=" * 20, flush=True)

def tentar(f):
    try:
        f()
    except Exception:
        traceback.print_exc(limit=2, file=sys.stdout)

def caged():
    secao("CAGED")
    ftp = ftplib.FTP("ftp.mtps.gov.br", timeout=60, encoding="latin-1")
    ftp.login()
    ftp.cwd("pdet/microdados/NOVO CAGED")
    buf = io.BytesIO()
    ftp.retrbinary("RETR Layout Não-identificado Novo Caged Movimentação.xlsx", buf.write)
    import pandas as pd
    for aba, df in pd.read_excel(io.BytesIO(buf.getvalue()), sheet_name=None).items():
        print("aba", aba)
        print(df.to_string()[:4000])
    ftp.cwd("2026/202609")
    buf = io.BytesIO()
    ftp.retrbinary("RETR CAGEDEXC202609.7z", buf.write)
    import py7zr
    buf.seek(0)
    with tempfile.TemporaryDirectory() as d:
        with py7zr.SevenZipFile(buf) as z:
            z.extractall(path=d)
        for nome in os.listdir(d):
            with open(os.path.join(d, nome), encoding="utf-8", errors="replace") as f:
                for i, linha in enumerate(f):
                    print(linha.rstrip())
                    if i >= 3:
                        break
    print(ftp.nlst("/pdet/microdados/NOVO CAGED/2025")[:3])

def anac():
    secao("ANAC")
    base = "https://sistemas.anac.gov.br/dadosabertos/Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/Dados%20Estat%C3%ADsticos%20do%20Transporte%20A%C3%A9reo/"
    for nome in ["Dados_Estatisticos.csv", "Dados_Estatisticos_2021_a_2030.json", "Dados_Estatisticos_parte.csv"]:
        h = S.head(base + nome, timeout=60)
        print(nome, h.status_code, h.headers.get("content-length"), h.headers.get("last-modified"), h.headers.get("accept-ranges"))
        tamanho = int(h.headers.get("content-length") or 0)
        if tamanho and nome.endswith(".csv"):
            r = S.get(base + nome, headers={"Range": f"bytes={tamanho-1500}-{tamanho-1}"}, timeout=60)
            print("fim:", r.status_code, r.content.decode("utf-8", "replace")[-1200:])
        if nome.endswith(".json"):
            r = S.get(base + nome, headers={"Range": "bytes=0-1500"}, timeout=60)
            print("início json:", r.status_code, r.content[:1500].decode("utf-8", "replace"))
    r = S.get("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/", timeout=60)
    print("Aerodromos", r.status_code, re.findall(r'href="([^"]+)"', r.text))
    for sub in re.findall(r'href="([^"]+/)"', r.text):
        if sub.startswith(".."):
            continue
        r2 = S.get("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/" + sub, timeout=60)
        print(" ", sub, re.findall(r'href="([^"]+)"', r2.text)[:20])

def anac_cadastro():
    secao("ANAC cadastro aeródromos")
    r = S.get("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/", timeout=60)
    achados = []
    def andar(url, prof=0):
        if prof > 3:
            return
        rr = S.get(url, timeout=60)
        for l in re.findall(r'href="([^"]+)"', rr.text):
            if l.startswith("..") or l == "null":
                continue
            if l.endswith("/"):
                andar(url + l, prof + 1)
            elif re.search(r"\.(csv|xlsx?|json)$", l, re.I):
                achados.append(url + l)
    andar("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/")
    for a in achados[:30]:
        print(a)
    pub = [a for a in achados if "blico" in a.lower() and a.lower().endswith(".csv")]
    if pub:
        r = S.get(pub[0], timeout=60)
        print(r.content[:1500].decode("latin-1"))

def alesp():
    secao("ALESP")
    for url in ["https://www.al.sp.gov.br/repositorioDados/processo_legislativo/proposituras.zip",
                "http://www.al.sp.gov.br/repositorioDados/processo_legislativo/proposituras.zip",
                "https://www.al.sp.gov.br/repositorioDados/legislacao/legislacao_normas.zip",
                "https://www.al.sp.gov.br/dados-abertos/recurso/56",
                "https://www.al.sp.gov.br/propositura/pesquisa?busca=turismo&tamanho=5",
                "https://ckan.al.sp.gov.br/alesp-dados-abertos"]:
        for tentativa in range(2):
            try:
                r = S.get(url, timeout=120)
                print(url, r.status_code, len(r.content), r.headers.get("content-type"), r.headers.get("server"))
                if r.status_code == 200 and url.endswith(".zip"):
                    z = zipfile.ZipFile(io.BytesIO(r.content))
                    print(z.namelist())
                    with z.open(z.namelist()[0]) as f:
                        print(f.read(2500).decode("utf-8", "replace"))
                elif r.status_code == 200:
                    print(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:1500])
                    print([l for l in re.findall(r'href="([^"]+)"', r.text) if "zip" in l or "xml" in l][:20])
                else:
                    print(r.text[:300])
                break
            except Exception as e:
                print(url, "erro", e)
                time.sleep(5)

def querido_diario():
    secao("QUERIDO DIÁRIO")
    import ssl, socket
    for url in ["https://queridodiario.ok.org.br/api/cities?city_name=Guararema",
                "https://api.queridodiario.ok.org.br/cities?city_name=Guararema",
                "https://queridodiario.ok.org.br/api/gazettes?territory_ids=3518305&querystring=turismo&size=1"]:
        try:
            r = S.get(url, timeout=60)
            print(url, r.status_code, r.text[:800])
        except Exception as e:
            print(url, "erro", e)
    try:
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        with socket.create_connection(("api.queridodiario.ok.org.br", 443), timeout=20) as s:
            with ctx.wrap_socket(s, server_hostname="api.queridodiario.ok.org.br") as t:
                print("tls ok com SECLEVEL=1", t.version(), t.cipher())
    except Exception as e:
        print("tls SECLEVEL=1 falhou", e)
    import subprocess
    print(subprocess.run(["curl", "-sS", "-m", "30", "-o", "/dev/null", "-w", "%{http_code} %{ssl_verify_result}\n",
                          "https://api.queridodiario.ok.org.br/cities?city_name=Guararema"], capture_output=True, text=True))

def cetesb():
    secao("CETESB")
    for url in ["https://cetesb.sp.gov.br/residuossolidos/wp-content/uploads/sites/26/2024/05/Inventario-Estadual-de-Residuos-Solidos-Urbanos-no-Estado-de-Sao-Paulo-2023.pdf",
                "https://repositorio.cetesb.sp.gov.br/server/api/discover/search/objects?query=Invent%C3%A1rio%20Estadual%20de%20Res%C3%ADduos%20S%C3%B3lidos%20Urbanos&size=10&sort=dc.date.issued,DESC",
                "https://cetesb.sp.gov.br/residuossolidos/publicacoes-e-relatorios/"]:
        r = S.get(url, timeout=120)
        print(url, r.status_code, len(r.content), r.headers.get("content-type"), r.headers.get("server"))
        if "json" in (r.headers.get("content-type") or ""):
            js = r.json()
            for o in js["_embedded"]["searchResult"]["_embedded"]["objects"][:10]:
                it = o["_embedded"]["indexableObject"]
                print("  ", it.get("name"), it.get("uuid"), it.get("handle"))
        elif r.status_code != 200 or "html" in (r.headers.get("content-type") or ""):
            print(r.text[:500])
        else:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(r.content)) as doc:
                print("páginas", len(doc.pages))
                achou = 0
                for i, pg in enumerate(doc.pages):
                    t = pg.extract_text() or ""
                    if re.search(r"Guararema|Iporanga", t) and "IQR" in t:
                        print(f"--- página {i+1} ---")
                        print(t[:2500])
                        achou += 1
                        if achou >= 2:
                            break

def openalex():
    secao("OPENALEX")
    r = S.get("https://api.openalex.org/works", params={"search": '"Guararema" AND (turismo OR tourism)', "per-page": 1}, timeout=60)
    print(r.status_code, json.dumps(r.json().get("meta"), ensure_ascii=False))

for f in [alesp, querido_diario, cetesb, anac, anac_cadastro, openalex, caged]:
    tentar(f)

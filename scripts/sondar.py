"""Sondagem dos endpoints das fontes novas: só imprime estrutura, nada é gravado."""
import ftplib, io, json, re, sys, time, zipfile, traceback
import requests

S = requests.Session()
S.headers["User-Agent"] = "observatorio-turismo-amitesp/0.1 (pesquisa EACH-USP)"

def secao(nome):
    print("\n" + "=" * 20 + " " + nome + " " + "=" * 20, flush=True)

def tentar(f):
    try:
        f()
    except Exception:
        traceback.print_exc(limit=3, file=sys.stdout)

def caged():
    secao("CAGED FTP")
    ftp = ftplib.FTP("ftp.mtps.gov.br", timeout=60, encoding="latin-1")
    ftp.login()
    ftp.cwd("pdet/microdados/NOVO CAGED")
    anos = sorted(ftp.nlst())
    print("raiz:", anos[-8:])
    ultimo_ano = [a for a in anos if re.fullmatch(r"\d{4}", a)][-1]
    ftp.cwd(ultimo_ano)
    meses = sorted(ftp.nlst())
    print(ultimo_ano, "->", meses)
    ftp.cwd(meses[-1])
    arquivos = []
    ftp.retrlines("LIST", arquivos.append)
    print("\n".join(arquivos))
    nome = [a.split()[-1] for a in arquivos if "CAGEDMOV" in a][0]
    buf = io.BytesIO()
    inicio = time.time()
    ftp.retrbinary("RETR " + nome, buf.write)
    print("baixado", nome, len(buf.getvalue()), "bytes em", round(time.time() - inicio), "s")
    import py7zr
    buf.seek(0)
    with py7zr.SevenZipFile(buf) as z:
        nomes = z.getnames()
        print("no 7z:", nomes)
        dados = z.read([nomes[0]])[nomes[0]]
    linhas = []
    for i, linha in enumerate(dados):
        linhas.append(linha.decode("utf-8", "replace").rstrip())
        if i >= 3:
            break
    print("\n".join(linhas))

def anac():
    secao("ANAC")
    base = "https://sistemas.anac.gov.br/dadosabertos/"
    r = S.get(base, timeout=60)
    print(r.status_code, r.url)
    print(re.findall(r'href="([^"]+)"', r.text)[:60])
    alvo = base + "Voos%20e%20opera%C3%A7%C3%B5es%20a%C3%A9reas/Dados%20Estat%C3%ADsticos%20do%20Transporte%20A%C3%A9reo/"
    r = S.get(alvo, timeout=60)
    print(r.status_code, r.url)
    links = re.findall(r'href="([^"]+)"', r.text)
    print(links)
    csvs = [l for l in links if l.lower().endswith(".csv")]
    if csvs:
        url = requests.compat.urljoin(r.url, csvs[-1])
        with S.get(url, stream=True, timeout=120) as resp:
            print("HEAD", url, resp.status_code, resp.headers.get("content-length"))
            pedaco = next(resp.iter_content(4000))
            print(pedaco.decode("utf-8", "replace")[:1500])
    r = S.get(base + "Aer%C3%B3dromos/", timeout=60)
    print("aerodromos", r.status_code, re.findall(r'href="([^"]+)"', r.text)[:40])

def antt():
    secao("ANTT")
    api = "https://dados.antt.gov.br/api/3/action/package_show"
    for pacote in ["sisaut-nacional-internacional"]:
        p = S.get(api, params={"id": pacote}, timeout=60).json()["result"]
        recursos = p["resources"]
        print(pacote, len(recursos), "recursos; últimos:")
        for r_ in recursos[-4:]:
            print(" ", r_["name"], r_.get("last_modified"), r_["url"])
        url = recursos[-1]["url"]
        with S.get(url, stream=True, timeout=120) as resp:
            pedaco = b""
            for c in resp.iter_content(200000):
                pedaco += c
                if len(pedaco) > 600000:
                    break
        texto = pedaco.decode("utf-8", "replace")
        linhas = texto.splitlines()
        print("\n".join(linhas[:4]))
        cab = linhas[0].split(";")
        if "tipo_viagem" in cab:
            i = cab.index("tipo_viagem")
            from collections import Counter
            print(Counter(l.split(";")[i] for l in linhas[1:-1] if len(l.split(";")) == len(cab)).most_common(10))
    busca = S.get("https://dados.antt.gov.br/api/3/action/package_search", params={"q": "fretamento", "rows": 20}, timeout=60).json()
    print([(x["name"], x["title"]) for x in busca["result"]["results"]])

def cetesb():
    secao("CETESB")
    for url in ["https://cetesb.sp.gov.br/residuossolidos/publicacoes-e-relatorios/",
                "https://cetesb.sp.gov.br/praias/publicacoes-relatorios/"]:
        r = S.get(url, timeout=60)
        links = [l for l in re.findall(r'href="([^"]+)"', r.text) if re.search(r"\.(pdf|xlsx?|csv|zip)$", l, re.I)]
        print(url, r.status_code, len(links))
        for l in links[:25]:
            print("  ", l)

def cetesb_pdf():
    secao("CETESB PDF")
    r = S.get("https://cetesb.sp.gov.br/residuossolidos/publicacoes-e-relatorios/", timeout=60)
    links = [l for l in re.findall(r'href="([^"]+)"', r.text) if "nventario" in l and l.lower().endswith(".pdf")]
    print(links[:10])
    url = sorted(links, key=lambda l: re.findall(r"20\d\d", l)[-1] if re.findall(r"20\d\d", l) else "")[-1]
    pdf = S.get(url, timeout=180).content
    print("pdf", url, len(pdf))
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        print("páginas", len(doc.pages))
        achou = 0
        for i, pg in enumerate(doc.pages):
            t = pg.extract_text() or ""
            if re.search(r"Bocaina|Iporanga|Guararema", t) and "IQR" in t:
                print(f"--- página {i+1} ---")
                print(t[:1800])
                tabs = pg.extract_tables()
                print("tabelas:", len(tabs), tabs[0][:6] if tabs else None)
                achou += 1
                if achou >= 2:
                    break

def alesp():
    secao("ALESP")
    for nome in ["proposituras.zip", "legislacao_normas.zip"]:
        url = "https://www.al.sp.gov.br/repositorioDados/processo_legislativo/" + nome
        if nome.startswith("legislacao"):
            url = "https://www.al.sp.gov.br/repositorioDados/legislacao/" + nome
        r = S.get(url, timeout=300)
        print(nome, r.status_code, len(r.content), r.headers.get("content-type"))
        if r.status_code != 200:
            continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        print(z.namelist())
        with z.open(z.namelist()[0]) as f:
            print(f.read(3000).decode("utf-8", "replace"))

def alesp_normas():
    secao("ALESP normas (catálogo)")
    r = S.get("https://www.al.sp.gov.br/dados-abertos/", timeout=60)
    print([l for l in re.findall(r'href="([^"]+)"', r.text) if "recurso" in l or "grupo" in l][:60])

def querido_diario():
    secao("QUERIDO DIÁRIO")
    r = S.get("https://api.queridodiario.ok.org.br/cities", params={"city_name": ""}, timeout=60)
    print(r.status_code, r.text[:300])
    try:
        cidades = r.json()["cities"]
        sp = [c for c in cidades if c.get("state_code") == "SP"]
        print("cidades SP:", len(sp), sp[:3])
    except Exception as e:
        print("cities falhou", e)
    r = S.get("https://api.queridodiario.ok.org.br/gazettes",
              params={"territory_ids": "3550308", "querystring": '"conselho municipal de turismo"', "size": 2,
                      "excerpt_size": 200, "number_of_excerpts": 1}, timeout=60)
    print(r.status_code, r.text[:1500])

def producoes():
    secao("GOOGLE NEWS e OPENALEX")
    r = S.get("https://news.google.com/rss/search", params={"q": '"Guararema" turismo when:30d', "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}, timeout=60)
    print(r.status_code, r.text.count("<item>"), r.text[:600])
    r = S.get("https://api.openalex.org/works", params={"search": '"Guararema" AND (turismo OR tourism)', "per-page": 2, "mailto": "observatorio@example.org"}, timeout=60)
    print(r.status_code, json.dumps(r.json().get("meta"), ensure_ascii=False)[:400])
    print([w.get("title") for w in r.json().get("results", [])])

for f in [antt, alesp, alesp_normas, querido_diario, producoes, cetesb, cetesb_pdf, anac, caged]:
    tentar(f)

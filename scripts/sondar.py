"""Sondagem, quarta rodada."""
import io, json, re, sys, traceback
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
    secao("ALESP bundle")
    js = S.get("https://www.al.sp.gov.br/legis-web-files/main-CQJNXIdr.js", timeout=60).text
    print(len(js))
    urls = sorted(set(re.findall(r"""["'`](/[a-zA-Z0-9_\-/{}$.]*(?:api|rest|json|pesquisa|propositura)[a-zA-Z0-9_\-/{}$.?=&]*)["'`]""", js)))
    print("\n".join(urls[:80]))
    for trecho in re.findall(r".{200}fetch\(.{300}", js)[:6]:
        print("--- fetch ---", trecho)
    base = re.findall(r"""["'`](https?://[^"'`]+)["'`]""", js)
    print("absolutas:", sorted(set(base))[:40])

def alesp_api():
    secao("ALESP API tentativa")
    for url in ["https://www.al.sp.gov.br/legis-api/propositura/pesquisa?busca=turismo&tamanho=5",
                "https://www.al.sp.gov.br/api/propositura/pesquisa?busca=turismo&tamanho=5",
                "https://www.al.sp.gov.br/legis-web/api/propositura/pesquisa?busca=turismo&tamanho=5"]:
        r = S.get(url, timeout=60, headers={"Accept": "application/json"})
        print(url, r.status_code, r.headers.get("content-type"), r.text[:600])

def alesp_normas():
    secao("ALESP normas")
    r = S.get("https://www.al.sp.gov.br/legislacao/", timeout=60)
    print(r.status_code, re.findall(r'<script[^>]+src="([^"]+)"', r.text))
    for src in re.findall(r'<script[^>]+src="([^"]+)"', r.text):
        if "ruxit" in src:
            continue
        js = S.get(requests.compat.urljoin("https://www.al.sp.gov.br/legislacao/", src), timeout=60).text
        urls = sorted(set(re.findall(r"""["'`](/[a-zA-Z0-9_\-/{}$.]*(?:api|rest|json|pesquisa|norma)[a-zA-Z0-9_\-/{}$.?=&]*)["'`]""", js)))
        print(src, len(js))
        print("\n".join(urls[:60]))

def cetesb():
    secao("CETESB 2021")
    url = None
    api = "https://repositorio.cetesb.sp.gov.br/server/api"
    bundles = S.get(f"{api}/core/items/cb7f98f4-aba3-4300-9ac5-2835ffff31c4/bundles", timeout=60).json()["_embedded"]["bundles"]
    for b in bundles:
        bs = S.get(b["_links"]["bitstreams"]["href"], timeout=60).json()["_embedded"]["bitstreams"]
        for x in bs:
            print(b["name"], x["name"], x["sizeBytes"])
            if b["name"] == "ORIGINAL" and x["name"].lower().endswith(".pdf"):
                url = x["_links"]["content"]["href"]
    pdf = S.get(url, timeout=300).content
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        print("páginas", len(doc.pages))
        vistos = 0
        for i, pg in enumerate(doc.pages):
            t = pg.extract_text() or ""
            if re.search(r"Guararema|Iporanga|Bocaina", t):
                print(f"--- página {i+1} ---")
                print(t[:2200])
                vistos += 1
                if vistos >= 4:
                    break

for f in [alesp, alesp_api, alesp_normas, cetesb]:
    tentar(f)

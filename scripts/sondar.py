"""Sondagem: estrutura do texto compilado da Lei 17.469/2021 (municípios turísticos)."""
import html
import re

import requests

S = requests.Session()
S.headers.update({"User-Agent": "ObservatorioTurismoAMITESP/0.1 (pesquisa academica EACH-USP)"})
URL = "https://www.al.sp.gov.br/repositorio/legislacao/lei/2021/compilacao-lei-17469-13.12.2021.html"
r = S.get(URL, timeout=90)
bruto = r.content.decode(r.apparent_encoding or "latin-1", errors="replace")
print("tags de riscado:", {t: len(re.findall(t, bruto, re.I)) for t in ["<strike", "<s>", "<del", "line-through"]})
print("amostra de marcação:", re.findall(r".{0,200}(?:<strike|line-through).{0,300}", bruto, re.I | re.S)[:3])
paragrafos = re.findall(r"<p[^>]*>(.*?)</p>", bruto, re.S | re.I)
print("parágrafos:", len(paragrafos))
for i, p in enumerate(paragrafos):
    texto = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p))).strip()
    if re.search(r"Artigo|classificad|Estância|Interesse Turístico|Revogad|Anexo|ANEXO", texto) or i % 40 == 0:
        print(f"[{i}]", texto[:260])

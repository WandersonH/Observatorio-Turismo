"""Sondagem: anexos I e II da Lei 17.469/2021 compilada."""
import html
import re

import requests

S = requests.Session()
S.headers.update({"User-Agent": "ObservatorioTurismoAMITESP/0.1 (pesquisa academica EACH-USP)"})
URL = "https://www.al.sp.gov.br/repositorio/legislacao/lei/2021/compilacao-lei-17469-13.12.2021.html"
r = S.get(URL, timeout=90)
bruto = r.content.decode(r.apparent_encoding or "latin-1", errors="replace")
sem_riscado = re.sub(r"<s>.*?</s>", " ", bruto, flags=re.S | re.I)
print("tabelas:", len(re.findall(r"<table", sem_riscado, re.I)), "td:", len(re.findall(r"<td", sem_riscado, re.I)))
for m in re.finditer(r"ANEXO\s+I{1,2}\b", sem_riscado):
    trecho = sem_riscado[m.start():m.start() + 6000]
    texto = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", trecho)))
    print("\n>>>", texto[:3500])
print("\nmarcação crua após ANEXO II:", sem_riscado[sem_riscado.rfind("ANEXO II"):][:1500])

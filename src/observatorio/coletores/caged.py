"""Novo CAGED (MTE): admissões, desligamentos e saldo de empregos formais nas atividades
características do turismo (ACTs), por município de SP.

Lê os microdados mensais do servidor FTP do PDET (arquivos nacionais em 7z), fica só com
São Paulo e com as subclasses CNAE de `config/act_cnae.csv`, e soma por município, mês e
grupo de ACT. Os declarados fora do prazo (FOR) entram no mês a que se referem, se ele
estiver na janela; as exclusões (EXC) são descontadas.

A lista de subclasses segue o universo do SIMT/IPEA (88 subclasses em 10 grupos); o recorte
usado no índice ainda será definido com a coordenação.
"""

from __future__ import annotations

import ftplib
import logging
import re
import tempfile
from pathlib import Path

import pandas as pd

from ..cobertura import Cobertura
from ..config import pasta_config
from ..normalizacao import nome_coluna
from .base import Coletor, Resultado
from .ibge import cadastro_mestre

log = logging.getLogger(__name__)

SERVIDOR = "ftp.mtps.gov.br"
PASTA = "/pdet/microdados/NOVO CAGED"
UF_SP = "35"
COLUNAS = {"competencia": ("competenciamov",), "uf": ("uf",), "municipio": ("municipio",),
           "subclasse": ("subclasse",), "saldo": ("saldomovimentacao",),
           "competencia_exc": ("competenciaexc",)}


def subclasses_act() -> pd.DataFrame:
    return pd.read_csv(pasta_config() / "act_cnae.csv", dtype=str)


def _coluna(colunas: list[str], candidatos: tuple[str, ...]) -> str | None:
    for c in colunas:
        if c in candidatos:
            return c
    return None


def ler_microdados(caminho: Path, act: set[str], tamanho_bloco: int = 500_000) -> tuple[pd.DataFrame, int]:
    """Lê um TXT do Novo CAGED em blocos; devolve as linhas de SP nas ACTs e o total de linhas de SP."""
    cabecalho = pd.read_csv(caminho, sep=";", nrows=0, encoding="utf-8").columns
    normalizados = {nome_coluna(c): c for c in cabecalho}
    escolhidas = {}
    for alvo, candidatos in COLUNAS.items():
        achada = _coluna(list(normalizados), candidatos)
        if achada:
            escolhidas[alvo] = normalizados[achada]
    faltando = {"competencia", "uf", "municipio", "subclasse", "saldo"} - set(escolhidas)
    if faltando:
        raise ValueError(f"colunas do CAGED não encontradas: {sorted(faltando)} em {list(cabecalho)}")
    partes, total_sp = [], 0
    for bloco in pd.read_csv(caminho, sep=";", encoding="utf-8", dtype=str, usecols=list(escolhidas.values()),
                             chunksize=tamanho_bloco):
        bloco = bloco.rename(columns={v: k for k, v in escolhidas.items()})
        sp = bloco[bloco["uf"].str.strip() == UF_SP]
        total_sp += len(sp)
        partes.append(sp[sp["subclasse"].str.strip().str.zfill(7).isin(act)])
    df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=list(escolhidas))
    df["subclasse"] = df["subclasse"].str.strip().str.zfill(7)
    df["saldo"] = pd.to_numeric(df["saldo"], errors="coerce").fillna(0).astype(int)
    return df, total_sp


def agregar(mov: pd.DataFrame, grupos: dict[str, str], mapa6: dict[str, str]) -> pd.DataFrame:
    df = mov.copy()
    df["grupo"] = df["subclasse"].map(grupos)
    df["codigo_ibge"] = df["municipio"].str.strip().str[:6].map(mapa6)
    df["mes"] = df["competencia"].str.strip().str[:4] + "-" + df["competencia"].str.strip().str[4:6]
    df["sinal"] = df.get("sinal", 1)
    df["admissoes"] = ((df["saldo"] > 0) * df["sinal"]).astype(int)
    df["desligamentos"] = ((df["saldo"] < 0) * df["sinal"]).astype(int)
    df["saldo"] = df["saldo"] * df["sinal"]
    return (df.dropna(subset=["codigo_ibge"])
              .groupby(["codigo_ibge", "mes", "grupo"], as_index=False)[["admissoes", "desligamentos", "saldo"]].sum())


class ColetorCAGED(Coletor):
    fonte = "caged"
    descricao = "Novo CAGED: emprego formal nas atividades características do turismo, mensal"

    def _ftp(self) -> ftplib.FTP:
        ftp = ftplib.FTP(SERVIDOR, timeout=120, encoding="latin-1")
        ftp.login()
        return ftp

    def competencias(self, ftp: ftplib.FTP, meses: int) -> list[str]:
        ftp.cwd(PASTA)
        anos = sorted(a for a in ftp.nlst() if re.fullmatch(r"\d{4}", a))
        todas = []
        for ano in anos[-3:]:
            ftp.cwd(f"{PASTA}/{ano}")
            todas += sorted(m for m in ftp.nlst() if re.fullmatch(r"\d{6}", m))
        return todas[-meses:]

    def _baixar(self, ftp: ftplib.FTP, competencia: str, tipo: str, pasta: Path) -> Path | None:
        nome = f"CAGED{tipo}{competencia}.7z"
        ftp.cwd(f"{PASTA}/{competencia[:4]}/{competencia}")
        if nome not in ftp.nlst():
            return None
        destino = pasta / nome
        with open(destino, "wb") as f:
            ftp.retrbinary("RETR " + nome, f.write)
        import py7zr  # dependência do coletor

        with py7zr.SevenZipFile(destino) as z:
            z.extractall(path=pasta)
        destino.unlink()
        txt = sorted(pasta.glob(f"CAGED{tipo}{competencia}*.txt"))
        return txt[0] if txt else None

    def coletar(self, meses: int = 12, **_) -> Resultado:
        act = subclasses_act()
        grupos = dict(zip(act["subclasse"], act["grupo"]))
        cadastro = cadastro_mestre()
        mapa6 = {c[:6]: c for c in cadastro["codigo_ibge"]}
        ftp = self._ftp()
        janela = self.competencias(ftp, meses)
        log.info("CAGED: competências %s a %s", janela[0], janela[-1])

        partes, total_sp, lidos = [], 0, []
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp)
            for competencia in janela:
                for tipo, sinal in (("MOV", 1), ("FOR", 1), ("EXC", -1)):
                    try:
                        txt = self._baixar(ftp, competencia, tipo, pasta)
                    except ftplib.all_errors as erro:
                        log.warning("CAGED %s %s: %s; reconectando", tipo, competencia, erro)
                        ftp = self._ftp()
                        txt = self._baixar(ftp, competencia, tipo, pasta)
                    if txt is None:
                        continue
                    df, sp = ler_microdados(txt, set(grupos))
                    txt.unlink()
                    # FOR e EXC valem na competência original (competenciamov), se ela estiver na janela
                    df = df[df["competencia"].str.strip().isin(janela)]
                    df["sinal"] = sinal
                    df["arquivo"] = f"{tipo}{competencia}"
                    partes.append(df)
                    if tipo == "MOV":
                        total_sp += sp
                    lidos.append(f"{tipo}{competencia}")
                    log.info("CAGED %s%s: %d linhas de SP, %d em ACTs", tipo, competencia, sp, len(df))
        ftp.close()
        mov = pd.concat(partes, ignore_index=True)
        tratado = agregar(mov, grupos, mapa6)

        base = set(cadastro.loc[cadastro["na_base_amitesp"].astype(bool), "codigo_ibge"])
        mov_mov = mov[mov["arquivo"].str.startswith("MOV")]
        cobertura = Cobertura(
            fonte=self.fonte, tabela="emprego_act", universo=int(total_sp), amostra=int(len(mov_mov)),
            unidade="movimentações de SP declaradas no prazo, nas ACTs",
            municipios_com_dado=len(set(tratado["codigo_ibge"]) & base), municipios_esperados=len(base),
            notas=[f"competências {janela[0]} a {janela[-1]}", f"arquivos lidos: {len(lidos)}",
                   f"subclasses ACT: {len(grupos)} (universo SIMT/IPEA)",
                   "universo = todas as movimentações de SP no prazo; amostra = as que caem nas ACTs"],
        )
        bruto = mov.drop(columns=["uf"], errors="ignore")
        return Resultado(tabelas={"movimentacoes_act": bruto}, tratadas={"emprego_act": tratado},
                         coberturas=[cobertura])

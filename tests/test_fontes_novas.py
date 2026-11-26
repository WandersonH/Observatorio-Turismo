"""Leitores das fontes novas, sem rede: amostras no formato que cada fonte entrega."""


import pandas as pd
import pytest

from observatorio.coletores.alesp import ler_classificacao, registros
from observatorio.coletores.anac import aeroportos_sp
from observatorio.coletores.antt import ler_licencas, mes_do_recurso, movimentos, por_municipio
from observatorio.coletores.caged import agregar, ler_microdados, subclasses_act
from observatorio.coletores.cetesb import ler_tabela_iqr
from observatorio.coletores.google_places import coluna_nome, similaridade
from observatorio.coletores.producoes import itens_rss
from observatorio.normalizacao import LocalizadorMunicipios, texto_simples

MAPA = {"guararema": "3518305", "guarulhos": "3518800", "saopaulo": "3550308", "campinas": "3509502"}


def test_localizador_ignora_estado_de_sao_paulo():
    loc = LocalizadorMunicipios({"3518305": "Guararema", "3550308": "São Paulo", "1": "Bom Jesus dos Perdões",
                                 "2": "Bom Jesus"})
    assert loc.achar("Declara Guararema e Bom Jesus dos Perdões, Estado de São Paulo, MIT") == ["3518305", "1"]
    assert loc.achar("evento na capital, em São Paulo") == ["3550308"]


def test_act_tem_88_subclasses_sem_repeticao():
    act = subclasses_act()
    assert len(act) == 88 and act["subclasse"].is_unique and act["subclasse"].str.len().eq(7).all()


def test_caged_le_microdados_e_agrega(tmp_path):
    arquivo = tmp_path / "CAGEDMOV202609.txt"
    arquivo.write_text(
        "competênciamov;região;uf;município;seção;subclasse;saldomovimentação;idade\n"
        "202609;3;35;351830;I;5510801;1;30\n"
        "202609;3;35;351830;I;5510801;-1;22\n"
        "202609;3;35;351830;I;5611201;1;40\n"
        "202609;3;35;351830;G;4711302;1;19\n"      # comércio: fora das ACTs
        "202609;3;33;330455;I;5510801;1;50\n",     # RJ: fora de SP
        encoding="utf-8")
    act = subclasses_act()
    df, total_sp = ler_microdados(arquivo, set(act["subclasse"]))
    assert total_sp == 4 and len(df) == 3
    df["sinal"] = 1
    tabela = agregar(df, dict(zip(act["subclasse"], act["grupo"])), {"351830": "3518305"})
    aloj = tabela[tabela["grupo"] == "Alojamento"].iloc[0]
    assert (aloj["admissoes"], aloj["desligamentos"], aloj["saldo"]) == (1, 1, 0)
    assert tabela["mes"].unique().tolist() == ["2026-09"]


def test_caged_exclusao_desconta():
    df = pd.DataFrame({"competencia": ["202609"] * 2, "municipio": ["351830"] * 2, "subclasse": ["5510801"] * 2,
                       "saldo": [1, 1], "sinal": [1, -1]})
    tabela = agregar(df, {"5510801": "Alojamento"}, {"351830": "3518305"})
    assert tabela.iloc[0]["saldo"] == 0 and tabela.iloc[0]["admissoes"] == 0


def _csv_antt(linhas):
    cab = ("data_solicitacao;data_inicio_viagem;data_fim_viagem;cnpj;razao_social;cnpj_cpf_contratante;contratante;"
           "placa;tipo_veiculo;numero_licenca_viagem;data_autorizacao_viagem;tipo_viagem;municipio_origem;"
           "uf_município_origem;distancia_total;total_passageiros;tipo_trecho;sequencia_trecho;pais_inicio_trecho;"
           "UF_inicio_trecho;municipio_inicio_trecho;localidade_inicio_trecho;data_hora_partida_inicio_trecho;"
           "pais_final_trecho;UF_final_trecho;municipio_final_trecho;localidade_final_trecho;"
           "data_hora_chegada_final_trecho;distancia_trecho;granularidade")
    return ("\n".join([cab] + linhas)).encode("latin-1")


def _linha(lic, tipo, origem, uf_origem, pax, uf_fim, fim):
    return (f'"01/11";"01/11/2026";"02/11/2026";"x";"Empresa";"0**";"J***";"ABC1234";"ONIBUS";"{lic}";"x";"{tipo}";'
            f'"{origem}";"{uf_origem}";100;{pax};"Passagem";1;"BRASIL";"MG";"{origem}";"C";"x";"BRASIL";"{uf_fim}";'
            f'"{fim}";"C";"x";10;"Nacional"')


def test_antt_chegadas_saidas_e_exclusoes():
    conteudo = _csv_antt([
        _linha(1, "Comum", "POUSO ALEGRE", "MG", 40, "SP", "GUARAREMA"),
        _linha(1, "Comum", "POUSO ALEGRE", "MG", 40, "SP", "GUARULHOS"),
        _linha(2, "Transporte de Trabalhadores", "POUSO ALEGRE", "MG", 20, "SP", "GUARAREMA"),
        _linha(3, "Comum", "CAMPINAS", "SP", 30, "MG", "POUSO ALEGRE"),
        _linha(3, "Comum", "CAMPINAS", "SP", 30, "SP", "CAMPINAS"),  # retorno à origem
    ])
    trechos = ler_licencas(conteudo)
    assert "contratante" not in trechos.columns
    tabela = por_municipio(movimentos(trechos, MAPA)).set_index("codigo_ibge")
    assert tabela.loc["3518305", "licencas_chegada"] == 1 and tabela.loc["3518305", "passageiros_chegada"] == 40
    assert tabela.loc["3509502", "licencas_saida"] == 1 and tabela.loc["3509502", "licencas_chegada"] == 0


@pytest.mark.parametrize("nome, esperado", [("Licenças de Viagem - Out2026", (2026, 10)),
                                            ("Licenças de Viagem - Mar2026", (2026, 3)), ("Outro", None)])
def test_mes_do_recurso(nome, esperado):
    assert mes_do_recurso(nome) == esperado


def test_anac_aerodromos_em_latin1_com_uf_por_extenso():
    texto = ("Atualizado em: 2026-11-15\n"
             "Código OACI;CIAD;Nome;Município;UF;Município Servido;UF Servido\n"
             "SBGR;SP0001;Guarulhos;GUARULHOS;São Paulo;São Paulo;São Paulo\n"
             "SBRB;AC0001;Plácido de Castro;RIO BRANCO;Acre;Rio Branco;Acre\n")
    sp = aeroportos_sp(texto.encode("latin-1"), MAPA)
    assert sp.to_dict("records") == [{"sigla": "SBGR", "municipio_aeroporto": "GUARULHOS", "codigo_ibge": "3518800"}]


def test_cetesb_le_linha_do_anexo_e_ignora_rankings():
    texto = "\n".join([
        "11 GUARAREMA Mogi das Cruzes 6 8,9 Jambeiro - A.P.",
        "GUARAREMA Mogi das Cruzes 2 20,97 9,7 8,9 Jambeiro - A.P.   ",
        "GUARAREMA Mogi das Cruzes 2 7,80 8,50    Jambeiro - AP",
        "SÃO PAULO São Paulo 6 12.345,67 8,0 6,5 Caieiras - A.P.",
    ])
    nomes = {texto_simples("Guararema"): "3518305", texto_simples("São Paulo"): "3550308"}
    df = ler_tabela_iqr(texto, nomes).set_index("codigo_ibge")
    assert df.loc["3518305", "iqr"] == 8.9 and df.loc["3518305", "residuos_t_dia"] == 20.97
    assert df.loc["3550308", "residuos_t_dia"] == 12345.67 and not df.loc["3550308", "iqr_adequado"]


def test_alesp_registros_genericos():
    xml = ("<?xml version='1.0' encoding='UTF-8'?><proposituras>"
           "<propositura><IdDocumento>1</IdDocumento><Ementa>Declara Guararema Município de Interesse Turístico</Ementa>"
           "</propositura><propositura><IdDocumento>2</IdDocumento><Ementa>Outro tema</Ementa></propositura>"
           "</proposituras>").encode()
    lidos = list(registros(xml))
    assert [r["iddocumento"] for r in lidos] == ["1", "2"] and "ementa" in lidos[0]


def test_rss_do_google_noticias():
    xml = ("<rss><channel><item><title>Festival em Guararema</title><link>https://x</link>"
           "<pubDate>Wed, 25 Nov 2026 10:00:00 GMT</pubDate><source url='https://y'>Jornal</source></item>"
           "</channel></rss>")
    assert itens_rss(xml) == [{"titulo": "Festival em Guararema", "link": "https://x", "veiculo": "Jornal",
                               "publicado": "2026-11-25"}]


def test_pareamento_google():
    assert similaridade("Pousada Recanto do Vale", "Pousada Recanto do Vale - Guararema") > 0.6
    assert similaridade("Hotel Central", "Pizzaria Bella") < 0.6
    assert coluna_nome(pd.DataFrame(columns=["codigo_ibge", "razao_social", "nome_fantasia"])) == "nome_fantasia"


def test_alesp_classificacao_ignora_trechos_revogados():
    pagina = """<html><p>(&Uacute;ltima atualiza&ccedil;&atilde;o: Lei n&#176; 18.379, de 23/12/2025)</p>
    <s><p>I - Guararema (revogado)</p></s>
    <h4>ANEXO I<br>a que se refere o artigo 2&#176;</h4><table><tr><td>Classifica&ccedil;&atilde;o</td><td>Munic&iacute;pio</td></tr>
    <tr><td>1.</td><td>Itanha&eacute;m</td></tr><tr><td>2.</td><td>Guararema</td></tr></table>
    <h4>ANEXO II<br>a que se refere o artigo 3&#176;</h4><table><tr><td>Classifica&ccedil;&atilde;o</td><td>Munic&iacute;pio</td></tr>
    <tr><td>1.</td><td>Ara&ccedil;atuba</td></tr><s><tr><td>2.</td><td>Revogada</td></tr></s></table></html>"""
    tabela, atualizacao = ler_classificacao(pagina)
    assert atualizacao == "Lei n° 18.379, de 23/12/2025"
    assert tabela.to_dict("records") == [
        {"categoria_turistica": "Estância Turística", "posicao_ranking": 1, "municipio_lei": "Itanhaém"},
        {"categoria_turistica": "Estância Turística", "posicao_ranking": 2, "municipio_lei": "Guararema"},
        {"categoria_turistica": "Município de Interesse Turístico", "posicao_ranking": 1, "municipio_lei": "Araçatuba"}]


def test_get_tenta_de_novo_em_erro_passageiro(monkeypatch):
    import time as _time

    from observatorio.coletores.base import Coletor

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    respostas = iter([Resp(522), Resp(200)])

    class Teste(Coletor):
        fonte = "teste"

        def coletar(self, **_):
            return None

    c = Teste()
    monkeypatch.setattr(c.sessao, "get", lambda *a, **k: next(respostas))
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    assert c.get("https://exemplo").status_code == 200

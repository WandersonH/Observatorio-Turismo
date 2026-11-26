"""Linha de comando: ``coletar <fonte>``, ``rodar-tudo``, ``site`` e ``fontes``."""

from __future__ import annotations

import argparse
import logging
import sys

from .coletores import COLETORES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="observatorio", description=__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)

    coletar = sub.add_parser("coletar", help="executa um coletor e grava bruto e cobertura")
    coletar.add_argument("fonte", choices=sorted(COLETORES))
    coletar.add_argument("--anos", nargs="*", type=int, help="exercícios (Siconfi)")
    coletar.add_argument("--todos", action="store_true", help="todos os 645 municípios de SP, não só a base")
    coletar.add_argument("--incluir-guias", action="store_true", help="Cadastur: inclui guias (pessoas físicas)")

    sub.add_parser("fontes", help="lista os coletores disponíveis")
    rodar = sub.add_parser("rodar-tudo", help="roda os coletores e registra o que rodou, falhou ou não existe")
    rodar.add_argument("--fontes", nargs="*", help="só estas fontes (para rodar em paralelo)")
    site = sub.add_parser("site", help="gera o site e a API estática a partir das cargas tratadas")
    site.add_argument("--saida", default="_site")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.comando == "fontes":
        for fonte, classe in sorted(COLETORES.items()):
            print(f"{fonte:10s} {classe.descricao}")
        return 0

    if args.comando == "rodar-tudo":
        from .execucao import resumo, rodar_tudo

        # Falhas ficam registradas no status.json; o comando não aborta para o site sair mesmo assim
        print(resumo(rodar_tudo(args.fontes or None)))
        return 0

    if args.comando == "site":
        from .site import construir

        print(f"site em {construir(args.saida)}")
        return 0

    parametros = {"anos": args.anos, "todos": args.todos, "incluir_guias": args.incluir_guias}
    resultado = COLETORES[args.fonte]().executar(**parametros)
    for cobertura in resultado.coberturas:
        print(cobertura.resumo())
    return 0


if __name__ == "__main__":
    sys.exit(main())

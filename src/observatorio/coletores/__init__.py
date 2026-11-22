"""Registro dos coletores disponíveis. Novos coletores entram aqui."""

from .cadastur import ColetorCadastur
from .ibge import ColetorIBGE
from .siconfi import ColetorSiconfi

COLETORES = {c.fonte: c for c in (ColetorIBGE, ColetorCadastur, ColetorSiconfi)}

__all__ = ["COLETORES"]

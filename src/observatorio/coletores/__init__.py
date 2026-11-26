"""Registro dos coletores disponíveis. Novos coletores entram aqui."""

from .alesp import ColetorAlesp
from .anac import ColetorANAC
from .antt import ColetorANTT
from .cadastur import ColetorCadastur
from .caged import ColetorCAGED
from .cetesb import ColetorCETESB
from .google_places import ColetorGooglePlaces
from .ibge import ColetorIBGE
from .planos_diretores import ColetorPlanosDiretores
from .producoes import ColetorProducoes
from .siconfi import ColetorSiconfi

COLETORES = {c.fonte: c for c in (ColetorIBGE, ColetorCadastur, ColetorSiconfi, ColetorCAGED, ColetorANAC,
                                  ColetorANTT, ColetorCETESB, ColetorAlesp, ColetorPlanosDiretores,
                                  ColetorProducoes, ColetorGooglePlaces)}

__all__ = ["COLETORES"]

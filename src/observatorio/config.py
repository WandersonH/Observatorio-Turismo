"""Localização da pasta config/ (catálogo de fontes e municípios da base)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def pasta_config() -> Path:
    """Pela variável OBS_CONFIG, pela pasta atual ou pelo repositório."""
    candidatos = [Path(os.environ["OBS_CONFIG"])] if os.environ.get("OBS_CONFIG") else []
    candidatos += [Path.cwd() / "config", Path(__file__).resolve().parents[2] / "config"]
    for pasta in candidatos:
        if (pasta / "fontes.yaml").exists():
            return pasta
    raise FileNotFoundError("pasta config/ não encontrada; defina OBS_CONFIG")


def catalogo_fontes() -> list[dict]:
    return yaml.safe_load((pasta_config() / "fontes.yaml").read_text(encoding="utf-8"))["fontes"]

"""Configuração central e portável (Linux + Windows).

Regras (bot-lol.md, seções 5 e 14):
  - Nenhum caminho hardcoded por SO: tudo via pathlib, relativo à raiz.
  - Segredos vêm de variáveis de ambiente / .env, nunca do código.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()  # carrega .env se existir; em produção pode usar env vars puras
except ImportError:  # dotenv é opcional em runtime; env vars puras bastam
    pass

# Raiz do projeto = pasta que contém este pacote.
BASE_DIR = Path(__file__).resolve().parent.parent

# Estado local (fora do Git). Construído de forma portável.
DATA_DIR = Path(os.environ.get("BOT_LOL_DATA_DIR", BASE_DIR / "data"))
CACHE_DIR = Path(os.environ.get("BOT_LOL_CACHE_DIR", BASE_DIR / "cache"))
DB_PATH = Path(os.environ.get("BOT_LOL_DB_PATH", DATA_DIR / "bot_lol.db"))

# Roteamento Riot (grupo joga no BR).
RIOT_REGIONAL = os.environ.get("RIOT_REGIONAL", "americas")
RIOT_PLATFORM = os.environ.get("RIOT_PLATFORM", "br1")

# Segredos (podem estar vazios nesta fase; cada marco usa o seu).
RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")


def ensure_dirs() -> None:
    """Cria as pastas de estado local se ainda não existirem."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

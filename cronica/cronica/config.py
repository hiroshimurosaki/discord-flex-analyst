"""Configuração — caminhos portáveis, segredos por ambiente.

Nenhum caminho hardcoded por SO (tudo `pathlib`, relativo à raiz do projeto) e
nenhum segredo no código. `RIOT_API_KEY` vem do ambiente ou do `.env`; ela nunca
aparece em arquivo versionado nem em saída de log.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv é conveniência; env vars puras bastam
    pass

RAIZ = Path(__file__).resolve().parent.parent

DIR_DADOS = Path(os.environ.get("CRONICA_DIR_DADOS", RAIZ / "dados"))
DIR_CACHE = Path(os.environ.get("CRONICA_DIR_CACHE", RAIZ / "cache"))
DIR_SAIDA = Path(os.environ.get("CRONICA_DIR_SAIDA", RAIZ / "saida"))
DIR_CANONE = Path(os.environ.get("CRONICA_DIR_CANONE", RAIZ / "canone"))

BANCO = Path(os.environ.get("CRONICA_BANCO", DIR_DADOS / "fatos.db"))

# Riot: o grupo joga no BR. account-v1 e match-v5 roteiam por 'americas'.
RIOT_REGIONAL = os.environ.get("RIOT_REGIONAL", "americas")
RIOT_PLATFORM = os.environ.get("RIOT_PLATFORM", "br1")
RIOT_API_KEY = os.environ.get("RIOT_API_KEY", "")

# Filas. A história é de Flex; SoloQ entra como subtrama de personagem.
FILA_FLEX = 440
FILA_SOLO = 420
FILAS_COLETADAS = (FILA_FLEX, FILA_SOLO)

# --- LLM: Claude Code headless (`claude -p`), não a API HTTP ---
# Autentica pela assinatura, então o custo fica no plano. Em CI o token vem de
# CLAUDE_CODE_OAUTH_TOKEN. ANTHROPIC_API_KEY tem precedência sobre ele, por isso
# `narracao/llm.py` a remove do ambiente do subprocesso.
CLAUDE_BIN = os.environ.get("CRONICA_CLAUDE_BIN", "claude")
CLAUDE_MODEL = os.environ.get("CRONICA_CLAUDE_MODEL", "sonnet")
CLAUDE_TIMEOUT_S = int(os.environ.get("CRONICA_CLAUDE_TIMEOUT_S", "300"))


def garantir_dirs() -> None:
    for d in (DIR_DADOS, DIR_CACHE, DIR_SAIDA, DIR_CANONE):
        d.mkdir(parents=True, exist_ok=True)
    (DIR_SAIDA / "briefings").mkdir(parents=True, exist_ok=True)
    (DIR_SAIDA / "capitulos").mkdir(parents=True, exist_ok=True)

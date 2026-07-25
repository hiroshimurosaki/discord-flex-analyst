"""Registra os slash commands na API do Discord (rodar quando mudarem).

Com o bot de gateway, `discord.py` sincronizava os comandos ao conectar. Sem
processo de pé, o registro vira uma chamada HTTP explícita — é isto.

Uso:
    DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... python -m scripts.registrar_comandos
    ... --global      # registra global (propaga em até 1h; sem, é por guild)

Comandos por guild aparecem na hora — use isso enquanto estiver iterando.
"""
from __future__ import annotations

import os
import sys

import requests

from bot_lol import config

API = "https://discord.com/api/v10"

_RECORTE = {
    "name": "recorte",
    "description": "Flex (sério), Normais (zoeira) ou Solo/Duo",
    "type": 3,                      # STRING
    "required": False,
    "choices": [
        {"name": "Flex", "value": "flex"},
        {"name": "Normais", "value": "normais"},
        {"name": "Solo/Duo", "value": "solo"},
    ],
}

_JOGADOR = {
    "name": "jogador",
    "description": "Nome do jogador",
    "type": 3,
    "required": True,
    "autocomplete": True,
}

_PARTIDA = {
    "name": "partida",
    "description": "ID da partida (padrão: a mais recente)",
    "type": 4,                      # INTEGER
    "required": False,
}

COMANDOS = [
    {"name": "recordes", "description": "Hall da Fama do grupo",
     "options": [_RECORTE]},
    {"name": "perfil", "description": "Ficha individual de um jogador",
     "options": [_JOGADOR, _RECORTE]},
    {"name": "time", "description": "Post da última partida em grupo",
     "options": [_PARTIDA]},
    {"name": "jogador", "description": "Análise individual numa partida",
     "options": [_JOGADOR, _PARTIDA]},
]


def main() -> None:
    app_id = config.DISCORD_APP_ID or os.environ.get("DISCORD_APP_ID", "")
    token = config.DISCORD_BOT_TOKEN
    guild = config.DISCORD_GUILD_ID
    usar_global = "--global" in sys.argv

    if not (app_id and token):
        print("Defina DISCORD_APP_ID e DISCORD_BOT_TOKEN.", file=sys.stderr)
        raise SystemExit(1)
    if not usar_global and not guild:
        print("Defina DISCORD_GUILD_ID (ou passe --global).", file=sys.stderr)
        raise SystemExit(1)

    url = (f"{API}/applications/{app_id}/commands" if usar_global else
           f"{API}/applications/{app_id}/guilds/{guild}/commands")

    # PUT substitui o conjunto inteiro: comandos removidos daqui somem de lá.
    r = requests.put(url, json=COMANDOS, timeout=20,
                     headers={"Authorization": f"Bot {token}"})
    if not r.ok:
        print(f"Falhou ({r.status_code}): {r.text[:800]}", file=sys.stderr)
        raise SystemExit(1)

    escopo = "globalmente" if usar_global else f"na guild {guild}"
    print(f"{len(r.json())} comandos registrados {escopo}:")
    for c in r.json():
        print(f"  /{c['name']}")


if __name__ == "__main__":
    main()

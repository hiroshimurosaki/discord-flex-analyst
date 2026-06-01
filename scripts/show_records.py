"""Mostra o /recordes (Flex e normais) e o /perfil de cada jogador.

Uso:  python -m scripts.show_records
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol import records
from bot_lol.db import database as db


def main() -> None:
    conn = db.get_connection()
    grupo = conn.execute("SELECT id, nome FROM grupos ORDER BY id LIMIT 1").fetchone()
    if not grupo:
        print("Sem grupo no banco. Rode primeiro: python -m scripts.seed_demo")
        return

    print("═" * 60)
    print(records.formatar_recordes(conn, grupo["id"], grupo["nome"], records.FLEX))
    print("\n" + "═" * 60)
    print(records.formatar_recordes(conn, grupo["id"], grupo["nome"], records.NORMAIS))

    print("\n" + "═" * 60 + "\n PERFIS INDIVIDUAIS (Flex)\n" + "═" * 60)
    for j in conn.execute("SELECT id, nick_display FROM jogadores ORDER BY id"):
        txt = records.formatar_perfil(conn, grupo["id"], j["id"], j["nick_display"])
        # só mostra quem tem jogos
        if "sem partidas" not in txt:
            print("\n" + txt)
    conn.close()


if __name__ == "__main__":
    main()

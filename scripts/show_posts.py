"""Mostra como ficariam os posts do Discord para as partidas no banco.

Uso:  python -m scripts.show_posts
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol.db import database as db
from bot_lol.post import montar_post


def main() -> None:
    conn = db.get_connection()
    partidas = conn.execute(
        "SELECT id FROM partidas WHERE queue_id=440 ORDER BY inicio_ts DESC LIMIT 3"
    ).fetchall()
    for row in partidas:
        print("\n" + "═" * 60)
        print(montar_post(conn, row["id"]))
    conn.close()


if __name__ == "__main__":
    main()

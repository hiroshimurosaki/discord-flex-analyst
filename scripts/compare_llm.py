"""Compara modelos/efforts narrando as partidas reais (decisão do usuário).

Gera a 🎙️ narrativa das partidas em grupo com cada configuração e imprime lado
a lado pra você calibrar antes de cravar CLAUDE_MODEL/CLAUDE_EFFORT no .env.

Narração é uma tarefa barata: a suspeita padrão é que `sonnet` + `low` já basta,
e cada degrau acima custa cota da assinatura. Este script é pra confirmar isso
com os SEUS jogos, não pra aceitar de palavra.

Uso:  python -m scripts.compare_llm                    (última partida)
      python -m scripts.compare_llm todas              (as 3 últimas)
      python -m scripts.compare_llm todas sonnet:low opus:medium
"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol import config, llm, post
from bot_lol.db import database as db

# (modelo, effort) — o default cobre a pergunta que importa: subir de modelo
# muda a narrativa o suficiente pra justificar o gasto?
PADRAO = [("sonnet", "low"), ("sonnet", "medium"), ("opus", "low")]


def _parse_args(argv: list[str]) -> tuple[int, list[tuple[str, str]]]:
    todas = "todas" in argv
    combos = []
    for a in argv:
        if ":" in a:
            m, _, e = a.partition(":")
            combos.append((m, e))
    return (3 if todas else 1), (combos or PADRAO)


def main() -> None:
    if not llm.disponivel():
        print(f"Binário '{config.CLAUDE_BIN}' não encontrado.\n"
              "  npm install -g @anthropic-ai/claude-code\n"
              "  claude   # e faça /login com sua conta Pro")
        return

    limit, combos = _parse_args(sys.argv[1:])

    conn = db.get_connection()
    partidas = conn.execute(
        "SELECT id, match_id FROM partidas WHERE em_grupo=1 "
        "ORDER BY inicio_ts DESC LIMIT ?", (limit,)).fetchall()
    if not partidas:
        print("Nenhuma partida em grupo no banco. Rode o backfill primeiro.")
        conn.close()
        return

    for row in partidas:
        fatos = post.fatos_partida(conn, row["id"])
        print("\n" + "█" * 64)
        print(f" PARTIDA {row['match_id']}")
        print("█" * 64)

        for modelo, effort in combos:
            # `analisar` lê o effort do config, então trocamos por chamada.
            anterior, config.CLAUDE_EFFORT = config.CLAUDE_EFFORT, effort
            try:
                t0 = time.monotonic()
                texto = llm.analisar(fatos, modelo)
                dt = time.monotonic() - t0
                print(f"\n──────── {modelo} · effort={effort} · {dt:.1f}s ────────")
                print(texto)
            except Exception as e:
                print(f"\n──────── {modelo} · effort={effort} ────────")
                print(f"falhou: {e}")
            finally:
                config.CLAUDE_EFFORT = anterior
    conn.close()


if __name__ == "__main__":
    main()

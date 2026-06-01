"""Compara Flash vs Pro narrando as partidas reais (decisão do usuário).

Resolve os nomes reais dos modelos na sua conta, gera a 🎙️ narrativa das
partidas em grupo com cada modelo e imprime lado a lado pra você calibrar.

Uso:  python -m scripts.compare_llm            (última partida)
      python -m scripts.compare_llm todas      (as 3)
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol import config, llm, post
from bot_lol.db import database as db


def main() -> None:
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY ausente. Pegue a chave grátis em "
              "https://aistudio.google.com/apikey e coloque no .env.")
        return

    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    modelos = llm.resolver_modelos(client)
    print("Modelos resolvidos na sua conta:")
    for k, v in modelos.items():
        print(f"  {k:<11} -> {v}")
    flash, pro = modelos.get("flash"), modelos.get("pro")
    if not flash:
        print("Não encontrei um modelo Flash na conta.")
        return

    conn = db.get_connection()
    todas = len(sys.argv) > 1 and sys.argv[1] == "todas"
    limit = 3 if todas else 1
    partidas = conn.execute(
        "SELECT id, match_id FROM partidas WHERE em_grupo=1 ORDER BY inicio_ts DESC LIMIT ?",
        (limit,)).fetchall()

    for row in partidas:
        # os fatos determinísticos (sem narrativa) viram o contexto
        fatos = post.montar_post(conn, row["id"])
        print("\n" + "█" * 64)
        print(f" PARTIDA {row['match_id']}")
        print("█" * 64)

        print(f"\n──────── FLASH ({flash}) ────────")
        print(llm.analisar(fatos, flash))

        if pro:
            # Pro exige thinking; dá orçamento maior pra não truncar a saída.
            print(f"\n──────── PRO ({pro}) ────────")
            print(llm.analisar(fatos, pro, max_output_tokens=8192))
    conn.close()


if __name__ == "__main__":
    main()

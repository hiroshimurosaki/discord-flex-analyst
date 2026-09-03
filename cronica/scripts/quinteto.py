"""Quem é o time canônico, segundo os dados.

Responde com dado o que a memória chuta: quais 5 pessoas jogaram flex juntas
mais vezes. Use antes de fechar o `elenco` do cânone.

    python -m scripts.quinteto
"""
from __future__ import annotations

import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica.cronologia.series import carregar_cenas   # noqa: E402
from cronica.fatos import db                           # noqa: E402


def main() -> int:
    conn = db.conectar()
    db.migrar(conn)
    cenas = carregar_cenas(conn, min_membros=2)
    if not cenas:
        print("banco vazio — rode `python -m scripts.coletar` antes.")
        return 1

    print(f"{len(cenas)} partidas de flex com 2+ membros no mesmo time.\n")

    print("presença individual:")
    solo = Counter(m for c in cenas for m in c.elenco)
    for m, n in solo.most_common():
        print(f"  {m:<14} {n:>4} jogos  ({100 * n / len(cenas):.0f}%)")

    quintetos = Counter()
    for c in cenas:
        if len(c.elenco) >= 5:
            for combo in combinations(sorted(c.elenco), 5):
                quintetos[combo] += 1
    if quintetos:
        print("\nquintetos mais frequentes:")
        for combo, n in quintetos.most_common(5):
            vit = sum(1 for c in cenas if set(combo) <= c.elenco and c.venceu)
            print(f"  {n:>4}x  {100 * vit / n:>5.1f}% WR   {', '.join(combo)}")
    else:
        print("\nnenhuma partida com 5 membros: o 'time canônico' é de 2 a 4.")

    print("\nduplas mais frequentes:")
    duplas = Counter()
    for c in cenas:
        for combo in combinations(sorted(c.elenco), 2):
            duplas[combo] += 1
    for combo, n in duplas.most_common(6):
        vit = sum(1 for c in cenas if set(combo) <= c.elenco and c.venceu)
        print(f"  {n:>4}x  {100 * vit / n:>5.1f}% WR   {' + '.join(combo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

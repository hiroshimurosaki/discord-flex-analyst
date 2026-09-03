"""Coleta o histórico da Riot para o banco de fatos.

    export RIOT_API_KEY=...            # nunca commite a chave
    python -m scripts.coletar canone/time.yaml

Idempotente: re-rodar só baixa o que falta. A primeira coleta de 8 jogadores com
chave de dev leva horas por causa do rate limit — chave de produção resolve.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica import config                                   # noqa: E402
from cronica.canone import carregar                          # noqa: E402
from cronica.fatos import coleta, db                         # noqa: E402
from cronica.fatos.riot import ClienteRiot, ErroRiot         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("canone", nargs="?", default="canone/time.yaml")
    ap.add_argument("--max-por-membro", type=int, default=1000)
    ap.add_argument("--so-flex", action="store_true",
                    help="pula SoloQ (mais rápido; perde a subtrama de personagem)")
    a = ap.parse_args()

    config.garantir_dirs()
    can = carregar(a.canone)
    conn = db.conectar()
    db.migrar(conn)

    try:
        cliente = ClienteRiot()
    except ErroRiot as e:
        print(f"✗ {e}")
        return 1

    print(f"resolvendo PUUIDs de {len(can.membros)} membros...")
    mapa = coleta.resolver_puuids(conn, cliente, can)
    if not mapa:
        print("✗ nenhum PUUID resolvido — confira as grafias dos Riot IDs.")
        return 1

    filas = (config.FILA_FLEX,) if a.so_flex else config.FILAS_COLETADAS
    print(f"\ncoletando filas {filas}...")
    s = coleta.coletar(conn, cliente, mapa, filas=filas,
                       max_por_membro=a.max_por_membro)
    print(f"\n✓ {s['novas']} partidas novas ({s['em_grupo']} em grupo, "
          f"{s['timelines']} com timeline) — banco: {config.BANCO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

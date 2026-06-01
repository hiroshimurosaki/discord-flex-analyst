"""Backfill: puxa TODO o histórico disponível (Flex, SoloQ, normais) dos 8.

Cataloga cada partida única uma vez (dedupe por match_id). Baixa timeline só
das partidas EM GRUPO (2+ membros no mesmo time), pra economizar chamadas.
Solo/normais entram no dataset (champion mastery / contexto), mas com em_grupo=0.

Reaproveita o cache em disco — re-rodar não rebaixa o que já pegou.
A chave de dev expira em 24h; se morrer no meio, troque no .env e re-rode.

Uso:  python -m scripts.backfill            (até 1000 por jogador)
      python -m scripts.backfill 300        (limita a 300 por jogador)
"""
from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol import config, records
from bot_lol.db import database as db
from bot_lol.ingest import detectar_em_grupo, ingest_match, parse_participacoes
from bot_lol.riot_api import RiotClient

PERMITIDAS = records.PERMITIDAS  # Flex + SoloQ + normais (sem ARAM/Arena/etc.)


def purgar_indesejadas(conn, grupo_id: int) -> int:
    """Remove partidas de filas fora da allowlist (e suas participações/análises)."""
    qs = ",".join(str(q) for q in PERMITIDAS)
    ids = [r["id"] for r in conn.execute(
        f"SELECT id FROM partidas WHERE grupo_id=? AND queue_id NOT IN ({qs})", (grupo_id,))]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM analises WHERE partida_id IN ({marks})", ids)
    conn.execute(f"DELETE FROM participacoes WHERE partida_id IN ({marks})", ids)
    conn.execute(f"DELETE FROM partidas WHERE id IN ({marks})", ids)
    conn.commit()
    return len(ids)

PLAYERS = [
    ("Hiroshi", "10102"), ("Qiak", "000"), ("Yuya Freecss", "BR1"),
    ("Thokyru", "BR1"), ("Top Mogger", "Dasky"), ("Nashorn", "Shiro"),
    ("Lukyy", "Luky"), ("Nyachi", "mee"),
]


def main() -> None:
    max_total = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    config.ensure_dirs()
    client = RiotClient()
    conn = db.get_connection()
    db.init_db(conn)
    grupo_id = db.ensure_grupo(conn, "Esquadrão Flex", discord_guild_id="demo")

    print("== PUUIDs ==")
    puuid_to_jogador: dict[str, int] = {}
    for name, tag in PLAYERS:
        puuid = client.get_puuid(name, tag)
        if not puuid:
            print(f"  ✗ {name}#{tag}")
            continue
        puuid_to_jogador[puuid] = db.ensure_jogador(conn, grupo_id, puuid, name, f"{name}#{tag}")
        print(f"  ✓ {name}")

    removidas = purgar_indesejadas(conn, grupo_id)
    if removidas:
        print(f"\nPurgadas {removidas} partidas de filas indesejadas (ARAM/Arena/etc.).")

    print(f"\n== IDs de partida (só {sorted(PERMITIDAS)}, até {max_total}/jogador) ==")
    ids: set[str] = set()
    for puuid in puuid_to_jogador:
        antes = len(ids)
        for q in PERMITIDAS:  # uma varredura por fila permitida -> não baixa o resto
            ids.update(client.get_match_ids_all(puuid, max_total=max_total, queue=q))
        print(f"  +{len(ids)-antes}  (únicas acumuladas: {len(ids)})")
    ids = sorted(ids)
    print(f"\nTotal de partidas únicas: {len(ids)}")

    print("\n== Ingestão (timeline só p/ partidas em grupo) ==")
    novas = grupo = puladas = 0
    for i, mid in enumerate(ids, 1):
        if db.partida_existe(conn, grupo_id, mid):
            puladas += 1
            continue
        m = client.get_match(mid)
        if not m:
            continue
        if m.get("info", {}).get("queueId") not in PERMITIDAS:  # defesa extra
            puladas += 1
            continue
        # decide em_grupo antes pra saber se baixa timeline
        linhas = parse_participacoes(m, puuid_to_jogador)
        tl = client.get_timeline(mid) if detectar_em_grupo(linhas) else None
        pid = ingest_match(conn, grupo_id, puuid_to_jogador, m, tl)
        if pid:
            novas += 1
            if tl is not None:
                grupo += 1
        if i % 50 == 0:
            print(f"   ...{i}/{len(ids)}  (novas {novas}, grupo {grupo}, já tinha {puladas})")

    print(f"\nPronto. Novas {novas} · em grupo {grupo} · já existiam {puladas}.")
    tot = conn.execute("SELECT COUNT(*) c FROM partidas WHERE grupo_id=?", (grupo_id,)).fetchone()["c"]
    emg = conn.execute("SELECT COUNT(*) c FROM partidas WHERE grupo_id=? AND em_grupo=1", (grupo_id,)).fetchone()["c"]
    print(f"Banco agora: {tot} partidas ({emg} em grupo).")
    conn.close()


if __name__ == "__main__":
    main()

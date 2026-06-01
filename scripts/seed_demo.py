"""Demo do núcleo de dados: puxa as 3 últimas Flex do grupo e grava no banco.

Mostra a regra pedida pelo usuário: uma partida vira UM log só; quando 2+
membros estão juntos, marca `em_grupo` e a análise olha a sinergia (quem
jogou junto, mesmo time, quem venceu).

Uso (na raiz do projeto, com .venv ativo e RIOT_API_KEY no .env):
    python -m scripts.seed_demo
"""
from __future__ import annotations

import sys
from datetime import datetime

# Console do Windows (cp1252) não imprime Unicode; força UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from bot_lol import config
from bot_lol.db import database as db
from bot_lol.ingest import ingest_match
from bot_lol.riot_api import RiotClient

QUEUE_FLEX = 440

PLAYERS = [
    ("Hiroshi", "10102"), ("Qiak", "000"), ("Yuya Freecss", "BR1"),
    ("Thokyru", "BR1"), ("Top Mogger", "Dasky"), ("Nashorn", "Shiro"),
    ("Lukyy", "Luky"), ("Nyachi", "mee"),
]


def main() -> None:
    config.ensure_dirs()
    client = RiotClient()
    conn = db.get_connection()
    db.init_db(conn)

    grupo_id = db.ensure_grupo(conn, "Esquadrão Flex", discord_guild_id="demo")
    print(f"Grupo id={grupo_id}  | banco: {config.DB_PATH}")

    # 1) PUUIDs + cadastro dos jogadores
    print("\n== Resolvendo PUUIDs e cadastrando jogadores ==")
    puuid_to_jogador: dict[str, int] = {}
    puuid_to_nick: dict[str, str] = {}
    for name, tag in PLAYERS:
        puuid = client.get_puuid(name, tag)
        if not puuid:
            print(f"  ✗ {name}#{tag} (não encontrado)")
            continue
        jid = db.ensure_jogador(conn, grupo_id, puuid, nick_display=name,
                                riot_id=f"{name}#{tag}")
        puuid_to_jogador[puuid] = jid
        puuid_to_nick[puuid] = name
        print(f"  ✓ {name}#{tag}")

    # 2) Coleta IDs de Flex (recentes) de cada um e une (dedupe natural)
    print("\n== Coletando IDs de Flex recentes ==")
    ids: set[str] = set()
    for puuid in puuid_to_jogador:
        ids.update(client.get_match_ids(puuid, count=5, queue=QUEUE_FLEX))
    print(f"  {len(ids)} partidas Flex únicas encontradas")

    # 3) Baixa e ordena por data; pega as 3 mais recentes
    baixadas = [(m["info"]["gameStartTimestamp"], m)
                for mid in ids if (m := client.get_match(mid))]
    baixadas.sort(key=lambda x: x[0], reverse=True)
    ultimas3 = [m for _, m in baixadas[:3]]

    # 4) Ingesta cada uma (timeline só destas 3) — UM log por partida
    print("\n== Gravando as 3 últimas Flex no banco ==")
    for m in ultimas3:
        mid = m["metadata"]["matchId"]
        tl = client.get_timeline(mid)
        pid = ingest_match(conn, grupo_id, puuid_to_jogador, m, tl)
        print(f"  {'gravada' if pid else 'já existia'}: {mid}")

    # 5) Lê de volta do banco e mostra a sinergia
    print("\n" + "=" * 64)
    print(" AS 3 ÚLTIMAS FLEX — como ficaram no banco")
    print("=" * 64)
    partidas = conn.execute(
        "SELECT * FROM partidas WHERE grupo_id=? AND queue_id=? "
        "ORDER BY inicio_ts DESC LIMIT 3", (grupo_id, QUEUE_FLEX)).fetchall()

    for p in partidas:
        quando = datetime.fromtimestamp(p["inicio_ts"] / 1000).strftime("%d/%m %H:%M")
        dur = f"{p['duracao_seg'] // 60}min"
        print(f"\n● {p['match_id']}  ({quando}, {dur})")
        print(f"  em_grupo={'SIM' if p['em_grupo'] else 'não'} | "
              f"vencedor=time {p['vencedor_team']} | timeline={'sim' if p['tem_timeline'] else 'não'}")

        membros = conn.execute(
            "SELECT pa.*, j.nick_display FROM participacoes pa "
            "JOIN jogadores j ON j.id = pa.jogador_id "
            "WHERE pa.partida_id=? ORDER BY pa.team_id, pa.dano DESC",
            (p["id"],)).fetchall()

        por_time: dict[int, list] = {}
        for mb in membros:
            por_time.setdefault(mb["team_id"], []).append(mb)

        for team_id, lista in por_time.items():
            venceu = "🏆 venceu" if team_id == p["vencedor_team"] else "perdeu"
            tag = "(JUNTOS)" if len(lista) >= 2 else "(sozinho)"
            print(f"    Time {team_id} {tag} — {venceu}:")
            for mb in lista:
                ld = f", lanediff@10 {mb['lanediff_10']:+d}" if mb["lanediff_10"] is not None else ""
                print(f"      {mb['nick_display']:<14} {mb['campeao']:<12} "
                      f"{mb['role'] or '?':<8} {mb['kills']}/{mb['deaths']}/{mb['assists']} "
                      f"| dano {mb['dano']}{ld}")

    conn.close()
    print("\nPronto. Banco salvo em", config.DB_PATH)


if __name__ == "__main__":
    main()

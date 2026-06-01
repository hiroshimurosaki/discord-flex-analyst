"""Teste leve do gerador de post (sem cache -> seção de momentos é pulada)."""
import json

from bot_lol import post
from bot_lol.db import database as db


def _setup():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    j1 = db.ensure_jogador(conn, g, "P-A", "Hiroshi")
    j2 = db.ensure_jogador(conn, g, "P-B", "Qiak")
    pid = db.insert_partida(conn, g, "BR1_SEMCACHE", 440, 1800, 0, 100, True, False)
    linhas = [
        {"partida_id": pid, "jogador_id": j1, "puuid": "P-A", "team_id": 100,
         "role": "MIDDLE", "campeao": "Naafiri", "win": 1, "kills": 9, "deaths": 4,
         "assists": 9, "dano": 50000, "ouro": 14000, "visao": 20, "farm": 200,
         "lanediff_10": 1233, "challenges_json": json.dumps({"soloKills": 5})},
        {"partida_id": pid, "jogador_id": j2, "puuid": "P-B", "team_id": 100,
         "role": "BOTTOM", "campeao": "Caitlyn", "win": 1, "kills": 14, "deaths": 5,
         "assists": 8, "dano": 52000, "ouro": 15000, "visao": 30, "farm": 250,
         "lanediff_10": -355, "challenges_json": json.dumps({})},
        # oponente direto do mid (não-membro)
        {"partida_id": pid, "jogador_id": None, "puuid": "E-1", "team_id": 200,
         "role": "MIDDLE", "campeao": "Lissandra", "win": 0, "kills": 2, "deaths": 9,
         "assists": 3, "dano": 20000, "ouro": 8000, "visao": 10, "farm": 157,
         "challenges_json": json.dumps({})},
    ]
    db.insert_participacoes(conn, linhas)
    return conn, pid


def test_post_tem_blocos_essenciais():
    conn, pid = _setup()
    txt = post.montar_post(conn, pid)
    assert "Vitória" in txt
    assert "Escalação" in txt
    assert "Duelo de rota" in txt
    # maior dano deve ser o Qiak (52k)
    assert "Maior dano: **Qiak**" in txt
    # duelo de rota do mid achou o oponente Lissandra
    assert "vs Lissandra" in txt
    # conquista de challenge (soloKills do Hiroshi)
    assert "abates solo" in txt

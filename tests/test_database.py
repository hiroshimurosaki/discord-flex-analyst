"""Testes leves da camada de dados (o que dói se quebrar silenciosamente).

Cobre: schema aplica, entidades fazem upsert, fatos inserem, e o dedupe
de partida (regra crítica — a mesma partida aparece para vários membros).
"""
import sqlite3

from bot_lol.db import database as db


def make_conn() -> sqlite3.Connection:
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    return conn


def test_schema_cria_tabelas():
    conn = make_conn()
    nomes = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"grupos", "jogadores", "partidas", "participacoes"} <= nomes


def test_ensure_grupo_idempotente():
    conn = make_conn()
    g1 = db.ensure_grupo(conn, "Esquadrão Flex", discord_guild_id="123")
    g2 = db.ensure_grupo(conn, "Esquadrão Flex", discord_guild_id="123")
    assert g1 == g2  # mesmo guild -> mesmo grupo


def test_ensure_jogador_atualiza_nick():
    conn = make_conn()
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    j1 = db.ensure_jogador(conn, g, puuid="PUUID-A", nick_display="Hiro")
    j2 = db.ensure_jogador(conn, g, puuid="PUUID-A", nick_display="Hiroshi")
    assert j1 == j2
    row = conn.execute("SELECT nick_display FROM jogadores WHERE id=?", (j1,)).fetchone()
    assert row["nick_display"] == "Hiroshi"


def test_dedupe_partida():
    conn = make_conn()
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    assert not db.partida_existe(conn, g, "BR1_1")
    db.insert_partida(conn, g, "BR1_1", queue_id=440, duracao_seg=1800,
                      inicio_ts=0, vencedor_team=100, em_grupo=True, tem_timeline=True)
    assert db.partida_existe(conn, g, "BR1_1")


def test_insert_participacoes_aceita_nao_membro():
    conn = make_conn()
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    j = db.ensure_jogador(conn, g, puuid="PUUID-A", nick_display="Hiro")
    pid = db.insert_partida(conn, g, "BR1_1", 440, 1800, 0, 100, True, False)
    n = db.insert_participacoes(conn, [
        {"partida_id": pid, "jogador_id": j, "puuid": "PUUID-A", "team_id": 100,
         "campeao": "Zac", "win": 1, "dano": 30000},
        # não-membro: jogador_id NULL
        {"partida_id": pid, "jogador_id": None, "puuid": "RANDOM-X", "team_id": 200,
         "campeao": "Teemo", "win": 0, "dano": 12000},
    ])
    assert n == 2
    total = conn.execute("SELECT COUNT(*) c FROM participacoes").fetchone()["c"]
    assert total == 2

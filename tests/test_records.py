"""Testes do motor de recordes (agregação pura)."""
import json

from bot_lol import records
from bot_lol.db import database as db


def _part(conn, g, jH, jQ, match_id, win_team, dano_h, dano_q, dur=1800):
    pid = db.insert_partida(conn, g, match_id, 440, dur, 0, win_team, True, False)
    db.insert_participacoes(conn, [
        {"partida_id": pid, "jogador_id": jH, "puuid": "P-H", "team_id": 100,
         "role": "MIDDLE", "campeao": "Naafiri", "win": int(win_team == 100),
         "kills": 9, "deaths": 4, "assists": 9, "dano": dano_h, "ouro": 14000,
         "visao": 20, "farm": 200, "kp": 0.5, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": jQ, "puuid": "P-Q", "team_id": 100,
         "role": "BOTTOM", "campeao": "Caitlyn", "win": int(win_team == 100),
         "kills": 12, "deaths": 5, "assists": 8, "dano": dano_q, "ouro": 15000,
         "visao": 25, "farm": 230, "kp": 0.6, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": None, "puuid": "E1", "team_id": 200,
         "role": "MIDDLE", "campeao": "Zed", "win": int(win_team == 200),
         "kills": 3, "deaths": 8, "assists": 4, "dano": 18000, "ouro": 9000,
         "visao": 8, "farm": 150, "kp": 0.3, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": None, "puuid": "E2", "team_id": 200,
         "role": "BOTTOM", "campeao": "Ezreal", "win": int(win_team == 200),
         "kills": 4, "deaths": 6, "assists": 5, "dano": 16000, "ouro": 9500,
         "visao": 12, "farm": 180, "kp": 0.35, "challenges_json": json.dumps({})},
    ])
    return pid


def _setup():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    jH = db.ensure_jogador(conn, g, "P-H", "Hiroshi")
    jQ = db.ensure_jogador(conn, g, "P-Q", "Qiak")
    p1 = _part(conn, g, jH, jQ, "BR1_1", 100, dano_h=30000, dano_q=40000)
    p2 = _part(conn, g, jH, jQ, "BR1_2", 200, dano_h=55000, dano_q=20000)  # derrota; Hiroshi recorde dano
    p3 = _part(conn, g, jH, jQ, "BR1_3", 100, dano_h=28000, dano_q=33000)
    return conn, g, jH, jQ, p1, p2, p3


def test_recorde_maior_dano():
    conn, g, jH, jQ, p1, p2, p3 = _setup()
    rec = records.recordes_grupo(conn, g, records.FLEX)
    assert rec["maior_dano"]["valor"] == 55000
    assert rec["maior_dano"]["nick"] == "Hiroshi"
    assert rec["maior_dano"]["partida_id"] == p2


def test_recordes_batidos_aponta_partida_certa():
    conn, g, jH, jQ, p1, p2, p3 = _setup()
    batidos = records.recordes_batidos(conn, g, p2, records.FLEX)
    # p2 detém o recorde de maior dano (Hiroshi 55k)
    assert any("Maior dano" in b for b in batidos)


def test_perfil_basico():
    conn, g, jH, jQ, p1, p2, p3 = _setup()
    pf = records.perfil(conn, g, jH, records.FLEX)
    assert pf["jogos"] == 3
    assert round(pf["wr"]) == 67  # ganhou 2 de 3
    assert pf["rec_dano"] == 55000
    assert pf["melhor_duo"]["nick"] == "Qiak"


def test_recorte_solo_isola_dos_jogos_em_grupo():
    """Recorte Solo/Duo (em_grupo=None) enxerga o jogo solo; Flex (em_grupo=1) não."""
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    jH = db.ensure_jogador(conn, g, "P-H", "Hiroshi")
    # jogo SOLO: queue 420, em_grupo=0, só o Hiroshi do grupo na partida
    pid = db.insert_partida(conn, g, "BR1_SOLO", 420, 1700, 10, 100, False, False)
    db.insert_participacoes(conn, [
        {"partida_id": pid, "jogador_id": jH, "puuid": "P-H", "team_id": 100,
         "role": "MIDDLE", "campeao": "Ahri", "win": 1, "kills": 10, "deaths": 2,
         "assists": 5, "dano": 40000, "ouro": 13000, "visao": 18, "farm": 210,
         "kp": 0.5, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": None, "puuid": "E1", "team_id": 200,
         "role": "MIDDLE", "campeao": "Zed", "win": 0, "kills": 2, "deaths": 7,
         "assists": 3, "dano": 18000, "ouro": 8000, "visao": 9, "farm": 150,
         "kp": 0.3, "challenges_json": json.dumps({})},
    ])
    # Flex (time fechado) ignora o jogo solo.
    assert records.perfil(conn, g, jH, records.FLEX, em_grupo=1) == {}
    # Solo/Duo enxerga.
    pf = records.perfil(conn, g, jH, records.SOLO, em_grupo=None)
    assert pf["jogos"] == 1 and pf["wr"] == 100.0
    assert pf["melhor_duo"] is None  # jogo solo não tem colega de grupo
    rec = records.recordes_grupo(conn, g, records.SOLO, em_grupo=None)
    assert rec["maior_dano"]["valor"] == 40000 and rec["maior_dano"]["nick"] == "Hiroshi"

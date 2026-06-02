"""Testes do detector de tendências (cálculo puro sobre o banco)."""
import json

from bot_lol import records, tendencias
from bot_lol.db import database as db


def _add(conn, g, jid, idx, win, champ, opp_champ, ts, queue=420, team=100):
    """Insere uma partida ranqueada: o membro (MID) + o oponente direto (MID)."""
    vencedor = team if win else (200 if team == 100 else 100)
    pid = db.insert_partida(conn, g, f"BR1_{idx}", queue, 1800, ts, vencedor, False, False)
    db.insert_participacoes(conn, [
        {"partida_id": pid, "jogador_id": jid, "puuid": "P-A", "team_id": team,
         "role": "MIDDLE", "campeao": champ, "win": int(win), "kills": 8, "deaths": 3,
         "assists": 6, "dano": 30000, "ouro": 13000, "visao": 18, "farm": 200,
         "kp": 0.5, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": None, "puuid": f"E{idx}",
         "team_id": 200 if team == 100 else 100, "role": "MIDDLE", "campeao": opp_champ,
         "win": int(not win), "kills": 3, "deaths": 8, "assists": 4, "dano": 16000,
         "ouro": 8000, "visao": 9, "farm": 150, "kp": 0.3, "challenges_json": json.dumps({})},
    ])
    return pid


def _setup():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    jid = db.ensure_jogador(conn, g, "P-A", "Hiroshi")
    # 30 jogos de Ahri: 15 antigos ruins (4V), 15 recentes bons (11V) -> subindo.
    idx = 0
    for i in range(15):  # antigos: 4 derrotas vs Zed + 4V/7D vs Garen = 4V total
        if i < 4:
            win, opp = False, "Zed"      # os 4 vs Zed são derrotas
        else:
            win, opp = i < 8, "Garen"    # i=4..7 vitórias; i>=8 derrotas
        _add(conn, g, jid, idx, win, "Ahri", opp, ts=1000 + idx); idx += 1
    for i in range(15):  # recentes
        win = i < 11
        _add(conn, g, jid, idx, win, "Ahri", "Lux", ts=1000 + idx); idx += 1
    return conn, g, jid


def test_forma_detecta_subida():
    conn, g, jid = _setup()
    pv = tendencias.perfil_vivo(conn, g, jid, records.RANKED)
    assert pv["jogos"] == 30
    f = pv["forma"]
    assert f["direcao"] == "subindo"
    assert f["recente"]["wr"] > f["antiga"]["wr"]


def test_campeao_em_ascensao():
    conn, g, jid = _setup()
    pv = tendencias.perfil_vivo(conn, g, jid, records.RANKED)
    ahri = next((m for m in pv["campeoes"] if m["campeao"] == "Ahri"), None)
    assert ahri is not None and ahri["direcao"] == "↑"


def test_matchup_pior_aparece():
    conn, g, jid = _setup()
    pv = tendencias.perfil_vivo(conn, g, jid, records.RANKED)
    zed = next((m for m in pv["matchups"]["piores"] if m["vs"] == "Zed"), None)
    assert zed is not None
    assert zed["jogos"] == 4 and zed["wr"] == 0.0  # 4 derrotas vs Zed


def test_resumo_curto_nao_vazio():
    conn, g, jid = _setup()
    resumo = tendencias.resumo_curto(tendencias.perfil_vivo(conn, g, jid, records.RANKED))
    assert "forma subindo" in resumo
    assert "Zed" in resumo  # sofre contra Zed (0%)


def test_sem_jogos_retorna_vazio():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    jid = db.ensure_jogador(conn, g, "P-X", "Ninguem")
    assert tendencias.perfil_vivo(conn, g, jid) == {}
    assert tendencias.formatar({}) == ""
    assert tendencias.resumo_curto({}) == ""

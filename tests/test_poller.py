"""Testes do poller (orquestração de ingestão) — com um RiotClient fake."""
from bot_lol import poller
from bot_lol.db import database as db


def _match(match_id, queue, puuid_membro, ts):
    """Partida mínima: 1 membro (time 100) + 1 não-membro (time 200)."""
    return {
        "metadata": {"matchId": match_id},
        "info": {
            "queueId": queue, "gameDuration": 1500, "gameStartTimestamp": ts,
            "participants": [
                {"participantId": 1, "puuid": puuid_membro, "teamId": 100, "win": True,
                 "championName": "Ahri", "teamPosition": "MIDDLE",
                 "kills": 8, "deaths": 2, "assists": 6,
                 "totalDamageDealtToChampions": 25000, "totalDamageTaken": 18000,
                 "goldEarned": 12000, "visionScore": 20,
                 "totalMinionsKilled": 200, "neutralMinionsKilled": 0},
                {"participantId": 6, "puuid": "ENEMY", "teamId": 200, "win": False,
                 "championName": "Zed", "teamPosition": "MIDDLE",
                 "kills": 2, "deaths": 8, "assists": 3,
                 "totalDamageDealtToChampions": 15000, "totalDamageTaken": 22000,
                 "goldEarned": 8000, "visionScore": 9,
                 "totalMinionsKilled": 160, "neutralMinionsKilled": 0},
            ],
        },
    }


class FakeClient:
    """Devolve IDs/matches canned; conta chamadas de timeline."""
    def __init__(self, ids_por_puuid, matches):
        self.ids_por_puuid = ids_por_puuid
        self.matches = matches
        self.timelines_pedidas = []

    def get_match_ids(self, puuid, count=5, queue=None, start=0):
        return self.ids_por_puuid.get(puuid, [])[:count]

    def get_match(self, match_id):
        return self.matches.get(match_id)

    def get_timeline(self, match_id):
        self.timelines_pedidas.append(match_id)
        return {"info": {"frames": []}}


def _setup():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    db.ensure_jogador(conn, g, "P-A", "Hiroshi")
    return conn, g


def test_poll_ingere_partidas_novas():
    conn, g = _setup()
    matches = {
        "BR1_1": _match("BR1_1", 420, "P-A", ts=100),   # solo/duo
        "BR1_2": _match("BR1_2", 440, "P-A", ts=200),   # flex
        "BR1_ARAM": _match("BR1_ARAM", 450, "P-A", ts=300),  # ARAM -> deve ser ignorada
    }
    client = FakeClient({"P-A": ["BR1_2", "BR1_ARAM", "BR1_1"]}, matches)
    novos = poller.poll_grupo(conn, client, g)
    # 2 ingeridas (420 e 440); ARAM fora da allowlist
    assert len(novos) == 2
    queues = {conn.execute("SELECT queue_id FROM partidas WHERE id=?", (pid,)).fetchone()["queue_id"]
              for pid in novos}
    assert queues == {420, 440}
    # ordem de post = ordem de início (ts 100 antes de 200)
    primeiro = conn.execute("SELECT match_id FROM partidas WHERE id=?", (novos[0],)).fetchone()["match_id"]
    assert primeiro == "BR1_1"
    # jogo solo (1 membro) não baixa timeline
    assert client.timelines_pedidas == []


def test_poll_deduplica_e_nao_reinsere():
    conn, g = _setup()
    matches = {"BR1_1": _match("BR1_1", 420, "P-A", ts=100)}
    client = FakeClient({"P-A": ["BR1_1"]}, matches)
    assert len(poller.poll_grupo(conn, client, g)) == 1
    # segunda rodada: nada novo (já está no banco)
    assert poller.poll_grupo(conn, client, g) == []

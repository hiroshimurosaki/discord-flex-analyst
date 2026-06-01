"""Testes do parsing de partida (lógica pura — sem rede)."""
from bot_lol import ingest


def _match():
    """2 membros (time 100) + 1 não-membro (time 200), partida mínima."""
    return {
        "metadata": {"matchId": "BR1_X"},
        "info": {
            "queueId": 440, "gameDuration": 1800, "gameStartTimestamp": 123,
            "participants": [
                {"participantId": 1, "puuid": "P-A", "teamId": 100, "win": True,
                 "championName": "Zac", "teamPosition": "JUNGLE",
                 "kills": 5, "deaths": 2, "assists": 10,
                 "totalDamageDealtToChampions": 20000, "totalDamageTaken": 30000,
                 "goldEarned": 12000, "visionScore": 25,
                 "totalMinionsKilled": 50, "neutralMinionsKilled": 80},
                {"participantId": 2, "puuid": "P-B", "teamId": 100, "win": True,
                 "championName": "Jinx", "teamPosition": "BOTTOM",
                 "kills": 8, "deaths": 1, "assists": 4,
                 "totalDamageDealtToChampions": 35000, "totalDamageTaken": 12000,
                 "goldEarned": 15000, "visionScore": 15,
                 "totalMinionsKilled": 200, "neutralMinionsKilled": 0},
                {"participantId": 6, "puuid": "P-ENEMY", "teamId": 200, "win": False,
                 "championName": "Teemo", "teamPosition": "TOP",
                 "kills": 1, "deaths": 6, "assists": 2,
                 "totalDamageDealtToChampions": 9000, "totalDamageTaken": 25000,
                 "goldEarned": 7000, "visionScore": 10,
                 "totalMinionsKilled": 100, "neutralMinionsKilled": 0},
            ],
        },
    }


def test_parse_participacoes_basico():
    linhas = ingest.parse_participacoes(_match(), {"P-A": 1, "P-B": 2})
    assert len(linhas) == 3
    a = next(l for l in linhas if l["puuid"] == "P-A")
    assert a["jogador_id"] == 1 and a["campeao"] == "Zac"
    assert a["farm"] == 130  # 50 + 80
    inimigo = next(l for l in linhas if l["puuid"] == "P-ENEMY")
    assert inimigo["jogador_id"] is None  # não-membro


def test_kp_calculado():
    linhas = ingest.parse_participacoes(_match(), {"P-A": 1})
    a = next(l for l in linhas if l["puuid"] == "P-A")
    # time 100 fez 13 kills; A participou de 5+10=15 -> capado pela soma do time
    assert a["kp"] == round(15 / 13, 3)


def test_role_invalid_vira_none():
    m = _match()
    m["info"]["participants"][0]["teamPosition"] = "Invalid"
    linhas = ingest.parse_participacoes(m, {"P-A": 1})
    assert next(l for l in linhas if l["puuid"] == "P-A")["role"] is None


def test_detectar_em_grupo():
    # 2 membros no MESMO time -> em_grupo
    linhas = ingest.parse_participacoes(_match(), {"P-A": 1, "P-B": 2})
    assert ingest.detectar_em_grupo(linhas) is True
    # só 1 membro -> não é grupo
    linhas2 = ingest.parse_participacoes(_match(), {"P-A": 1})
    assert ingest.detectar_em_grupo(linhas2) is False

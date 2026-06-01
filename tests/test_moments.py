"""Testes da detecção de momentos-chave (lógica pura — sem rede)."""
from bot_lol import moments


def _match():
    parts = []
    for pid in range(1, 11):
        parts.append({"participantId": pid, "puuid": f"P{pid}",
                      "teamId": 100 if pid <= 5 else 200,
                      "championName": f"Champ{pid}"})
    return {"info": {"participants": parts}}


def _frame(minute, g100, g200, events=None):
    pf = {}
    for pid in range(1, 11):
        gold = (g100 if pid <= 5 else g200) // 5
        pf[str(pid)] = {"participantId": pid, "totalGold": gold,
                        "position": {"x": 1000 * pid, "y": 1000 * pid}}
    return {"participantFrames": pf, "events": events or []}


def _timeline():
    # diff: 0 -> +500 -> +500 -> +4500 (grande swing entre min 2 e 3)
    frames = [
        _frame(0, 2500, 2500),
        _frame(1, 5000, 4500),
        _frame(2, 7500, 7000, events=[
            {"type": "ELITE_MONSTER_KILL", "timestamp": 120000,
             "monsterType": "DRAGON", "monsterSubType": "FIRE_DRAGON",
             "killerTeamId": 100},
        ]),
        _frame(3, 14000, 9500, events=[
            # teamfight: 3 mortes no time 200 perto de 180s
            {"type": "CHAMPION_KILL", "timestamp": 175000, "killerId": 1,
             "victimId": 6, "position": {"x": 7000, "y": 7000},
             "victimDamageReceived": [{"participantId": 1}, {"participantId": 2}]},
            {"type": "CHAMPION_KILL", "timestamp": 180000, "killerId": 2,
             "victimId": 7, "position": {"x": 7100, "y": 7000},
             "victimDamageReceived": [{"participantId": 2}]},
            {"type": "CHAMPION_KILL", "timestamp": 185000, "killerId": 3,
             "victimId": 8, "position": {"x": 7200, "y": 7000},
             "victimDamageReceived": [{"participantId": 3}, {"participantId": 1}]},
        ]),
    ]
    return {"info": {"frames": frames}}


def test_gold_series_e_swing():
    m, tl = _match(), _timeline()
    series = moments.team_gold_series(m, tl)
    assert series[0]["diff"] == 0
    assert series[3]["diff"] == 4500
    swing = moments.gold_swings(series, top=1)[0]
    assert swing["de_min"] == 2 and swing["ate_min"] == 3
    assert swing["delta"] == 4000  # de +500 para +4500


def test_parse_kills_e_teamfight():
    m, tl = _match(), _timeline()
    kills = moments.parse_kills(m, tl)
    assert len(kills) == 3
    fights = moments.teamfights(kills, gap_s=18)
    assert len(fights) == 1
    f = fights[0]
    assert f["n_kills"] == 3
    assert f["mortes_por_time"] == {200: 3}
    assert f["saldo_100"] == 3  # time 100 venceu a briga


def test_objetivos():
    objs = moments.objectives(_match(), _timeline())
    drag = [o for o in objs if o["tipo"].startswith("Dragão")]
    assert drag and drag[0]["time"] == 100


def test_pickoff_isolado_vs_teamfight():
    """Mortes em teamfight (juntas no tempo) NÃO viram pick-off."""
    m, tl = _match(), _timeline()
    kills = moments.parse_kills(m, tl)
    # todas as 3 mortes estão agrupadas -> nenhuma é isolada -> 0 pick-offs
    picks = moments.detect_pickoffs(m, tl, kills, min_t=0)
    assert picks == []

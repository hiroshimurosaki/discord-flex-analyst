"""Ingestão é onde nascem os erros silenciosos: role suja, time errado,
não-membro tratado como membro. Um erro aqui vira 'fato' e contamina a história
inteira sem levantar exceção."""
from cronica.fatos import ingest


def part(puuid, time, role, champ, win, **kw):
    d = {"puuid": puuid, "teamId": time, "teamPosition": role,
         "championName": champ, "win": win, "kills": 5, "deaths": 3,
         "assists": 7, "totalDamageDealtToChampions": 20000,
         "totalDamageTaken": 25000, "goldEarned": 12000, "visionScore": 30,
         "totalMinionsKilled": 150, "neutralMinionsKilled": 10, "challenges": {}}
    d.update(kw)
    return d


def match(participantes, queue=440, versao="15.14.678.1234"):
    return {"metadata": {"matchId": "BR1_1"},
            "info": {"queueId": queue, "gameStartTimestamp": 1700000000000,
                     "gameDuration": 1800, "gameVersion": versao,
                     "participants": participantes,
                     "teams": [{"teamId": 100, "win": True},
                               {"teamId": 200, "win": False}]}}


ROLES = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]


def dez(membros_no_time_100=2):
    ps = []
    for i, r in enumerate(ROLES):
        puuid = f"MEMBRO{i}" if i < membros_no_time_100 else f"OUTRO{i}"
        ps.append(part(puuid, 100, r, "Ahri", True))
    for i, r in enumerate(ROLES):
        ps.append(part(f"INIM{i}", 200, r, "Zed", False))
    return ps


def test_role_invalida_vira_none():
    assert ingest._role("Invalid") is None
    assert ingest._role("") is None
    assert ingest._role(None) is None
    assert ingest._role("bottom") == "BOTTOM"


def test_patch_reduz_para_major_minor():
    assert ingest._patch("15.14.678.1234") == "15.14"
    assert ingest._patch(None) is None


def test_guarda_os_dez_participantes():
    r = ingest.parse_partida(match(dez()), {"MEMBRO0": "a", "MEMBRO1": "b"})
    assert len(r["participacoes"]) == 10
    membros = [p for p in r["participacoes"] if p["membro_id"]]
    assert len(membros) == 2
    assert all(p["membro_id"] is None for p in r["participacoes"]
               if p["puuid"].startswith("INIM"))


def test_em_grupo_exige_mesmo_time():
    """Dois amigos em times OPOSTOS não são 'o time jogando junto'."""
    ps = dez(membros_no_time_100=1)
    ps[5] = part("MEMBRO_X", 200, "TOP", "Zed", False)
    r = ingest.parse_partida(match(ps), {"MEMBRO0": "a", "MEMBRO_X": "b"})
    assert r["partida"]["n_membros"] == 1
    assert r["partida"]["em_grupo"] == 0


def test_kill_participation_usa_kills_do_proprio_time():
    ps = dez()
    r = ingest.parse_partida(match(ps), {"MEMBRO0": "a"})
    p = next(x for x in r["participacoes"] if x["puuid"] == "MEMBRO0")
    assert p["kp"] == round((5 + 7) / 25, 4)   # 5 jogadores x 5 kills


def test_lanediff_compara_com_o_oponente_direto():
    ps = dez()
    tl = {"info": {"frames": [
        {"participantFrames": {str(i + 1): {"totalGold": 500}
                               for i in range(10)}}
        for _ in range(11)]}}
    # aos 10 min: MEMBRO0 (TOP, índice 1) com 4000, o TOP inimigo (índice 6) 3000
    tl["info"]["frames"][10]["participantFrames"]["1"] = {"totalGold": 4000}
    tl["info"]["frames"][10]["participantFrames"]["6"] = {"totalGold": 3000}
    m = match(ps)
    r = ingest.parse_partida(m, {"MEMBRO0": "a"})
    ingest.enriquecer_com_timeline(r["participacoes"], m, tl)
    p = next(x for x in r["participacoes"] if x["puuid"] == "MEMBRO0")
    assert p["ouro_10"] == 4000
    assert p["lanediff_10"] == 1000


def test_timeline_curta_nao_estoura():
    m = match(dez())
    r = ingest.parse_partida(m, {"MEMBRO0": "a"})
    ingest.enriquecer_com_timeline(r["participacoes"], m,
                                   {"info": {"frames": []}})
    assert all(p["ouro_10"] is None for p in r["participacoes"])


def test_deficit_max_e_positivo_e_acha_o_pior_minuto():
    m = match(dez())
    frames = []
    for ouro_nosso in [1000, 800, 600, 900, 1400]:
        pf = {str(i + 1): {"totalGold": ouro_nosso} for i in range(5)}
        pf.update({str(i + 1): {"totalGold": 1000} for i in range(5, 10)})
        frames.append({"participantFrames": pf, "events": []})
    d = ingest.derivar_timeline(m, {"info": {"frames": frames}}, 100)
    assert d["deficit_max"] == 2000     # (1000-600)*5 no minuto 2
    assert d["minuto_deficit"] == 2
    assert d["pico_max"] == 2000

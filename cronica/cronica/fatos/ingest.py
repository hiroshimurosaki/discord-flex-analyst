"""JSON da Riot -> linhas do banco. Lógica PURA: nenhuma rede, nenhum I/O.

É pura de propósito. Ingestão é onde nascem os erros silenciosos (role suja,
time errado, participação de não-membro tratada como membro) e um erro aqui
contamina a história inteira lá na frente, disfarçado de fato. Função pura é
função que dá pra testar sem chave de API e sem rede — e `tests/` faz isso.
"""
from __future__ import annotations

import json
from typing import Optional

ROLES_VALIDAS = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}


def _role(bruta: Optional[str]) -> Optional[str]:
    """A Riot devolve '' e 'Invalid' com frequência (remakes, modos especiais).
    Fingir que isso é uma role produziria matchups inventados."""
    r = (bruta or "").strip().upper()
    return r if r in ROLES_VALIDAS else None


def _patch(game_version: Optional[str]) -> Optional[str]:
    """'15.14.678.1234' -> '15.14'. Fronteira de era barata e semanticamente
    rica: patch muda o jogo, e o grupo sente sem saber nomear."""
    if not game_version:
        return None
    partes = str(game_version).split(".")
    return ".".join(partes[:2]) if len(partes) >= 2 else None


def parse_partida(match: dict, puuid_para_membro: dict[str, str]) -> dict:
    """Devolve {'partida': {...}, 'participacoes': [...]} pronto pro banco.

    `puuid_para_membro` mapeia PUUID -> id do cânone. Quem não está no mapa é
    não-membro e entra com `membro_id=None` — mas ENTRA, porque sem os 10 não
    existe percentil nem matchup.
    """
    info = match["info"]
    parts = info["participants"]

    # Kills por time: denominador do kill participation.
    kills_time: dict[int, int] = {}
    for p in parts:
        kills_time[p["teamId"]] = kills_time.get(p["teamId"], 0) + int(p.get("kills", 0))

    # Membros por time -> em_grupo. Conta no MESMO time: dois amigos em times
    # opostos não são "o time jogando junto", são um inhouse.
    membros_por_time: dict[int, int] = {}
    for p in parts:
        if p["puuid"] in puuid_para_membro:
            membros_por_time[p["teamId"]] = membros_por_time.get(p["teamId"], 0) + 1
    n_membros = max(membros_por_time.values()) if membros_por_time else 0
    nosso_time = (max(membros_por_time, key=lambda t: membros_por_time[t])
                  if membros_por_time else None)

    vencedor = None
    for t in info.get("teams", []):
        if t.get("win"):
            vencedor = t.get("teamId")

    partida = {
        "match_id": match["metadata"]["matchId"],
        "fila": int(info.get("queueId", 0)),
        "inicio_ts": int(info.get("gameStartTimestamp") or info.get("gameCreation") or 0),
        "duracao_seg": int(info.get("gameDuration", 0)),
        "vencedor_team": vencedor,
        "patch": _patch(info.get("gameVersion")),
        "n_membros": n_membros,
        "em_grupo": 1 if n_membros >= 2 else 0,
        "nosso_time": nosso_time,   # não vai pro banco; usado pela timeline
    }

    participacoes = []
    for p in parts:
        tk = kills_time.get(p["teamId"], 0)
        kp = round((int(p.get("kills", 0)) + int(p.get("assists", 0))) / tk, 4) if tk else None
        participacoes.append({
            "puuid": p["puuid"],
            "membro_id": puuid_para_membro.get(p["puuid"]),
            "team_id": p["teamId"],
            "role": _role(p.get("teamPosition")),
            "campeao": p.get("championName"),
            "win": 1 if p.get("win") else 0,
            "kills": p.get("kills"), "deaths": p.get("deaths"),
            "assists": p.get("assists"),
            "dano": p.get("totalDamageDealtToChampions"),
            "dano_recebido": p.get("totalDamageTaken"),
            "ouro": p.get("goldEarned"),
            "visao": p.get("visionScore"),
            "farm": int(p.get("totalMinionsKilled", 0)) + int(p.get("neutralMinionsKilled", 0)),
            "kp": kp,
            "ouro_10": None, "ouro_15": None, "lanediff_10": None,
            # ~125 métricas já calculadas pela Riot. Baratas de guardar e
            # destravam seletor novo depois sem recoletar nada.
            "challenges_json": json.dumps(p.get("challenges") or {}, ensure_ascii=False),
        })
    return {"partida": partida, "participacoes": participacoes}


# --------------------------------------------------------------- timeline

def _ouro_por_frame(timeline: dict) -> list[dict[str, int]]:
    """[{participantId: totalGold}] por frame (≈1 por minuto)."""
    frames = timeline.get("info", {}).get("frames", [])
    out = []
    for f in frames:
        pf = f.get("participantFrames") or {}
        out.append({int(k): int(v.get("totalGold", 0)) for k, v in pf.items()})
    return out


def enriquecer_com_timeline(participacoes: list[dict], match: dict,
                            timeline: dict) -> None:
    """Preenche ouro_10 / ouro_15 / lanediff_10 IN PLACE.

    `lanediff_10` é ouro aos 10 menos o do oponente DIRETO (mesma role, time
    contrário). É a métrica de rota mais honesta disponível: compara você com a
    única pessoa que jogou exatamente o mesmo jogo que você.
    """
    frames = _ouro_por_frame(timeline)
    if len(frames) < 2:
        return
    ordem = [p["puuid"] for p in match["info"]["participants"]]  # participantId = índice+1
    por_puuid = {p["puuid"]: p for p in participacoes}

    def ouro_em(minuto: int) -> dict[str, int]:
        if minuto >= len(frames):
            return {}
        f = frames[minuto]
        return {ordem[pid - 1]: g for pid, g in f.items() if 1 <= pid <= len(ordem)}

    o10, o15 = ouro_em(10), ouro_em(15)
    for puuid, g in o10.items():
        if puuid in por_puuid:
            por_puuid[puuid]["ouro_10"] = g
    for puuid, g in o15.items():
        if puuid in por_puuid:
            por_puuid[puuid]["ouro_15"] = g

    if o10:
        por_role: dict[tuple[int, str], str] = {}
        for p in participacoes:
            if p["role"]:
                por_role[(p["team_id"], p["role"])] = p["puuid"]
        for p in participacoes:
            if not p["role"] or p["puuid"] not in o10:
                continue
            outro_time = 200 if p["team_id"] == 100 else 100
            adv = por_role.get((outro_time, p["role"]))
            if adv and adv in o10:
                p["lanediff_10"] = o10[p["puuid"]] - o10[adv]


def derivar_timeline(match: dict, timeline: dict, nosso_time: Optional[int]) -> dict:
    """Condensa a timeline no que a história usa: a curva de ouro do NOSSO time
    contra o outro, e o pior momento dela.

    `deficit_max` é o que faz o seletor `virada` existir. Sem ele, "a partida em
    que vocês estavam mortos e ganharam" não é encontrável — e essa é
    exatamente a cena que qualquer história quer.
    """
    frames = _ouro_por_frame(timeline)
    ordem = [p["puuid"] for p in match["info"]["participants"]]
    time_de = {p["puuid"]: p["teamId"] for p in match["info"]["participants"]}
    if nosso_time is None:
        nosso_time = 100

    serie: list[int] = []   # ouro nosso - ouro deles, por minuto
    for f in frames:
        nos = eles = 0
        for pid, g in f.items():
            if not (1 <= pid <= len(ordem)):
                continue
            if time_de.get(ordem[pid - 1]) == nosso_time:
                nos += g
            else:
                eles += g
        serie.append(nos - eles)

    if not serie:
        return {"formato": 1, "serie_ouro": [], "deficit_max": None,
                "pico_max": None, "minuto_deficit": None, "objetivos": []}

    pior = min(serie)
    objetivos = []
    for f in timeline.get("info", {}).get("frames", []):
        for ev in f.get("events", []):
            if ev.get("type") in ("ELITE_MONSTER_KILL", "BUILDING_KILL"):
                objetivos.append({
                    "minuto": int(ev.get("timestamp", 0) // 60000),
                    "tipo": ev.get("monsterType") or ev.get("buildingType"),
                    "sub": ev.get("monsterSubType") or ev.get("towerType"),
                    "nosso": ev.get("killerTeamId") == nosso_time
                    if ev.get("killerTeamId") is not None else None,
                })
    return {
        "formato": 1,
        "serie_ouro": serie,
        "deficit_max": -pior if pior < 0 else 0,
        "pico_max": max(serie) if max(serie) > 0 else 0,
        "minuto_deficit": serie.index(pior),
        "objetivos": objetivos,
    }

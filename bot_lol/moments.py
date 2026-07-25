"""Detecção de momentos-chave a partir da timeline (peça reutilizável).

Serve tanto ao post normal ("a briga que decidiu o jogo") quanto à fase 2
(quizzes). Tudo é DETERMINÍSTICO — a LLM depois só narra o que isto acha.

Sinais, do mais sólido ao "melhor palpite" (ver bot-lol.md, seção 12):
  - Objetivos (dragão/barão/arauto/torre): eventos explícitos. Confiável.
  - Swing de ouro: maior virada na diferença de ouro entre times. Robusto.
  - Teamfights: abates agrupados no tempo. Confiável.
  - Multikills: vários abates de um jogador numa janela curta. Confiável.
  - Pick-off: morte isolada longe do time. Heurística — "melhor palpite".
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

# Mapa Summoner's Rift ~ 0..14820 nos dois eixos.
_MAP_MAX = 14820


def pid_map(match: dict) -> dict[int, dict]:
    """participantId -> {nome, team, puuid}."""
    out = {}
    for p in match.get("info", {}).get("participants", []):
        out[p.get("participantId")] = {
            "nome": p.get("championName"),
            "team": p.get("teamId"),
            "puuid": p.get("puuid"),
        }
    return out


def _frames(timeline: dict) -> list[dict]:
    return timeline.get("info", {}).get("frames", [])


def _iter_events(timeline: dict):
    for fr in _frames(timeline):
        for e in fr.get("events", []):
            yield e


def region(x: int, y: int) -> str:
    """Rótulo grosseiro da zona do mapa (para narrativa)."""
    # diagonal: acima = TOP/lado azul-superior; abaixo = BOT
    if abs(x - y) < 2200:
        return "meio/rio"
    if x + y < _MAP_MAX:  # canto inferior-esquerdo
        return "BOT (lado azul)" if x > y else "TOP (lado azul)"
    return "TOP (lado vermelho)" if x < y else "BOT (lado vermelho)"


# ----------------------------------------------------------------------
# Ouro por time ao longo do tempo  -> swing de ouro
# ----------------------------------------------------------------------
def team_gold_series(match: dict, timeline: dict) -> list[dict]:
    pm = pid_map(match)
    series = []
    for i, fr in enumerate(_frames(timeline)):
        g = {100: 0, 200: 0}
        for pid_s, pf in fr.get("participantFrames", {}).items():
            team = pm.get(int(pid_s), {}).get("team")
            if team in g:
                g[team] += pf.get("totalGold", 0)
        series.append({"minuto": i, "g100": g[100], "g200": g[200],
                       "diff": g[100] - g[200]})
    return series


def gold_swings(series: list[dict], top: int = 1) -> list[dict]:
    """Maiores viradas na diferença de ouro entre minutos consecutivos."""
    swings = []
    for a, b in zip(series, series[1:]):
        swings.append({
            "de_min": a["minuto"], "ate_min": b["minuto"],
            "delta": b["diff"] - a["diff"],          # +: time 100 ganhou
            "diff_antes": a["diff"], "diff_depois": b["diff"],
        })
    swings.sort(key=lambda s: abs(s["delta"]), reverse=True)
    return swings[:top]


# ----------------------------------------------------------------------
# Abates -> teamfights, multikills, pick-offs
# ----------------------------------------------------------------------
def parse_kills(match: dict, timeline: dict) -> list[dict]:
    pm = pid_map(match)
    kills = []
    for e in _iter_events(timeline):
        if e.get("type") != "CHAMPION_KILL":
            continue
        vid = e.get("victimId")
        kid = e.get("killerId")
        assists = e.get("assistingParticipantIds") or []
        # quantos inimigos distintos bateram na vítima (cerco)
        atacantes = {d.get("participantId") for d in e.get("victimDamageReceived", [])
                     if pm.get(d.get("participantId"), {}).get("team")
                     != pm.get(vid, {}).get("team")}
        kills.append({
            "t": e.get("timestamp", 0) / 1000.0,
            "killer": kid, "victim": vid, "assists": assists,
            "killer_team": pm.get(kid, {}).get("team"),
            "victim_team": pm.get(vid, {}).get("team"),
            "pos": e.get("position", {}),
            "n_atacantes": len(atacantes),
            "bounty": e.get("bounty", 0) + e.get("shutdownBounty", 0),
        })
    return kills


def teamfights(kills: list[dict], gap_s: float = 18.0) -> list[dict]:
    """Agrupa abates próximos no tempo numa mesma briga."""
    if not kills:
        return []
    kills = sorted(kills, key=lambda k: k["t"])
    grupos = [[kills[0]]]
    for k in kills[1:]:
        if k["t"] - grupos[-1][-1]["t"] <= gap_s:
            grupos[-1].append(k)
        else:
            grupos.append([k])
    fights = []
    for g in grupos:
        if len(g) < 2:
            continue  # 1 morte só não é "briga"
        mortes = defaultdict(int)
        for k in g:
            if k["victim_team"]:
                mortes[k["victim_team"]] += 1
        fights.append({
            "ini": g[0]["t"], "fim": g[-1]["t"], "n_kills": len(g),
            "mortes_por_time": dict(mortes),
            "saldo_100": mortes.get(200, 0) - mortes.get(100, 0),  # +: time 100 ganhou
            "valor_ouro": sum(k["bounty"] for k in g),
            "kills": g,
        })
    return fights


def multikills(match: dict, timeline: dict) -> list[dict]:
    pm = pid_map(match)
    out = []
    for e in _iter_events(timeline):
        if e.get("type") == "CHAMPION_SPECIAL_KILL" and e.get("multiKillLength", 0) >= 2:
            out.append({
                "t": e.get("timestamp", 0) / 1000.0,
                "jogador": pm.get(e.get("killerId"), {}).get("nome"),
                "killer": e.get("killerId"),
                "tamanho": e.get("multiKillLength"),
            })
    return out


def _dist(a: dict, b: dict) -> float:
    return math.hypot(a.get("x", 0) - b.get("x", 0), a.get("y", 0) - b.get("y", 0))


def _positions_at(timeline: dict, t_s: float) -> dict[int, dict]:
    """Posições amostradas no frame de minuto mais próximo do instante t."""
    frames = _frames(timeline)
    idx = min(int(round(t_s / 60.0)), len(frames) - 1)
    out = {}
    for pid_s, pf in frames[idx].get("participantFrames", {}).items():
        out[int(pid_s)] = pf.get("position", {})
    return out


def detect_pickoffs(match: dict, timeline: dict, kills: list[dict],
                    dist_aliado: float = 2800.0, gap_s: float = 18.0,
                    min_t: float = 600.0) -> list[dict]:
    """Heurística (MELHOR PALPITE, não verdade): morte ISOLADA, cercada e
    longe do time. Para cortar o ruído do early (posição amostrada a cada
    1min faz lanes distintas parecerem "sozinho"), exige:
      - morte isolada no tempo (nenhum outro abate em ±gap_s) -> não é teamfight
      - 2+ inimigos bateram na vítima (cercada)
      - aliado vivo mais próximo além de dist_aliado
      - após min_t (fim da fase de rotas; default 10min)
    """
    pm = pid_map(match)
    ts_all = sorted(k["t"] for k in kills)
    picks = []
    for k in kills:
        vid, vteam = k["victim"], k["victim_team"]
        if not vid or not vteam or k["n_atacantes"] < 2 or k["t"] < min_t:
            continue
        # isolada no tempo? (nenhum outro abate por perto -> não é briga)
        vizinhos = [t for t in ts_all if t != k["t"] and abs(t - k["t"]) <= gap_s]
        if vizinhos:
            continue
        pos = _positions_at(timeline, k["t"])
        vpos = pos.get(vid)
        if not vpos:
            continue
        aliados = [pos[p] for p, inf in pm.items()
                   if inf.get("team") == vteam and p != vid and p in pos]
        if not aliados:
            continue
        d_aliado = min(_dist(vpos, a) for a in aliados)
        if d_aliado > dist_aliado:
            picks.append({
                "t": k["t"], "vitima": pm.get(vid, {}).get("nome"),
                "victim": vid, "n_atacantes": k["n_atacantes"],
                "dist_aliado": round(d_aliado), "pos": k["pos"],
                "regiao": region(k["pos"].get("x", 0), k["pos"].get("y", 0)),
            })
    return picks


def derivar(match: dict, timeline: dict) -> dict:
    """Condensa a timeline nos momentos que o post usa — pronto pra persistir.

    Por que isto existe: a timeline crua é o objeto caro (minuto a minuto, os 10
    jogadores) e vive em `cache/`, que é disco local. No GitHub Actions o
    `cache/` nasce vazio a cada run, e o post perderia a seção de momentos EM
    SILÊNCIO — os números continuam batendo, só some a parte interessante.

    A saída é auto-contida e serializável: identifica jogadores por `puuid` (o
    `participantId` só faz sentido dentro de um match) e não guarda nada que dê
    pra recalcular a partir do banco. É derivado, então é regravável — se a
    heurística de pick-off melhorar, reprocessa sem re-ingerir nada.
    """
    pm = pid_map(match)

    series = team_gold_series(match, timeline)
    swing = None
    if len(series) >= 2:
        s = gold_swings(series, top=1)[0]
        swing = {"lider_team": 100 if s["delta"] > 0 else 200,
                 "delta": s["delta"],
                 "de_min": s["de_min"], "ate_min": s["ate_min"]}

    kills = parse_kills(match, timeline)

    briga = None
    fights = teamfights(kills)
    if fights:
        d = max(fights, key=lambda f: (abs(f["saldo_100"]), f["valor_ouro"]))
        briga = {"ini": d["ini"], "fim": d["fim"], "n_kills": d["n_kills"],
                 "vencedor_team": 100 if d["saldo_100"] > 0 else 200}

    objs = objectives(match, timeline)
    dragoes: dict[int, int] = {100: 0, 200: 0}
    barao: dict[int, Optional[float]] = {100: None, 200: None}
    for o in objs:
        time_ = o.get("time")
        if time_ not in (100, 200):
            continue
        if o["tipo"].startswith("Dragão"):
            dragoes[time_] += 1
        elif o["tipo"] == "Barão" and barao[time_] is None:
            barao[time_] = o["t"]

    mks = []
    for mk in multikills(match, timeline):
        inf = pm.get(mk["killer"])
        if inf and inf.get("puuid"):
            mks.append({"puuid": inf["puuid"], "campeao": mk["jogador"],
                        "tamanho": mk["tamanho"], "t": mk["t"]})
    mks.sort(key=lambda m: m["tamanho"], reverse=True)

    picks = []
    for pk in detect_pickoffs(match, timeline, kills):
        inf = pm.get(pk["victim"])
        if inf and inf.get("puuid"):
            picks.append({"puuid": inf["puuid"], "campeao": pk["vitima"],
                          "regiao": pk["regiao"], "t": pk["t"]})

    return {
        "v": 1,                       # versão do formato; muda se o shape mudar
        "swing": swing,
        "briga_decisiva": briga,
        "dragoes": {str(k): v for k, v in dragoes.items()},
        "barao": {str(k): v for k, v in barao.items()},
        "multikills": mks,
        "pickoffs": picks,
    }


def objectives(match: dict, timeline: dict) -> list[dict]:
    pm = pid_map(match)
    out = []
    primeira_torre = True
    for e in _iter_events(timeline):
        t = e.get("type")
        ts = e.get("timestamp", 0) / 1000.0
        if t == "ELITE_MONSTER_KILL":
            mt = e.get("monsterType")
            sub = e.get("monsterSubType", "")
            nome = {"DRAGON": f"Dragão ({sub})", "BARON_NASHOR": "Barão",
                    "RIFTHERALD": "Arauto", "HORDE": "Voidgrub"}.get(mt, mt)
            out.append({"t": ts, "tipo": nome, "time": e.get("killerTeamId")})
        elif t == "BUILDING_KILL" and e.get("buildingType") == "TOWER_BUILDING" and primeira_torre:
            out.append({"t": ts, "tipo": "1ª torre",
                        "time": 200 if e.get("teamId") == 100 else 100})  # teamId = time que PERDEU a torre
            primeira_torre = False
        elif t == "CHAMPION_SPECIAL_KILL" and e.get("killType") == "KILL_FIRST_BLOOD":
            out.append({"t": ts, "tipo": "First blood",
                        "time": pm.get(e.get("killerId"), {}).get("team")})
    return sorted(out, key=lambda o: o["t"])

"""Ingestão: transforma o JSON de uma partida da Riot em linhas do banco.

Regra central (pedido do usuário): a mesma partida aparece para vários
membros, mas vira UM log só. Quando 2+ membros estão no MESMO time, a
partida é marcada `em_grupo` — é o gancho para a análise de sinergia.

Parsing é lógica pura (sem rede): recebe o match JSON + a timeline opcional
e devolve as participações já calculadas. Fácil de testar.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from .db import database as db


def _gold_at(timeline: Optional[dict], minute: int) -> dict[int, int]:
    """Ouro total de cada participante (1-10) no minuto pedido."""
    if not timeline:
        return {}
    frames = timeline.get("info", {}).get("frames", [])
    if not frames:
        return {}
    minute = min(minute, len(frames) - 1)
    pf = frames[minute].get("participantFrames", {})
    return {int(pid): f.get("totalGold", 0) for pid, f in pf.items()}


def _clean_role(part: dict) -> Optional[str]:
    """teamPosition vem suja ('Invalid' em remakes/modos especiais)."""
    pos = part.get("teamPosition") or part.get("individualPosition") or ""
    return pos if pos and pos != "Invalid" else None


def metricas_timeline(match: dict, timeline: Optional[dict]) -> dict[int, dict]:
    """participantId -> {ouro_10, ouro_15, lanediff_10} a partir da timeline.

    Fonte única: usada na ingestão (gravar no banco) E no post sob demanda
    (quando a timeline só foi baixada depois — ex.: jogos solo). {} se sem timeline.
    """
    if not timeline:
        return {}
    parts = match.get("info", {}).get("participants", [])
    g10 = _gold_at(timeline, 10)
    g15 = _gold_at(timeline, 15)
    lanediff10: dict[int, int] = {}
    if g10:
        by_pos: dict[str, dict[int, int]] = defaultdict(dict)
        for p in parts:
            pos = p.get("teamPosition") or "?"
            by_pos[pos][p.get("teamId")] = p.get("participantId")
        teams = list({p.get("teamId") for p in parts})
        if len(teams) == 2:
            t0, t1 = teams
            for pos, sides in by_pos.items():
                if pos == "?" or t0 not in sides or t1 not in sides:
                    continue
                a, b = sides[t0], sides[t1]
                if a in g10 and b in g10:
                    lanediff10[a] = g10[a] - g10[b]
                    lanediff10[b] = g10[b] - g10[a]
    return {p.get("participantId"): {
        "ouro_10": g10.get(p.get("participantId")),
        "ouro_15": g15.get(p.get("participantId")),
        "lanediff_10": lanediff10.get(p.get("participantId")),
    } for p in parts}


def parse_participacoes(match: dict, puuid_to_jogador: dict[str, int],
                        timeline: Optional[dict] = None) -> list[dict]:
    """Devolve uma linha por participante (os 10). jogador_id NULL = não-membro.
    Inclui ouro@10/@15 e lanediff@10 quando há timeline."""
    info = match.get("info", {})
    parts = info.get("participants", [])

    # KP precisa do total de kills do time.
    team_kills: dict[int, int] = defaultdict(int)
    for p in parts:
        team_kills[p.get("teamId")] += p.get("kills", 0)

    # Métricas de timeline (por participantId) — fonte única compartilhada.
    tl_m = metricas_timeline(match, timeline)

    linhas = []
    for p in parts:
        pid = p.get("participantId")
        puuid = p.get("puuid")
        tk = team_kills.get(p.get("teamId"), 0)
        kp = round((p.get("kills", 0) + p.get("assists", 0)) / tk, 3) if tk else 0.0
        m_tl = tl_m.get(pid, {})
        linhas.append({
            "jogador_id": puuid_to_jogador.get(puuid),  # None = não-membro
            "puuid": puuid,
            "team_id": p.get("teamId"),
            "role": _clean_role(p),
            "campeao": p.get("championName"),
            "win": int(bool(p.get("win"))),
            "kills": p.get("kills"),
            "deaths": p.get("deaths"),
            "assists": p.get("assists"),
            "dano": p.get("totalDamageDealtToChampions"),
            "dano_recebido": p.get("totalDamageTaken"),
            "ouro": p.get("goldEarned"),
            "visao": p.get("visionScore"),
            "farm": p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0),
            "kp": kp,
            "ouro_10": m_tl.get("ouro_10"),
            "ouro_15": m_tl.get("ouro_15"),
            "lanediff_10": m_tl.get("lanediff_10"),
            # 125 métricas pré-calculadas pela Riot, guardadas cruas (JSON).
            "challenges_json": json.dumps(p.get("challenges", {})),
        })
    return linhas


def detectar_em_grupo(linhas: list[dict]) -> bool:
    """em_grupo = 2+ membros no MESMO time (gancho da sinergia)."""
    por_time: dict[int, int] = defaultdict(int)
    for ln in linhas:
        if ln["jogador_id"] is not None:
            por_time[ln["team_id"]] += 1
    return any(qtd >= 2 for qtd in por_time.values())


def ingest_match(conn, grupo_id: int, puuid_to_jogador: dict[str, int],
                 match: dict, timeline: Optional[dict] = None) -> Optional[int]:
    """Grava uma partida (dedupe por match_id) + as 10 participações.
    Retorna o id da partida, ou None se já existia."""
    info = match.get("info", {})
    match_id = match.get("metadata", {}).get("matchId")
    if not match_id or db.partida_existe(conn, grupo_id, match_id):
        return None

    linhas = parse_participacoes(match, puuid_to_jogador, timeline)
    em_grupo = detectar_em_grupo(linhas)
    vencedor = next((ln["team_id"] for ln in linhas if ln["win"]), None)

    partida_id = db.insert_partida(
        conn, grupo_id, match_id,
        queue_id=info.get("queueId"),
        duracao_seg=info.get("gameDuration"),
        inicio_ts=info.get("gameStartTimestamp"),
        vencedor_team=vencedor,
        em_grupo=em_grupo,
        tem_timeline=timeline is not None,
    )
    for ln in linhas:
        ln["partida_id"] = partida_id
    db.insert_participacoes(conn, linhas)

    # Momentos derivados: a timeline crua só existe aqui (e em cache/, que é
    # disco local). Condensar agora é o que faz o post continuar completo quando
    # ele for montado noutro lugar — no Actions ou no Vercel, sem cache nenhum.
    if timeline is not None:
        from . import moments
        try:
            db.salvar_momentos(conn, partida_id, moments.derivar(match, timeline))
        except Exception as e:
            # Timeline malformada/curta não pode derrubar a ingestão: o fato
            # (partida + participações) já está gravado e é o que não se recupera.
            print(f"[ingest] momentos de {match_id} falharam: {e}")

    return partida_id

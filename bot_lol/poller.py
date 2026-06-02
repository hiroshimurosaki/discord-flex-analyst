"""Poller — ingestão automática (marco 3).

Sem webhook na Riot: detecção de partida nova = polling. A cada rodada,
checa as últimas N partidas de cada membro, ingere as que ainda não estão
no banco (dedupe por match_id) e devolve os partida_id recém-criados — pra
borda do Discord postar.

Lógica pura de orquestração: recebe um `client` (RiotClient ou fake nos
testes) e uma conexão. Não fala com o Discord nem sabe de event loop.
"""
from __future__ import annotations

from . import ingest, records
from .db import database as db


def puuids_do_grupo(conn, grupo_id: int) -> dict[str, int]:
    """puuid -> jogador_id dos membros ATIVOS do grupo."""
    return {r["puuid"]: r["id"] for r in db.jogadores_do_grupo(conn, grupo_id)
            if r["ativo"]}


def poll_grupo(conn, client, grupo_id: int, por_jogador: int = 5) -> list[int]:
    """Uma rodada de polling para um grupo. Ingere as partidas novas (timeline
    só p/ jogos em grupo) e retorna os partida_id criados, na ordem de início."""
    puuid_to_jogador = puuids_do_grupo(conn, grupo_id)
    if not puuid_to_jogador:
        return []

    # Coleta os match_ids recentes de todos os membros (dedupe entre eles).
    candidatos: list[str] = []
    vistos: set[str] = set()
    for puuid in puuid_to_jogador:
        for mid in client.get_match_ids(puuid, count=por_jogador):
            if mid not in vistos:
                vistos.add(mid)
                candidatos.append(mid)

    novos: list[tuple[int, int]] = []  # (inicio_ts, partida_id)
    for mid in candidatos:
        if db.partida_existe(conn, grupo_id, mid):
            continue
        m = client.get_match(mid)
        if not m:
            continue
        if m.get("info", {}).get("queueId") not in records.PERMITIDAS:
            continue  # ARAM/Arena/etc. — fora da allowlist
        linhas = ingest.parse_participacoes(m, puuid_to_jogador)
        tl = client.get_timeline(mid) if ingest.detectar_em_grupo(linhas) else None
        pid = ingest.ingest_match(conn, grupo_id, puuid_to_jogador, m, tl)
        if pid:
            novos.append((m.get("info", {}).get("gameStartTimestamp") or 0, pid))

    novos.sort(key=lambda x: x[0])  # posta na ordem em que foram jogadas
    return [pid for _, pid in novos]

"""Orquestra narrativa + cache (liga db + llm + post).

Regra: 1 chamada à LLM por partida gera a narrativa do time E a de cada
jogador; tudo é guardado em `analises`. Próximas consultas (time ou qualquer
jogador) leem do banco — zero chamadas repetidas.
"""
from __future__ import annotations

from typing import Optional

from . import llm, post, tendencias
from .db import database as db


def obter_analises(conn, partida_id: int, modelo: Optional[str] = None,
                   forcar: bool = False) -> Optional[dict]:
    """Devolve {"time": txt, "jogadores": {nick: txt}} do cache; gera se faltar.
    Retorna None se não há LLM configurada e nada em cache."""
    if not forcar:
        cached = db.get_analises(conn, partida_id)
        if cached and cached.get("time"):
            return cached

    if not llm.disponivel():
        return None

    # membros da partida (jogadores do grupo que participaram)
    membros = conn.execute(
        "SELECT pa.jogador_id, j.nick_display FROM participacoes pa "
        "JOIN jogadores j ON j.id = pa.jogador_id WHERE pa.partida_id=?",
        (partida_id,)).fetchall()
    nicks = [m["nick_display"] for m in membros]
    id_por_nick = {m["nick_display"]: m["jogador_id"] for m in membros}

    fatos = post.fatos_partida(conn, partida_id)

    # Perfil vivo (marco 6): injeta o histórico ranqueado de cada membro como
    # CONTEXTO, pra LLM situar o desempenho ("vem subindo", "apanha de Irelia").
    grupo_id = conn.execute("SELECT grupo_id FROM partidas WHERE id=?",
                            (partida_id,)).fetchone()["grupo_id"]
    pv_linhas = []
    for m in membros:
        resumo = tendencias.resumo_curto(tendencias.perfil_vivo(conn, grupo_id, m["jogador_id"]))
        if resumo:
            pv_linhas.append(f"- {m['nick_display']}: {resumo}")
    contexto = fatos
    if pv_linhas:
        contexto += ("\n\n=== PERFIL VIVO (histórico ranqueado dos jogadores — "
                     "contexto, não recalcule) ===\n" + "\n".join(pv_linhas))

    data = llm.analisar_lote(contexto, nicks, modelo)

    # casa nicks retornados (case-insensitive) com os jogador_id
    por_jogador: dict[int, str] = {}
    lower = {n.lower(): i for n, i in id_por_nick.items()}
    for nick, texto in (data.get("jogadores") or {}).items():
        jid = lower.get((nick or "").lower())
        if jid is not None and texto:
            por_jogador[jid] = texto

    db.salvar_analises(conn, partida_id, data.get("time", ""), por_jogador, data.get("modelo", ""))
    return db.get_analises(conn, partida_id)

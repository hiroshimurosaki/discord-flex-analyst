"""Gerador do post de partida (marco 4 — saída mínima, SEM LLM).

Lê uma partida do banco e devolve o texto determinístico que iria pro
Discord: escalação, duelo de rota vs oponente direto, momentos-chave,
destaques e conquistas (challenges). A narrativa (🎙️) é o marco 5 (LLM)
e entra como placeholder por enquanto.

Momentos vêm da timeline em cache (já baixada na ingestão).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from . import config, moments, records
from .db import database as db

_ROLE_PT = {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID",
            "BOTTOM": "ADC", "UTILITY": "SUP"}


def _mmss(t: float) -> str:
    return f"{int(t)//60}:{int(t)%60:02d}"


def _load_cache(match_id: str):
    mp = config.CACHE_DIR / f"{match_id}.json"
    tp = config.CACHE_DIR / f"{match_id}_timeline.json"
    match = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None
    tl = json.loads(tp.read_text(encoding="utf-8")) if tp.exists() else None
    return match, tl


def _tl_metricas_por_puuid(match, tl) -> dict[str, dict]:
    """puuid -> {ouro_10, ouro_15, lanediff_10} a partir do cache da timeline.

    Usado como fallback quando a partida foi ingerida SEM timeline (ex.: jogos
    solo no backfill) mas a timeline foi baixada depois sob demanda."""
    if not match or not tl:
        return {}
    from . import ingest
    por_pid = ingest.metricas_timeline(match, tl)
    out = {}
    for p in match.get("info", {}).get("participants", []):
        m = por_pid.get(p.get("participantId"))
        if m:
            out[p.get("puuid")] = m
    return out


def _momentos(conn, partida_id: int, match_id: str) -> Optional[dict]:
    """Momentos derivados da partida, do banco.

    Se a partida foi ingerida antes desta tabela existir mas a timeline ainda
    está no cache local, deriva e grava agora — assim um banco antigo se cura
    sozinho na primeira vez que alguém olhar a partida, em vez de exigir
    re-ingestão. Onde não há cache (Actions, Vercel) simplesmente não há seção,
    que é o comportamento correto: não dá pra inventar o que não foi guardado.
    """
    mom = db.get_momentos(conn, partida_id)
    if mom is not None:
        return mom

    match, tl = _load_cache(match_id)
    if not (match and tl):
        return None
    try:
        mom = moments.derivar(match, tl)
    except Exception:
        return None
    db.salvar_momentos(conn, partida_id, mom)
    return mom


def _render_momentos(mom: dict, nosso_time: int, vencedor_team: Optional[int],
                     nick_de: dict[str, str]) -> list[str]:
    """Momentos estruturados -> linhas do post. Só formatação, zero cálculo."""
    L = ["\n**🔑 Momentos-chave**"]

    swing = mom.get("swing")
    if swing and vencedor_team and swing["lider_team"] != vencedor_team:
        L.append("• 🔄 **Virada**: o maior swing de ouro foi de quem perdeu — jogo de comeback.")

    briga = mom.get("briga_decisiva")
    if briga:
        quem = "nós" if briga["vencedor_team"] == nosso_time else "o inimigo"
        L.append(f"• ⚔️ Briga decisiva {_mmss(briga['ini'])}–{_mmss(briga['fim'])}: "
                 f"{briga['n_kills']} abates, **{quem}** levou a melhor.")

    # Chaves de time viram string no JSON — normaliza na leitura.
    drags = (mom.get("dragoes") or {}).get(str(nosso_time), 0)
    barao_t = (mom.get("barao") or {}).get(str(nosso_time))
    L.append(f"• 🐉 Objetivos nossos: {drags} dragão(ões)"
             + (f", Barão {_mmss(barao_t)}" if barao_t else ""))

    rotulo = {2: "Double", 3: "Triple", 4: "Quadra", 5: "PENTA"}
    for mk in [m for m in mom.get("multikills") or [] if m["puuid"] in nick_de][:3]:
        L.append(f"• 💥 {nick_de[mk['puuid']]} ({mk['campeao']}) — "
                 f"{rotulo.get(mk['tamanho'], mk['tamanho'])} Kill {_mmss(mk['t'])}")

    for pk in [p for p in mom.get("pickoffs") or [] if p["puuid"] in nick_de]:
        L.append(f"• 💀 {nick_de[pk['puuid']]} pego sozinho no {pk['regiao']} ({_mmss(pk['t'])})")

    return L


def montar_post(conn, partida_id: int, narrador=None) -> str:
    """Post do time. Se `narrador` (callable: fatos->texto) for dado, preenche
    a 🎙️; senão, placeholder. Para o fluxo com cache, use fatos_partida()."""
    fatos = fatos_partida(conn, partida_id)
    if narrador is None:
        return fatos + "\n\n🎙️ *[narrativa da LLM entra no marco 5]*"
    try:
        narrativa = narrador(fatos)
    except Exception as e:
        narrativa = f"_(narrativa indisponível: {e})_"
    return fatos + "\n\n**🎙️ A leitura**\n" + narrativa


def fatos_partida(conn, partida_id: int) -> str:
    """Bloco determinístico do time (sem narrativa) — vira display E contexto da LLM."""
    p = conn.execute("SELECT * FROM partidas WHERE id=?", (partida_id,)).fetchone()
    parts = conn.execute(
        "SELECT pa.*, j.nick_display FROM participacoes pa "
        "LEFT JOIN jogadores j ON j.id = pa.jogador_id WHERE pa.partida_id=?",
        (partida_id,)).fetchall()

    # Qual é o nosso time (onde estão os membros)?
    por_time: dict[int, list] = {}
    for r in parts:
        por_time.setdefault(r["team_id"], []).append(r)
    nosso_time = max(por_time, key=lambda t: sum(1 for r in por_time[t] if r["jogador_id"]))
    venceu = p["vencedor_team"] == nosso_time

    membros = sorted([r for r in por_time[nosso_time] if r["jogador_id"]],
                     key=lambda r: r["dano"] or 0, reverse=True)
    # mapa role -> participante (para achar o oponente direto)
    role_map: dict[str, dict[int, dict]] = {}
    for r in parts:
        if r["role"]:
            role_map.setdefault(r["role"], {})[r["team_id"]] = r
    outro_time = next(t for t in por_time if t != nosso_time)

    L = []
    res = "🏆 **Vitória**" if venceu else "❌ **Derrota**"
    dur = f"{(p['duracao_seg'] or 0)//60}:{(p['duracao_seg'] or 0)%60:02d}"
    quando = datetime.fromtimestamp((p["inicio_ts"] or 0) / 1000).strftime("%d/%m %H:%M")
    fila = {440: "Ranked Flex", 420: "SoloQ", 450: "ARAM"}.get(p["queue_id"], f"queue {p['queue_id']}")
    juntos = sum(1 for r in por_time[nosso_time] if r["jogador_id"])
    L.append(f"{res} • {fila} em {dur}")
    L.append(f"`{quando}` · {juntos} do grupo juntos\n")

    # --- Escalação ---
    L.append("**Escalação**")
    L.append("```")
    L.append(f"{'JOGADOR':<13}{'CAMPEÃO':<12}{'ROLE':<5}{'KDA':<10}{'DANO':>7}")
    for r in membros:
        kda = f"{r['kills']}/{r['deaths']}/{r['assists']}"
        L.append(f"{r['nick_display'][:12]:<13}{(r['campeao'] or '?')[:11]:<12}"
                 f"{_ROLE_PT.get(r['role'], '?'):<5}{kda:<10}{(r['dano'] or 0)/1000:>6.1f}k")
    L.append("```")

    # Fallback de ouro@10 para partidas ingeridas SEM timeline cuja timeline foi
    # baixada depois. Só funciona onde há cache local; no Actions/Vercel devolve
    # vazio e o duelo mostra "s/ dado", que é honesto.
    tlm = _tl_metricas_por_puuid(*_load_cache(p["match_id"]))

    # --- Duelo de rota (vs oponente direto) ---
    L.append("**⚔️ Duelo de rota** (vs adversário direto, @10min)")
    for r in membros:
        opp = role_map.get(r["role"], {}).get(outro_time)
        if not opp:
            continue
        ld = r["lanediff_10"]
        if ld is None:
            ld = tlm.get(r["puuid"], {}).get("lanediff_10")
        farm_d = (r["farm"] or 0) - (opp["farm"] or 0)
        sinal = "🟢" if (ld or 0) >= 0 else "🔴"
        ldtxt = f"ouro@10 {ld:+d}" if ld is not None else "ouro@10 s/ dado"
        L.append(f"{sinal} {r['nick_display']} ({r['campeao']}) vs {opp['campeao']} "
                 f"— {ldtxt}, CS {farm_d:+d}")

    # --- Momentos-chave (do banco; ver tabela `momentos`) ---
    mom = _momentos(conn, partida_id, p["match_id"])
    if mom:
        L.extend(_render_momentos(mom, nosso_time, p["vencedor_team"],
                                  {r["puuid"]: r["nick_display"] for r in membros}))

    # --- Destaques + Conquistas (challenges) ---
    L.append("\n**🏅 Destaques**")
    mvp = membros[0]
    L.append(f"• 🥇 Maior dano: **{mvp['nick_display']}** ({(mvp['dano'] or 0)/1000:.1f}k)")
    visao = max(membros, key=lambda r: r["visao"] or 0)
    L.append(f"• 👁️ Visão: **{visao['nick_display']}** ({visao['visao']} de visão)")

    conquistas = _conquistas(membros)
    if conquistas:
        L.append("**🎖️ Conquistas**")
        L.extend(f"• {c}" for c in conquistas)

    # --- Recordes batidos nesta partida (callout 🆕) ---
    queues = records.FLEX if p["queue_id"] in records.FLEX else records.NORMAIS
    grupo_id = conn.execute("SELECT grupo_id FROM partidas WHERE id=?", (partida_id,)).fetchone()["grupo_id"]
    batidos = records.recordes_batidos(conn, grupo_id, partida_id, queues)
    if batidos:
        L.append("\n**🏆 Recordes**")
        L.extend(f"• {b}" for b in batidos)

    return "\n".join(L)


def montar_post_individual(conn, partida_id: int, jogador_id: int, narrador=None) -> str:
    """Post focado num jogador. O `narrador` (individual) recebe os FATOS
    COMPLETOS do time como contexto, pra situar o desempenho dele."""
    fatos_ind = fatos_jogador(conn, partida_id, jogador_id)
    if fatos_ind is None:
        return "Esse jogador não participou dessa partida."
    if narrador is None:
        return fatos_ind + "\n\n🎙️ *[análise individual entra com a LLM]*"
    fatos_time = fatos_partida(conn, partida_id)  # contexto completo p/ a LLM
    try:
        analise = narrador(fatos_time)
    except Exception as e:
        analise = f"_(análise indisponível: {e})_"
    return fatos_ind + "\n\n**🎙️ Análise individual**\n" + analise


def fatos_jogador(conn, partida_id: int, jogador_id: int) -> Optional[str]:
    """Bloco determinístico individual (linha + duelo de rota + conquistas)."""
    p = conn.execute("SELECT * FROM partidas WHERE id=?", (partida_id,)).fetchone()
    eu = conn.execute(
        "SELECT pa.*, j.nick_display FROM participacoes pa JOIN jogadores j ON j.id=pa.jogador_id "
        "WHERE pa.partida_id=? AND pa.jogador_id=?", (partida_id, jogador_id)).fetchone()
    if not eu:
        return None

    venceu = p["vencedor_team"] == eu["team_id"]
    res = "🏆 Vitória" if venceu else "❌ Derrota"
    dur = f"{(p['duracao_seg'] or 0)//60}min"
    opp = conn.execute(
        "SELECT campeao, farm, ouro FROM participacoes WHERE partida_id=? AND team_id<>? AND role=?",
        (partida_id, eu["team_id"], eu["role"])).fetchone()

    L = [f"👤 **{eu['nick_display']}** — {eu['campeao']} ({_ROLE_PT.get(eu['role'], '?')}) · {res} em {dur}", ""]
    L.append(f"KDA **{eu['kills']}/{eu['deaths']}/{eu['assists']}** · dano {(eu['dano'] or 0)/1000:.1f}k "
             f"· ouro {(eu['ouro'] or 0)/1000:.1f}k · visão {eu['visao']} · CS {eu['farm']}")
    if opp:
        ld = eu["lanediff_10"]
        if ld is None:
            match, tl = _load_cache(p["match_id"])
            ld = _tl_metricas_por_puuid(match, tl).get(eu["puuid"], {}).get("lanediff_10")
        sinal = "🟢" if (ld or 0) >= 0 else "🔴"
        ldtxt = f"ouro@10 {ld:+d}" if ld is not None else "sem ouro@10"
        L.append(f"⚔️ Rota vs {opp['campeao']}: {sinal} {ldtxt}, CS {(eu['farm'] or 0)-(opp['farm'] or 0):+d}")
    conq = _conquistas([eu])
    if conq:
        L.extend(f"🎖️ {c}" for c in conq)
    return "\n".join(L)


def _conquistas(membros) -> list[str]:
    """Highlights a partir dos challenges crus (determinístico)."""
    out = []
    for r in membros:
        try:
            ch = json.loads(r["challenges_json"] or "{}")
        except (TypeError, ValueError):
            continue
        nick, champ = r["nick_display"], r["campeao"]
        if ch.get("soloKills", 0) >= 2:
            out.append(f"🔪 {nick} fez {int(ch['soloKills'])} abates solo")
        if ch.get("maxCsAdvantageOnLaneOpponent", 0) >= 20:
            out.append(f"🌾 {nick} ({champ}) abriu +{int(ch['maxCsAdvantageOnLaneOpponent'])} de CS na rota")
        if ch.get("enemyChampionImmobilizations", 0) >= 15:
            out.append(f"🧊 {nick} imobilizou inimigos {int(ch['enemyChampionImmobilizations'])}x")
        if ch.get("turretPlatesTaken", 0) >= 4:
            out.append(f"🏰 {nick} levou {int(ch['turretPlatesTaken'])} placas de torre")
        if ch.get("teamDamagePercentage", 0) >= 0.30:
            out.append(f"💣 {nick} foi {ch['teamDamagePercentage']*100:.0f}% do dano do time")
    return out[:5]

"""Motor de recordes e perfis — agregação pura sobre o banco (sem LLM, sem API).

Segue a decisão fechada: só conta partidas em_grupo (time fechado). Dois
recortes: FLEX sério (440) e NORMAIS zoeira (draft/blind/quickplay/ARAM).
"melhor partida" sai em duas leituras: percentil-na-partida (justo entre
roles) e KDA (intuitivo).

Recordes se recalculam na hora — nenhuma tabela nova. Quanto mais partidas
acumulam, mais ricos ficam.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

FLEX = {440}
SOLO = {420}
NORMAIS = {400, 430, 490}        # draft, blind, quickplay (SEM ARAM/Arena)
# Filas que entram no dataset. Fora daqui: ARAM(450), Arena(1700/1710),
# URF, bots, Clash, etc. — não queremos.
PERMITIDAS = FLEX | SOLO | NORMAIS

# Métricas (maior = melhor) usadas no percentil-na-partida.
_PCT_METRICAS = ["dano", "ouro", "visao", "kp", "farm"]


def _pct(valores: list[float], v: float) -> float:
    """Percentil de v dentro da lista: % de jogadores que ele superou."""
    n = len(valores)
    if n <= 1:
        return 100.0
    piores = sum(1 for x in valores if x < v)
    return round(100.0 * piores / (n - 1), 1)


def _data(ts: Optional[int]) -> str:
    from datetime import datetime
    return datetime.fromtimestamp((ts or 0) / 1000).strftime("%d/%m/%Y") if ts else "?"


def _partidas_grupo(conn, grupo_id: int, queues: set[int]) -> list:
    qs = ",".join("?" for _ in queues)
    return conn.execute(
        f"SELECT * FROM partidas WHERE grupo_id=? AND em_grupo=1 AND queue_id IN ({qs}) "
        "ORDER BY inicio_ts", (grupo_id, *queues)).fetchall()


def _membros(conn, partida_id: int) -> list:
    return conn.execute(
        "SELECT pa.*, j.nick_display FROM participacoes pa "
        "JOIN jogadores j ON j.id = pa.jogador_id WHERE pa.partida_id=?",
        (partida_id,)).fetchall()


def percentis_da_partida(conn, partida_id: int) -> dict[str, float]:
    """puuid do membro -> percentil médio (vs os 10) nessa partida."""
    todos = conn.execute(
        "SELECT * FROM participacoes WHERE partida_id=?", (partida_id,)).fetchall()
    if not todos:
        return {}
    por_metrica = {mt: [r[mt] or 0 for r in todos] for mt in _PCT_METRICAS}
    out = {}
    for r in todos:
        if r["jogador_id"] is None:
            continue
        media = sum(_pct(por_metrica[mt], r[mt] or 0) for mt in _PCT_METRICAS) / len(_PCT_METRICAS)
        out[r["puuid"]] = round(media, 1)
    return out


def _kda(r) -> float:
    d = r["deaths"] or 0
    return (r["kills"] + r["assists"]) / d if d else float(r["kills"] + r["assists"])


def _team_gold(conn, partida_id: int) -> dict[int, int]:
    g = defaultdict(int)
    for r in conn.execute("SELECT team_id, ouro FROM participacoes WHERE partida_id=?",
                          (partida_id,)):
        g[r["team_id"]] += r["ouro"] or 0
    return g


def _nosso_time(conn, partida_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT team_id, COUNT(*) c FROM participacoes WHERE partida_id=? AND jogador_id IS NOT NULL "
        "GROUP BY team_id ORDER BY c DESC LIMIT 1", (partida_id,)).fetchone()
    return row["team_id"] if row else None


# ----------------------------------------------------------------------
# Recordes do grupo
# ----------------------------------------------------------------------
def recordes_grupo(conn, grupo_id: int, queues: set[int] = FLEX) -> dict:
    """Devolve {categoria: {valor, nick, campeao, partida_id, data, ...}}."""
    partidas = _partidas_grupo(conn, grupo_id, queues)
    rec: dict[str, dict] = {}

    def melhor(cat, valor, **extra):
        if cat not in rec or valor > rec[cat]["valor"]:
            rec[cat] = {"valor": valor, **extra}

    for p in partidas:
        pid = p["id"]
        membros = _membros(conn, pid)
        pcts = percentis_da_partida(conn, pid)
        nosso = _nosso_time(conn, pid)
        venceu = p["vencedor_team"] == nosso
        gold = _team_gold(conn, pid)
        base = {"partida_id": pid, "match_id": p["match_id"], "data": _data(p["inicio_ts"])}

        # match-level
        diff = gold.get(nosso, 0) - gold.get(next((t for t in gold if t != nosso), nosso), 0)
        if venceu:
            melhor("maior_stomp", diff, **base, dur=p["duracao_seg"])
            melhor("vitoria_rapida", -(p["duracao_seg"] or 0), **base,
                   dur=p["duracao_seg"])  # negativo p/ "menor duração vence"
        else:
            melhor("maior_surra", -diff, **base, dur=p["duracao_seg"])
        melhor("jogo_longo", p["duracao_seg"] or 0, **base)

        # comeback: ganhou estando atrás no ouro@15
        if venceu:
            tot15 = conn.execute(
                "SELECT team_id, SUM(ouro_15) s FROM participacoes WHERE partida_id=? "
                "AND ouro_15 IS NOT NULL GROUP BY team_id", (pid,)).fetchall()
            if len(tot15) == 2:
                d15 = {r["team_id"]: r["s"] for r in tot15}
                deficit = d15.get(next(t for t in d15 if t != nosso), 0) - d15.get(nosso, 0)
                if deficit > 0:
                    melhor("comeback", deficit, **base)

        # member-level
        for r in membros:
            who = {"nick": r["nick_display"], "campeao": r["campeao"], **base}
            melhor("maior_dano", r["dano"] or 0, **who)
            melhor("mais_abates", r["kills"] or 0, **who)
            melhor("maior_kda", round(_kda(r), 2), **who, kda=f"{r['kills']}/{r['deaths']}/{r['assists']}")
            melhor("mais_visao", r["visao"] or 0, **who)
            melhor("mais_farm", r["farm"] or 0, **who)
            melhor("melhor_percentil", pcts.get(r["puuid"], 0), **who)
            try:
                ch = json.loads(r["challenges_json"] or "{}")
            except (TypeError, ValueError):
                ch = {}
            if "enemyChampionImmobilizations" in ch:
                melhor("mais_cc", int(ch["enemyChampionImmobilizations"]), **who)
    return rec


def recordes_batidos(conn, grupo_id: int, partida_id: int, queues: set[int] = FLEX) -> list[str]:
    """Quais recordes ESTA partida detém (para o callout '🆕' no post)."""
    rec = recordes_grupo(conn, grupo_id, queues)
    rotulos = {
        "maior_dano": ("⚔️ Maior dano", lambda r: f"{r['valor']/1000:.1f}k"),
        "mais_abates": ("🗡️ Mais abates", lambda r: f"{r['valor']}"),
        "maior_kda": ("🎯 Maior KDA", lambda r: r.get("kda", r["valor"])),
        "mais_visao": ("👁️ Mais visão", lambda r: f"{r['valor']}"),
        "mais_farm": ("🌾 Mais farm", lambda r: f"{r['valor']}"),
        "mais_cc": ("🧊 Mais imobilizações", lambda r: f"{r['valor']}"),
        "maior_stomp": ("🔥 Maior stomp", lambda r: f"+{r['valor']/1000:.1f}k ouro"),
        "vitoria_rapida": ("⚡ Vitória mais rápida", lambda r: f"{(r['dur'] or 0)//60}min"),
        "jogo_longo": ("🐢 Jogo mais longo", lambda r: f"{r['valor']//60}min"),
        "comeback": ("🔄 Maior comeback", lambda r: f"−{r['valor']/1000:.1f}k atrás"),
        "melhor_percentil": ("🏅 Melhor atuação", lambda r: f"{r['valor']:.0f}º pct"),
    }
    out = []
    for cat, r in rec.items():
        if r.get("partida_id") == partida_id and cat in rotulos:
            rotulo, fmt = rotulos[cat]
            quem = f"{r.get('nick')} ({r.get('campeao')})" if r.get("nick") else ""
            out.append(f"🆕 **{rotulo}**: {fmt(r)} {quem}".strip())
    return out


# ----------------------------------------------------------------------
# Perfil individual
# ----------------------------------------------------------------------
def perfil(conn, grupo_id: int, jogador_id: int, queues: set[int] = FLEX) -> dict:
    partidas = _partidas_grupo(conn, grupo_id, queues)
    pids = [p["id"] for p in partidas]
    if not pids:
        return {}
    meta = {p["id"]: p for p in partidas}

    qs = ",".join("?" for _ in pids)
    linhas = conn.execute(
        f"SELECT * FROM participacoes WHERE jogador_id=? AND partida_id IN ({qs})",
        (jogador_id, *pids)).fetchall()
    if not linhas:
        return {}

    n = len(linhas)
    vitorias = sum(1 for r in linhas if r["win"])
    soma = lambda c: sum(r[c] or 0 for r in linhas)
    medias = {
        "dano": soma("dano") / n, "kda": sum(_kda(r) for r in linhas) / n,
        "visao": soma("visao") / n, "farm": soma("farm") / n,
    }
    # melhor/pior partida (percentil + KDA lado a lado)
    com_pct = []
    for r in linhas:
        pcts = percentis_da_partida(conn, r["partida_id"])
        com_pct.append((pcts.get(r["puuid"], 0), r))
    melhor_p = max(com_pct, key=lambda x: x[0])
    pior_p = min(com_pct, key=lambda x: x[0])

    def desc(item):
        pct, r = item
        p = meta[r["partida_id"]]
        res = "V" if r["win"] else "D"
        return {"campeao": r["campeao"], "percentil": pct, "res": res,
                "kda": f"{r['kills']}/{r['deaths']}/{r['assists']}",
                "dur": (p["duracao_seg"] or 0) // 60, "data": _data(p["inicio_ts"])}

    # melhor/pior duo (parceiro de MESMO time), mínimo de jogos
    duo_g, duo_v = defaultdict(int), defaultdict(int)
    for r in linhas:
        colegas = conn.execute(
            "SELECT j.nick_display FROM participacoes pa JOIN jogadores j ON j.id=pa.jogador_id "
            "WHERE pa.partida_id=? AND pa.team_id=? AND pa.jogador_id IS NOT NULL AND pa.jogador_id<>?",
            (r["partida_id"], r["team_id"], jogador_id)).fetchall()
        for c in colegas:
            duo_g[c["nick_display"]] += 1
            duo_v[c["nick_display"]] += int(bool(r["win"]))
    duos = [{"nick": k, "jogos": duo_g[k], "wr": round(100 * duo_v[k] / duo_g[k], 1)}
            for k in duo_g if duo_g[k] >= 3]
    melhor_duo = max(duos, key=lambda d: d["wr"]) if duos else None
    pior_duo = min(duos, key=lambda d: d["wr"]) if duos else None

    # campeão-assinatura (mais jogado, com WR)
    champ_g, champ_v = defaultdict(int), defaultdict(int)
    for r in linhas:
        champ_g[r["campeao"]] += 1
        champ_v[r["campeao"]] += int(bool(r["win"]))
    assinatura = max(champ_g, key=champ_g.get)

    return {
        "jogos": n, "wr": round(100 * vitorias / n, 1), "medias": medias,
        "rec_dano": max(r["dano"] or 0 for r in linhas),
        "rec_abates": max(r["kills"] or 0 for r in linhas),
        "melhor_partida": desc(melhor_p), "pior_partida": desc(pior_p),
        "melhor_duo": melhor_duo, "pior_duo": pior_duo,
        "assinatura": {"campeao": assinatura, "jogos": champ_g[assinatura],
                       "wr": round(100 * champ_v[assinatura] / champ_g[assinatura], 1)},
    }


# ----------------------------------------------------------------------
# Formatação para o Discord (/recordes e /perfil)
# ----------------------------------------------------------------------
def formatar_recordes(conn, grupo_id: int, nome_grupo: str, queues: set[int] = FLEX) -> str:
    rec = recordes_grupo(conn, grupo_id, queues)
    total = len(_partidas_grupo(conn, grupo_id, queues))
    recorte = "Flex" if queues == FLEX else "Normais"
    L = [f"🏛️ **HALL DA FAMA — {nome_grupo}** ({recorte} · {total} partidas em grupo)"]
    if not rec:
        L.append("_(sem partidas nesse recorte ainda)_")
        return "\n".join(L)

    def quem(c):
        r = rec.get(c, {})
        return f"{r.get('nick')} · {r.get('campeao')}" if r.get("nick") else ""

    linhas = [
        ("⚔️", "Maior dano", lambda r: f"{r['valor']/1000:.1f}k", "maior_dano"),
        ("🗡️", "Mais abates", lambda r: f"{r['valor']}", "mais_abates"),
        ("🎯", "Maior KDA", lambda r: r.get("kda", r["valor"]), "maior_kda"),
        ("👁️", "Mais visão", lambda r: f"{r['valor']}", "mais_visao"),
        ("🌾", "Mais farm", lambda r: f"{r['valor']}", "mais_farm"),
        ("🧊", "Mais imobilizações", lambda r: f"{r['valor']}", "mais_cc"),
        ("🏅", "Melhor atuação", lambda r: f"{r['valor']:.0f}º pct", "melhor_percentil"),
        ("⚡", "Vitória mais rápida", lambda r: f"{(r['dur'] or 0)//60}min", "vitoria_rapida"),
        ("🐢", "Jogo mais longo", lambda r: f"{r['valor']//60}min", "jogo_longo"),
        ("🔥", "Maior stomp", lambda r: f"+{r['valor']/1000:.1f}k ouro", "maior_stomp"),
        ("💀", "Maior surra", lambda r: f"−{r['valor']/1000:.1f}k ouro", "maior_surra"),
        ("🔄", "Maior comeback", lambda r: f"−{r['valor']/1000:.1f}k atrás", "comeback"),
    ]
    for emoji, rotulo, fmt, cat in linhas:
        if cat in rec:
            r = rec[cat]
            extra = f"  ({quem(cat)})" if quem(cat) else ""
            L.append(f"{emoji} {rotulo:<22} **{fmt(r)}**{extra}  ·  {r['data']}")
    if total < 10:
        L.append("\n`⚠️ poucos jogos — recordes ainda voláteis`")
    return "\n".join(L)


def formatar_perfil(conn, grupo_id: int, jogador_id: int, nick: str,
                    queues: set[int] = FLEX) -> str:
    pf = perfil(conn, grupo_id, jogador_id, queues)
    if not pf:
        return f"👤 **{nick}** — sem partidas em grupo nesse recorte ainda."
    m = pf["medias"]
    L = [f"👤 **{nick}** — {pf['jogos']} jogos em grupo · {pf['wr']}% WR", ""]
    L.append(f"📊 Médias: dano {m['dano']/1000:.1f}k · KDA {m['kda']:.1f} · "
             f"visão {m['visao']:.0f} · CS {m['farm']:.0f}")
    L.append(f"🏆 Recordes pessoais: maior dano {pf['rec_dano']/1000:.1f}k · "
             f"mais abates {pf['rec_abates']}")
    mp, pp = pf["melhor_partida"], pf["pior_partida"]
    L.append(f"⭐ Melhor partida: {mp['campeao']} ({mp['res']} {mp['dur']}min) — "
             f"{mp['percentil']:.0f}º pct · KDA {mp['kda']}")
    L.append(f"💩 Pior partida: {pp['campeao']} ({pp['res']} {pp['dur']}min) — "
             f"{pp['percentil']:.0f}º pct · KDA {pp['kda']}")
    if pf["melhor_duo"]:
        d = pf["melhor_duo"]
        L.append(f"🤝 Melhor duo: {d['nick']} — {d['wr']}% em {d['jogos']}")
    if pf["pior_duo"] and pf["pior_duo"] != pf["melhor_duo"]:
        d = pf["pior_duo"]
        L.append(f"🥶 Pior duo: {d['nick']} — {d['wr']}% em {d['jogos']}")
    a = pf["assinatura"]
    L.append(f"🎮 Campeão-assinatura: {a['campeao']} ({a['wr']}% em {a['jogos']})")
    return "\n".join(L)

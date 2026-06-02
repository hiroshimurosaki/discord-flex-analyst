"""Detector de tendências (marco 6) — o "perfil vivo" de um jogador.

Cruza o histórico RANQUEADO (solo/duo + flex) e calcula, de forma 100%
determinística (a LLM nunca calcula), quatro leituras:

  1. Forma recente vs antiga  — "vem subindo/caindo" (janela móvel).
  2. Evolução por campeão     — "aprendendo Brand" (recente vs antigo no champ).
  3. Matchup por oponente     — "apanha de Irelia" (WR/ouro@10 vs o rival direto).
  4. Padrões condicionais     — onde rende mais (lado, fila, role).

Honestidade estatística: só reporta o que tem amostra mínima, e sempre carrega
a contagem de jogos. Vira (a) bloco no /perfil e (b) contexto do prompt da LLM.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from . import records
from .db import database as db

# Amostras mínimas — abaixo disso não cravamos tendência.
MIN_JOGOS = 20          # total ranqueado p/ falar de "forma"
JANELA = 15             # tamanho da janela recente (e da antiga, p/ comparar)
MIN_CAMPEAO = 6         # 3 recentes + 3 antigos
MIN_MATCHUP = 3         # jogos contra o mesmo campeão na rota
GAP_NOTAVEL = 12.0      # diferença de WR (pp) p/ um padrão valer menção


def _wr(vitorias: int, jogos: int) -> Optional[float]:
    return round(100.0 * vitorias / jogos, 1) if jogos else None


def _rows(conn, grupo_id: int, jogador_id: int, queues: set[int]):
    qs = ",".join("?" for _ in queues)
    return conn.execute(
        f"SELECT pa.*, pt.inicio_ts, pt.queue_id, pt.duracao_seg "
        f"FROM participacoes pa JOIN partidas pt ON pt.id = pa.partida_id "
        f"WHERE pa.jogador_id=? AND pt.grupo_id=? AND pt.queue_id IN ({qs}) "
        f"ORDER BY pt.inicio_ts", (jogador_id, grupo_id, *queues)).fetchall()


def _forma(conn, rows) -> Optional[dict]:
    """Janela recente vs a anterior: WR, percentil médio e KDA."""
    n = len(rows)
    if n < MIN_JOGOS:
        return None
    recente = rows[-JANELA:]
    antiga = rows[-2 * JANELA:-JANELA]
    if len(antiga) < JANELA // 2:  # sem janela antiga suficiente p/ comparar
        return None

    def agg(janela):
        v = sum(1 for r in janela if r["win"])
        kda = sum(records._kda(r) for r in janela) / len(janela)
        pcts = []
        for r in janela:
            p = records.percentis_da_partida(conn, r["partida_id"]).get(r["puuid"])
            if p is not None:
                pcts.append(p)
        pct = round(sum(pcts) / len(pcts), 1) if pcts else None
        return {"jogos": len(janela), "wr": _wr(v, len(janela)),
                "kda": round(kda, 2), "percentil": pct}

    r_ag, a_ag = agg(recente), agg(antiga)
    delta = (r_ag["wr"] or 0) - (a_ag["wr"] or 0)
    direcao = "subindo" if delta >= GAP_NOTAVEL else "caindo" if delta <= -GAP_NOTAVEL else "estável"
    return {"recente": r_ag, "antiga": a_ag, "delta_wr": round(delta, 1), "direcao": direcao}


def _campeoes(rows) -> list[dict]:
    """Campeões em ascensão/queda: WR da metade recente vs a antiga."""
    por_champ = defaultdict(list)
    for r in rows:
        por_champ[r["campeao"]].append(r)
    movers = []
    for champ, lst in por_champ.items():
        if len(lst) < MIN_CAMPEAO:
            continue
        meio = len(lst) // 2
        antiga, recente = lst[:meio], lst[meio:]
        wr_a = _wr(sum(1 for r in antiga if r["win"]), len(antiga))
        wr_r = _wr(sum(1 for r in recente if r["win"]), len(recente))
        delta = (wr_r or 0) - (wr_a or 0)
        if abs(delta) >= GAP_NOTAVEL:
            movers.append({"campeao": champ, "jogos": len(lst), "wr_recente": wr_r,
                           "wr_antiga": wr_a, "delta": round(delta, 1),
                           "direcao": "↑" if delta > 0 else "↓"})
    movers.sort(key=lambda m: -abs(m["delta"]))
    return movers


def _matchups(conn, grupo_id: int, jogador_id: int, queues: set[int]) -> dict:
    """WR e ouro@10 médio contra o oponente DIRETO (mesma role, time inimigo)."""
    qs = ",".join("?" for _ in queues)
    rows = conn.execute(
        f"SELECT opp.campeao AS vs, me.win AS win, me.lanediff_10 AS ld "
        f"FROM participacoes me "
        f"JOIN participacoes opp ON opp.partida_id = me.partida_id "
        f"  AND opp.team_id <> me.team_id AND opp.role = me.role "
        f"JOIN partidas pt ON pt.id = me.partida_id "
        f"WHERE me.jogador_id=? AND me.role IS NOT NULL "
        f"AND pt.grupo_id=? AND pt.queue_id IN ({qs})",
        (jogador_id, grupo_id, *queues)).fetchall()

    agg: dict[str, dict] = defaultdict(lambda: {"jogos": 0, "vit": 0, "ld": [], })
    for r in rows:
        a = agg[r["vs"]]
        a["jogos"] += 1
        a["vit"] += int(bool(r["win"]))
        if r["ld"] is not None:
            a["ld"].append(r["ld"])
    out = []
    for champ, a in agg.items():
        if a["jogos"] < MIN_MATCHUP:
            continue
        ld_med = round(sum(a["ld"]) / len(a["ld"])) if a["ld"] else None
        out.append({"vs": champ, "jogos": a["jogos"], "wr": _wr(a["vit"], a["jogos"]),
                    "lanediff": ld_med})
    piores = sorted(out, key=lambda m: (m["wr"], -m["jogos"]))[:3]
    melhores = sorted(out, key=lambda m: (-m["wr"], -m["jogos"]))[:3]
    return {"piores": piores, "melhores": melhores}


def _padroes(rows) -> list[str]:
    """Padrões condicionais notáveis: lado do mapa, fila, role."""
    n = len(rows)
    wr_geral = _wr(sum(1 for r in rows if r["win"]), n) or 0
    frases = []

    def split(keyfn, rotulos):
        buckets = defaultdict(lambda: [0, 0])
        for r in rows:
            k = keyfn(r)
            if k is None:
                continue
            buckets[k][0] += int(bool(r["win"]))
            buckets[k][1] += 1
        achados = []
        for k, (v, g) in buckets.items():
            if g >= max(5, n // 10):
                achados.append((rotulos.get(k, str(k)), _wr(v, g), g))
        return achados

    # lado azul (100) vs vermelho (200)
    lados = split(lambda r: r["team_id"], {100: "lado azul", 200: "lado vermelho"})
    if len(lados) == 2:
        (ra, wa, ga), (rb, wb, gb) = sorted(lados, key=lambda x: -(x[1] or 0))
        if (wa or 0) - (wb or 0) >= GAP_NOTAVEL:
            frases.append(f"Melhor de {ra} ({wa}% em {ga}) que de {rb} ({wb}% em {gb})")

    # solo/duo vs flex
    filas = split(lambda r: r["queue_id"], {420: "SoloQ", 440: "Flex"})
    if len(filas) == 2:
        (ra, wa, ga), (rb, wb, gb) = sorted(filas, key=lambda x: -(x[1] or 0))
        if (wa or 0) - (wb or 0) >= GAP_NOTAVEL:
            frases.append(f"Rende mais em {ra} ({wa}% em {ga}) que em {rb} ({wb}% em {gb})")

    # por role (quando joga mais de uma)
    roles = split(lambda r: r["role"], {"TOP": "TOP", "JUNGLE": "JG", "MIDDLE": "MID",
                                        "BOTTOM": "ADC", "UTILITY": "SUP"})
    if len(roles) >= 2:
        melhor = max(roles, key=lambda x: x[1] or 0)
        pior = min(roles, key=lambda x: x[1] or 0)
        if (melhor[1] or 0) - (pior[1] or 0) >= GAP_NOTAVEL:
            frases.append(f"Vai melhor de {melhor[0]} ({melhor[1]}% em {melhor[2]}) "
                          f"que de {pior[0]} ({pior[1]}% em {pior[2]})")
    return frases


def perfil_vivo(conn, grupo_id: int, jogador_id: int,
                queues: set[int] = records.RANKED) -> dict:
    """O perfil vivo completo. {} se não há jogos ranqueados suficientes."""
    rows = _rows(conn, grupo_id, jogador_id, queues)
    if not rows:
        return {}
    return {
        "jogos": len(rows),
        "forma": _forma(conn, rows),
        "campeoes": _campeoes(rows),
        "matchups": _matchups(conn, grupo_id, jogador_id, queues),
        "padroes": _padroes(rows),
    }


# ----------------------------------------------------------------------
# Saídas: bloco do /perfil (humano) e resumo curto (contexto da LLM)
# ----------------------------------------------------------------------
def formatar(pv: dict) -> str:
    """Bloco '📈 Tendências' pra anexar no /perfil. '' se nada relevante."""
    if not pv or not pv.get("jogos"):
        return ""
    L = [f"\n📈 **Tendências** (ranqueada · {pv['jogos']} jogos)"]
    f = pv.get("forma")
    if f:
        seta = {"subindo": "📈", "caindo": "📉", "estável": "➡️"}[f["direcao"]]
        r, a = f["recente"], f["antiga"]
        L.append(f"{seta} Forma: **{f['direcao']}** — WR {r['wr']}% (últimos {r['jogos']}) "
                 f"vs {a['wr']}% (antes); KDA {r['kda']} vs {a['kda']}")
    movers = pv.get("campeoes") or []
    if movers:
        txt = ", ".join(f"{m['direcao']} {m['campeao']} ({m['wr_antiga']}→{m['wr_recente']}%, {m['jogos']}j)"
                        for m in movers[:3])
        L.append(f"🎮 Evolução por campeão: {txt}")
    mu = pv.get("matchups") or {}
    if mu.get("piores"):
        txt = ", ".join(f"{m['vs']} ({m['wr']}% em {m['jogos']}"
                        + (f", ouro@10 {m['lanediff']:+d}" if m["lanediff"] is not None else "") + ")"
                        for m in mu["piores"])
        L.append(f"😤 Sofre contra: {txt}")
    if mu.get("melhores"):
        txt = ", ".join(f"{m['vs']} ({m['wr']}% em {m['jogos']})" for m in mu["melhores"])
        L.append(f"😎 Domina: {txt}")
    for frase in (pv.get("padroes") or []):
        L.append(f"🔎 {frase}")
    return "\n".join(L) if len(L) > 1 else ""


def resumo_curto(pv: dict) -> str:
    """Resumo compacto pro prompt da LLM (1-3 frases). '' se nada relevante."""
    if not pv or not pv.get("jogos"):
        return ""
    partes = []
    f = pv.get("forma")
    if f and f["direcao"] != "estável":
        partes.append(f"forma {f['direcao']} (WR {f['recente']['wr']}% nos últimos "
                       f"{f['recente']['jogos']} vs {f['antiga']['wr']}% antes)")
    movers = pv.get("campeoes") or []
    if movers:
        m = movers[0]
        verbo = "aprendendo" if m["direcao"] == "↑" else "desandando em"
        partes.append(f"{verbo} {m['campeao']} ({m['wr_antiga']}→{m['wr_recente']}%)")
    piores = (pv.get("matchups") or {}).get("piores") or []
    if piores and piores[0]["wr"] is not None and piores[0]["wr"] < 45:
        m = piores[0]
        partes.append(f"sofre contra {m['vs']} ({m['wr']}% em {m['jogos']})")
    if pv.get("padroes"):
        partes.append(pv["padroes"][0].lower())
    return "; ".join(partes)

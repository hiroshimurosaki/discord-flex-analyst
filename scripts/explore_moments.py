"""Explora os momentos-chave das partidas já no banco/cache.

Lê o match + timeline do cache (sem tocar na API) e narra, por partida:
swing de ouro decisivo, teamfight que decidiu, pick-offs (melhor palpite),
objetivos e multikills — tudo determinístico.

Uso:  python -m scripts.explore_moments
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from bot_lol import config, moments
from bot_lol.db import database as db


def mmss(t: float) -> str:
    return f"{int(t)//60}:{int(t)%60:02d}"


def nick_or_champ(pid: int, pm: dict, puuid_nick: dict) -> str:
    inf = pm.get(pid, {})
    nick = puuid_nick.get(inf.get("puuid"))
    return f"{nick} ({inf.get('nome')})" if nick else inf.get("nome", "?")


def load(mid: str):
    m = json.loads((config.CACHE_DIR / f"{mid}.json").read_text(encoding="utf-8"))
    tl = json.loads((config.CACHE_DIR / f"{mid}_timeline.json").read_text(encoding="utf-8"))
    return m, tl


def main() -> None:
    conn = db.get_connection()
    puuid_nick = {r["puuid"]: r["nick_display"]
                  for r in conn.execute("SELECT puuid, nick_display FROM jogadores")}
    partidas = conn.execute(
        "SELECT match_id, vencedor_team, duracao_seg FROM partidas "
        "WHERE queue_id=440 ORDER BY inicio_ts DESC LIMIT 3").fetchall()

    for row in partidas:
        mid = row["match_id"]
        m, tl = load(mid)
        pm = moments.pid_map(m)
        venc = row["vencedor_team"]

        print("\n" + "=" * 66)
        print(f" {mid}  ({row['duracao_seg']//60}min)  — venceu time {venc}")
        print("=" * 66)

        # --- Swing de ouro ---
        series = moments.team_gold_series(m, tl)
        swing = moments.gold_swings(series, top=1)[0]
        max_lead = max(series, key=lambda s: abs(s["diff"]))
        lider = 100 if swing["delta"] > 0 else 200
        print(f"\n[Ouro] Maior lead no jogo: time {100 if max_lead['diff']>0 else 200} "
              f"+{abs(max_lead['diff'])} ouro aos {max_lead['minuto']}min.")
        print(f"[Swing decisivo] Entre {swing['de_min']}-{swing['ate_min']}min a "
              f"diferença virou {swing['delta']:+d} de ouro a favor do time {lider} "
              f"(de {swing['diff_antes']:+d} para {swing['diff_depois']:+d}).")
        if lider != venc:
            print("    ⚠ VIRADA: o maior swing favoreceu o time que PERDEU o jogo "
                  "— ouro não conta a história toda; foi jogo de comeback.")

        # --- Teamfight decisiva (a que cai dentro do swing) ---
        kills = moments.parse_kills(m, tl)
        fights = moments.teamfights(kills)
        decisiva = None
        for f in fights:
            if swing["de_min"] * 60 <= f["ini"] <= swing["ate_min"] * 60 + 60:
                decisiva = f
                break
        if not decisiva and fights:
            decisiva = max(fights, key=lambda f: (abs(f["saldo_100"]), f["valor_ouro"]))
        if decisiva:
            ganhou = 100 if decisiva["saldo_100"] > 0 else 200
            print(f"\n[Teamfight decisiva] {mmss(decisiva['ini'])}-{mmss(decisiva['fim'])}: "
                  f"{decisiva['n_kills']} abates, time {ganhou} ganhou a briga "
                  f"({decisiva['mortes_por_time']}), {decisiva['valor_ouro']} de ouro em bounties.")
            for k in decisiva["kills"]:
                print(f"    {mmss(k['t'])}  {nick_or_champ(k['killer'], pm, puuid_nick)} "
                      f"matou {nick_or_champ(k['victim'], pm, puuid_nick)}")

        # --- Pick-offs (melhor palpite) ---
        picks = moments.detect_pickoffs(m, tl, kills)
        print(f"\n[Pick-offs detectados] {len(picks)} (heurística — melhor palpite):")
        for p in picks:
            print(f"    {mmss(p['t'])}  {nick_or_champ(p['victim'], pm, puuid_nick)} "
                  f"pego sozinho no {p['regiao']} ({p['n_atacantes']} inimigos, "
                  f"aliado mais próximo a {p['dist_aliado']} de distância)")

        # --- Objetivos ---
        print("\n[Objetivos]:")
        for o in moments.objectives(m, tl):
            print(f"    {mmss(o['t'])}  {o['tipo']} — time {o['time']}")

        # --- Multikills ---
        mks = moments.multikills(m, tl)
        if mks:
            print("\n[Multikills]:")
            for mk in mks:
                rotulo = {2: "Double", 3: "Triple", 4: "Quadra", 5: "PENTA"}.get(mk["tamanho"], str(mk["tamanho"]))
                print(f"    {mmss(mk['t'])}  {nick_or_champ(mk['killer'], pm, puuid_nick)} — {rotulo} Kill")

    conn.close()


if __name__ == "__main__":
    main()

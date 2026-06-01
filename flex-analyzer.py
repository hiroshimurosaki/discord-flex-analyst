#!/usr/bin/env python3
"""
============================================================
 ANALISADOR DE FLEX — Riot API (match-v5)
============================================================
Puxa o histórico de partidas do seu grupo direto da API oficial
da Riot e calcula o que os perfis agregados (OP.GG/Porofessor)
NÃO conseguem mostrar:

  • WR de ESCALAÇÃO real (qual quinteto exato ganha mais)
  • Sinergia de trio/quarteto (não só duplas)
  • Performance "juntos vs. separados" por jogador
  • Teste do confound do Lukyy (ele puxa pra baixo, ou entra
    justo nos jogos já bagunçados?)
  • Validação do "afoga no late" (distribuição real de duração)
  • Comps de campeão que mais vencem juntas

------------------------------------------------------------
COMO USAR
------------------------------------------------------------
1. Tenha Python 3.9+ instalado.
2. Instale a dependência:
       pip install requests
3. Pegue sua chave de DEV em https://developer.riotgames.com
   (logado com sua conta Riot — a chave expira em 24h).
4. Cole a chave abaixo em API_KEY (ou defina a env var RIOT_API_KEY).
5. Rode:
       python flex_analyzer.py

O script cria uma pasta ./cache com os JSONs das partidas, então
se a chave expirar no meio, você pega outra e re-roda SEM perder
o que já baixou. No fim ele gera:
   • analise_flex.json   (dados crus organizados)
   • resumo_flex.txt      (resumo legível — COLE ISSO NO CHAT)
============================================================
"""

import os
import sys
import json
import time
import itertools
from collections import defaultdict, Counter
from pathlib import Path

try:
    import requests
except ImportError:
    print("Falta a lib 'requests'. Rode:  pip install requests")
    sys.exit(1)

# ============================================================
# CONFIGURAÇÃO  — edite aqui
# ============================================================
API_KEY = os.environ.get("RIOT_API_KEY", "COLE_SUA_CHAVE_AQUI")

# Servidor BR:
#  - PLATFORM: usado para alguns endpoints legados (não essencial aqui)
#  - REGIONAL: match-v5 e account-v1 usam o roteamento REGIONAL.
#    BR fica em "americas".
PLATFORM = "br1"
REGIONAL = "americas"

# Seu grupo — Riot IDs (gameName, tagLine)
PLAYERS = [
    ("Hiroshi",       "10102"),
    ("Qiak",          "000"),
    ("Yuya Freecss",  "BR1"),
    ("Thokyru",       "BR1"),
    ("Top Mogger",    "Dasky"),
    ("Nashorn",       "Shiro"),
    ("Lukyy",         "Luky"),
    ("Nyachi",        "mee"),
]

# Quantas partidas puxar por jogador (máx 100 por chamada de IDs;
# o script pagina se você pedir mais).
MATCHES_PER_PLAYER = 100

# Filas a considerar na análise (None = todas).
# 420 = Ranked Solo/Duo | 440 = Ranked Flex | 400/430 = Normais | 450 = ARAM
# Deixe como está p/ "análise completa" (todas), ou filtre depois.
QUEUE_FILTER = None  # ex.: {440} para só Flex

CACHE_DIR = Path("./cache")
CACHE_DIR.mkdir(exist_ok=True)

# ============================================================
# RATE LIMITING (chave de DEV: 20 req/s e 100 req/2min)
# ============================================================
class RateLimiter:
    """Respeita os dois limites da chave de dev de forma conservadora."""
    def __init__(self):
        self.times = []  # timestamps das últimas requisições

    def wait(self):
        now = time.time()
        # mantém só os últimos 120s
        self.times = [t for t in self.times if now - t < 120]
        # limite de 100 req / 120s
        if len(self.times) >= 95:
            sleep_for = 120 - (now - self.times[0]) + 1
            if sleep_for > 0:
                print(f"   [rate] aguardando {sleep_for:.0f}s (limite 2min)...")
                time.sleep(sleep_for)
        # limite de 20 req/s -> espaça ~0.06s entre chamadas
        if self.times and now - self.times[-1] < 0.06:
            time.sleep(0.06)
        self.times.append(time.time())

rl = RateLimiter()

def riot_get(url, params=None, tries=4):
    """GET com header de auth, rate limit e retry em 429/5xx."""
    headers = {"X-Riot-Token": API_KEY}
    for attempt in range(tries):
        rl.wait()
        r = requests.get(url, headers=headers, params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            retry = int(r.headers.get("Retry-After", "10"))
            print(f"   [429] rate limit estourado, dormindo {retry}s...")
            time.sleep(retry + 1)
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 401:
            print("\n[ERRO] 401 — chave inválida ou expirada. Pegue uma nova "
                  "em developer.riotgames.com e rode de novo.")
            sys.exit(1)
        if r.status_code == 404:
            return None
        print(f"   [HTTP {r.status_code}] {url} -> {r.text[:200]}")
        time.sleep(2)
    return None

# ============================================================
# ENDPOINTS
# ============================================================
def get_puuid(game_name, tag_line):
    url = f"https://{REGIONAL}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
    data = riot_get(url)
    return data.get("puuid") if data else None

def get_match_ids(puuid, count=100):
    """Pagina os IDs de partida (100 por chamada)."""
    ids = []
    start = 0
    while len(ids) < count:
        batch = min(100, count - len(ids))
        url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
        data = riot_get(url, params={"start": start, "count": batch})
        if not data:
            break
        ids.extend(data)
        if len(data) < batch:
            break
        start += batch
    return ids

def get_match(match_id):
    """Busca a partida — com cache em disco."""
    cache_file = CACHE_DIR / f"{match_id}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    data = riot_get(url)
    if data:
        cache_file.write_text(json.dumps(data))
    return data

# Inclui dados minuto-a-minuto (ouro@10/@15, lane diff). Dobra as chamadas.
INCLUDE_TIMELINE = True

def get_timeline(match_id):
    """Busca a timeline (minuto-a-minuto) — com cache em disco separado."""
    cache_file = CACHE_DIR / f"{match_id}_timeline.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    url = f"https://{REGIONAL}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
    data = riot_get(url)
    if data:
        cache_file.write_text(json.dumps(data))
    return data

def gold_at(timeline, minute):
    """Extrai o ouro total de cada participante (1-10) no minuto pedido."""
    if not timeline:
        return {}
    frames = timeline.get("info", {}).get("frames", [])
    if minute >= len(frames):
        if not frames:
            return {}
        minute = len(frames) - 1
    pf = frames[minute].get("participantFrames", {})
    return {int(pid): f.get("totalGold", 0) for pid, f in pf.items()}

def percentiles(values_by_pid):
    """Recebe {pid: valor} e devolve {pid: percentil 0-100} dentro da partida.
    Percentil = % de jogadores que esse superou."""
    items = list(values_by_pid.items())
    n = len(items)
    if n <= 1:
        return {pid: 100.0 for pid, _ in items}
    out = {}
    for pid, v in items:
        worse = sum(1 for _, v2 in items if v2 < v)
        out[pid] = round(100.0 * worse / (n - 1), 1)
    return out

# ============================================================
# COLETA
# ============================================================
def collect():
    if API_KEY == "COLE_SUA_CHAVE_AQUI":
        print("[ERRO] Você não colou a chave. Edite API_KEY no topo do arquivo,\n"
              "       ou rode:  RIOT_API_KEY=sua_chave python flex_analyzer.py")
        sys.exit(1)

    print("=" * 60)
    print(" ETAPA 1/3 — Resolvendo PUUIDs")
    print("=" * 60)
    puuids = {}        # puuid -> nick
    nick_puuid = {}    # nick  -> puuid
    for name, tag in PLAYERS:
        puuid = get_puuid(name, tag)
        if puuid:
            puuids[puuid] = name
            nick_puuid[name] = puuid
            print(f"  ✓ {name}#{tag}")
        else:
            print(f"  ✗ {name}#{tag}  (não encontrado — confira o Riot ID)")
    our_puuids = set(puuids.keys())

    print("\n" + "=" * 60)
    print(" ETAPA 2/3 — Baixando partidas (usa cache; pode re-rodar)")
    print("=" * 60)
    all_match_ids = set()
    for name, tag in PLAYERS:
        puuid = nick_puuid.get(name)
        if not puuid:
            continue
        ids = get_match_ids(puuid, MATCHES_PER_PLAYER)
        all_match_ids.update(ids)
        print(f"  {name}: {len(ids)} partidas")
    print(f"\n  Total de partidas únicas a processar: {len(all_match_ids)}")

    matches = []
    for i, mid in enumerate(sorted(all_match_ids), 1):
        m = get_match(mid)
        if m:
            matches.append(m)
        if i % 25 == 0:
            print(f"   ...{i}/{len(all_match_ids)} processadas")

    # Timelines — só para partidas EM GRUPO (>=2 nossos no mesmo time),
    # pra não dobrar chamadas em jogos solo que não entram na análise de grupo.
    timelines = {}
    if INCLUDE_TIMELINE:
        group_matches = []
        for m in matches:
            parts = m.get("info", {}).get("participants", [])
            mine = [p for p in parts if p.get("puuid") in our_puuids]
            by_team = defaultdict(int)
            for p in mine:
                by_team[p.get("teamId")] += 1
            if any(c >= 2 for c in by_team.values()):
                group_matches.append(m.get("metadata", {}).get("matchId"))
        print(f"\n  Baixando timelines de {len(group_matches)} partidas em grupo "
              f"(dobra as chamadas — pode demorar)...")
        for i, mid in enumerate(group_matches, 1):
            if not mid:
                continue
            t = get_timeline(mid)
            if t:
                timelines[mid] = t
            if i % 25 == 0:
                print(f"   ...{i}/{len(group_matches)} timelines")

    return puuids, our_puuids, matches, timelines

# ============================================================
# ANÁLISE
# ============================================================
def analyze(puuids, our_puuids, matches, timelines=None):
    nick = lambda p: puuids.get(p, "?")
    timelines = timelines or {}

    # estruturas
    solo_games   = defaultdict(int)   # nick -> nº partidas (qualquer)
    solo_wins    = defaultdict(int)
    pair_games   = defaultdict(int)   # frozenset(a,b) -> jogos juntos
    pair_wins    = defaultdict(int)
    lineup_games = defaultdict(int)   # frozenset(5) -> jogos
    lineup_wins  = defaultdict(int)
    champ_games  = defaultdict(int)   # (nick,champ) -> jogos
    champ_wins   = defaultdict(int)
    durations    = []                 # (won, minutes) p/ "afoga no late"
    # confound do Lukyy: WR DOS OUTROS nos jogos COM e SEM ele
    others_with_lukyy = [0, 0]        # [wins, games] dos colegas qd Lukyy joga
    others_without    = [0, 0]

    # CAMADA NOVA — ranking interno por partida.
    # Para cada métrica, guardamos a soma de percentis e a contagem, em
    # três "visões": vs10 (todos), vs4 (só colegas), vsrole (mesma role).
    METRICS = ["dano", "dano_recebido", "ouro", "visao", "kp", "farm",
               "ouro10", "ouro15", "lanediff10"]
    # estrutura: pcts[visao][metrica][nick] = [soma_percentil, n]
    pcts = {v: {mt: defaultdict(lambda: [0.0, 0]) for mt in METRICS}
            for v in ("vs10", "vs4", "vsrole")}
    # "melhor da partida" (top-1 entre os colegas) por métrica
    best_in_team = {mt: defaultdict(int) for mt in METRICS}  # nick -> vezes top1
    team_appear  = defaultdict(int)  # nick -> partidas em grupo (>=2 nossos)
    role_of      = defaultdict(Counter)  # nick -> contagem de roles detectadas

    considered = 0
    for m in matches:
        info = m.get("info", {})
        if QUEUE_FILTER and info.get("queueId") not in QUEUE_FILTER:
            continue
        parts = info.get("participants", [])
        # quem do nosso grupo está nessa partida (e em qual time)
        mine = [p for p in parts if p.get("puuid") in our_puuids]
        if not mine:
            continue
        considered += 1
        dur_min = info.get("gameDuration", 0) / 60.0

        # por jogador nosso
        for p in mine:
            n = nick(p["puuid"])
            won = bool(p.get("win"))
            solo_games[n] += 1
            solo_wins[n]  += int(won)
            champ = p.get("championName", "?")
            champ_games[(n, champ)] += 1
            champ_wins[(n, champ)]  += int(won)
            durations.append((won, dur_min))

        # agrupa nossos jogadores por time (só conta sinergia entre
        # quem está NO MESMO time)
        by_team = defaultdict(list)
        for p in mine:
            by_team[p.get("teamId")].append(p)

        lukyy_in_match = any(nick(p["puuid"]) == "Lukyy" for p in mine)

        # ---------- CAMADA NOVA: ranking interno por partida ----------
        def metric_values(participants):
            vals = {mt: {} for mt in METRICS}
            team_kills = defaultdict(int)
            for q in participants:
                team_kills[q.get("teamId")] += q.get("kills", 0)
            for q in participants:
                pid = q.get("participantId")
                vals["dano"][pid]          = q.get("totalDamageDealtToChampions", 0)
                vals["dano_recebido"][pid] = q.get("totalDamageTaken", 0)
                vals["ouro"][pid]          = q.get("goldEarned", 0)
                vals["visao"][pid]         = q.get("visionScore", 0)
                vals["farm"][pid]          = q.get("totalMinionsKilled", 0) + q.get("neutralMinionsKilled", 0)
                tk = team_kills.get(q.get("teamId"), 0)
                kp = (q.get("kills", 0) + q.get("assists", 0)) / tk if tk else 0
                vals["kp"][pid] = round(kp, 3)
            return vals

        base_vals = metric_values(parts)

        tl = timelines.get(m.get("metadata", {}).get("matchId"))
        if tl:
            g10 = gold_at(tl, 10)
            g15 = gold_at(tl, 15)
            for q in parts:
                pid = q.get("participantId")
                if pid in g10: base_vals["ouro10"][pid] = g10[pid]
                if pid in g15: base_vals["ouro15"][pid] = g15[pid]
            by_pos = defaultdict(dict)
            for q in parts:
                by_pos[q.get("teamPosition") or "?"][q.get("teamId")] = q.get("participantId")
            teams_l = list({q.get("teamId") for q in parts})
            if len(teams_l) == 2 and g10:
                t0, t1 = teams_l
                for position, sides in by_pos.items():
                    if position == "?" or t0 not in sides or t1 not in sides:
                        continue
                    a, b = sides[t0], sides[t1]
                    if a in g10 and b in g10:
                        base_vals["lanediff10"][a] = g10[a] - g10[b]
                        base_vals["lanediff10"][b] = g10[b] - g10[a]

        for p in mine:
            n = nick(p["puuid"])
            posn = p.get("teamPosition") or p.get("individualPosition") or "?"
            if posn and posn != "?":
                role_of[n][posn] += 1

        our_pids    = {p.get("participantId") for p in mine}
        pid_to_nick = {p.get("participantId"): nick(p["puuid"]) for p in mine}
        team_of_pid = {p.get("participantId"): p.get("teamId") for p in parts}
        pos_of_pid  = {p.get("participantId"): (p.get("teamPosition") or "?") for p in parts}

        for mt in METRICS:
            vmap = base_vals.get(mt, {})
            if not vmap:
                continue
            p10 = percentiles(vmap)
            for pid in list(vmap.keys()):
                if pid not in our_pids:
                    continue
                n = pid_to_nick[pid]
                pcts["vs10"][mt][n][0] += p10.get(pid, 0); pcts["vs10"][mt][n][1] += 1
                same_team_ours = {q: vmap[q] for q in vmap
                                  if q in our_pids and team_of_pid.get(q) == team_of_pid.get(pid)}
                if len(same_team_ours) >= 2:
                    p4 = percentiles(same_team_ours)
                    pcts["vs4"][mt][n][0] += p4.get(pid, 0); pcts["vs4"][mt][n][1] += 1
                same_role = {q: vmap[q] for q in vmap
                             if pos_of_pid.get(q) == pos_of_pid.get(pid) and pos_of_pid.get(pid) != "?"}
                if len(same_role) >= 2:
                    pr = percentiles(same_role)
                    pcts["vsrole"][mt][n][0] += pr.get(pid, 0); pcts["vsrole"][mt][n][1] += 1
            for team_id2 in {team_of_pid.get(pid) for pid in our_pids}:
                ours_here = {pid: vmap[pid] for pid in our_pids
                             if team_of_pid.get(pid) == team_id2 and pid in vmap}
                if len(ours_here) >= 2:
                    top_pid = max(ours_here, key=ours_here.get)
                    best_in_team[mt][pid_to_nick[top_pid]] += 1

        for team_id2, group in by_team.items():
            if len(group) >= 2:
                for p in group:
                    team_appear[nick(p["puuid"])] += 1
        # ---------- fim da camada nova ----------

        for team_id, group in by_team.items():
            if len(group) >= 1:
                won = bool(group[0].get("win"))
            # duplas
            for a, b in itertools.combinations(group, 2):
                key = frozenset((nick(a["puuid"]), nick(b["puuid"])))
                pair_games[key] += 1
                pair_wins[key]  += int(bool(a.get("win")))
            # escalação de 5 (quinteto exato)
            if len(group) == 5:
                key = frozenset(nick(p["puuid"]) for p in group)
                lineup_games[key] += 1
                lineup_wins[key]  += int(bool(group[0].get("win")))

            # confound do Lukyy: olha o WR dos COLEGAS (sem contar o Lukyy)
            for p in group:
                n = nick(p["puuid"])
                if n == "Lukyy":
                    continue
                bucket = others_with_lukyy if lukyy_in_match else others_without
                bucket[0] += int(bool(p.get("win")))
                bucket[1] += 1

    def wr(w, g):
        return round(100.0 * w / g, 1) if g else None

    # --- monta saída ---
    out = {"meta": {"partidas_consideradas": considered,
                    "jogadores": list(solo_games.keys())}}

    out["individual"] = {
        n: {"jogos": g, "vitorias": solo_wins[n], "wr": wr(solo_wins[n], g)}
        for n, g in sorted(solo_games.items(), key=lambda x: -x[1])
    }

    out["duplas"] = sorted(
        [{"dupla": sorted(list(k)), "jogos": g, "wr": wr(pair_wins[k], g)}
         for k, g in pair_games.items() if g >= 3],
        key=lambda x: (-x["jogos"], -(x["wr"] or 0))
    )

    out["escalacoes_5"] = sorted(
        [{"time": sorted(list(k)), "jogos": g, "wr": wr(lineup_wins[k], g)}
         for k, g in lineup_games.items() if g >= 2],
        key=lambda x: (-(x["wr"] or 0), -x["jogos"])
    )

    # campeões por jogador (top 6)
    champs_by_player = defaultdict(list)
    for (n, c), g in champ_games.items():
        champs_by_player[n].append({"campeao": c, "jogos": g, "wr": wr(champ_wins[(n, c)], g)})
    out["campeoes"] = {
        n: sorted(lst, key=lambda x: -x["jogos"])[:6]
        for n, lst in champs_by_player.items()
    }

    # "afoga no late": WR por faixa de duração
    buckets = {"<20min": [0, 0], "20-25": [0, 0], "25-30": [0, 0],
               "30-35": [0, 0], "35+": [0, 0]}
    for won, mn in durations:
        if   mn < 20: b = "<20min"
        elif mn < 25: b = "20-25"
        elif mn < 30: b = "25-30"
        elif mn < 35: b = "30-35"
        else:         b = "35+"
        buckets[b][0] += int(won); buckets[b][1] += 1
    out["duracao_wr"] = {k: {"jogos": v[1], "wr": wr(v[0], v[1])} for k, v in buckets.items()}

    # --- CAMADA NOVA: desempenho relativo por partida (percentis) ---
    def avg(pair):
        return round(pair[0] / pair[1], 1) if pair[1] else None
    desempenho = {}
    for view in ("vs10", "vs4", "vsrole"):
        desempenho[view] = {}
        for mt in METRICS:
            desempenho[view][mt] = {
                n: {"percentil_medio": avg(pair), "jogos": pair[1]}
                for n, pair in pcts[view][mt].items() if pair[1] > 0
            }
    out["desempenho_percentil"] = desempenho
    out["melhor_do_time"] = {mt: dict(best_in_team[mt]) for mt in METRICS}
    out["aparicoes_grupo"] = dict(team_appear)
    out["roles_detectadas"] = {n: dict(c) for n, c in role_of.items()}

    # confound do Lukyy
    out["teste_lukyy"] = {
        "colegas_COM_lukyy":  {"jogos": others_with_lukyy[1], "wr": wr(others_with_lukyy[0], others_with_lukyy[1])},
        "colegas_SEM_lukyy":  {"jogos": others_without[1],    "wr": wr(others_without[0], others_without[1])},
        "leitura": ("Se o WR dos COLEGAS cai junto com o Lukyy, o efeito é real/contextual; "
                    "se os colegas mantêm WR parecido, a queda é mais específica do desempenho dele."),
    }

    return out

# ============================================================
# RELATÓRIO LEGÍVEL
# ============================================================
def write_report(out):
    L = []
    L.append("=" * 56)
    L.append(" RESUMO FLEX — DADOS DA API DA RIOT (match-v5)")
    L.append("=" * 56)
    L.append(f"Partidas consideradas: {out['meta']['partidas_consideradas']}\n")

    L.append("--- WIN RATE INDIVIDUAL (todas as filas puxadas) ---")
    for n, d in out["individual"].items():
        L.append(f"  {n:16s} {d['wr']}%  ({d['vitorias']}/{d['jogos']})")

    L.append("\n--- MELHORES ESCALAÇÕES DE 5 (>=2 jogos) ---")
    if out["escalacoes_5"]:
        for e in out["escalacoes_5"][:8]:
            L.append(f"  {e['wr']}%  ({e['jogos']}j)  {', '.join(e['time'])}")
    else:
        L.append("  (nenhum quinteto com 2+ jogos — talvez joguem menos de 5 juntos)")

    L.append("\n--- DUPLAS (>=3 jogos, por volume) ---")
    for d in out["duplas"][:15]:
        L.append(f"  {d['wr']}%  ({d['jogos']}j)  {' + '.join(d['dupla'])}")

    L.append("\n--- 'AFOGA NO LATE?' — WR POR DURAÇÃO ---")
    for faixa, d in out["duracao_wr"].items():
        if d["jogos"]:
            L.append(f"  {faixa:8s} {d['wr']}%  ({d['jogos']}j)")

    L.append("\n--- TESTE DO LUKYY (é ele ou o contexto?) ---")
    tl = out["teste_lukyy"]
    L.append(f"  Colegas COM Lukyy: {tl['colegas_COM_lukyy']['wr']}% ({tl['colegas_COM_lukyy']['jogos']}j)")
    L.append(f"  Colegas SEM Lukyy: {tl['colegas_SEM_lukyy']['wr']}% ({tl['colegas_SEM_lukyy']['jogos']}j)")

    # CAMADA NOVA no relatório
    METRIC_LABELS = {"dano":"Dano", "dano_recebido":"Dano recebido", "ouro":"Ouro",
                     "visao":"Visão", "kp":"Particip. abate", "farm":"Farm",
                     "ouro10":"Ouro@10", "ouro15":"Ouro@15", "lanediff10":"Lane diff@10"}
    for view, vlabel in [("vs10","VS OS 10 DA PARTIDA"),
                         ("vs4","VS OS COLEGAS DE TIME"),
                         ("vsrole","VS MESMA ROLE")]:
        L.append(f"\n--- DESEMPENHO (percentil médio 0-100) · {vlabel} ---")
        dv = out["desempenho_percentil"][view]
        # tabela: jogadores nas linhas, métricas nas colunas principais
        metrics_show = ["dano","visao","ouro","kp","farm"]
        if view != "vs4":
            metrics_show += ["ouro10","ouro15","lanediff10"]
        header = "  " + f"{'Jogador':14s}" + "".join(f"{METRIC_LABELS[m][:8]:>10s}" for m in metrics_show)
        L.append(header)
        # ordena por dano percentil
        nicks = sorted({n for m in metrics_show for n in dv.get(m, {})},
                       key=lambda n: -(dv.get("dano",{}).get(n,{}).get("percentil_medio") or 0))
        for n in nicks:
            row = f"  {n:14s}"
            for m in metrics_show:
                cell = dv.get(m, {}).get(n)
                row += f"{(str(cell['percentil_medio']) if cell else '-'):>10s}"
            L.append(row)

    L.append("\n--- 'MELHOR DO TIME' — nº de partidas como top-1 entre os nossos ---")
    for mt in ["dano","visao","ouro","kp","farm"]:
        bt = out["melhor_do_time"].get(mt, {})
        if bt:
            ranking = sorted(bt.items(), key=lambda x: -x[1])
            txt = ", ".join(f"{n} ({c}x)" for n, c in ranking[:4])
            L.append(f"  {METRIC_LABELS[mt]:16s}: {txt}")

    L.append("\n--- ROLES DETECTADAS (pela API, por jogador) ---")
    for n, roles in out["roles_detectadas"].items():
        rs = ", ".join(f"{r} {c}x" for r, c in sorted(roles.items(), key=lambda x: -x[1]))
        L.append(f"  {n:14s}: {rs}")

    L.append("\n--- CAMPEÕES POR JOGADOR (top 6, todas as filas) ---")
    for n, lst in out["campeoes"].items():
        cs = ", ".join(f"{c['campeao']} {c['wr']}%/{c['jogos']}j" for c in lst)
        L.append(f"  {n}: {cs}")

    L.append("\n" + "=" * 56)
    L.append(" Cole este resumo no chat com o Claude para gerar")
    L.append(" os slides de análise PROFUNDA.")
    L.append("=" * 56)

    report = "\n".join(L)
    Path("resumo_flex.txt").write_text(report, encoding="utf-8")
    print("\n" + report)

# ============================================================
# MAIN
# ============================================================
def main():
    puuids, our_puuids, matches, timelines = collect()
    print("\n" + "=" * 60)
    print(" ETAPA 3/3 — Analisando")
    print("=" * 60)
    out = analyze(puuids, our_puuids, matches, timelines)
    Path("analise_flex.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(out)
    print("\n✓ Arquivos gerados: analise_flex.json  e  resumo_flex.txt")

if __name__ == "__main__":
    main()
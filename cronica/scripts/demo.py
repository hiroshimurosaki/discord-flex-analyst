"""Histórico sintético — o pipeline inteiro rodando sem chave da Riot.

Gera partidas no **formato cru da Riot** e as passa pelo `ingest` de verdade,
não direto no banco. A diferença importa: assim o demo exercita o mesmo caminho
que os dados reais vão percorrer, e um bug de parsing aparece aqui em vez de
aparecer depois de três horas de coleta.

A história sintética tem estrutura de propósito — hiato, troca de elenco,
subida, queda — para você conferir se a detecção de eras acha o que está lá.
Está tudo declarado em `ROTEIRO_SINTETICO`: se o `scripts.construir` devolver
eras muito diferentes disso, é a detecção que está errada, não a sua memória.

    python -m scripts.demo              # ~260 partidas em 5 eras
    python -m scripts.demo --limpar     # zera o banco antes
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica import config                     # noqa: E402
from cronica.fatos import db, ingest           # noqa: E402

SEMENTE = 20260903

# Nomes FICTÍCIOS de propósito. O `canone/demo.yaml` precisa de personalidade
# preenchida para o dossiê ter o que cruzar, e personalidade inventada não deve
# andar colada no nome de ninguém de verdade.
ELENCO = {   # id -> (nome, role, pool de campeões)
    "motor":   ("Motor", "JUNGLE", ["Viego", "Lee Sin", "Nidalee"]),
    "atirador": ("Atirador", "BOTTOM", ["Jinx", "Kai'Sa", "Caitlyn"]),
    "ancora":  ("Âncora", "UTILITY", ["Thresh", "Nautilus", "Lulu"]),
    "teimoso": ("Teimoso", "TOP", ["Garen", "Darius", "Aatrox"]),
    "calado":  ("Calado", "MIDDLE", ["Ahri", "Syndra", "Viktor"]),
    "visita":  ("Visita", "BOTTOM", ["Ezreal", "Jhin"]),
    "reserva": ("Reserva", "JUNGLE", ["Hecarim", "Warwick"]),
    "primo":   ("Primo", "TOP", ["Sett", "Camille"]),
}
TITULARES = ["motor", "atirador", "ancora", "teimoso", "calado"]
INIMIGOS = {
    "TOP": ["Renekton", "Jax", "Ornn", "Gnar"],
    "JUNGLE": ["Vi", "Kha'Zix", "Sejuani"],
    "MIDDLE": ["Zed", "Orianna", "Sylas"],
    "BOTTOM": ["Lucian", "Xayah", "Draven"],
    "UTILITY": ["Leona", "Karma", "Rakan"],
}

# (nome, dias de hiato antes, nº de partidas, winrate alvo, elenco, patch)
ROTEIRO_SINTETICO = [
    ("o começo",          0,  42, 0.36, TITULARES, "14.20"),
    ("a volta",          48,  50, 0.54, TITULARES, "15.02"),
    ("sem o Motor",       6,  44, 0.41,
     ["reserva", "atirador", "ancora", "teimoso", "calado"], "15.08"),
    ("a subida",         74,  58, 0.64, TITULARES, "15.14"),
    ("o platô",           4,  46, 0.59, TITULARES, "15.20"),
]


def _participante(puuid, time_id, role, campeao, venceu, rng, forca):
    """`forca` (0..1) modula os números para o dossiê ter o que medir."""
    base_k = rng.randint(2, 9) + int(forca * 6) + (2 if venceu else 0)
    mortes = max(1, rng.randint(2, 9) - int(forca * 3) + (0 if venceu else 2))
    return {
        "puuid": puuid, "teamId": time_id, "teamPosition": role,
        "championName": campeao, "win": venceu,
        "kills": base_k, "deaths": mortes,
        "assists": rng.randint(3, 16) + int(forca * 4),
        "totalDamageDealtToChampions": int(rng.gauss(20000, 4000) * (0.7 + forca)),
        "totalDamageTaken": int(rng.gauss(24000, 5000)),
        "goldEarned": int(rng.gauss(12000, 1800) * (0.85 + forca * 0.4)),
        "visionScore": int(rng.gauss(28, 9) * (1.8 if role == "UTILITY" else 1)),
        "totalMinionsKilled": 0 if role == "UTILITY" else int(rng.gauss(190, 45)),
        "neutralMinionsKilled": int(rng.gauss(90, 30)) if role == "JUNGLE" else 0,
        "challenges": {"kda": round((base_k + 8) / mortes, 2)},
    }


def _timeline(match, venceu, rng, deficit_alvo=0):
    """Timeline mínima: ouro por minuto dos 10, com um déficit plantado quando
    a partida é para virar o seletor `virada`."""
    dur_min = max(int(match["info"]["gameDuration"] / 60), 12)
    parts = match["info"]["participants"]
    frames = []
    for minuto in range(dur_min + 1):
        pf, ev = {}, []
        for i, p in enumerate(parts, 1):
            nosso = p["teamId"] == 100
            base = 500 + minuto * rng.gauss(340, 30)
            # curva: cede ouro no começo e recupera se for virada
            if deficit_alvo and nosso:
                fase = min(minuto / max(dur_min * 0.55, 1), 1.0)
                base -= (deficit_alvo / 5) * (1 - fase) * 1.4
            if venceu == nosso:
                base += minuto * 45
            pf[str(i)] = {"totalGold": max(int(base), 500)}
        if minuto and minuto % 7 == 0:
            ev.append({"type": "ELITE_MONSTER_KILL",
                       "timestamp": minuto * 60000, "monsterType": "DRAGON",
                       "monsterSubType": "FIRE_DRAGON",
                       "killerTeamId": 100 if venceu else 200})
        frames.append({"participantFrames": pf, "events": ev,
                       "timestamp": minuto * 60000})
    return {"info": {"frames": frames}}


def gerar(rng: random.Random) -> tuple[list, dict]:
    puuids = {mid: f"PUUID_DEMO_{mid.upper():_<24}" for mid in ELENCO}
    partidas = []
    dia = datetime(2024, 9, 1, 21, 0, tzinfo=timezone.utc)
    n = 0

    for era_i, (_nome, hiato, qtd, wr, elenco, patch) in enumerate(ROTEIRO_SINTETICO):
        dia += timedelta(days=hiato)
        for j in range(qtd):
            n += 1
            dia += timedelta(days=rng.choice([0, 0, 1, 1, 2, 3]),
                             hours=rng.randint(0, 3))
            venceu = rng.random() < wr
            dur = int(rng.gauss(1900, 380))
            dur = max(900, min(dur, 3000))

            parts = []
            for k, mid in enumerate(elenco):
                nome, role, pool = ELENCO[mid]
                # pool estável com assinatura -> gera pares de 'espelho'
                champ = pool[(j + k) % len(pool)] if j % 3 else pool[0]
                # Teimoso melhora ao longo da história: o arco plantado no demo
                forca = 0.5
                if mid == "teimoso":
                    forca = 0.12 + 0.16 * era_i
                elif mid == "motor":
                    forca = 0.85
                parts.append(_participante(puuids[mid], 100, role, champ,
                                           venceu, rng, forca))
            for role in ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]:
                parts.append(_participante(
                    f"INIMIGO_{n}_{role}", 200, role,
                    INIMIGOS[role][(j + era_i) % len(INIMIGOS[role])],
                    not venceu, rng, 0.5))

            partidas.append({
                "metadata": {"matchId": f"BR1_DEMO{n:05d}"},
                "info": {
                    "queueId": config.FILA_FLEX,
                    "gameStartTimestamp": int(dia.timestamp() * 1000),
                    "gameDuration": dur, "gameVersion": f"{patch}.700.1234",
                    "participants": parts,
                    "teams": [{"teamId": 100, "win": venceu},
                              {"teamId": 200, "win": not venceu}],
                },
                "_venceu": venceu,
                # uma virada plantada por era, para o seletor ter o que achar
                "_deficit": 9000 if (venceu and j == qtd // 3) else 0,
            })

    # SoloQ: a subtrama de personagem
    for mid in ELENCO:
        nome, role, pool = ELENCO[mid]
        d = datetime(2024, 9, 5, tzinfo=timezone.utc)
        for j in range(70):
            n += 1
            d += timedelta(days=rng.choice([1, 2, 3, 5]))
            venceu = rng.random() < (0.58 if mid == "visita" else 0.48)
            parts = [_participante(puuids[mid], 100, role,
                                   pool[j % len(pool)], venceu, rng, 0.5)]
            for k in range(4):
                parts.append(_participante(f"RANDOM_{n}_{k}", 100,
                                           ["TOP", "JUNGLE", "MIDDLE", "BOTTOM",
                                            "UTILITY"][k if k < 4 else 4],
                                           "Ryze", venceu, rng, 0.5))
            for k, r in enumerate(["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"]):
                parts.append(_participante(f"INIM_{n}_{k}", 200, r,
                                           INIMIGOS[r][0], not venceu, rng, 0.5))
            partidas.append({
                "metadata": {"matchId": f"BR1_SOLO{n:05d}"},
                "info": {"queueId": config.FILA_SOLO,
                         "gameStartTimestamp": int(d.timestamp() * 1000),
                         "gameDuration": 1800, "gameVersion": "15.10.1.1",
                         "participants": parts,
                         "teams": [{"teamId": 100, "win": venceu},
                                   {"teamId": 200, "win": not venceu}]},
                "_venceu": venceu, "_deficit": 0,
            })
    return partidas, puuids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limpar", action="store_true")
    a = ap.parse_args()

    config.garantir_dirs()
    if a.limpar and config.BANCO.exists():
        config.BANCO.unlink()
        print(f"banco removido: {config.BANCO}")

    rng = random.Random(SEMENTE)
    conn = db.conectar()
    db.migrar(conn)

    partidas, puuids = gerar(rng)
    for mid, (nome, role, _pool) in ELENCO.items():
        db.upsert_membro(conn, mid, puuids[mid], f"{nome}#DEMO", nome,
                         mid in TITULARES, role)
    mapa = {v: k for k, v in puuids.items()}

    em_grupo = 0
    for m in partidas:
        venceu, deficit = m.pop("_venceu"), m.pop("_deficit")
        parsed = ingest.parse_partida(m, mapa)
        p, parts = parsed["partida"], parsed["participacoes"]
        nosso = p.pop("nosso_time", None)
        derivado = None
        if p["em_grupo"]:
            tl = _timeline(m, venceu, rng, deficit)
            ingest.enriquecer_com_timeline(parts, m, tl)
            derivado = ingest.derivar_timeline(m, tl, nosso)
            em_grupo += 1
        pid = db.inserir_partida(conn, p, parts)
        if derivado:
            db.salvar_timeline_derivada(conn, pid, derivado)
    conn.commit()

    print(f"✓ {len(partidas)} partidas geradas ({em_grupo} em grupo) "
          f"-> {config.BANCO}")
    print("\nestrutura plantada (o que a detecção deveria reencontrar):")
    for nome, hiato, qtd, wr, elenco, patch in ROTEIRO_SINTETICO:
        h = f"após {hiato}d parados" if hiato else "início"
        print(f"  {nome:<16} {qtd:>3} jogos  WR alvo {wr:.0%}  {h:<18} "
              f"patch {patch}")
    print("\npróximo passo:\n  python -m scripts.construir canone/demo.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

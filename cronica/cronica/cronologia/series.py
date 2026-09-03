"""Banco -> a série que a história segmenta.

Uma "cena" aqui é uma partida do fio principal (flex, 2+ membros no mesmo time)
já resolvida: quem estava, o que jogaram, se ganharam, quão feio ficou.
Tudo em memória, cronológico, porque a detecção de eras varre a série dezenas
de vezes e ir ao banco a cada varredura seria pagar I/O por nada.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional

from .. import config
from ..fatos import db


@dataclass
class Cena:
    """Uma partida do fio principal, já resolvida do ponto de vista do time."""
    partida_id: int
    match_id: str
    ts: int                       # ms UTC
    data: dt.date
    venceu: bool
    duracao_seg: int
    patch: Optional[str]
    elenco: frozenset[str]        # membros presentes NO NOSSO TIME
    campeoes: dict[str, str]      # membro_id -> campeão
    roles: dict[str, str]
    kda: dict[str, tuple[int, int, int]]
    ouro: dict[str, int]
    dano: dict[str, int]
    visao: dict[str, int]
    farm: dict[str, int]
    lanediff_10: dict[str, Optional[int]]
    kp: dict[str, Optional[float]]
    oponentes: dict[str, str] = field(default_factory=dict)  # role -> campeão inimigo
    # Dano dos DEZ da partida, e o índice de cada membro dentro dessa lista.
    # É o que permite o percentil-na-partida honesto: você contra os dez que
    # jogaram aquele jogo — mesmo patch, mesmo elo, mesma duração. Contra os
    # quatro companheiros só se mede quem carregou o próprio time, que é uma
    # pergunta diferente e bem menos interessante.
    dano_dos_dez: tuple[int, ...] = ()
    dano_por_membro: dict[str, int] = field(default_factory=dict)
    deficit_max: Optional[int] = None
    pico_max: Optional[int] = None
    minuto_deficit: Optional[int] = None

    @property
    def duracao_min(self) -> float:
        return round(self.duracao_seg / 60, 1)


def carregar_cenas(conn, fila: int = config.FILA_FLEX,
                   min_membros: int = 2) -> list[Cena]:
    """A série principal, cronológica."""
    partidas = db.partidas_do_grupo(conn, fila=fila, min_membros=min_membros)
    if not partidas:
        return []
    ids = [p["id"] for p in partidas]
    parts = db.participacoes_de(conn, ids)
    tls = db.timelines_derivadas(conn, ids)

    cenas: list[Cena] = []
    for p in partidas:
        linhas = parts.get(p["id"], [])
        nossos = [l for l in linhas if l["membro_id"]]
        if not nossos:
            continue
        # O time do grupo é aquele onde estão mais membros. Empate (inhouse
        # 2x2) resolve pelo menor teamId: arbitrário, mas estável — e o filtro
        # de min_membros já torna isso raríssimo.
        por_time: dict[int, list[dict]] = {}
        for l in nossos:
            por_time.setdefault(l["team_id"], []).append(l)
        nosso_time = min(por_time, key=lambda t: (-len(por_time[t]), t))
        nossos = por_time[nosso_time]

        adversarios = {l["role"]: l["campeao"] for l in linhas
                       if l["team_id"] != nosso_time and l["role"]}
        tl = tls.get(p["id"]) or {}
        cenas.append(Cena(
            partida_id=p["id"], match_id=p["match_id"], ts=p["inicio_ts"],
            data=dt.datetime.fromtimestamp(p["inicio_ts"] / 1000, dt.timezone.utc).date(),
            venceu=bool(nossos[0]["win"]),
            duracao_seg=p["duracao_seg"], patch=p["patch"],
            elenco=frozenset(l["membro_id"] for l in nossos),
            campeoes={l["membro_id"]: l["campeao"] for l in nossos},
            roles={l["membro_id"]: l["role"] for l in nossos if l["role"]},
            kda={l["membro_id"]: (l["kills"] or 0, l["deaths"] or 0, l["assists"] or 0)
                 for l in nossos},
            ouro={l["membro_id"]: l["ouro"] or 0 for l in nossos},
            dano={l["membro_id"]: l["dano"] or 0 for l in nossos},
            visao={l["membro_id"]: l["visao"] or 0 for l in nossos},
            farm={l["membro_id"]: l["farm"] or 0 for l in nossos},
            lanediff_10={l["membro_id"]: l["lanediff_10"] for l in nossos},
            kp={l["membro_id"]: l["kp"] for l in nossos},
            oponentes=adversarios,
            dano_dos_dez=tuple(sorted(l["dano"] or 0 for l in linhas)),
            dano_por_membro={l["membro_id"]: l["dano"] or 0 for l in nossos},
            deficit_max=tl.get("deficit_max"), pico_max=tl.get("pico_max"),
            minuto_deficit=tl.get("minuto_deficit"),
        ))
    cenas.sort(key=lambda c: c.ts)
    return cenas


def wr(cenas: list[Cena]) -> Optional[float]:
    return round(100 * sum(c.venceu for c in cenas) / len(cenas), 1) if cenas else None


def nucleo(cenas: list[Cena], limiar: float = 0.6) -> frozenset[str]:
    """Quem 'era o time' nesse trecho: membros presentes em >= `limiar` das
    partidas. Presença esporádica não redefine o elenco — é isso que separa
    'o Nashorn entrou no lugar do Hiroshi' de 'o Nashorn jogou uma vez'."""
    if not cenas:
        return frozenset()
    conta: dict[str, int] = {}
    for c in cenas:
        for m in c.elenco:
            conta[m] = conta.get(m, 0) + 1
    return frozenset(m for m, n in conta.items() if n / len(cenas) >= limiar)


def presenca(cenas: list[Cena]) -> dict[str, float]:
    """membro -> fração das partidas do trecho em que jogou."""
    if not cenas:
        return {}
    conta: dict[str, int] = {}
    for c in cenas:
        for m in c.elenco:
            conta[m] = conta.get(m, 0) + 1
    return {m: round(n / len(cenas), 3) for m, n in
            sorted(conta.items(), key=lambda kv: -kv[1])}

"""Orquestra a coleta: cânone -> PUUIDs -> partidas -> banco.

Duas decisões de custo que valem a leitura:

1. **Timeline só para partida em grupo.** A timeline é o objeto caro (minuto a
   minuto, 10 jogadores). Ela alimenta `virada` e `lanediff`, que só importam
   no fio principal. SoloQ é subtrama de personagem e vive bem sem ela — baixar
   timeline de 1500 partidas de soloq multiplicaria a coleta por 2 para
   enriquecer texto que ninguém vai ler.

2. **Coleta por fila, não geral.** Pedir `queue=440` e `queue=420` separado é
   uma chamada a mais de paginação e evita baixar ARAM, Arena e modo rotativo —
   que não entram na história e custariam a maior parte do tráfego.
"""
from __future__ import annotations


from .. import config
from ..canone import Canone
from . import db, ingest
from .riot import ClienteRiot


def resolver_puuids(conn, cliente: ClienteRiot, canone: Canone,
                    verbose: bool = True) -> dict[str, str]:
    """Riot ID -> PUUID, gravado em `membros`. Devolve PUUID -> id do cânone.

    Falhar aqui é comum e barato de diagnosticar (grafia de Riot ID), então
    reporta cada membro em vez de estourar no primeiro — assim você corrige
    todos os typos de uma vez.
    """
    mapa: dict[str, str] = {}
    faltando: list[str] = []
    for m in canone.membros.values():
        achou = None
        for nome, tag in m.puuid_keys:
            achou = cliente.puuid(nome, tag)
            if achou:
                if verbose:
                    print(f"  ✓ {m.nome:<16} {nome}#{tag}")
                db.upsert_membro(conn, m.id, achou, f"{nome}#{tag}", m.nome,
                                 m.titular, m.role)
                mapa[achou] = m.id
                break
        if not achou:
            faltando.append(f"{m.id} ({', '.join(m.riot_ids)})")
            if verbose:
                print(f"  ✗ {m.nome:<16} não resolveu — confira a grafia")
    conn.commit()
    if faltando and verbose:
        print(f"\n  {len(faltando)} não resolvido(s): {'; '.join(faltando)}")
    return mapa


def coletar(conn, cliente: ClienteRiot, puuid_para_membro: dict[str, str],
            filas: tuple[int, ...] = config.FILAS_COLETADAS,
            max_por_membro: int = 1000, verbose: bool = True) -> dict:
    """Baixa e ingere. Idempotente: re-rodar só pega o que faltava."""
    vistos: set[str] = set()
    for puuid in puuid_para_membro:
        for fila in filas:
            for mid in cliente.ids_de_partida(puuid, fila=fila, maximo=max_por_membro):
                vistos.add(mid)

    novos = [m for m in sorted(vistos) if not db.partida_existe(conn, m)]
    if verbose:
        print(f"\n  {len(vistos)} partidas no histórico, {len(novos)} novas")

    stats = {"vistas": len(vistos), "novas": 0, "em_grupo": 0, "timelines": 0}
    for i, match_id in enumerate(novos, 1):
        match = cliente.partida(match_id)
        if not match:
            continue
        if int(match.get("info", {}).get("queueId", 0)) not in filas:
            continue   # defesa: o histórico por fila às vezes devolve vizinho

        parsed = ingest.parse_partida(match, puuid_para_membro)
        partida, parts = parsed["partida"], parsed["participacoes"]
        nosso_time = partida.pop("nosso_time", None)

        derivado = None
        if partida["em_grupo"]:
            tl = cliente.timeline(match_id)
            if tl:
                ingest.enriquecer_com_timeline(parts, match, tl)
                derivado = ingest.derivar_timeline(match, tl, nosso_time)

        pid = db.inserir_partida(conn, partida, parts)
        if derivado:
            db.salvar_timeline_derivada(conn, pid, derivado)
            stats["timelines"] += 1
        stats["novas"] += 1
        stats["em_grupo"] += partida["em_grupo"]

        if verbose and i % 25 == 0:
            print(f"    {i}/{len(novos)}...", flush=True)
        if i % 50 == 0:
            conn.commit()
    conn.commit()
    return stats

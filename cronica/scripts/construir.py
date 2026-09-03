"""Fatos -> cronologia -> roteiro -> briefings. Nenhuma chamada de modelo.

Este é o comando que você mais vai rodar. Ele produz a estrutura inteira da
história (eras, capítulos, cenas escaladas, dossiês) e os briefings — que são o
que a narração vai poder dizer. Se o briefing está errado, o capítulo vai estar
errado, e sai muito mais barato descobrir isso aqui.

    python -m scripts.construir canone/time.yaml
    python -m scripts.construir --min-partidas 20     # capítulos mais longos
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica import config                                # noqa: E402
from cronica.canone import carregar                       # noqa: E402
from cronica.cronologia import eras as eras_mod           # noqa: E402
from cronica.cronologia.series import carregar_cenas      # noqa: E402
from cronica.fatos import db                              # noqa: E402
from cronica.narracao.escrever import escrever_tudo       # noqa: E402
from cronica.roteiro import capitulos as cap_mod          # noqa: E402


def construir(caminho_canone: str, min_partidas: int, min_membros: int):
    config.garantir_dirs()
    can = carregar(caminho_canone)
    conn = db.conectar()
    db.migrar(conn)

    cenas = carregar_cenas(conn, fila=config.FILA_FLEX, min_membros=min_membros)
    if not cenas:
        raise SystemExit("nenhuma partida em grupo no banco — rode "
                         "`python -m scripts.coletar` (ou `scripts.demo`).")

    eras, fronteiras = eras_mod.detectar(cenas, min_partidas=min_partidas)

    soloq = {mid: db.participacoes_do_membro(conn, mid, fila=config.FILA_SOLO)
             for mid in can.membros}
    caps = cap_mod.montar(cenas, eras, can, soloq_por_membro=soloq)

    (config.DIR_SAIDA / "cronologia.json").write_text(json.dumps({
        "partidas": len(cenas),
        "periodo": [cenas[0].data.isoformat(), cenas[-1].data.isoformat()],
        "eras": [e.para_json() for e in eras],
        "fronteiras": [{"indice": f.indice, "motivo": f.motivo, "forca": f.forca,
                        "detalhe": f.detalhe, "p_valor": f.p_valor}
                       for f in fronteiras],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.DIR_SAIDA / "roteiro.json").write_text(
        json.dumps([c.para_json() for c in caps], ensure_ascii=False, indent=2,
                   default=str), encoding="utf-8")
    return can, cenas, eras, caps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("canone", nargs="?", default="canone/time.yaml")
    ap.add_argument("--min-partidas", type=int, default=eras_mod.MIN_PARTIDAS_ERA,
                    help="mínimo de partidas por era (menor = mais capítulos)")
    ap.add_argument("--min-membros", type=int, default=2,
                    help="quantos do elenco no mesmo time para a partida contar")
    a = ap.parse_args()

    can, cenas, eras, caps = construir(a.canone, a.min_partidas, a.min_membros)

    print(f"{len(cenas)} partidas em grupo, {cenas[0].data} a {cenas[-1].data}")
    print(f"{len(eras)} eras detectadas:\n")
    print(f"  {'#':>2}  {'período':<25} {'forma':<14} {'jogos':>5} {'WR':>6} "
          f"{'delta':>8}  abertura")
    for e in eras:
        d = f"{e.delta_wr:+g}pp" if e.delta_wr is not None else "—"
        print(f"  {e.numero:>2}  {str(e.data_inicio) + ' – ' + str(e.data_fim):<25} "
              f"{e.forma:<14} {e.jogos:>5} {e.wr:>5}% {d:>8}  {e.abertura or 'início'}"
              + (f" (p={e.p_valor})" if e.p_valor else ""))

    print("\ngerando briefings (sem chamar o modelo):")
    escrever_tudo(caps, can, so_briefing=True)
    print(f"\n✓ estrutura em {config.DIR_SAIDA}/cronologia.json e roteiro.json")
    print(f"✓ briefings em {config.DIR_SAIDA}/briefings/ — leia antes de narrar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

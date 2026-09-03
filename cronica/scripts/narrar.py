"""Briefings -> capítulos escritos. Aqui é onde o modelo entra.

Sequencial de propósito: o capítulo N recebe a bíblia produzida pelo N-1. Doze
chamadas em paralelo produziriam doze textos que não sabem um do outro.

    python -m scripts.narrar canone/time.yaml
    python -m scripts.narrar --so 3       # renarra só o capítulo 3
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica import config                            # noqa: E402
from cronica.narracao import llm                      # noqa: E402
from cronica.narracao.escrever import escrever_tudo   # noqa: E402
from scripts.construir import construir               # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("canone", nargs="?", default="canone/time.yaml")
    ap.add_argument("--min-partidas", type=int, default=12)
    ap.add_argument("--min-membros", type=int, default=2)
    ap.add_argument("--so", type=int, help="narra só este capítulo")
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--refazer", action="store_true",
                    help="reescreve capítulos já existentes (zera a bíblia)")
    a = ap.parse_args()

    if not llm.disponivel():
        print(f"✗ '{config.CLAUDE_BIN}' não está no PATH.\n"
              f"  npm install -g @anthropic-ai/claude-code && claude  (/login)")
        return 1

    can, _cenas, _eras, caps = construir(a.canone, a.min_partidas, a.min_membros)
    if a.so:
        caps = [c for c in caps if c.numero == a.so]
        if not caps:
            print(f"✗ capítulo {a.so} não existe")
            return 1
        print("⚠ narrando um capítulo isolado: a bíblia parte do zero, então "
              "ele pode repetir o que os anteriores já contaram.")

    print(f"narrando {len(caps)} capítulo(s) com {a.modelo or config.CLAUDE_MODEL}:")
    escrever_tudo(caps, can, so_briefing=False, refazer=a.refazer)
    print(f"\n✓ capítulos em {config.DIR_SAIDA}/capitulos/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

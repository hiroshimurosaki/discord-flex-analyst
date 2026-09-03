"""Capítulos -> livro.md + slides.md (Marp).

    python -m scripts.renderizar canone/time.yaml
    npx @marp-team/marp-cli@latest saida/slides.md -o saida/slides.html
    npx @marp-team/marp-cli@latest saida/slides.md --pdf
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica import config                    # noqa: E402
from cronica.canone import carregar           # noqa: E402
from cronica.render import livro, slides      # noqa: E402


def _eras_do_json() -> list:
    """Lê as eras de `cronologia.json` para não refazer a detecção só para
    desenhar o gráfico. SimpleNamespace basta: o render só lê atributos."""
    p = config.DIR_SAIDA / "cronologia.json"
    if not p.exists():
        raise SystemExit("falta saida/cronologia.json — rode `scripts.construir`.")
    return [SimpleNamespace(**e)
            for e in json.loads(p.read_text(encoding="utf-8"))["eras"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("canone", nargs="?", default="canone/time.yaml")
    ap.add_argument("--sem-prosa", action="store_true",
                    help="deck só com capa, números e cenas (a prosa vira sua fala)")
    a = ap.parse_args()

    can = carregar(a.canone)
    eras = _eras_do_json()
    dir_caps = config.DIR_SAIDA / "capitulos"

    pl = livro.montar(dir_caps, can, eras=eras)
    ps = slides.montar(dir_caps, can, eras, com_prosa=not a.sem_prosa)
    print(f"✓ livro   {pl}")
    print(f"✓ slides  {ps}")
    print(f"\n  npx @marp-team/marp-cli@latest {ps} -o saida/slides.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

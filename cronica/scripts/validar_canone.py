"""Valida o cânone e mostra o que ainda falta preencher.

Rode isto sempre que mexer no YAML. Cânone com typo no id de um personagem faz o
dossiê dele sumir do briefing sem erro nenhum — e você só descobre lendo o
capítulo e achando estranho.

    python -m scripts.validar_canone canone/time.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cronica.canone import ErroCanone, METRICAS, carregar  # noqa: E402


def main(argv: list[str]) -> int:
    caminho = Path(argv[1]) if len(argv) > 1 else Path("canone/time.yaml")
    try:
        c = carregar(caminho)
    except ErroCanone as e:
        print(f"✗ cânone inválido: {e}")
        return 1

    print(f"✓ cânone válido — {c.time}"
          + (f", desde {c.desde}" if c.desde else ""))
    print(f"\n  titulares  ({len(c.titulares)}): "
          + ", ".join(f"{m.nome} [{m.role or '?'}]" for m in c.titulares))
    print(f"  substitutos ({len(c.substitutos)}): "
          + ", ".join(f"{m.nome} -> {m.entra_no_lugar_de or '?'}"
                      for m in c.substitutos))
    print(f"  eventos: {len(c.eventos)}")

    if len(c.titulares) != 5:
        print(f"\n  ⚠ {len(c.titulares)} titulares (esperado 5). "
              f"O seletor de 'quinteto completo' só dispara com o time fechado.")
    roles = [m.role for m in c.titulares if m.role]
    if len(set(roles)) != len(roles):
        print(f"  ⚠ roles repetidas entre titulares: {roles}. "
              f"Rode `python -m scripts.quinteto` depois de coletar.")

    print("\n  preenchimento do cânone:")
    faltando_afirma = []
    for m in c.titulares + c.substitutos:
        p = c.personagem(m.id)
        campos = {"arquetipo": p.arquetipo, "personalidade": p.personalidade,
                  "se_acha": p.se_acha, "medo": p.medo}
        vazios = [k for k, v in campos.items()
                  if not v or v.upper().startswith("TODO")]
        marca = "✓" if not vazios else "·"
        extra = f"  falta: {', '.join(vazios)}" if vazios else ""
        print(f"    {marca} {m.nome:<16}{extra}")
        if p.se_acha and not p.se_acha.upper().startswith("TODO") and not p.afirma:
            faltando_afirma.append(m.nome)

    if faltando_afirma:
        print(f"\n  ⚠ têm `se_acha` mas nenhum `afirma`: {', '.join(faltando_afirma)}")
        print("    Sem `afirma`, o código não emite veredito e a narração só pode")
        print("    relacionar a auto-imagem com os números — nunca dizer que ela")
        print("    é verdadeira ou falsa. Métricas disponíveis:")
        for k, v in METRICAS.items():
            print(f"      {k:<12} {v}")
    if not c.voz or c.voz.upper().startswith("TODO"):
        print("\n  ⚠ `voz` não preenchida: os capítulos vão sair com tom genérico.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Capítulos -> o livro corrido (`saida/livro.md`).

A fonte canônica é o markdown de cada capítulo, versionado. O livro é uma
derivação: concatena, põe a linha do tempo na abertura e as fichas de personagem
no fim. Nunca edite `livro.md` — edite o capítulo e regenere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..canone import Canone

RE_FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def ler_capitulo(caminho: Path) -> tuple[dict, str]:
    """Devolve (frontmatter, corpo). Frontmatter é uma linha `chave: json`."""
    txt = caminho.read_text(encoding="utf-8")
    m = RE_FM.match(txt)
    if not m:
        return {}, txt
    fm: dict = {}
    for linha in m.group(1).splitlines():
        if ":" not in linha:
            continue
        k, _, v = linha.partition(":")
        try:
            fm[k.strip()] = json.loads(v.strip())
        except json.JSONDecodeError:
            fm[k.strip()] = v.strip()
    return fm, txt[m.end():].lstrip()


def montar(dir_capitulos: Path, canone: Canone, eras: Optional[list] = None,
           saida: Optional[Path] = None) -> Path:
    from . import svg

    arquivos = sorted(dir_capitulos.glob("cap*.md"))
    if not arquivos:
        raise FileNotFoundError(f"nenhum capítulo em {dir_capitulos}")

    p = [f"# {canone.time}", ""]
    if canone.desde:
        p.append(f"*A história desde {canone.desde}.*\n")
    if eras:
        p.append(svg.linha_do_tempo(eras, titulo="Winrate por era") + "\n")
        p.append("| # | período | forma | jogos | winrate | núcleo |")
        p.append("|---|---|---|---|---|---|")
        for e in eras:
            nucleo = ", ".join(canone.membros[m].nome if m in canone.membros else m
                               for m in e.nucleo)
            p.append(f"| {e.numero} | {e.data_inicio} – {e.data_fim} | "
                     f"`{e.forma}` | {e.jogos} | {e.wr}% | {nucleo} |")
        p.append("")
    p.append("---\n")

    for arq in arquivos:
        fm, corpo = ler_capitulo(arq)
        p.append(corpo.rstrip())
        p.append("\n---\n")

    p.append("## O elenco\n")
    for m in canone.titulares + canone.substitutos:
        per = canone.personagem(m.id)
        papel = "titular" if m.titular else (
            f"substituto de {canone.membros[m.entra_no_lugar_de].nome}"
            if m.entra_no_lugar_de and m.entra_no_lugar_de in canone.membros
            else "substituto")
        p.append(f"### {m.nome}")
        p.append(f"*{papel}{' · ' + m.role.lower() if m.role else ''}*"
                 + (f" — {per.arquetipo}" if per.arquetipo else ""))
        if per.personalidade:
            p.append(f"\n{per.personalidade}")
        if per.bordoes:
            p.append("\n" + " · ".join(f'"{b}"' for b in per.bordoes))
        p.append("")

    saida = saida or dir_capitulos.parent / "livro.md"
    saida.write_text("\n".join(p), encoding="utf-8")
    return saida

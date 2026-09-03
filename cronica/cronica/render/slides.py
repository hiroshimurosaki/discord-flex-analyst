"""Capítulos -> deck Marp (`saida/slides.md`).

Marp porque o deck é markdown puro com um bloco de CSS no topo: abre no VS Code
com a extensão, exporta PDF/HTML/PPTX por linha de comando, e continua sendo um
arquivo de texto versionável. Nada de build de JS entre você e o slide.

    npx @marp-team/marp-cli@latest saida/slides.md -o saida/slides.html
    npx @marp-team/marp-cli@latest saida/slides.md --pdf

A regra de corte: um slide sustenta UMA ideia. A prosa do capítulo é o roteiro
de fala; o slide carrega a frase de abertura, os números e o gráfico. Despejar o
capítulo inteiro num slide seria transformar apresentação em documento.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..canone import Canone
from . import svg
from .livro import ler_capitulo

TEMA = """---
marp: true
paginate: true
theme: default
style: |
  section {
    background: #14161a; color: #e8eaed;
    font-family: -apple-system, "Segoe UI", Inter, system-ui, sans-serif;
    padding: 56px 64px;
  }
  h1 { font-size: 1.9em; color: #fff; margin-bottom: .1em; }
  h2 { font-size: 1.25em; color: #cfd4dc; font-weight: 600; }
  section.capa { justify-content: center; text-align: center; }
  section.capa h1 { font-size: 3em; }
  .sub { color: #9aa2ae; font-size: .95em; }
  .grande { font-size: 3.4em; font-weight: 700; line-height: 1; color: #fff; }
  .kpis { display: flex; gap: 48px; margin: 24px 0; }
  .kpi small { display: block; color: #9aa2ae; font-size: .5em;
               font-weight: 500; margin-top: 6px; letter-spacing: .02em; }
  .cita { font-size: 1.35em; line-height: 1.45; color: #fff;
          border-left: 3px solid #5b8ec4; padding-left: 20px; }
  table { font-size: .78em; border-collapse: collapse; }
  th, td { border-bottom: 1px solid #2b2f36; padding: 5px 12px; }
  th { color: #9aa2ae; font-weight: 600; }
  svg { color: #e8eaed; max-width: 100%; }
  .tag { display: inline-block; background: #232830; color: #cfd4dc;
         padding: 3px 11px; border-radius: 999px; font-size: .62em;
         letter-spacing: .04em; text-transform: uppercase; }
---
"""

ROTULO_PAPEL = {
    "primeira_vez": "A primeira vez", "fundo_do_poco": "O fundo do poço",
    "catarse": "A virada de chave", "virada": "A virada",
    "espelho": "O espelho", "entra_o_substituto": "O substituto",
    "recorde": "O recorde", "pico_de_personagem": "O jogo dele",
    "queda_livre": "A queda",
}


def _capa(canone: Canone, eras: list) -> str:
    per = (f"{eras[0].data_inicio} — {eras[-1].data_fim}" if eras else "")
    jogos = sum(e.jogos for e in eras)
    vit = sum(e.vitorias for e in eras)
    wr = round(100 * vit / jogos, 1) if jogos else 0
    return (f"<!-- _class: capa -->\n\n# {canone.time}\n\n"
            f"<p class='sub'>{per} · {jogos} partidas de flex em grupo · "
            f"{wr}% de vitória</p>\n")


def _slide_panorama(eras: list) -> str:
    return ("## A história inteira, de uma vez\n\n"
            + svg.linha_do_tempo(eras, largura=1000, altura=300)
            + "\n\n<p class='sub'>Cada barra é uma era detectada pelos dados: "
              "largura = partidas, altura = winrate.</p>\n")


def _slide_abertura_cap(fm: dict) -> str:
    sinais = " · ".join(fm.get("sinais", [])[:2])
    return (f"<!-- _class: capa -->\n\n"
            f"<p class='tag'>Capítulo {fm.get('capitulo')} · {fm.get('forma')}</p>\n\n"
            f"# {fm.get('titulo')}\n\n"
            f"<p class='sub'>{fm.get('subtitulo', '')}</p>\n\n"
            f"<p class='sub'>{fm.get('inicio')} — {fm.get('fim')}"
            + (f" · {sinais}" if sinais else "") + "</p>\n")


def _slide_numeros(fm: dict) -> str:
    delta = fm.get("delta_wr")
    dtxt = (f"{delta:+g}pp vs a era anterior" if delta is not None else "primeira era")
    return ("## Os números\n\n<div class='kpis'>"
            f"<div class='kpi grande'>{fm.get('jogos')}<small>PARTIDAS</small></div>"
            f"<div class='kpi grande'>{fm.get('wr')}%<small>VITÓRIAS</small></div>"
            f"<div class='kpi grande'>{fm.get('vitorias')}<small>VENCIDAS</small></div>"
            f"</div>\n\n<p class='sub'>{dtxt} · núcleo: "
            + ", ".join(fm.get("nucleo", [])) + "</p>\n")


def _slide_abertura_frase(fm: dict) -> str:
    frase = fm.get("abertura")
    return f"<p class='cita'>{frase}</p>\n" if frase else ""


def _slide_cenas(fm: dict) -> str:
    ms = fm.get("momentos") or []
    if not ms:
        return ""
    p = ["## As cenas deste capítulo\n"]
    for m in ms:
        p.append(f"**{ROTULO_PAPEL.get(m['papel'], m['papel'])}** — {m['titulo']}\n")
    return "\n".join(p)


def _slides_prosa(corpo: str, por_slide: int = 3) -> list[str]:
    """A prosa vira slides de fala: parágrafos agrupados, títulos preservados."""
    blocos = [b.strip() for b in corpo.split("\n\n") if b.strip()]
    blocos = [b for b in blocos if not b.startswith("# ")]
    saida, atual = [], []
    for b in blocos:
        if b.startswith("## ") and atual:
            saida.append("\n\n".join(atual))
            atual = []
        atual.append(b)
        if len(atual) >= por_slide:
            saida.append("\n\n".join(atual))
            atual = []
    if atual:
        saida.append("\n\n".join(atual))
    return saida


def montar(dir_capitulos: Path, canone: Canone, eras: list,
           saida: Optional[Path] = None, com_prosa: bool = True) -> Path:
    arquivos = sorted(dir_capitulos.glob("cap*.md"))
    if not arquivos:
        raise FileNotFoundError(f"nenhum capítulo em {dir_capitulos}")

    slides: list[str] = [_capa(canone, eras), _slide_panorama(eras)]
    for arq in arquivos:
        fm, corpo = ler_capitulo(arq)
        for s in (_slide_abertura_cap(fm), _slide_abertura_frase(fm),
                  _slide_numeros(fm), _slide_cenas(fm)):
            if s:
                slides.append(s)
        if com_prosa:
            slides.extend(_slides_prosa(corpo))

    slides.append("## O elenco\n\n" + "\n".join(
        f"**{m.nome}** — {'titular' if m.titular else 'substituto'}"
        + (f" · {m.role.lower()}" if m.role else "")
        + (f" · *{canone.personagem(m.id).arquetipo}*"
           if canone.personagem(m.id).arquetipo else "")
        + "\n" for m in canone.titulares + canone.substitutos))

    saida = saida or dir_capitulos.parent / "slides.md"
    saida.write_text(TEMA + "\n" + "\n\n---\n\n".join(slides) + "\n",
                     encoding="utf-8")
    return saida

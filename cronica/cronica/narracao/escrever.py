"""Orquestra a narração: briefing + bíblia -> capítulo em markdown.

Sequencial de propósito. Paralelizar as chamadas seria mais rápido e quebraria a
única coisa que faz disso uma história: o capítulo N precisa da bíblia produzida
pelo capítulo N-1. Doze chamadas em paralelo produzem doze textos que não sabem
um do outro.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .. import config
from ..canone import Canone
from ..roteiro import briefing as brief_mod
from ..roteiro.capitulos import Capitulo
from . import biblia as biblia_mod
from . import llm


def _frontmatter(cap: Capitulo, dados: dict) -> str:
    """Metadados no topo do markdown: é daqui que o render de slides tira
    título, subtítulo e números sem reparsear a prosa."""
    e = cap.era
    fm = {
        "capitulo": cap.numero, "titulo": dados["titulo"],
        "subtitulo": dados["subtitulo"],
        "abertura": dados["frase_de_abertura"],
        "forma": e.forma, "inicio": e.data_inicio.isoformat(),
        "fim": e.data_fim.isoformat(), "jogos": e.jogos, "vitorias": e.vitorias,
        "wr": e.wr, "delta_wr": e.delta_wr,
        "nucleo": e.nucleo, "sinais": e.sinais,
        "momentos": [{"papel": m.papel, "titulo": m.titulo} for m in cap.momentos],
    }
    linhas = ["---"]
    for k, v in fm.items():
        linhas.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    linhas.append("---")
    return "\n".join(linhas)


def escrever_tudo(capitulos: list[Capitulo], canone: Canone,
                  dir_saida: Optional[Path] = None,
                  so_briefing: bool = False, refazer: bool = False,
                  log: Callable[[str], None] = print) -> list[Path]:
    """Gera briefings e (se não for `so_briefing`) narra cada capítulo.

    `so_briefing=True` roda o pipeline inteiro sem gastar uma chamada de modelo.
    É o modo em que você vai passar a maior parte do tempo: se o briefing está
    errado, o capítulo vai estar errado, e é muito mais barato descobrir isso
    lendo markdown do que lendo prosa.

    Retoma de onde parou: capítulo já escrito é pulado (a bíblia salva em disco
    mantém a continuidade), a não ser com `refazer=True`. Sem isso, uma falha no
    capítulo 9 obrigaria a reescrever os oito anteriores — e a reescrever
    significa textos diferentes, porque a geração não é determinística.
    """
    dir_saida = dir_saida or config.DIR_SAIDA
    (dir_saida / "briefings").mkdir(parents=True, exist_ok=True)
    (dir_saida / "capitulos").mkdir(parents=True, exist_ok=True)

    caminho_biblia = dir_saida / "biblia.json"
    b = (biblia_mod.vazia() if refazer
         else biblia_mod.carregar(caminho_biblia))
    gerados: list[Path] = []

    for cap in capitulos:
        texto_brief = brief_mod.gerar(cap, canone, biblia=b)
        pb = dir_saida / "briefings" / f"cap{cap.numero:02d}.md"
        pb.write_text(texto_brief, encoding="utf-8")
        log(f"  briefing  cap{cap.numero:02d}  "
            f"({cap.era.forma}, {cap.era.jogos} jogos, "
            f"{len(cap.momentos)} cenas)  -> {pb}")
        if so_briefing:
            gerados.append(pb)
            continue

        pc = dir_saida / "capitulos" / f"cap{cap.numero:02d}.md"
        if pc.exists() and not refazer:
            log(f"  capítulo  cap{cap.numero:02d}  já existe, pulando "
                f"(use --refazer para reescrever)")
            gerados.append(pc)
            continue

        dados = llm.narrar(texto_brief, voz=canone.voz)
        pc.write_text(_frontmatter(cap, dados) + "\n\n# " + dados["titulo"]
                      + f"\n\n*{dados['subtitulo']}*\n\n" + dados["texto"] + "\n",
                      encoding="utf-8")
        log(f"  capítulo  cap{cap.numero:02d}  \"{dados['titulo']}\"  -> {pc}")
        gerados.append(pc)

        b = biblia_mod.atualizar(b, dados, cap.numero, dados["titulo"])
        biblia_mod.salvar(b, caminho_biblia)

    return gerados

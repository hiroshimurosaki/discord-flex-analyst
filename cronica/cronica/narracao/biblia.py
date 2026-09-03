"""A bíblia — o estado que corre entre capítulos.

Narrar 12 capítulos com 12 chamadas independentes produz 12 variações do mesmo
texto: a LLM não sabe que já usou "o time finalmente encaixou" três vezes, e não
sabe que a briga do capítulo 4 já foi contada. Ela também não tem para onde
apontar, porque cada chamada é um fim em si.

A bíblia resolve as duas coisas. Depois de cada capítulo, guarda o que foi
contado, as imagens gastas, onde a emoção parou, e — o que mais importa — as
**promessas em aberto**. É a promessa que dá direção: o capítulo seguinte é
instruído a pagar ou a adiar conscientemente, e isso é a diferença entre uma
sequência de relatórios e uma narrativa com arco.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config

CAMINHO = config.DIR_SAIDA / "biblia.json"
MAX_IMAGENS = 60      # a lista serve para PROIBIR repetição, não para arquivar
MAX_FATOS = 120


def vazia() -> dict:
    return {"capitulos": 0, "resumo_ate_aqui": "", "fatos_contados": [],
            "imagens_usadas": [], "estado_emocional": "", "promessas_abertas": []}


def carregar(caminho: Path | None = None) -> dict:
    caminho = caminho or CAMINHO
    if not caminho.exists():
        return vazia()
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar(b: dict, caminho: Path | None = None) -> None:
    caminho = caminho or CAMINHO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")


def atualizar(b: dict, capitulo: dict, numero: int, titulo: str) -> dict:
    """Absorve um capítulo narrado.

    As promessas do capítulo anterior são SUBSTITUÍDAS, não acumuladas: se o
    capítulo novo não repetiu uma promessa, ele a considerou paga ou abandonada,
    e carregar promessa morta para sempre faria o prompt inchar de dívida que
    ninguém vai cobrar.
    """
    b = dict(b)
    b["capitulos"] = numero
    b["fatos_contados"] = (b.get("fatos_contados", [])
                           + list(capitulo.get("fatos_contados", [])))[-MAX_FATOS:]
    b["imagens_usadas"] = (b.get("imagens_usadas", [])
                           + list(capitulo.get("imagens_usadas", [])))[-MAX_IMAGENS:]
    b["estado_emocional"] = capitulo.get("estado_emocional", "")
    b["promessas_abertas"] = list(capitulo.get("promessas_abertas", []))
    linha = f"Cap. {numero:02d} — {titulo}: {capitulo.get('subtitulo', '')}"
    b["resumo_ate_aqui"] = ((b.get("resumo_ate_aqui", "") + "\n" + linha).strip())
    return b

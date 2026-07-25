"""Texto do post -> embeds do Discord, sem perder o final.

Existe por dois motivos:

1. **O post é montado em três lugares diferentes** — o bot com gateway, o ciclo
   do GitHub Actions (via webhook) e o handler de Interactions no Vercel. Só o
   primeiro tem `discord.py` disponível. Aqui a saída é `dict` puro, que serve
   aos três (`discord.Embed.from_dict` aceita o mesmo shape).

2. **Truncar em 4096 corta justamente o fim** — que é onde ficam os recordes e a
   narrativa. O `description` de um embed tem limite de 4096 caracteres, e a
   versão anterior fazia `texto[:4096]` calado. Aqui o texto é PARTIDO em vários
   embeds, cortando em parágrafo e reabrindo blocos de código quando preciso.
"""
from __future__ import annotations

LIMITE_DESC = 4096      # limite do campo description de um embed
MAX_EMBEDS = 10         # limite de embeds por mensagem

AZUL = 0x5865F2
VERDE = 0x57F287
VERMELHO = 0xED4245


def _fechado(trecho: str) -> bool:
    """True se o trecho não deixa um bloco ``` aberto."""
    return trecho.count("```") % 2 == 0


def partir(texto: str, limite: int = LIMITE_DESC) -> list[str]:
    """Quebra o texto em pedaços que cabem num embed, preservando o sentido.

    Prefere cortar em linha em branco, depois em quebra de linha, e só corta no
    meio da linha como último recurso. Se o corte cair dentro de um bloco de
    código, fecha o bloco no pedaço que sai e reabre no seguinte — senão o
    Discord renderiza o resto da mensagem como código.
    """
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    resto = texto
    while resto:
        if len(resto) <= limite:
            partes.append(resto)
            break

        # margem para o ``` de fechamento, caso seja preciso reabrir depois
        corte = limite - 8
        janela = resto[:corte]
        for sep in ("\n\n", "\n", " "):
            pos = janela.rfind(sep)
            if pos > corte // 2:      # só aceita se não jogar fora meio pedaço
                corte = pos + len(sep)
                break

        pedaco, resto = resto[:corte].rstrip(), resto[corte:].lstrip("\n")
        if not _fechado(pedaco):
            pedaco += "\n```"
            resto = "```\n" + resto
        partes.append(pedaco)

    return partes


def construir(texto: str, cor: int = AZUL) -> list[dict]:
    """Texto -> lista de embeds (dicts). Só o primeiro leva a cor de destaque."""
    pedacos = partir(texto)[:MAX_EMBEDS]
    return [{"description": p, "color": cor} for p in pedacos]


def cor_do_resultado(texto: str) -> int:
    """Verde em vitória, vermelho em derrota, azul quando não dá pra saber."""
    if "🏆" in texto[:120]:
        return VERDE
    if "❌" in texto[:120]:
        return VERMELHO
    return AZUL

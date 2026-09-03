"""Escalação de cenas — função narrativa, não magnitude.

O seletor NÃO pergunta "qual foi a maior partida?". Pergunta "que papel esta
cena cumpre?" — e cada papel tem uma query própria. É casting: uma cena entra
porque a história precisa dela ali, não porque o número era grande.

A diferença é concreta. A partida de maior dano da história provavelmente foi
um jogo de 45 minutos que ninguém lembra. A partida que importa é a que
significa algo *depois do que veio antes* — e isso é uma propriedade da
sequência, não da linha.

O seletor mais importante é `espelho` (ver docstring dele): é o único que mostra
evolução em vez de afirmá-la.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

from ..cronologia.series import Cena

PAPEIS = [
    "primeira_vez", "fundo_do_poco", "catarse", "virada", "espelho",
    "entra_o_substituto", "recorde", "pico_de_personagem", "queda_livre",
]


@dataclass
class Momento:
    papel: str
    titulo: str
    partida_ids: list[int]
    data: str
    porque: str                       # por que ESTA cena foi escalada
    dados: dict = field(default_factory=dict)
    inferencia: bool = False          # marca o que é leitura, não fato

    def para_json(self) -> dict:
        return asdict(self)


def _ficha(c: Cena) -> dict:
    """Os números de uma cena, no formato que vai para o briefing."""
    return {
        "partida_id": c.partida_id, "match_id": c.match_id,
        "data": c.data.isoformat(), "resultado": "vitória" if c.venceu else "derrota",
        "duracao_min": c.duracao_min, "patch": c.patch,
        "elenco": sorted(c.elenco),
        "composicao": {m: c.campeoes.get(m) for m in sorted(c.elenco)},
        "roles": {m: c.roles.get(m) for m in sorted(c.elenco)},
        "kda": {m: f"{k}/{d}/{a}" for m, (k, d, a) in sorted(c.kda.items())},
        "oponentes_por_rota": c.oponentes,
        "deficit_max_ouro": c.deficit_max,
        "pico_max_ouro": c.pico_max,
    }


# ------------------------------------------------------------- seletores

def primeira_vez(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """Estreias. Só existem uma vez na história inteira, então `contexto`
    carrega o que já foi estreado para os capítulos seguintes não repetirem."""
    out: list[Momento] = []
    ja = contexto.setdefault("estreias", set())
    if "primeira_partida" not in ja and contexto.get("primeira_era"):
        c = cenas[0]
        ja.add("primeira_partida")
        out.append(Momento("primeira_vez", "A primeira vez", [c.partida_id],
                           c.data.isoformat(),
                           "a primeira partida do histórico em grupo", _ficha(c)))
    if "primeira_vitoria" not in ja:
        v = next((c for c in cenas if c.venceu), None)
        if v is not None and contexto.get("primeira_era"):
            ja.add("primeira_vitoria")
            out.append(Momento("primeira_vez", "A primeira vitória", [v.partida_id],
                               v.data.isoformat(),
                               "primeira vitória registrada em grupo", _ficha(v)))
    if "quinteto_completo" not in ja:
        alvo = contexto.get("titulares") or set()
        if alvo:
            c = next((c for c in cenas if alvo <= c.elenco), None)
            if c is not None:
                ja.add("quinteto_completo")
                out.append(Momento(
                    "primeira_vez", "O quinteto titular completo, pela primeira vez",
                    [c.partida_id], c.data.isoformat(),
                    "primeira partida com os cinco titulares juntos", _ficha(c)))
    return out


def _maior_sequencia(cenas: list[Cena], vitoria: bool) -> tuple[int, int, int]:
    """(tamanho, início, fim_exclusivo) da maior sequência de vitórias/derrotas."""
    melhor = (0, 0, 0)
    i = 0
    while i < len(cenas):
        if cenas[i].venceu == vitoria:
            j = i
            while j < len(cenas) and cenas[j].venceu == vitoria:
                j += 1
            if j - i > melhor[0]:
                melhor = (j - i, i, j)
            i = j
        else:
            i += 1
    return melhor


def fundo_do_poco(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """A pior sequência de derrotas da era, ancorada na derrota que a fechou."""
    n, ini, fim = _maior_sequencia(cenas, vitoria=False)
    if n < 3:
        return []
    c = cenas[fim - 1]
    return [Momento("fundo_do_poco", f"{n} derrotas seguidas",
                    [x.partida_id for x in cenas[ini:fim]], c.data.isoformat(),
                    f"maior sequência de derrotas da era ({n} jogos, "
                    f"{cenas[ini].data.isoformat()} a {c.data.isoformat()})",
                    {"tamanho": n, "ultima_derrota": _ficha(c),
                     "primeira_derrota": _ficha(cenas[ini])})]


def catarse(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """A vitória que encerrou a seca. Só existe se a seca existiu."""
    n, ini, fim = _maior_sequencia(cenas, vitoria=False)
    if n < 3 or fim >= len(cenas):
        return []
    c = cenas[fim]
    return [Momento("catarse", f"A vitória que quebrou {n} derrotas",
                    [c.partida_id], c.data.isoformat(),
                    f"primeira vitória depois da seca de {n} jogos", _ficha(c))]


def virada(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """Maior déficit de ouro revertido em vitória.

    Exige timeline (`deficit_max`). Quando ela não existe, o seletor devolve
    vazio em vez de improvisar com outro critério — uma virada inventada a
    partir do placar final seria uma cena falsa, e a história perderia mais com
    isso do que ganha com o preenchimento.
    """
    cands = [c for c in cenas if c.venceu and (c.deficit_max or 0) >= 3000]
    if not cands:
        return []
    c = max(cands, key=lambda x: x.deficit_max or 0)
    return [Momento("virada", f"{c.deficit_max} de ouro atrás, e ganharam",
                    [c.partida_id], c.data.isoformat(),
                    f"maior desvantagem de ouro revertida na era "
                    f"(pior momento aos {c.minuto_deficit} min)",
                    _ficha(c) | {"minuto_do_deficit": c.minuto_deficit})]


def queda_livre(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """A derrota mais dura da era: maior vantagem de ouro jogada fora."""
    cands = [c for c in cenas if not c.venceu and (c.pico_max or 0) >= 3000]
    if not cands:
        return []
    c = max(cands, key=lambda x: x.pico_max or 0)
    return [Momento("queda_livre", f"{c.pico_max} de ouro à frente, e perderam",
                    [c.partida_id], c.data.isoformat(),
                    "maior vantagem de ouro perdida na era", _ficha(c))]


def entra_o_substituto(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """A partida em que um substituto entrou e o resultado foi notável.

    Substituto não é 'outro jogador': é um papel narrativo. A presença dele
    muda o time, e o capítulo quer saber se mudou para melhor.
    """
    subs: set[str] = contexto.get("substitutos") or set()
    if not subs:
        return []
    com_sub = [c for c in cenas if c.elenco & subs]
    if len(com_sub) < 2:
        return []
    vit = sum(c.venceu for c in com_sub)
    wr_sub = round(100 * vit / len(com_sub), 1)
    sem_sub = [c for c in cenas if not (c.elenco & subs)]
    wr_sem = round(100 * sum(c.venceu for c in sem_sub) / len(sem_sub), 1) if sem_sub else None
    destaque = max(com_sub, key=lambda c: (c.venceu, c.deficit_max or 0))
    quem = sorted(destaque.elenco & subs)
    return [Momento("entra_o_substituto", f"Com {', '.join(quem)} no time",
                    [destaque.partida_id], destaque.data.isoformat(),
                    f"{len(com_sub)} jogos da era com substituto",
                    _ficha(destaque) | {
                        "jogos_com_substituto": len(com_sub), "wr_com": wr_sub,
                        "jogos_sem_substituto": len(sem_sub), "wr_sem": wr_sem,
                        "substitutos_presentes": quem},
                    inferencia=len(com_sub) < 8)]


def pico_de_personagem(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """O melhor jogo de cada titular na era.

    'Melhor' = maior share de dano numa vitória, com desempate por KDA. É um
    critério, não a verdade — e o briefing declara isso, para a narração não
    escrever 'o melhor jogo da vida dele'.
    """
    out: list[Momento] = []
    for m in sorted(contexto.get("titulares") or set()):
        dele = [c for c in cenas if m in c.elenco and c.venceu]
        if len(dele) < 3:
            continue

        def nota(c: Cena) -> tuple[float, float]:
            tot = sum(c.dano.values()) or 1
            k, d, a = c.kda[m]
            return (c.dano[m] / tot, (k + a) / max(d, 1))

        c = max(dele, key=nota)
        tot = sum(c.dano.values()) or 1
        k, d, a = c.kda[m]
        out.append(Momento("pico_de_personagem", f"O jogo de {m}", [c.partida_id],
                           c.data.isoformat(),
                           f"maior participação no dano do time entre as vitórias "
                           f"de {m} na era ({len(dele)} vitórias consideradas)",
                           # NÃO usar a chave "kda": `_ficha` já a usa para o
                           # K/D/A do time inteiro, e sobrescrever quebraria a
                           # tabela de composição do briefing.
                           _ficha(c) | {"membro": m, "campeao": c.campeoes.get(m),
                                        "share_dano_pct": round(100 * c.dano[m] / tot, 1),
                                        "kda_do_destaque": f"{k}/{d}/{a}"},
                           inferencia=True))
    return out


def recorde(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """Primeira vez que um recorde do grupo foi batido DENTRO desta era.

    O estado corre no `contexto` entre capítulos: um recorde só é notícia na era
    em que caiu. Recontar o mesmo recorde em três capítulos é o defeito clássico
    de gerar capítulos independentes.
    """
    melhores: dict = contexto.setdefault("recordes", {})
    out: list[Momento] = []
    provas: list[tuple[str, Callable[[Cena], Optional[float]], str]] = [
        ("partida mais longa", lambda c: c.duracao_seg, "min"),
        ("maior virada", lambda c: (c.deficit_max or 0) if c.venceu else None, "ouro"),
        ("maior dano do time", lambda c: sum(c.dano.values()), "dano"),
        ("vitória mais rápida", lambda c: -c.duracao_seg if c.venceu else None, "min"),
    ]
    for nome, chave, unidade in provas:
        for c in cenas:
            v = chave(c)
            if v is None:
                continue
            atual = melhores.get(nome)
            if atual is None or v > atual["valor"]:
                melhores[nome] = {"valor": v, "partida_id": c.partida_id,
                                  "data": c.data.isoformat(), "novo": True}
        m = melhores.get(nome)
        if m and m.pop("novo", False):
            c = next((x for x in cenas if x.partida_id == m["partida_id"]), None)
            if c is not None:
                out.append(Momento("recorde", f"Novo recorde: {nome}",
                                   [c.partida_id], c.data.isoformat(),
                                   f"o recorde de '{nome}' do grupo caiu nesta era",
                                   _ficha(c) | {"recorde": nome, "unidade": unidade}))
    return out[:1]   # no máximo um recorde por capítulo: mais que isso vira lista


# ------------------------------------------------------------- o espelho

MIN_COMPOSICAO = 0.4     # portão duro: ver `_similaridade`


def _similaridade(a: Cena, b: Cena) -> tuple[float, float]:
    """(similaridade total, similaridade de composição), ambas 0..1.

    A composição é devolvida separada porque ela é um PORTÃO, não só um peso.
    Com ela apenas somando, duas partidas do mesmo elenco com campeões
    completamente diferentes chegam a 0.5 pelos outros termos e passariam — e
    aí o espelho promete "o mesmo jogo" mostrando dois jogos que não têm um
    único campeão em comum. A cena deixaria de provar o que anuncia.
    """
    pares_a = {(m, a.campeoes.get(m)) for m in a.elenco}
    pares_b = {(m, b.campeoes.get(m)) for m in b.elenco}
    if not pares_a or not pares_b:
        return 0.0, 0.0
    comp = len(pares_a & pares_b) / len(pares_a | pares_b)

    el = len(a.elenco & b.elenco) / len(a.elenco | b.elenco)

    opp_a = {(r, ch) for r, ch in a.oponentes.items()}
    opp_b = {(r, ch) for r, ch in b.oponentes.items()}
    opp = len(opp_a & opp_b) / len(opp_a | opp_b) if (opp_a and opp_b) else 0.0

    dur = 1 - min(abs(a.duracao_seg - b.duracao_seg) / 1800, 1.0)
    return 0.5 * comp + 0.25 * el + 0.15 * opp + 0.10 * dur, comp


def espelho(cenas: list[Cena], contexto: dict) -> list[Momento]:
    """*** O dispositivo central de evolução. ***

    Procura, entre as cenas desta era e TODO o passado, o par mais parecido com
    resultado OPOSTO e maior distância no tempo. A saída é sempre a mesma forma:
    "vocês já jogaram exatamente isto e perderam; agora ganharam".

    Por que isto vale mais que qualquer gráfico: "o winrate subiu 12pp" é uma
    abstração que ninguém sente. "Em março essa mesma composição perdeu em 24
    minutos com o Lukyy 400 de ouro atrás aos 10; em novembro ganhou em 31 com
    ele 300 à frente" é a MESMA informação acontecendo com pessoas. Evolução
    mostrada, não afirmada — e verificável, porque as duas partidas existem.

    Só devolve par com similaridade >= 0.45: abaixo disso "parecida" vira
    licença poética, e a cena deixa de provar o que promete.
    """
    passado: list[Cena] = contexto.get("passado") or []
    if not passado:
        return []
    melhor = None
    for atual in cenas:
        for antiga in passado:
            if antiga.venceu == atual.venceu:
                continue
            sim, comp = _similaridade(atual, antiga)
            if comp < MIN_COMPOSICAO or sim < 0.45:
                continue
            dias = (atual.data - antiga.data).days
            if dias < 30:
                continue
            escore = sim * (1 + min(dias / 365, 2))
            if melhor is None or escore > melhor[0]:
                melhor = (escore, sim, dias, antiga, atual)
    if melhor is None:
        return []
    _esc, sim, dias, antiga, atual = melhor
    direcao = "derrota -> vitória" if atual.venceu else "vitória -> derrota"
    return [Momento(
        "espelho", f"O mesmo jogo, {dias} dias depois",
        [antiga.partida_id, atual.partida_id], atual.data.isoformat(),
        f"partidas com composição parecida (similaridade {sim:.3f}) e resultado "
        f"invertido, separadas por {dias} dias",
        {"direcao": direcao, "dias_entre": dias,
         "similaridade": round(sim, 3),
         "antes": _ficha(antiga), "depois": _ficha(atual),
         "lanediff_10_antes": antiga.lanediff_10,
         "lanediff_10_depois": atual.lanediff_10},
        inferencia=False)]


SELETORES: dict[str, Callable[[list[Cena], dict], list[Momento]]] = {
    "primeira_vez": primeira_vez,
    "espelho": espelho,
    "virada": virada,
    "catarse": catarse,
    "fundo_do_poco": fundo_do_poco,
    "entra_o_substituto": entra_o_substituto,
    "recorde": recorde,
    "queda_livre": queda_livre,
    "pico_de_personagem": pico_de_personagem,
}

# Ordem de preferência quando há mais candidatos que vagas. É uma decisão
# narrativa: estreia e espelho contam evolução; pico de personagem é o mais
# dispensável porque se repete em todo capítulo.
PRIORIDADE = ["primeira_vez", "espelho", "virada", "catarse", "fundo_do_poco",
              "entra_o_substituto", "recorde", "queda_livre", "pico_de_personagem"]


def escalar(cenas: list[Cena], contexto: dict, maximo: int = 6) -> list[Momento]:
    """Roda todos os seletores e escala até `maximo` cenas, uma por papel."""
    achados: dict[str, list[Momento]] = {}
    for papel in PRIORIDADE:
        try:
            m = SELETORES[papel](cenas, contexto)
        except (KeyError, IndexError, ValueError):
            m = []   # um seletor sem dado nunca derruba o capítulo
        if m:
            achados[papel] = m

    escalados: list[Momento] = []
    for papel in PRIORIDADE:
        if papel not in achados or len(escalados) >= maximo:
            continue
        if papel == "pico_de_personagem":
            # só preenche as vagas que sobraram, e alterna quem ganha destaque
            # entre capítulos para não ser sempre o mesmo carry
            vagas = maximo - len(escalados)
            fila: list[str] = contexto.setdefault("rodizio_picos", [])
            ordenados = sorted(achados[papel],
                               key=lambda m: fila.index(m.dados["membro"])
                               if m.dados["membro"] in fila else -1)
            for m in ordenados[:vagas]:
                escalados.append(m)
                membro = m.dados["membro"]
                if membro in fila:
                    fila.remove(membro)
                fila.append(membro)
        else:
            escalados.append(achados[papel][0])
    return escalados[:maximo]

"""Detecção de eras — onde 800 partidas viram 12 capítulos.

O problema: uma história linear precisa de capítulos, e capítulo não é janela
de tempo arbitrária. Um capítulo é um trecho em que **o time era a mesma
coisa**. Detectar fronteira é detectar quando ele deixou de ser.

Quatro geradores de fronteira, dos mais honestos aos mais inferenciais:

  1. HIATO          — gap de calendário. Não é inferência, é subtração de datas.
  2. ELENCO         — o núcleo do time mudou e continuou mudado.
  3. PATCH/SPLIT    — fronteira que a Riot desenhou e o grupo sentiu.
  4. QUEBRA DE WR   — segmentação binária com teste z de duas proporções.

O 4 é o único estatístico, e por isso é o único que carrega **p-valor** para
fora. Uma era não é "o que o algoritmo achou": é uma afirmação com força
declarada. Fronteira fraca vira ressalva no briefing e a narração é proibida de
cravar em cima dela.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field, asdict
from typing import Optional

from .series import Cena, nucleo, presenca, wr

# --- parâmetros; todos explícitos porque todos são opinião defensável ---
MIN_PARTIDAS_ERA = 12      # abaixo disso não é fase, é sequência
HIATO_DIAS = 21            # 3 semanas sem jogar já é "o grupo parou"
HIATO_LONGO_DIAS = 60      # some isso e a volta é um capítulo de retomada
JANELA_ELENCO = 10         # partidas de cada lado para achar o núcleo
ALFA = 0.05                # significância exigida da quebra de WR
DELTA_WR_NOTAVEL = 10.0    # pp para chamar de ascensão/queda


@dataclass
class Fronteira:
    indice: int            # a era nova começa NESTA cena
    motivo: str            # hiato | elenco | patch | wr
    forca: str             # 'certa' (calendário/elenco) | 'estatistica'
    detalhe: str = ""
    p_valor: Optional[float] = None


@dataclass
class Era:
    numero: int
    inicio: int            # índices na lista de cenas [inicio, fim)
    fim: int
    data_inicio: dt.date
    data_fim: dt.date
    jogos: int
    vitorias: int
    wr: float
    forma: str             # estreia|ascensao|plato|queda|reconstrucao|retomada
    sinais: list[str] = field(default_factory=list)
    delta_wr: Optional[float] = None
    p_valor: Optional[float] = None
    nucleo: list[str] = field(default_factory=list)
    presenca: dict[str, float] = field(default_factory=dict)
    entraram: list[str] = field(default_factory=list)
    sairam: list[str] = field(default_factory=list)
    hiato_antes_dias: Optional[int] = None
    duracao_media_min: Optional[float] = None
    patches: list[str] = field(default_factory=list)
    abertura: Optional[str] = None   # motivo da fronteira que abriu a era

    def para_json(self) -> dict:
        d = asdict(self)
        d["data_inicio"] = self.data_inicio.isoformat()
        d["data_fim"] = self.data_fim.isoformat()
        return d


# ----------------------------------------------------------- estatística

def _z_duas_proporcoes(v1: int, n1: int, v2: int, n2: int) -> tuple[float, float]:
    """z e p (bicaudal) para H0: as duas metades têm o mesmo winrate.

    Sem scipy de propósito: `erfc` da stdlib dá o p-valor normal com precisão
    de sobra, e uma dependência a menos é uma dependência a menos num projeto
    que alguém vai rodar daqui a dois anos.
    """
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p1, p2 = v1 / n1, v2 / n2
    p = (v1 + v2) / (n1 + n2)
    den = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if den == 0:
        return 0.0, 1.0
    z = (p1 - p2) / den
    return z, math.erfc(abs(z) / math.sqrt(2))


def _melhor_quebra(vit: list[int], base: int, minimo: int
                   ) -> Optional[tuple[int, float, float]]:
    """Corte de maior |z| dentro de um bloco, respeitando o mínimo dos dois lados."""
    n = len(vit)
    if n < 2 * minimo:
        return None
    total = sum(vit)
    melhor = None
    acum = sum(vit[:minimo])
    for corte in range(minimo, n - minimo + 1):
        z, p = _z_duas_proporcoes(acum, corte, total - acum, n - corte)
        if melhor is None or abs(z) > abs(melhor[1]):
            melhor = (base + corte, z, p)
        if corte < n:
            acum += vit[corte]
    return melhor


def _segmentar(vit: list[int], base: int = 0, minimo: int = MIN_PARTIDAS_ERA,
               alfa: float = ALFA) -> list[tuple[int, float]]:
    """Segmentação binária recursiva: acha o corte mais significativo, aceita se
    passar de `alfa`, e recorre nos dois lados. Devolve [(índice, p)]."""
    achado = _melhor_quebra(vit, base, minimo)
    if not achado:
        return []
    corte, _z, p = achado
    if p > alfa:
        return []
    rel = corte - base
    return (_segmentar(vit[:rel], base, minimo, alfa)
            + [(corte, p)]
            + _segmentar(vit[rel:], corte, minimo, alfa))


# ------------------------------------------------------------- fronteiras

def _fronteiras_hiato(cenas: list[Cena]) -> list[Fronteira]:
    out = []
    for i in range(1, len(cenas)):
        dias = (cenas[i].data - cenas[i - 1].data).days
        if dias >= HIATO_DIAS:
            out.append(Fronteira(i, "hiato", "certa",
                                 f"{dias} dias sem jogar em grupo"))
    return out


def _fronteiras_elenco(cenas: list[Cena], janela: int = JANELA_ELENCO
                       ) -> list[Fronteira]:
    """Onde o NÚCLEO do time trocou e ficou trocado.

    Compara o núcleo das `janela` partidas anteriores com o das `janela`
    seguintes. Sem a exigência de persistência, cada partida com substituto
    viraria uma fronteira e a história teria 200 capítulos de uma partida.
    """
    out: list[Fronteira] = []
    n = len(cenas)
    if n < 2 * janela:
        return out
    def _dist(a: frozenset, b: frozenset) -> float:
        uniao = a | b
        return len(uniao - (a & b)) / len(uniao) if uniao else 0.0

    candidatos: list[tuple[int, float, float, frozenset, frozenset]] = []
    for i in range(janela, n - janela + 1):
        antes = nucleo(cenas[i - janela:i])
        depois = nucleo(cenas[i:i + janela])
        if not antes or not depois or antes == depois:
            continue
        dist = _dist(antes, depois)
        if dist < 0.2:   # menos de ~1 em 5 do núcleo: não é troca
            continue
        # Contraste LOCAL (3 partidas de cada lado). Sem ele, a janela larga
        # empata em todo um platô de índices — a troca já é "visível" alguns
        # jogos antes de acontecer — e o desempate pelo menor índice colocaria
        # a fronteira até `janela*0.4` partidas ANTES da troca real, jogando o
        # fim de uma era para dentro da seguinte.
        local = _dist(nucleo(cenas[max(0, i - 3):i], limiar=0.5),
                      nucleo(cenas[i:i + 3], limiar=0.5))
        candidatos.append((i, dist, local, antes, depois))

    # Máximos locais: uma troca real gera um platô de candidatos adjacentes, e
    # queremos o pico dele, não a largura toda.
    candidatos.sort(key=lambda c: (-(c[1] + c[2]), c[0]))
    usados: list[int] = []
    for i, _dist_g, _dist_l, antes, depois in candidatos:
        if any(abs(i - u) < janela for u in usados):
            continue
        usados.append(i)
        entrou = sorted(depois - antes)
        saiu = sorted(antes - depois)
        partes = []
        if entrou:
            partes.append("entra " + ", ".join(entrou))
        if saiu:
            partes.append("sai " + ", ".join(saiu))
        out.append(Fronteira(i, "elenco", "certa", "; ".join(partes)))
    return sorted(out, key=lambda f: f.indice)


def _fronteiras_patch(cenas: list[Cena]) -> list[Fronteira]:
    """Virada de temporada (major do patch). Split intra-temporada não é
    detectável só pelo patch, então ficamos com o corte que é inequívoco."""
    out = []
    for i in range(1, len(cenas)):
        a, b = cenas[i - 1].patch, cenas[i].patch
        if not a or not b:
            continue
        if a.split(".")[0] != b.split(".")[0]:
            out.append(Fronteira(i, "patch", "certa", f"temporada {a} -> {b}"))
    return out


def _fronteiras_wr(cenas: list[Cena], blocos: list[int]) -> list[Fronteira]:
    """Quebras estatísticas DENTRO de cada bloco já delimitado pelas fronteiras
    certas. Rodar a segmentação no histórico inteiro faria ela redescobrir as
    mesmas quebras que o calendário já explicou, com menos confiança."""
    out: list[Fronteira] = []
    vit = [int(c.venceu) for c in cenas]
    for ini, fim in zip(blocos, blocos[1:]):
        for idx, p in _segmentar(vit[ini:fim], base=ini):
            out.append(Fronteira(idx, "wr", "estatistica",
                                 f"mudança de winrate (p={p:.3f})", p_valor=p))
    return out


# ------------------------------------------------------------------ forma

def _forma(delta: Optional[float], hiato: Optional[int],
           entraram: list[str], sairam: list[str],
           primeira: bool) -> tuple[str, list[str]]:
    """A curva dramática é CALCULADA, não imaginada.

    A narração recebe 'esta era é uma queda de -18pp' e escreve sobre uma
    queda. Ela não pode decidir que foi uma fase boa porque o texto fluiu
    melhor assim — que é exatamente o que uma LLM faz quando você deixa.
    `sinais` carrega o resto (um capítulo pode ser retomada E ascensão).
    """
    sinais: list[str] = []
    if hiato and hiato >= HIATO_LONGO_DIAS:
        sinais.append(f"volta depois de {hiato} dias parados")
    elif hiato and hiato >= HIATO_DIAS:
        sinais.append(f"volta depois de {hiato} dias")
    if entraram:
        sinais.append("chega " + ", ".join(entraram))
    if sairam:
        sinais.append("sai " + ", ".join(sairam))
    if delta is not None and abs(delta) >= DELTA_WR_NOTAVEL:
        sinais.append(f"winrate {'+' if delta > 0 else ''}{delta}pp vs a era anterior")

    if primeira:
        return "estreia", sinais
    if hiato and hiato >= HIATO_LONGO_DIAS:
        return "retomada", sinais
    if entraram or sairam:
        return "reconstrucao", sinais
    if delta is not None and delta >= DELTA_WR_NOTAVEL:
        return "ascensao", sinais
    if delta is not None and delta <= -DELTA_WR_NOTAVEL:
        return "queda", sinais
    return "plato", sinais


# ------------------------------------------------------------------ público

def detectar(cenas: list[Cena], min_partidas: int = MIN_PARTIDAS_ERA
             ) -> tuple[list[Era], list[Fronteira]]:
    """A série -> eras + as fronteiras que as criaram (para auditoria)."""
    if not cenas:
        return [], []
    n = len(cenas)
    if n < 2 * min_partidas:
        # Histórico curto demais para segmentar sem inventar estrutura.
        return _montar([0, n], cenas, {}), []

    certas = (_fronteiras_hiato(cenas) + _fronteiras_elenco(cenas)
              + _fronteiras_patch(cenas))
    # Dedupe: hiato e troca de elenco costumam cair no mesmo lugar (as pessoas
    # somem e o time se remonta). Mantém a de motivo mais explicativo.
    prioridade = {"elenco": 0, "hiato": 1, "patch": 2, "wr": 3}
    por_indice: dict[int, Fronteira] = {}
    for f in sorted(certas, key=lambda f: prioridade[f.motivo]):
        vizinha = next((k for k in por_indice if abs(k - f.indice) <= 3), None)
        if vizinha is None:
            por_indice[f.indice] = f

    blocos = sorted({0, n} | set(por_indice))
    for f in _fronteiras_wr(cenas, blocos):
        if not any(abs(k - f.indice) <= 3 for k in por_indice):
            por_indice[f.indice] = f

    cortes = _absorver_curtas(sorted({0, n} | set(por_indice)), min_partidas)
    fronteiras = [por_indice[c] for c in cortes if c in por_indice]
    return _montar(cortes, cenas, {f.indice: f for f in fronteiras}), fronteiras


def _absorver_curtas(cortes: list[int], minimo: int) -> list[int]:
    """Funde segmentos menores que o mínimo no vizinho.

    Um trecho de 4 partidas pode ser estatisticamente real e ainda assim não
    ser um capítulo: não dá para contar uma história sobre 4 jogos sem inflar
    ruído em significado. O mínimo é uma decisão narrativa, não estatística.
    """
    cortes = sorted(set(cortes))
    while len(cortes) > 2:
        # o segmento mais curto que ainda está abaixo do mínimo
        curtos = [i for i in range(len(cortes) - 1)
                  if cortes[i + 1] - cortes[i] < minimo]
        if not curtos:
            break
        i = min(curtos, key=lambda k: cortes[k + 1] - cortes[k])

        # Funde com o vizinho MENOR: absorver o trecho curto na era já enorme
        # ao lado apagaria a fase inteira, enquanto juntar os dois pequenos
        # tende a produzir um capítulo do tamanho certo. Nas bordas só há um
        # vizinho possível.
        esq = cortes[i] - cortes[i - 1] if i > 0 else None
        dir_ = cortes[i + 2] - cortes[i + 1] if i + 2 < len(cortes) else None
        if esq is None:
            alvo = i + 1
        elif dir_ is None:
            alvo = i
        else:
            alvo = i if esq <= dir_ else i + 1
        cortes.pop(alvo)
    return cortes


def _montar(cortes: list[int], cenas: list[Cena],
            fronteiras: dict[int, Fronteira]) -> list[Era]:
    eras: list[Era] = []
    anterior: Optional[Era] = None
    for num, (ini, fim) in enumerate(zip(cortes, cortes[1:]), 1):
        trecho = cenas[ini:fim]
        if not trecho:
            continue
        vit = sum(c.venceu for c in trecho)
        w = wr(trecho) or 0.0
        delta = round(w - anterior.wr, 1) if anterior else None
        hiato = ((trecho[0].data - cenas[ini - 1].data).days if ini > 0 else None)

        nuc = nucleo(trecho)
        nuc_ant = frozenset(anterior.nucleo) if anterior else frozenset()
        entraram = sorted(nuc - nuc_ant) if anterior else []
        sairam = sorted(nuc_ant - nuc) if anterior else []

        p_val = None
        f = fronteiras.get(ini)
        if f and f.p_valor is not None:
            p_val = round(f.p_valor, 4)

        forma, sinais = _forma(delta, hiato, entraram, sairam, anterior is None)
        era = Era(
            numero=num, inicio=ini, fim=fim,
            data_inicio=trecho[0].data, data_fim=trecho[-1].data,
            jogos=len(trecho), vitorias=vit, wr=w,
            forma=forma, sinais=sinais, delta_wr=delta, p_valor=p_val,
            nucleo=sorted(nuc), presenca=presenca(trecho),
            entraram=entraram, sairam=sairam, hiato_antes_dias=hiato,
            duracao_media_min=round(sum(c.duracao_seg for c in trecho)
                                    / len(trecho) / 60, 1),
            patches=sorted({c.patch for c in trecho if c.patch}),
            abertura=(f.motivo if f else None),
        )
        eras.append(era)
        anterior = era
    return eras

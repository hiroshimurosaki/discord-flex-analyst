"""Marco — um turning point declarado, e o veredito de quem respondeu a ele.

A cronologia detecta eras a partir do dado (`eras.py`). Isso acha *quando* o
time mudou, mas nunca *por causa de quê* — e há mudanças cuja causa só existe
fora do jogo. Um dossiê apresentado numa call, em que alguém aponta o que cada
um precisa consertar, é exatamente isso: a data é conhecida, a intenção é
conhecida, e o efeito é uma pergunta empírica aberta.

Este módulo responde a pergunta. Para cada apontamento do cânone
(`membro` + `metrica` + `direcao`), mede a métrica nas partidas ANTES e DEPOIS
da data e emite um veredito.

Por que um teste de permutação e não um t de Welch: as métricas aqui são feias
para a teoria — mortes é contagem, `rota` (ouro aos 10) tem cauda pesada, e as
amostras por lado costumam ficar em 10-40 partidas. O teste de permutação não
assume distribuição nenhuma: embaralha os rótulos antes/depois N vezes e conta
quantas vezes o acaso produziu uma diferença tão grande quanto a observada. É
mais honesto justamente onde a amostra é pequena, e cabe em dez linhas.

O p-valor é reprodutível (semente fixa) porque ele vai parar num slide, e um
número que muda a cada execução não é um argumento.
"""
from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, asdict
from typing import Optional

from ..canone import Apontamento, Canone, METRICAS
from . import dossie
from .series import Cena

MIN_LADO = 6          # partidas de cada lado para haver veredito
P_FORTE = 0.05        # abaixo disto a mudança é afirmável
P_SUGESTIVO = 0.20    # entre P_FORTE e isto: indício, não veredito
ITERACOES = 10_000
SEMENTE = 20250529    # a data do dossiê; determinístico e fácil de auditar


def _media(v: list[float]) -> float:
    return sum(v) / len(v)


def _p_permutacao(antes: list[float], depois: list[float],
                  iteracoes: int = ITERACOES, semente: int = SEMENTE) -> float:
    """Probabilidade de o acaso produzir uma diferença tão extrema quanto a vista.

    Bilateral de propósito: 'ele mudou' inclui 'ele piorou', e um dossiê que só
    consegue detectar melhora é um dossiê que já sabia a resposta.
    """
    obs = abs(_media(depois) - _media(antes))
    pool = antes + depois
    n = len(antes)
    rng = random.Random(semente)
    extremos = 0
    for _ in range(iteracoes):
        rng.shuffle(pool)
        if abs(_media(pool[:n]) - _media(pool[n:])) >= obs - 1e-12:
            extremos += 1
    # (+1) no numerador e denominador: sem isso um p=0 afirmaria impossibilidade,
    # que nenhuma amostra finita autoriza.
    return round((extremos + 1) / (iteracoes + 1), 4)


def _melhorou(delta: float, metrica: str, direcao: str) -> bool:
    """O delta anda no sentido pedido?

    Duas inversões se compõem aqui. `morre_pouco` mede mortes, então a QUALIDADE
    sobe quando o número desce. E `direcao='baixo'` pede o contrário do padrão.
    Mesma convenção do `afirma`/`dossie`, de propósito: uma regra só no projeto.
    """
    sinal = -1.0 if metrica == "morre_pouco" else 1.0
    querido = 1.0 if direcao == "alto" else -1.0
    return delta * sinal * querido > 0


@dataclass
class Resposta:
    """Como UMA pessoa respondeu a UM apontamento."""
    membro: str
    tipo: str
    metrica: Optional[str]
    direcao: str
    rotulo_metrica: str
    apontamento: str          # o que foi dito a ela, com as palavras de quem disse
    n_antes: int
    n_depois: int
    media_antes: Optional[float]
    media_depois: Optional[float]
    delta: Optional[float]
    p: Optional[float]
    veredito: str             # atendeu | indicio | inerte | piorou | sem_dado

    def dict(self) -> dict:
        return asdict(self)


def _binaria(cenas: list[Cena], membro: str, pertence) -> list[float]:
    """1.0 quando a partida satisfaz o predicado, 0.0 quando não.

    Serve role e pool: 'parou de jogar ADC' é a média desta série caindo, e a
    média de uma série 0/1 é exatamente a fatia de partidas. O mesmo teste de
    permutação vale aqui sem adaptação — ele nunca soube o que os números
    significavam, só embaralha rótulos.
    """
    return [1.0 if pertence(c) else 0.0 for c in cenas if membro in c.elenco]


def _por_semana(cenas: list[Cena], membro: str) -> list[float]:
    """Partidas por semana, uma entrada por semana do período.

    Volume não é propriedade de uma partida — é uma taxa —, então a série tem
    de ser de semanas, não de jogos. Semanas sem jogo entram como zero de
    propósito: sumir com elas mediria "quando joga, joga quanto", que é outra
    pergunta e responde bonito demais para quem sumiu dois meses.
    """
    meus = sorted(c.ts for c in cenas if membro in c.elenco)
    if not meus:
        return []
    UMA_SEMANA = 7 * 24 * 3600 * 1000
    ini, fim = meus[0], meus[-1]
    n = max(1, int((fim - ini) // UMA_SEMANA) + 1)
    baldes = [0.0] * n
    for ts in meus:
        baldes[min(int((ts - ini) // UMA_SEMANA), n - 1)] += 1.0
    return baldes


def _amostras(cenas: list[Cena], ap: Apontamento,
              corte_ts: int) -> tuple[list[float], list[float], str, str]:
    """(antes, depois, direção desejada, rótulo) para qualquer tipo.

    Normalizar aqui é o que permite um veredito só lá embaixo: seja métrica de
    desempenho, disciplina de role, pool ou volume, tudo vira duas listas de
    números e uma direção.
    """
    antes = [c for c in cenas if c.ts < corte_ts]
    depois = [c for c in cenas if c.ts >= corte_ts]
    m = ap.membro

    if ap.tipo == "metrica":
        return ([v for _, v in dossie.serie(antes, m, ap.metrica)],
                [v for _, v in dossie.serie(depois, m, ap.metrica)],
                ap.direcao, METRICAS.get(ap.metrica, ap.metrica or ""))

    if ap.tipo in ("role_evitada", "role_alvo"):
        alvo = (ap.role or "").upper()

        def pred(c, alvo=alvo, m=m):
            return (c.roles.get(m) or "").upper() == alvo

        # 'evitada' quer a fatia CAINDO: mesma medida, direção virada.
        direcao = "baixo" if ap.tipo == "role_evitada" else "alto"
        return (_binaria(antes, m, pred), _binaria(depois, m, pred), direcao,
                f"% de partidas em {alvo}")

    if ap.tipo == "pool":
        alvo_c = {x.casefold() for x in ap.campeoes}

        def pred(c, alvo_c=alvo_c, m=m):
            return (c.campeoes.get(m) or "").casefold() in alvo_c

        return (_binaria(antes, m, pred), _binaria(depois, m, pred), "alto",
                f"% de partidas em {', '.join(ap.campeoes)}")

    if ap.tipo == "volume":
        return (_por_semana(antes, m), _por_semana(depois, m), "alto",
                "partidas por semana")

    return ([], [], ap.direcao, "sem medida")


def avaliar_ap(cenas: list[Cena], ap: Apontamento, corte_ts: int,
               iteracoes: int = ITERACOES) -> Resposta:
    """Mede um apontamento antes e depois do corte e emite o veredito.

    Cinco vereditos, e cada um é uma cena diferente no slide:

      atendeu    mudou no sentido pedido, e o acaso não explica   -> pagamento
      indicio    mudou no sentido pedido, mas a amostra é curta   -> esperança
      inerte     não mudou de forma distinguível de ruído         -> o dossiê não pegou
      piorou     mudou no sentido contrário                       -> conflito
      sem_dado   não jogou o bastante de um dos lados             -> silêncio honesto
    """
    a, b, direcao, rotulo = _amostras(cenas, ap, corte_ts)
    base = dict(membro=ap.membro, tipo=ap.tipo, metrica=ap.metrica,
                direcao=direcao, rotulo_metrica=rotulo, apontamento=ap.texto,
                n_antes=len(a), n_depois=len(b))

    if ap.tipo == "livre" or len(a) < MIN_LADO or len(b) < MIN_LADO:
        return Resposta(**base, media_antes=None, media_depois=None,
                        delta=None, p=None, veredito="sem_dado")

    ma, mb = _media(a), _media(b)
    delta = mb - ma
    p = _p_permutacao(a, b, iteracoes=iteracoes)

    # A inversão de sinal do `morre_pouco` só existe no vocabulário de
    # desempenho; role, pool e volume já vêm com a direção resolvida em
    # `_amostras`, e por isso passam `metrica=None` aqui.
    met = ap.metrica if ap.tipo == "metrica" else None
    if not _melhorou(delta, met or "", direcao):
        veredito = "piorou" if p <= P_FORTE else "inerte"
    elif p <= P_FORTE:
        veredito = "atendeu"
    elif p <= P_SUGESTIVO:
        veredito = "indicio"
    else:
        veredito = "inerte"

    return Resposta(**base, media_antes=round(ma, 2), media_depois=round(mb, 2),
                    delta=round(delta, 2), p=p, veredito=veredito)


def avaliar_apontamento(cenas: list[Cena], membro: str, metrica: str,
                        direcao: str, apontamento: str, corte_ts: int,
                        iteracoes: int = ITERACOES) -> Resposta:
    """Atalho para o caso `metrica`, que é o mais comum ao testar."""
    return avaliar_ap(cenas, Apontamento(membro=membro, texto=apontamento,
                                         tipo="metrica", metrica=metrica,
                                         direcao=direcao),
                      corte_ts, iteracoes=iteracoes)


def avaliar(cenas: list[Cena], canone: Canone, marco_id: str,
            iteracoes: int = ITERACOES) -> list[Resposta]:
    """Todos os apontamentos de um marco, na ordem em que foram declarados."""
    marco = canone.marco(marco_id)
    if marco is None:
        raise KeyError(f"marco '{marco_id}' não existe no cânone")
    corte = dt.datetime.combine(marco.data, dt.time.min, tzinfo=dt.timezone.utc)
    corte_ts = int(corte.timestamp() * 1000)
    return [avaliar_ap(cenas, ap, corte_ts, iteracoes=iteracoes)
            for ap in marco.apontamentos]

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

from ..canone import Canone, METRICAS
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
    metrica: str
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


def avaliar_apontamento(cenas: list[Cena], membro: str, metrica: str,
                        direcao: str, apontamento: str, corte_ts: int,
                        iteracoes: int = ITERACOES) -> Resposta:
    """Mede uma métrica antes e depois do corte e emite o veredito.

    Cinco vereditos, e cada um é uma cena diferente no slide:

      atendeu    mudou no sentido pedido, e o acaso não explica   -> pagamento
      indicio    mudou no sentido pedido, mas a amostra é curta   -> esperança
      inerte     não mudou de forma distinguível de ruído         -> o dossiê não pegou
      piorou     mudou no sentido contrário                       -> conflito
      sem_dado   não jogou o bastante de um dos lados             -> silêncio honesto
    """
    rotulo = METRICAS.get(metrica, metrica)
    antes_p = [c for c in cenas if c.ts < corte_ts]
    depois_p = [c for c in cenas if c.ts >= corte_ts]
    a = [v for _, v in dossie.serie(antes_p, membro, metrica)]
    b = [v for _, v in dossie.serie(depois_p, membro, metrica)]

    base = dict(membro=membro, metrica=metrica, direcao=direcao,
                rotulo_metrica=rotulo, apontamento=apontamento,
                n_antes=len(a), n_depois=len(b))

    if len(a) < MIN_LADO or len(b) < MIN_LADO:
        return Resposta(**base, media_antes=None, media_depois=None,
                        delta=None, p=None, veredito="sem_dado")

    ma, mb = _media(a), _media(b)
    delta = mb - ma
    p = _p_permutacao(a, b, iteracoes=iteracoes)

    if not _melhorou(delta, metrica, direcao):
        # Piorar só é afirmável com a mesma régua que exigimos para melhorar.
        veredito = "piorou" if p <= P_FORTE else "inerte"
    elif p <= P_FORTE:
        veredito = "atendeu"
    elif p <= P_SUGESTIVO:
        veredito = "indicio"
    else:
        veredito = "inerte"

    return Resposta(**base, media_antes=round(ma, 2), media_depois=round(mb, 2),
                    delta=round(delta, 2), p=p, veredito=veredito)


def avaliar(cenas: list[Cena], canone: Canone, marco_id: str,
            iteracoes: int = ITERACOES) -> list[Resposta]:
    """Todos os apontamentos de um marco, na ordem em que foram declarados."""
    marco = canone.marco(marco_id)
    if marco is None:
        raise KeyError(f"marco '{marco_id}' não existe no cânone")
    corte = dt.datetime.combine(marco.data, dt.time.min, tzinfo=dt.timezone.utc)
    corte_ts = int(corte.timestamp() * 1000)
    return [avaliar_apontamento(cenas, ap.membro, ap.metrica, ap.direcao,
                                ap.texto, corte_ts, iteracoes=iteracoes)
            for ap in marco.apontamentos]

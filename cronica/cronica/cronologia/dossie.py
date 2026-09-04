"""Dossiê de personagem — onde a auto-imagem encontra o dado.

Este módulo é o motor emocional do projeto. Ele não descreve desempenho: ele
compara **o que a pessoa acha que é** com **o que a pessoa mediu ser**, era por
era, e emite um veredito.

Cinco vereditos, e cada um é um tipo de cena diferente:

  confirmado             ele se acha X e sempre foi X          -> orgulho
  contradito             ele se acha X e nunca foi X           -> tensão, comédia
  virou_verdade          não era X, hoje é X                   -> *** EVOLUÇÃO ***
  desmentido_pelo_tempo  era X, hoje não é mais                -> perda, melancolia
  sem_dado               amostra insuficiente                  -> silêncio honesto

`virou_verdade` é a razão de o projeto existir. "O time melhorou 12pp de
winrate" é uma abstração que ninguém sente. "O Lukyy passou dois anos dizendo
que segurava a rota sozinho enquanto perdia 400 de ouro aos 10, e desde março
ele ganha 300" é a mesma informação acontecendo com uma pessoa.

Regra mantida: aqui só se calcula. O texto do veredito é rótulo, não prosa.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from statistics import median
from typing import Optional

from ..canone import Canone, METRICAS
from .series import Cena

MIN_AMOSTRA = 8            # partidas do membro na era para haver veredito
MIN_ERAS_PARA_ARCO = 2     # sem duas eras não existe "virou verdade"


# --------------------------------------------------------------- métricas

def _kda(k: int, d: int, a: int) -> float:
    return (k + a) / max(d, 1)


def _valor(c: Cena, membro: str, metrica: str) -> Optional[float]:
    """O valor de UMA métrica numa ÚNICA partida. `None` = indefinido ali.

    Dano e KP são **share do time**, não absoluto: 25k de dano não significa
    nada sem saber quanto o time todo fez. Normalizar dentro da partida é o que
    torna comparável um jogo de 22 minutos com um de 41.
    """
    if metrica == "dano":
        tot = sum(c.dano.values())
        return 100 * c.dano[membro] / tot if tot else None
    if metrica == "kp":
        v = c.kp.get(membro)
        return 100 * v if v is not None else None
    if metrica == "carrega":
        # Percentil-na-partida: posição do membro entre os DEZ que jogaram
        # aquele jogo. É a régua mais honesta disponível sem baixar o elo do
        # lobby — os dez viveram o mesmo patch, a mesma duração e o mesmo nível
        # de oposição. Medir só contra os quatro companheiros responderia outra
        # pergunta ("quem carregou o time?") e a chamaria pelo nome errado.
        dez = c.dano_dos_dez or tuple(sorted(c.dano.values()))
        if len(dez) < 2:
            return None
        pos = sum(1 for v in dez if v < c.dano[membro])
        return 100 * pos / (len(dez) - 1)
    if metrica == "rota":
        return c.lanediff_10.get(membro)
    if metrica == "visao":
        return c.visao[membro]
    if metrica == "farm":
        return c.farm[membro] / max(c.duracao_seg / 60, 1)
    if metrica == "kda":
        return _kda(*c.kda[membro])
    if metrica == "morre_pouco":
        return c.kda[membro][1]
    raise KeyError(f"métrica desconhecida: {metrica}")


def serie(cenas: list[Cena], membro: str, metrica: str) -> list[tuple[Cena, float]]:
    """A métrica partida a partida, em ordem cronológica.

    Existe porque média não sustenta duas coisas que a história precisa: um
    teste de significância (que exige a dispersão, não só o centro) e um
    gráfico de progressão (que É a série). `medir` passou a ser a média disto.
    """
    fora = []
    for c in cenas:
        if membro not in c.elenco:
            continue
        v = _valor(c, membro, metrica)
        if v is not None:
            fora.append((c, float(v)))
    return fora


def medir(cenas: list[Cena], membro: str) -> dict[str, Optional[float]]:
    """As métricas do membro num trecho — a média de cada `serie`."""
    minhas = [c for c in cenas if membro in c.elenco]
    if not minhas:
        return {m: None for m in METRICAS}

    fora: dict[str, Optional[float]] = {}
    for m in METRICAS:
        vals = [v for _, v in serie(minhas, membro, m)]
        fora[m] = round(sum(vals) / len(vals), 2) if vals else None
    fora["_jogos"] = len(minhas)
    fora["_wr"] = round(100 * sum(c.venceu for c in minhas) / len(minhas), 1)
    return fora


def _sustenta(valor: Optional[float], pares: list[float], direcao: str,
              metrica: str) -> Optional[bool]:
    """A alegação se sustenta neste trecho?

    Comparação contra os COMPANHEIROS, não contra um número absoluto: "eu dou
    muito dano" só quer dizer alguma coisa em relação aos outros quatro. Para
    `morre_pouco` a direção se inverte — menos é melhor.
    """
    if valor is None or len(pares) < 2:
        return None
    corte = median(pares)
    if metrica == "morre_pouco":
        return valor <= corte if direcao == "alto" else valor >= corte
    return valor >= corte if direcao == "alto" else valor <= corte


@dataclass
class Veredito:
    metrica: str
    direcao: str
    alegacao: str
    veredito: str
    rotulo_metrica: str
    valor_inicio: Optional[float] = None
    valor_agora: Optional[float] = None
    mediana_companheiros: Optional[float] = None   # sem o próprio avaliado
    jogos_agora: int = 0
    nota: str = ""

    def para_json(self) -> dict:
        return asdict(self)


@dataclass
class DossiePersonagem:
    membro: str
    nome: str
    jogos: int
    wr: Optional[float]
    metricas: dict[str, Optional[float]]
    metricas_era_anterior: dict[str, Optional[float]] = field(default_factory=dict)
    vereditos: list[Veredito] = field(default_factory=list)
    soloq: dict = field(default_factory=dict)
    presente: bool = True

    def para_json(self) -> dict:
        d = asdict(self)
        d["vereditos"] = [v.para_json() for v in self.vereditos]
        return d


def _metricas_do_time(cenas: list[Cena], membros: list[str], metrica: str,
                      exceto: Optional[str] = None) -> list[float]:
    """Os valores dos COMPANHEIROS na métrica — sem o próprio avaliado.

    Incluir o avaliado no cálculo da mediana contra a qual ele é julgado é um
    erro silencioso e grave: num time de cinco, o valor dele PODE ser a mediana,
    e aí `valor >= mediana` é verdadeiro por construção. O veredito viraria
    'confirmado' sem nenhuma evidência, exatamente nos casos medianos.
    """
    vals = []
    for m in membros:
        if m == exceto:
            continue
        v = medir(cenas, m).get(metrica)
        if v is not None:
            vals.append(v)
    return vals


def dossie_da_era(cenas_era: list[Cena], cenas_primeira_era: list[Cena],
                  canone: Canone, membro: str,
                  cenas_era_anterior: Optional[list[Cena]] = None,
                  soloq: Optional[dict] = None) -> DossiePersonagem:
    """Dossiê de um membro numa era, com veredito sobre cada alegação."""
    p = canone.personagem(membro)
    nome = canone.membros[membro].nome if membro in canone.membros else membro
    m_agora = medir(cenas_era, membro)
    jogos = int(m_agora.get("_jogos") or 0)
    presente = jogos > 0

    d = DossiePersonagem(
        membro=membro, nome=nome, jogos=jogos, wr=m_agora.get("_wr"),
        metricas={k: v for k, v in m_agora.items() if not k.startswith("_")},
        metricas_era_anterior=(
            {k: v for k, v in medir(cenas_era_anterior, membro).items()
             if not k.startswith("_")} if cenas_era_anterior else {}),
        soloq=soloq or {}, presente=presente,
    )

    colegas = sorted({x for c in cenas_era for x in c.elenco})
    m_inicio = medir(cenas_primeira_era, membro)
    colegas_inicio = sorted({x for c in cenas_primeira_era for x in c.elenco})

    for a in p.afirma:
        met, direcao = a["metrica"], a["direcao"]
        # Só herda `se_acha` quando a pessoa tem UMA alegação: com duas ou mais,
        # herdar colaria a mesma frase em métricas diferentes e a narração leria
        # "eu não morro à toa" como alegação sobre farm.
        alegacao = (a.get("texto")
                    or (p.se_acha if len(p.afirma) == 1 else "")
                    or f"se considera {direcao} em {METRICAS[met]}")
        v = Veredito(metrica=met, direcao=direcao, alegacao=alegacao,
                     veredito="sem_dado", rotulo_metrica=METRICAS[met],
                     valor_inicio=m_inicio.get(met), valor_agora=m_agora.get(met),
                     jogos_agora=jogos)

        if jogos < MIN_AMOSTRA:
            v.nota = (f"só {jogos} jogo(s) na era; abaixo do mínimo de "
                      f"{MIN_AMOSTRA} para cravar")
            d.vereditos.append(v)
            continue

        pares_agora = _metricas_do_time(cenas_era, colegas, met, exceto=membro)
        pares_inicio = _metricas_do_time(cenas_primeira_era, colegas_inicio, met,
                                         exceto=membro)
        if pares_agora:
            v.mediana_companheiros = round(median(pares_agora), 2)

        agora = _sustenta(m_agora.get(met), pares_agora, direcao, met)
        inicio = _sustenta(m_inicio.get(met), pares_inicio, direcao, met)

        if agora is None:
            v.nota = "métrica indisponível nesta era (timeline ausente?)"
        elif inicio is None:
            v.veredito = "confirmado" if agora else "contradito"
            v.nota = "sem base de comparação com o início"
        elif agora and inicio:
            v.veredito = "confirmado"
        elif agora and not inicio:
            v.veredito = "virou_verdade"
        elif not agora and inicio:
            v.veredito = "desmentido_pelo_tempo"
        else:
            v.veredito = "contradito"
        d.vereditos.append(v)

    return d


def subtrama_soloq(participacoes: list[dict], inicio_ts: int, fim_ts: int) -> dict:
    """SoloQ como subtrama: a jornada individual dentro da janela da era.

    Nunca vira capítulo. Serve a um tipo de frase que só ela permite: "enquanto
    o time afundava, ele estava subindo sozinho" — ou o contrário, que costuma
    ser mais interessante.
    """
    jan = [p for p in participacoes if inicio_ts <= p["inicio_ts"] <= fim_ts]
    if not jan:
        return {"jogos": 0}
    vit = sum(1 for p in jan if p["win"])
    champs: dict[str, int] = {}
    for p in jan:
        champs[p["campeao"]] = champs.get(p["campeao"], 0) + 1
    return {
        "jogos": len(jan),
        "wr": round(100 * vit / len(jan), 1),
        "kda": round(sum(_kda(p["kills"] or 0, p["deaths"] or 0, p["assists"] or 0)
                         for p in jan) / len(jan), 2),
        "top_campeoes": sorted(champs.items(), key=lambda kv: -kv[1])[:3],
    }

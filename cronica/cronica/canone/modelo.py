"""O cânone — tudo que a Riot API não sabe e só vocês sabem.

Esta é a camada 0 do pipeline (DESIGN.md §4). Ela é escrita à mão, versionada em
YAML, e validada aqui na entrada — porque um typo no `id` de um personagem faria
o dossiê dele sumir silenciosamente do briefing, e um dado faltando calado é pior
que um erro na cara.

O campo que faz mais trabalho é `Personagem.se_acha`: a auto-imagem. O código
cruza ela com o desempenho medido e classifica em confirmado / contradito /
virou_verdade — e é desse cruzamento que sai tensão narrativa em vez de relatório.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

TIPOS_EVENTO = {
    "hiato",          # o grupo parou de jogar
    "mudanca_vida",   # trabalho, faculdade, mudança de cidade, PC novo
    "conquista",      # subiu de elo, bateu meta, ganhou campeonato interno
    "atrito",         # briga, clima ruim, alguém saiu chateado
    "piada_interna",  # o material que dá voz ao grupo
    "marco",          # qualquer virada que vocês consideram divisória
}

VEREDITOS = ("confirmado", "contradito", "virou_verdade",
             "desmentido_pelo_tempo", "sem_dado")

# Vocabulário FECHADO de afirmações mensuráveis.
#
# `se_acha` é texto livre e serve à voz; mas para o código emitir um VEREDITO
# ele precisa de uma alegação que dê para medir. Fechado de propósito: cada
# entrada aqui tem uma métrica correspondente em `cronologia/dossie.py`, e um
# vocabulário aberto viraria uma LLM adivinhando o que "eu seguro a rota"
# significa em número — que é exatamente o que este projeto não faz.
METRICAS = {
    "dano":        "participação no dano do time (%)",
    "carrega":     "percentil dentro da partida (você vs os 10)",
    "rota":        "diferença de ouro aos 10 vs o oponente direto",
    "visao":       "vision score",
    "farm":        "farm por minuto",
    "kda":         "(kills+assists)/mortes",
    "morre_pouco": "mortes por partida",
    "kp":          "participação nos abates (%)",
}
DIRECOES = ("alto", "baixo")


class ErroCanone(Exception):
    """Cânone inválido. Sempre com o caminho do campo que quebrou."""


@dataclass(frozen=True)
class Membro:
    """Uma pessoa no elenco. `riot_ids` é lista porque conta é trocada."""
    id: str
    nome: str
    riot_ids: tuple[str, ...]
    role: Optional[str] = None            # TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY
    titular: bool = True
    entra_no_lugar_de: Optional[str] = None   # só para substitutos
    desde: Optional[str] = None               # 'YYYY-MM' — quando entrou no grupo

    @property
    def puuid_keys(self) -> tuple[tuple[str, str], ...]:
        """('Nome', 'TAG') por Riot ID, pronto para o account-v1."""
        out = []
        for rid in self.riot_ids:
            if "#" not in rid:
                raise ErroCanone(f"elenco.{self.id}: riot_id '{rid}' sem '#TAG'")
            nome, tag = rid.rsplit("#", 1)
            out.append((nome.strip(), tag.strip()))
        return tuple(out)


@dataclass(frozen=True)
class Personagem:
    """A pessoa como personagem. Texto livre é de propósito: é o que dá voz."""
    id: str
    arquetipo: str = ""
    personalidade: str = ""
    se_acha: str = ""                     # auto-imagem -> motor de tensão
    medo: str = ""
    bordoes: tuple[str, ...] = ()
    relacoes: dict[str, str] = field(default_factory=dict)
    # Alegações mensuráveis extraídas de `se_acha`. Cada uma vira um veredito
    # calculado (ver dossie.veredito) — é o que transforma auto-imagem em arco.
    afirma: tuple[dict, ...] = ()

    @property
    def preenchido(self) -> bool:
        """Vazio não é erro (dá para rodar o pipeline sem cânone), mas o
        briefing precisa saber para não fingir que conhece a pessoa."""
        return bool(self.arquetipo or self.personalidade or self.se_acha)


@dataclass(frozen=True)
class Evento:
    """Um marco fora do jogo, datado. Ancorado numa era pela cronologia."""
    data: dt.date
    tipo: str
    titulo: str
    texto: str = ""
    envolvidos: tuple[str, ...] = ()


@dataclass(frozen=True)
class Canone:
    time: str
    desde: Optional[str]
    membros: dict[str, Membro]
    personagens: dict[str, Personagem]
    eventos: tuple[Evento, ...]
    voz: str = ""          # instrução de tom que vai no prompt da narração

    # ---- consultas que o resto do pipeline usa ----
    @property
    def titulares(self) -> list[Membro]:
        return [m for m in self.membros.values() if m.titular]

    @property
    def substitutos(self) -> list[Membro]:
        return [m for m in self.membros.values() if not m.titular]

    def personagem(self, mid: str) -> Personagem:
        return self.personagens.get(mid, Personagem(id=mid))

    def eventos_entre(self, inicio: dt.date, fim: dt.date) -> list[Evento]:
        return [e for e in self.eventos if inicio <= e.data <= fim]

    def por_riot_id(self, riot_id: str) -> Optional[Membro]:
        alvo = riot_id.strip().casefold()
        for m in self.membros.values():
            if any(r.strip().casefold() == alvo for r in m.riot_ids):
                return m
        return None


# ------------------------------------------------------------------ carga

def _exigir(cond: bool, msg: str) -> None:
    if not cond:
        raise ErroCanone(msg)


def _texto(v: Any) -> str:
    """YAML devolve None para chave vazia; trata como string vazia."""
    return "" if v is None else str(v).strip()


def _lista_texto(v: Any, onde: str) -> tuple[str, ...]:
    if v is None:
        return ()
    _exigir(isinstance(v, list), f"{onde}: esperava lista, veio {type(v).__name__}")
    return tuple(_texto(x) for x in v if _texto(x))


def _data(v: Any, onde: str) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError as exc:
        raise ErroCanone(f"{onde}: data inválida '{v}' (use YYYY-MM-DD)") from exc


def _membro(mid: str, bruto: dict, titular: bool) -> Membro:
    onde = f"elenco.{'titulares' if titular else 'substitutos'}.{mid}"
    _exigir(isinstance(bruto, dict), f"{onde}: esperava mapa de campos")
    rids = bruto.get("riot_ids") or ([bruto["riot_id"]] if bruto.get("riot_id") else [])
    _exigir(bool(rids), f"{onde}: precisa de 'riot_id' ou 'riot_ids'")
    role = _texto(bruto.get("role")).upper() or None
    m = Membro(
        id=mid,
        nome=_texto(bruto.get("nome")) or mid,
        riot_ids=_lista_texto(rids, f"{onde}.riot_ids"),
        role=role,
        titular=titular,
        entra_no_lugar_de=_texto(bruto.get("entra_no_lugar_de")) or None,
        desde=_texto(bruto.get("desde")) or None,
    )
    m.puuid_keys  # valida as grafias agora, não na hora da chamada HTTP
    return m


def carregar(caminho: Path | str) -> Canone:
    """Lê e valida o YAML do cânone. Falha alto, com o campo culpado no erro."""
    caminho = Path(caminho)
    _exigir(caminho.exists(), f"cânone não encontrado: {caminho}")
    bruto = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    _exigir(isinstance(bruto, dict), "raiz do cânone deve ser um mapa")

    time_ = bruto.get("time") or {}
    _exigir(isinstance(time_, dict), "time: esperava mapa")

    elenco = bruto.get("elenco") or {}
    _exigir(isinstance(elenco, dict), "elenco: esperava mapa")
    membros: dict[str, Membro] = {}
    for chave, titular in (("titulares", True), ("substitutos", False)):
        grupo = elenco.get(chave) or {}
        _exigir(isinstance(grupo, dict),
                f"elenco.{chave}: esperava mapa id -> campos")
        for mid, dados in grupo.items():
            _exigir(mid not in membros, f"elenco: id duplicado '{mid}'")
            membros[str(mid)] = _membro(str(mid), dados or {}, titular)
    _exigir(bool(membros), "elenco: nenhum membro declarado")

    # Substituto tem de apontar para alguém que existe, senão o papel narrativo
    # "entrou no lugar do X" some do briefing sem ninguém notar.
    for m in membros.values():
        if m.entra_no_lugar_de:
            _exigir(m.entra_no_lugar_de in membros,
                    f"elenco.{m.id}.entra_no_lugar_de: '{m.entra_no_lugar_de}' "
                    f"não está no elenco")

    pers_bruto = bruto.get("personagens") or {}
    _exigir(isinstance(pers_bruto, dict), "personagens: esperava mapa")
    personagens: dict[str, Personagem] = {}
    for pid, dados in pers_bruto.items():
        pid = str(pid)
        _exigir(pid in membros,
                f"personagens.{pid}: não existe no elenco (typo no id?)")
        dados = dados or {}
        relacoes = dados.get("relacoes") or {}
        _exigir(isinstance(relacoes, dict), f"personagens.{pid}.relacoes: esperava mapa")
        for outro in relacoes:
            _exigir(str(outro) in membros,
                    f"personagens.{pid}.relacoes.{outro}: id fora do elenco")
        afirma_bruto = dados.get("afirma") or []
        _exigir(isinstance(afirma_bruto, list), f"personagens.{pid}.afirma: esperava lista")
        afirma = []
        for j, a in enumerate(afirma_bruto):
            onde = f"personagens.{pid}.afirma[{j}]"
            _exigir(isinstance(a, dict), f"{onde}: esperava mapa")
            met = _texto(a.get("metrica"))
            direcao = _texto(a.get("direcao")) or "alto"
            _exigir(met in METRICAS,
                    f"{onde}.metrica: '{met}' inválida (use: {sorted(METRICAS)})")
            _exigir(direcao in DIRECOES,
                    f"{onde}.direcao: '{direcao}' inválida (use: {list(DIRECOES)})")
            afirma.append({"metrica": met, "direcao": direcao,
                           "texto": _texto(a.get("texto"))})

        personagens[pid] = Personagem(
            id=pid,
            arquetipo=_texto(dados.get("arquetipo")),
            personalidade=_texto(dados.get("personalidade")),
            se_acha=_texto(dados.get("se_acha")),
            medo=_texto(dados.get("medo")),
            bordoes=_lista_texto(dados.get("bordoes"), f"personagens.{pid}.bordoes"),
            relacoes={str(k): _texto(v) for k, v in relacoes.items()},
            afirma=tuple(afirma),
        )

    ev_bruto = bruto.get("eventos") or []
    _exigir(isinstance(ev_bruto, list), "eventos: esperava lista")
    eventos = []
    for i, e in enumerate(ev_bruto):
        onde = f"eventos[{i}]"
        _exigir(isinstance(e, dict), f"{onde}: esperava mapa")
        tipo = _texto(e.get("tipo")) or "marco"
        _exigir(tipo in TIPOS_EVENTO,
                f"{onde}.tipo: '{tipo}' inválido (use: {sorted(TIPOS_EVENTO)})")
        envolvidos = _lista_texto(e.get("envolvidos"), f"{onde}.envolvidos")
        for x in envolvidos:
            _exigir(x in membros, f"{onde}.envolvidos: '{x}' não está no elenco")
        eventos.append(Evento(
            data=_data(e.get("data"), f"{onde}.data"),
            tipo=tipo,
            titulo=_texto(e.get("titulo")) or "(sem título)",
            texto=_texto(e.get("texto")),
            envolvidos=envolvidos,
        ))
    eventos.sort(key=lambda e: e.data)

    return Canone(
        time=_texto(time_.get("nome")) or "o time",
        desde=_texto(time_.get("desde")) or None,
        membros=membros,
        personagens=personagens,
        eventos=tuple(eventos),
        voz=_texto(bruto.get("voz")),
    )

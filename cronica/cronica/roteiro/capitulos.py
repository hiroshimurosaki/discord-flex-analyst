"""Era -> capítulo. O roteiro completo, antes de qualquer palavra ser escrita.

Esta é a fronteira do projeto: tudo até aqui é determinístico e auditável;
depois daqui é prosa. Um `Capitulo` contém exatamente o que a história vai
poder dizer — cenas escaladas, dossiês, eventos do cânone e os LIMITES da
amostra. Se o capítulo 7 ficou ruim, o defeito está aqui ou antes, nunca no
prompt.

O `contexto` que atravessa os capítulos é o que os torna uma sequência em vez
de uma coleção: estreias já usadas, recordes já batidos, todo o passado
disponível para o seletor `espelho`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..canone import Canone
from ..cronologia import dossie as dossie_mod
from ..cronologia.eras import Era
from ..cronologia.series import Cena
from . import momentos as mom


@dataclass
class Capitulo:
    numero: int
    era: Era
    titulo_provisorio: str            # rótulo do código; a LLM batiza de verdade
    momentos: list[mom.Momento]
    dossies: list[dossie_mod.DossiePersonagem]
    eventos: list[dict]
    limites: list[str]
    comparacao: dict = field(default_factory=dict)

    def para_json(self) -> dict:
        return {
            "numero": self.numero,
            "era": self.era.para_json(),
            "titulo_provisorio": self.titulo_provisorio,
            "momentos": [m.para_json() for m in self.momentos],
            "dossies": [d.para_json() for d in self.dossies],
            "eventos": self.eventos,
            "limites": self.limites,
            "comparacao": self.comparacao,
        }


ROTULO_FORMA = {
    "estreia": "O começo",
    "ascensao": "A subida",
    "plato": "O platô",
    "queda": "A queda",
    "reconstrucao": "A reconstrução",
    "retomada": "A volta",
}


def _limites(era: Era, cap_dossies: list[dossie_mod.DossiePersonagem]) -> list[str]:
    """O que a amostra NÃO permite afirmar.

    Gerado por código a partir de tamanhos de amostra e p-valores, e repassado
    literalmente ao prompt. É o que impede a história de virar mitologia: onde o
    dado é fraco, o briefing diz que é fraco, e a narração é proibida de cravar.
    """
    out: list[str] = []
    if era.jogos < 20:
        out.append(f"A era tem só {era.jogos} partidas: winrate de {era.wr}% "
                   f"carrega margem grande. Trate como indício.")
    if era.p_valor is not None and era.p_valor > 0.01:
        out.append(f"A fronteira que abre esta era é estatística (p={era.p_valor}); "
                   f"é sugestiva, não conclusiva. Não afirme que 'algo mudou' "
                   f"como fato — diga que os números apontam nessa direção.")
    if era.abertura in ("hiato", "elenco", "patch"):
        out.append(f"A fronteira desta era é de calendário/elenco ({era.abertura}), "
                   f"ou seja, é fato verificável — pode afirmar.")
    if era.delta_wr is not None and abs(era.delta_wr) < 5:
        out.append(f"A diferença de winrate para a era anterior é de "
                   f"{era.delta_wr}pp: pequena. Não construa uma virada em cima disso.")
    fracos = [d.nome for d in cap_dossies if d.presente and d.jogos < dossie_mod.MIN_AMOSTRA]
    if fracos:
        out.append(f"Amostra pequena nesta era para: {', '.join(fracos)}. "
                   f"Não emita veredito sobre eles.")
    ausentes = [d.nome for d in cap_dossies if not d.presente]
    if ausentes:
        out.append(f"Não jogaram nenhuma partida desta era: {', '.join(ausentes)}. "
                   f"Não os cite como presentes.")
    return out


def montar(cenas: list[Cena], eras: list[Era], canone: Canone,
           soloq_por_membro: Optional[dict[str, list[dict]]] = None
           ) -> list[Capitulo]:
    """Todos os capítulos, em ordem, com o contexto correndo entre eles."""
    soloq_por_membro = soloq_por_membro or {}
    titulares = {m.id for m in canone.titulares}
    substitutos = {m.id for m in canone.substitutos}

    contexto: dict = {
        "titulares": titulares,
        "substitutos": substitutos,
        "estreias": set(),
        "recordes": {},
        "rodizio_picos": [],
        "passado": [],
        "anotacoes": canone.partidas,
    }

    primeira_era_cenas = cenas[eras[0].inicio:eras[0].fim] if eras else []
    caps: list[Capitulo] = []
    anterior: Optional[Era] = None

    for i, era in enumerate(eras):
        trecho = cenas[era.inicio:era.fim]
        contexto["primeira_era"] = (i == 0)
        contexto["passado"] = cenas[:era.inicio]

        escalados = mom.escalar(trecho, contexto, maximo=6)

        trecho_anterior = (cenas[eras[i - 1].inicio:eras[i - 1].fim]
                           if i > 0 else None)
        ini_ts, fim_ts = trecho[0].ts, trecho[-1].ts
        dossies = []
        for mid in sorted(canone.membros):
            dossies.append(dossie_mod.dossie_da_era(
                trecho, primeira_era_cenas, canone, mid,
                cenas_era_anterior=trecho_anterior,
                soloq=dossie_mod.subtrama_soloq(
                    soloq_por_membro.get(mid, []), ini_ts, fim_ts),
            ))

        eventos = [
            {"data": e.data.isoformat(), "tipo": e.tipo, "titulo": e.titulo,
             "texto": e.texto, "envolvidos": list(e.envolvidos)}
            for e in canone.eventos_entre(era.data_inicio, era.data_fim)
        ]

        comparacao = {}
        if anterior:
            comparacao = {
                "era_anterior": anterior.numero,
                "wr_anterior": anterior.wr, "wr_atual": era.wr,
                "delta_wr": era.delta_wr,
                "duracao_media_anterior": anterior.duracao_media_min,
                "duracao_media_atual": era.duracao_media_min,
                "nucleo_anterior": anterior.nucleo, "nucleo_atual": era.nucleo,
            }

        caps.append(Capitulo(
            numero=era.numero, era=era,
            titulo_provisorio=ROTULO_FORMA.get(era.forma, "Capítulo"),
            momentos=escalados, dossies=dossies, eventos=eventos,
            limites=_limites(era, dossies), comparacao=comparacao,
        ))
        anterior = era
    return caps

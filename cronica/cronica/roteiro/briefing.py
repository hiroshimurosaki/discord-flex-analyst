"""Capítulo -> briefing. O contrato com a LLM.

Um markdown por capítulo contendo **tudo que a narração pode usar e nada além**.
Se um número não está aqui, ele não pode aparecer na história. Como o briefing é
gerado por código e é legível por você, a regra "a LLM não inventa número" deixa
de ser combinada e passa a ser verificável: leu algo estranho no capítulo 7?
abre `saida/briefings/cap07.md` e confere de onde veio.

O briefing também é o ponto de edição humano. Quer que o capítulo fale de uma
partida específica? Adiciona a cena aqui. É por isso que ele é markdown, e não
JSON: você tem que conseguir mexer.
"""
from __future__ import annotations

from typing import Optional

from ..canone import Canone
from ..cronologia.dossie import DossiePersonagem
from .capitulos import Capitulo

EXPLICA_VEREDITO = {
    "confirmado": "os números batem com a auto-imagem",
    "contradito": "os números NÃO batem com a auto-imagem",
    "virou_verdade": "não batia no começo da história e bate agora — isto é evolução medida",
    "desmentido_pelo_tempo": "batia no começo e não bate mais",
    "sem_dado": "amostra insuficiente para dizer",
}


def _tab(linhas: list[list[str]], cabecalho: list[str]) -> str:
    out = ["| " + " | ".join(cabecalho) + " |",
           "|" + "|".join("---" for _ in cabecalho) + "|"]
    for l in linhas:
        out.append("| " + " | ".join("—" if v is None or v == "" else str(v)
                                     for v in l) + " |")
    return "\n".join(out)


def _nome(canone: Canone, mid: str) -> str:
    m = canone.membros.get(mid)
    return m.nome if m else mid


def _bloco_composicao(canone: Canone, ficha: dict) -> str:
    linhas = []
    for mid in ficha.get("elenco", []):
        linhas.append([_nome(canone, mid), ficha["roles"].get(mid),
                       ficha["composicao"].get(mid), ficha["kda"].get(mid)])
    return _tab(linhas, ["jogador", "rota", "campeão", "K/D/A"])


def _momento_md(canone: Canone, m, nivel: str = "###") -> str:
    p = [f"{nivel} [{m.papel}] {m.titulo}",
         f"*{m.porque}*", ""]
    if m.inferencia:
        p.append("> **Critério, não verdade.** Esta cena foi escolhida por um "
                 "critério mecânico. Não escreva que foi 'a melhor partida dele' — "
                 "escreva o que os números mostram.\n")

    if m.papel == "espelho":
        d = m.dados
        p.append(f"**{d['direcao']}** · {d['dias_entre']} dias entre as duas · "
                 f"similaridade de composição {d['similaridade']}\n")
        for rot, chave in (("ANTES", "antes"), ("DEPOIS", "depois")):
            f = d[chave]
            p.append(f"**{rot} — {f['data']} · {f['resultado']} · "
                     f"{f['duracao_min']} min**\n")
            p.append(_bloco_composicao(canone, f) + "\n")
        ld_a, ld_d = d.get("lanediff_10_antes", {}), d.get("lanediff_10_depois", {})
        comuns = [k for k in ld_d if k in ld_a and ld_a[k] is not None
                  and ld_d[k] is not None]
        if comuns:
            p.append("**Ouro aos 10 vs o oponente direto — antes e depois:**\n")
            p.append(_tab([[_nome(canone, k), ld_a[k], ld_d[k],
                            f"{ld_d[k] - ld_a[k]:+d}"] for k in sorted(comuns)],
                          ["jogador", "antes", "depois", "delta"]) + "\n")
        return "\n".join(p)

    d = m.dados
    if "elenco" in d:
        cab = (f"**{d.get('data')} · {d.get('resultado')} · "
               f"{d.get('duracao_min')} min**")
        if d.get("patch"):
            cab += f" · patch {d['patch']}"
        p.append(cab + "\n")
        p.append(_bloco_composicao(canone, d) + "\n")
        if d.get("oponentes_por_rota"):
            p.append("Adversários por rota: " + ", ".join(
                f"{r}: {c}" for r, c in sorted(d["oponentes_por_rota"].items())) + "\n")
        if d.get("deficit_max_ouro") is not None:
            p.append(f"Ouro: pior momento {-d['deficit_max_ouro']}, "
                     f"melhor momento +{d.get('pico_max_ouro', 0)}\n")

    extras = {k: v for k, v in d.items() if k not in {
        "elenco", "composicao", "roles", "kda", "oponentes_por_rota", "data",
        "resultado", "duracao_min", "patch", "partida_id", "match_id",
        "deficit_max_ouro", "pico_max_ouro", "antes", "depois"}}
    if extras:
        p.append(_tab([[k, v] for k, v in extras.items()], ["dado", "valor"]) + "\n")
    return "\n".join(p)


def _dossie_md(canone: Canone, d: DossiePersonagem) -> str:
    per = canone.personagem(d.membro)
    p = [f"### {d.nome}"]
    if not d.presente:
        return "\n".join(p + ["*Não jogou nenhuma partida desta era. "
                              "Não cite como presente.*", ""])

    if per.arquetipo:
        p.append(f"**Arquétipo:** {per.arquetipo}")
    if per.personalidade:
        p.append(f"**Personalidade:** {per.personalidade}")
    if per.medo:
        p.append(f"**Medo:** {per.medo}")
    if per.bordoes:
        p.append("**Fala:** " + " · ".join(f'"{b}"' for b in per.bordoes))
    if per.relacoes:
        p.append("**Relações:** " + "; ".join(
            f"{_nome(canone, k)} — {v}" for k, v in per.relacoes.items()))
    if not per.preenchido:
        p.append("> Sem cânone preenchido para esta pessoa. **Não invente "
                 "personalidade**: fale só do que os números mostram.")
    p.append("")

    p.append(f"**Nesta era:** {d.jogos} jogos, {d.wr}% de vitória\n")
    rot = {"dano": "share de dano do time (%)", "carrega": "percentil na partida",
           "rota": "ouro@10 vs oponente direto", "visao": "vision score",
           "farm": "farm/min", "kda": "KDA", "morre_pouco": "mortes/jogo",
           "kp": "participação em abates (%)"}
    linhas = []
    for k, r in rot.items():
        atual = d.metricas.get(k)
        ant = d.metricas_era_anterior.get(k)
        delta = (round(atual - ant, 2) if atual is not None and ant is not None
                 else None)
        linhas.append([r, atual, ant, f"{delta:+}" if delta is not None else None])
    p.append(_tab(linhas, ["métrica", "esta era", "era anterior", "delta"]) + "\n")

    if per.se_acha:
        p.append(f"**Ele diz de si mesmo:** \"{per.se_acha}\"\n")
    if d.vereditos:
        p.append("**Auto-imagem vs. dado medido:**\n")
        for v in d.vereditos:
            p.append(f"- `{v.veredito}` — *{v.alegacao}* "
                     f"({v.rotulo_metrica}): no começo da história "
                     f"{v.valor_inicio}, nesta era {v.valor_agora}, "
                     f"mediana dos companheiros {v.mediana_companheiros}. "
                     f"→ {EXPLICA_VEREDITO[v.veredito]}."
                     + (f" ⚠ {v.nota}" if v.nota else ""))
        p.append("")
    elif per.se_acha:
        p.append("> A auto-imagem acima não tem alegação mensurável declarada "
                 "(`afirma` vazio no cânone). Você pode **relacioná-la** com os "
                 "números da tabela, mas não pode afirmar que ela é falsa ou "
                 "verdadeira como se tivesse sido medida.\n")

    if d.soloq.get("jogos"):
        s = d.soloq
        champs = ", ".join(f"{c} ({n})" for c, n in s.get("top_campeoes", []))
        p.append(f"**Subtrama — SoloQ no mesmo período:** {s['jogos']} jogos, "
                 f"{s['wr']}% WR, KDA {s['kda']}. Mais jogados: {champs}\n")
    return "\n".join(p)


def gerar(cap: Capitulo, canone: Canone, biblia: Optional[dict] = None) -> str:
    """O briefing completo de um capítulo, em markdown."""
    e = cap.era
    p: list[str] = []
    p.append(f"# Capítulo {cap.numero:02d} — {cap.titulo_provisorio}")
    p.append(f"\n**Forma detectada pelo código:** `{e.forma}`  ")
    p.append(f"**Período:** {e.data_inicio} a {e.data_fim}  ")
    p.append(f"**Partidas:** {e.jogos} ({e.vitorias}V / {e.jogos - e.vitorias}D) "
             f"— {e.wr}% de vitória\n")

    p.append("## Números da era\n")
    linhas = [["winrate", f"{e.wr}%"],
              ["duração média", f"{e.duracao_media_min} min"],
              ["núcleo do time", ", ".join(_nome(canone, m) for m in e.nucleo) or "—"],
              ["patches", ", ".join(e.patches) or "—"]]
    if e.hiato_antes_dias:
        linhas.append(["dias parados antes desta era", e.hiato_antes_dias])
    if e.abertura:
        linhas.append(["o que abriu esta era", e.abertura])
    if e.p_valor is not None:
        linhas.append(["p-valor da fronteira", e.p_valor])
    p.append(_tab(linhas, ["dado", "valor"]) + "\n")

    if e.sinais:
        p.append("**Sinais detectados:** " + "; ".join(e.sinais) + "\n")

    p.append("**Presença por jogador nesta era:**\n")
    p.append(_tab([[_nome(canone, m), f"{int(f * 100)}%"]
                   for m, f in e.presenca.items()], ["jogador", "jogou"]) + "\n")

    if cap.comparacao:
        c = cap.comparacao
        p.append("## Comparação com a era anterior\n")
        p.append(_tab([
            ["winrate", f"{c['wr_anterior']}%", f"{c['wr_atual']}%",
             f"{c['delta_wr']:+}pp" if c.get("delta_wr") is not None else None],
            ["duração média", c.get("duracao_media_anterior"),
             c.get("duracao_media_atual"), None],
            ["núcleo", ", ".join(_nome(canone, m) for m in c["nucleo_anterior"]),
             ", ".join(_nome(canone, m) for m in c["nucleo_atual"]), None],
        ], ["", "era anterior", "esta era", "delta"]) + "\n")

    if cap.eventos:
        p.append("## O que aconteceu fora do jogo (cânone)\n")
        for ev in cap.eventos:
            quem = (" — envolvidos: " + ", ".join(_nome(canone, x)
                                                  for x in ev["envolvidos"])
                    if ev["envolvidos"] else "")
            p.append(f"- **{ev['data']}** `{ev['tipo']}` **{ev['titulo']}**{quem}")
            if ev["texto"]:
                p.append(f"  \n  {ev['texto']}")
        p.append("")

    p.append("## Cenas escaladas\n")
    if not cap.momentos:
        p.append("*Nenhuma cena passou nos critérios de escalação nesta era. "
                 "Conte a era pelos agregados e pelos dossiês — não invente uma "
                 "partida específica.*\n")
    for m in cap.momentos:
        p.append(_momento_md(canone, m))
        p.append("")

    p.append("## Dossiê de personagem\n")
    for d in cap.dossies:
        p.append(_dossie_md(canone, d))
        p.append("")

    if biblia:
        p.append("## Bíblia — o que JÁ foi contado (não repita)\n")
        if biblia.get("resumo_ate_aqui"):
            p.append("**A história até aqui:**\n")
            p.append(biblia["resumo_ate_aqui"] + "\n")
        if biblia.get("fatos_contados"):
            p.append("**Fatos já usados** (não reconte):")
            for f in biblia["fatos_contados"][-25:]:
                p.append(f"- {f}")
            p.append("")
        if biblia.get("imagens_usadas"):
            p.append("**Imagens/metáforas já gastas** (procure outras): "
                     + "; ".join(biblia["imagens_usadas"][-20:]) + "\n")
        if biblia.get("estado_emocional"):
            p.append(f"**Onde o capítulo anterior terminou:** "
                     f"{biblia['estado_emocional']}\n")
        if biblia.get("promessas_abertas"):
            p.append("**Promessas em aberto** (pague ou adie conscientemente):")
            for pr in biblia["promessas_abertas"]:
                p.append(f"- {pr}")
            p.append("")

    p.append("## Limites — o que este capítulo NÃO pode afirmar\n")
    for l in cap.limites:
        p.append(f"- {l}")
    p.append("- Posição na timeline é amostrada a cada 60s. Motivação, tilt e "
             "intenção **não são dados**. Se for interpretar, escreva "
             "\"os números apontam\", nunca \"ele estava\".")
    p.append("- Nenhum número fora deste arquivo pode aparecer no capítulo.")
    p.append("")
    return "\n".join(p)

"""Gráficos em SVG gerado por código. Sem matplotlib, sem JS.

Motivo: o deck precisa abrir em qualquer lugar daqui a três anos — no navegador
de alguém, num PDF exportado, num print colado no grupo. SVG inline sempre abre;
uma imagem gerada por uma versão de matplotlib que ninguém mais tem, não.

Todos usam `currentColor` e uma paleta passada por parâmetro, então herdam o
tema do slide em vez de carregar um fundo branco para dentro de um deck escuro.
"""
from __future__ import annotations

from typing import Optional, Sequence

CORES_FORMA = {
    "estreia": "#7c8db5", "ascensao": "#3f9e6b", "plato": "#8a8f98",
    "queda": "#c25a5a", "reconstrucao": "#b08a3e", "retomada": "#5b8ec4",
}


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def linha_do_tempo(eras: Sequence, largura: int = 1000, altura: int = 260,
                   titulo: str = "") -> str:
    """A história inteira numa faixa: uma banda por era, altura = winrate.

    É o gráfico que responde "como foi a evolução?" sem ninguém precisar ler
    número nenhum — a silhueta já conta.
    """
    if not eras:
        return "<svg/>"
    pad_e, pad_b, pad_t = 44, 42, 30 if titulo else 14
    larg_util = largura - pad_e - 16
    alt_util = altura - pad_b - pad_t
    total = sum(e.jogos for e in eras) or 1

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
         f'role="img" aria-label="Winrate por era">']
    if titulo:
        p.append(f'<text x="0" y="16" font-size="14" font-weight="600" '
                 f'fill="currentColor">{_esc(titulo)}</text>')

    for pct in (0, 25, 50, 75, 100):
        y = pad_t + alt_util * (1 - pct / 100)
        tracejado = ' stroke-dasharray="4 4"' if pct == 50 else ''
        p.append(f'<line x1="{pad_e}" y1="{y:.1f}" x2="{largura - 16}" y2="{y:.1f}" '
                 f'stroke="currentColor" stroke-opacity="{0.28 if pct == 50 else 0.10}" '
                 f'stroke-width="1"{tracejado}/>')
        p.append(f'<text x="{pad_e - 8}" y="{y + 4:.1f}" text-anchor="end" '
                 f'font-size="11" fill="currentColor" fill-opacity="0.6">{pct}%</text>')

    x = pad_e
    for e in eras:
        w = max(larg_util * e.jogos / total, 3)
        h = alt_util * (e.wr / 100)
        y = pad_t + alt_util - h
        cor = CORES_FORMA.get(e.forma, "#8a8f98")
        p.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w - 2:.1f}" height="{h:.1f}" '
                 f'fill="{cor}" rx="3"><title>Era {e.numero} · {e.forma} · '
                 f'{e.jogos} jogos · {e.wr}%</title></rect>')
        if w > 26:
            p.append(f'<text x="{x + w / 2 - 1:.1f}" y="{y - 5:.1f}" '
                     f'text-anchor="middle" font-size="11" font-weight="600" '
                     f'fill="currentColor">{e.wr:.0f}%</text>')
        if w > 40:
            p.append(f'<text x="{x + w / 2 - 1:.1f}" y="{pad_t + alt_util + 15:.1f}" '
                     f'text-anchor="middle" font-size="10" fill="currentColor" '
                     f'fill-opacity="0.75">{e.numero}</text>')
        x += w

    p.append(f'<text x="{pad_e}" y="{altura - 8}" font-size="10" '
             f'fill="currentColor" fill-opacity="0.6">{_esc(str(eras[0].data_inicio))}</text>')
    p.append(f'<text x="{largura - 16}" y="{altura - 8}" text-anchor="end" '
             f'font-size="10" fill="currentColor" fill-opacity="0.6">'
             f'{_esc(str(eras[-1].data_fim))}</text>')
    p.append("</svg>")
    return "".join(p)


def sparkline(valores: Sequence[float], largura: int = 220, altura: int = 48,
              cor: str = "currentColor") -> str:
    """Curva minúscula, para caber ao lado de um número num slide."""
    vals = [v for v in valores if v is not None]
    if len(vals) < 2:
        return "<svg/>"
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    passo = (largura - 4) / (len(vals) - 1)
    pts = " ".join(f"{2 + i * passo:.1f},{2 + (altura - 4) * (1 - (v - lo) / span):.1f}"
                   for i, v in enumerate(vals))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}">'
            f'<polyline points="{pts}" fill="none" stroke="{cor}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>')


def barras_comparadas(rotulos: Sequence[str], antes: Sequence[Optional[float]],
                      depois: Sequence[Optional[float]], largura: int = 620,
                      titulo: str = "") -> str:
    """Antes vs. depois, par a par. É o gráfico do `espelho` e do dossiê —
    a única forma visual que mostra evolução em vez de estado."""
    pares = [(r, a, d) for r, a, d in zip(rotulos, antes, depois)
             if a is not None and d is not None]
    if not pares:
        return "<svg/>"
    lin_h, pad_e, pad_t = 30, 130, 26 if titulo else 8
    altura = pad_t + len(pares) * lin_h + 8
    maxv = max(max(abs(a), abs(d)) for _, a, d in pares) or 1
    escala = (largura - pad_e - 70) / maxv

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}">']
    if titulo:
        p.append(f'<text x="0" y="14" font-size="13" font-weight="600" '
                 f'fill="currentColor">{_esc(titulo)}</text>')
    for i, (rot, a, d) in enumerate(pares):
        y = pad_t + i * lin_h
        p.append(f'<text x="0" y="{y + 15}" font-size="12" fill="currentColor">'
                 f'{_esc(rot)}</text>')
        p.append(f'<rect x="{pad_e}" y="{y + 3}" width="{max(abs(a) * escala, 1):.1f}" '
                 f'height="8" fill="currentColor" fill-opacity="0.28" rx="2"/>')
        cor = "#3f9e6b" if d >= a else "#c25a5a"
        p.append(f'<rect x="{pad_e}" y="{y + 13}" width="{max(abs(d) * escala, 1):.1f}" '
                 f'height="8" fill="{cor}" rx="2"/>')
        p.append(f'<text x="{largura - 4}" y="{y + 17}" text-anchor="end" '
                 f'font-size="11" fill="currentColor" fill-opacity="0.8">'
                 f'{a:g} → {d:g}</text>')
    p.append("</svg>")
    return "".join(p)

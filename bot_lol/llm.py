"""Fronteira da LLM — `analisar(contexto) -> texto`.

Regra de ouro (bot-lol.md, seção 2): a LLM NUNCA calcula; ela só narra
números que o código já calculou. Trocar de provedor/modelo = mexer só aqui.

Provedor atual: Gemini (tier gratuito). O nome exato do modelo NÃO é cravado
de memória — `resolver_modelos()` lê os modelos disponíveis na conta e escolhe
o Flash/Pro reais, evitando quebrar quando a Google renomeia as gerações.
"""
from __future__ import annotations

from typing import Optional

from . import config

# A "voz" e as regras do comentarista. Determinístico no que importa: proíbe
# inventar número e manda respeitar amostra pequena.
SYSTEM_PROMPT = """\
Você é o comentarista do grupo de League of Legends — um analista com bom humor
que conhece os jogadores. Escreve em português do Brasil.

Sua função é NARRAR uma análise tática de UMA partida a partir de números que
JÁ FORAM CALCULADOS e estão no contexto. Tom: análise séria com zoeira leve.

REGRAS INVIOLÁVEIS:
- NUNCA invente, calcule ou estime números. Use SOMENTE os valores do contexto.
  Se algo não está lá, não cite.
- Seja honesto sobre incerteza: se o contexto disser que a amostra é pequena,
  trate como indício, não como verdade cravada.
- Em coisas subjetivas (ex.: "a briga que decidiu o jogo"), diga "os dados
  apontam X", não banque dono da verdade.
- Não repita as tabelas/listas do contexto; ESCREVA a leitura da partida.
- 120 a 180 palavras. Pode citar nomes de jogadores e campeões.
- Termine com 1 conclusão acionável (uma dica ou um destaque), quando fizer sentido.

Devolva APENAS o texto da narrativa (o que iria no campo "🎙️ A leitura").
"""


SYSTEM_PROMPT_INDIVIDUAL = """\
Você é o comentarista do grupo de League of Legends — analista com bom humor que
conhece os jogadores. Escreve em português do Brasil.

Recebe os números JÁ CALCULADOS de UMA partida (do time todo) e deve NARRAR o
desempenho ESPECÍFICO de {alvo}, sempre situando-o no contexto do time e dos
eventos da partida (quem carregou, como o time foi, brigas, objetivos).

REGRAS INVIOLÁVEIS:
- NUNCA invente ou calcule números. Use SOMENTE os valores do contexto. Se não
  está lá, não cite.
- Foque em {alvo}: como jogou a rota (vs o oponente direto), impacto no time,
  comportamento (snowball, pego sozinho, visão, etc.), e o que ajudou/atrapalhou.
- Relacione com o resto: {alvo} carregou ou foi carregado? Brilhou numa derrota
  ou sumiu numa vitória?
- Honestidade: amostra pequena = indício, não veredito. Nada de dono da verdade.
- 90 a 140 palavras. Termine com 1 dica acionável pra {alvo}.

Devolva APENAS o texto da análise individual.
"""


def narrador(modelo: Optional[str] = None):
    """Devolve um callable (fatos -> narrativa do time) pra injetar no post."""
    m = modelo or config.GEMINI_MODEL
    return lambda fatos: analisar(fatos, m)


def narrador_individual(alvo: str, modelo: Optional[str] = None):
    """Callable (fatos -> análise focada no jogador `alvo`)."""
    m = modelo or config.GEMINI_MODEL
    sp = SYSTEM_PROMPT_INDIVIDUAL.format(alvo=alvo)
    return lambda fatos: analisar(fatos, m, system_prompt=sp)


SYSTEM_PROMPT_LOTE = """\
Você é o comentarista do grupo de League of Legends — analista com bom humor que
conhece os jogadores. Escreve em português do Brasil.

Recebe os números JÁ CALCULADOS de UMA partida e deve produzir, de UMA vez:
1) a narrativa do TIME (120-180 palavras), e
2) a análise individual de CADA um destes jogadores: {membros}
   (80-120 palavras cada, focada nele, situando no contexto do time).

REGRAS INVIOLÁVEIS:
- NUNCA invente ou calcule números. Use SOMENTE os do contexto. Se não está, não cite.
- Honestidade: amostra pequena = indício, não veredito. Nada de dono da verdade em
  coisas subjetivas ("os dados apontam X").
- Cada análise individual termina com 1 dica acionável.

Responda em JSON EXATO, sem texto fora dele:
{{"time": "<narrativa do time>", "jogadores": {{"<nick exatamente como na lista>": "<análise>", ...}}}}
"""


def analisar_lote(fatos: str, membros: list[str], modelo: Optional[str] = None,
                  *, temperatura: float = 0.8) -> dict:
    """Uma chamada -> narrativa do time + análise de cada jogador. {time, jogadores}."""
    import json as _json
    from google import genai
    from google.genai import types

    key = config.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente — defina no .env.")
    m = modelo or config.GEMINI_MODEL
    client = genai.Client(api_key=key)
    sp = SYSTEM_PROMPT_LOTE.format(membros=", ".join(membros))

    base = dict(system_instruction=sp, temperature=temperatura,
                max_output_tokens=4096, response_mime_type="application/json")

    def _gerar(cfg):
        return client.models.generate_content(model=m, contents=fatos, config=cfg)

    try:
        cfg = types.GenerateContentConfig(
            **base, thinking_config=types.ThinkingConfig(thinking_budget=0))
        resp = _gerar(cfg)
    except Exception:
        resp = _gerar(types.GenerateContentConfig(**base))

    data = _json.loads(resp.text or "{}")
    jog = data.get("jogadores", {})
    if isinstance(jog, list):  # tolera formato [{nick, analise}]
        jog = {d.get("nick"): d.get("analise", "") for d in jog}
    return {"time": data.get("time", ""), "jogadores": jog, "modelo": m}


def resolver_modelos(client) -> dict:
    """Escolhe Flash e Pro reais entre os modelos disponíveis na conta."""
    nomes = []
    for m in client.models.list():
        acoes = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", [])
        if not acoes or "generateContent" in acoes:
            nomes.append(m.name.replace("models/", ""))

    def escolher(palavra, evitar=()):
        cands = [n for n in nomes if palavra in n.lower()
                 and not any(e in n.lower() for e in evitar)
                 and "preview" not in n.lower() and "exp" not in n.lower()]
        if not cands:
            return None
        # prefere alias 'latest'; senão, o nome "maior" (versão mais nova)
        latest = [n for n in cands if n.endswith("latest")]
        return sorted(latest or cands)[-1]

    return {"flash": escolher("flash", evitar=("lite",)),
            "pro": escolher("pro"),
            "flash-lite": escolher("flash-lite") or escolher("lite")}


def analisar(contexto: str, modelo: str, *, temperatura: float = 0.8,
             system_prompt: str = SYSTEM_PROMPT,
             thinking_budget: Optional[int] = 0,
             max_output_tokens: int = 2048) -> str:
    """Gera a narrativa de uma partida. `contexto` = os fatos determinísticos.

    thinking_budget=0 desliga o "pensamento" (narração não precisa) e evita
    que ele consuma o orçamento de saída. Modelos que exigem thinking (ex.: Pro)
    rejeitam 0 — nesse caso, refaz sem o ThinkingConfig.
    """
    from google import genai
    from google.genai import types

    key = config.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY ausente — defina no .env.")
    client = genai.Client(api_key=key)

    base = dict(system_instruction=system_prompt, temperature=temperatura,
                max_output_tokens=max_output_tokens)

    def _gerar(cfg):
        return client.models.generate_content(model=modelo, contents=contexto, config=cfg)

    try:
        cfg = types.GenerateContentConfig(
            **base, thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget))
        resp = _gerar(cfg)
    except Exception:
        # modelo não aceita esse budget de thinking -> usa o padrão dele
        resp = _gerar(types.GenerateContentConfig(**base))
    return (resp.text or "").strip()

"""Fronteira da LLM — os fatos entram, a narrativa sai.

Regra de ouro (bot-lol.md, seção 2): a LLM NUNCA calcula; ela só narra números
que o código já calculou. Trocar de provedor/modelo = mexer só aqui.

Provedor atual: **Claude Code em modo headless** (`claude -p`), não a API HTTP.
A diferença importa: o CLI autentica pela assinatura (OAuth), então o custo fica
dentro do plano em vez de bilhar créditos de API. Em CI o token vem da variável
`CLAUDE_CODE_OAUTH_TOKEN` (ver `.github/workflows/ciclo.yml`).

Três flags fazem o `claude` deixar de ser um agente e virar uma chamada de
modelo, que é tudo o que este projeto quer dele:

  --tools ""      nenhuma ferramenta: ele não lê arquivo, não roda bash, não
                  tem como "ir conferir" nada. É o que torna a regra "a LLM não
                  calcula" verificável, e não apenas combinada.
  --safe-mode     ignora CLAUDE.md, skills, hooks, plugins e MCP do ambiente —
                  o prompt é só o que está aqui, rode onde rodar.
  --json-schema   a saída é validada contra o schema pelo próprio CLI, o que
                  substitui o `response_mime_type` + `json.loads()` na esperança.

NÃO use `--bare`: apesar do nome sugerir o mesmo, ele ignora
CLAUDE_CODE_OAUTH_TOKEN e exige ANTHROPIC_API_KEY, ou seja, desliga a assinatura.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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
- Se houver uma seção "PERFIL VIVO", use-a como CONTEXTO do histórico (ex.: "vem
  melhorando", "costuma apanhar de Irelia") pra dar profundidade — sem recalcular
  nem tratar como fato desta partida.
- Cada análise individual termina com 1 dica acionável.
- No campo `nick`, repita o nome EXATAMENTE como aparece na lista acima.
"""

# O schema é a garantia de formato. `jogadores` é lista (e não objeto com uma
# chave por nick) porque JSON Schema não expressa chaves dinâmicas junto com
# additionalProperties: false — `analisar_lote` converte pra dict na saída.
_SCHEMA_LOTE = {
    "type": "object",
    "properties": {
        "time": {"type": "string"},
        "jogadores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nick": {"type": "string"},
                    "analise": {"type": "string"},
                },
                "required": ["nick", "analise"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["time", "jogadores"],
    "additionalProperties": False,
}


class LLMIndisponivel(RuntimeError):
    """O CLI não está instalado/autenticado — o chamador decide se degrada."""


def disponivel() -> bool:
    """True se dá pra chamar o Claude. Usado pra decidir entre gerar e degradar."""
    return shutil.which(config.CLAUDE_BIN) is not None


def _env_limpo() -> dict:
    """Ambiente do subprocesso sem o que atrapalha o `claude` filho.

    Duas limpezas, por motivos diferentes:

    1. `ANTHROPIC_API_KEY` — na ordem de precedência do Claude Code ela é a 3ª e
       `CLAUDE_CODE_OAUTH_TOKEN` é a 5ª, então uma chave esquecida no ambiente
       faz o CLI cobrar de créditos de API em vez da assinatura, e falhar.
    2. `CLAUDE_CODE_*` / `CLAUDECODE` — quando o bot é rodado de dentro de uma
       sessão do Claude Code (que é como você vai testar), o filho herdaria o
       estado da sessão pai. Um processo limpo é reprodutível; um aninhado não.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    for k in list(env):
        if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID",
                                                 "CLAUDE_EFFORT"):
            env.pop(k, None)
    # ...mas o token de CI é justamente um CLAUDE_CODE_*: preserva.
    if tok := os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    return env


def _chamar(prompt: str, system_prompt: str, *, schema: Optional[dict] = None,
            modelo: Optional[str] = None):
    """Roda `claude -p` e devolve o envelope JSON já parseado.

    Uma chamada, sem ferramentas e sem estado. `stdin` vai pra /dev/null porque
    senão o CLI espera 3 segundos por entrada que nunca vem.
    """
    if not disponivel():
        raise LLMIndisponivel(
            f"binário '{config.CLAUDE_BIN}' não encontrado. Instale o Claude Code "
            "(npm i -g @anthropic-ai/claude-code) e autentique com `claude` ou "
            "com CLAUDE_CODE_OAUTH_TOKEN.")

    cmd = [
        config.CLAUDE_BIN, "-p", prompt,
        "--model", modelo or config.CLAUDE_MODEL,
        "--system-prompt", system_prompt,
        "--tools", "",
        "--output-format", "json",
        "--no-session-persistence",
        "--safe-mode",
        "--effort", config.CLAUDE_EFFORT,
    ]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]

    try:
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=config.CLAUDE_TIMEOUT_S, env=_env_limpo())
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"claude -p estourou {config.CLAUDE_TIMEOUT_S}s") from e

    if proc.returncode != 0:
        raise RuntimeError(
            f"claude -p saiu com {proc.returncode}: {(proc.stderr or '')[-500:]}")

    try:
        env = json.loads(proc.stdout)
    except ValueError as e:
        raise RuntimeError(
            f"claude -p devolveu saída não-JSON: {proc.stdout[:300]}") from e

    if env.get("is_error"):
        raise RuntimeError(f"claude -p: {str(env.get('result'))[:500]}")
    return env


def analisar_lote(fatos: str, membros: list[str],
                  modelo: Optional[str] = None) -> dict:
    """Uma chamada -> narrativa do time + análise de cada jogador.

    Devolve {"time": str, "jogadores": {nick: str}, "modelo": str}. A forma do
    retorno é a mesma de antes de propósito: `analise.py` não muda.
    """
    env = _chamar(
        fatos,
        SYSTEM_PROMPT_LOTE.format(membros=", ".join(membros)),
        schema=_SCHEMA_LOTE,
        modelo=modelo,
    )

    # `structured_output` já vem validado contra o schema. O fallback pro
    # `result` cru cobre versões do CLI que não populem o campo.
    data = env.get("structured_output")
    if not isinstance(data, dict):
        data = json.loads(env.get("result") or "{}")

    jogadores = data.get("jogadores") or []
    if isinstance(jogadores, list):
        jogadores = {j["nick"]: j.get("analise", "")
                     for j in jogadores if isinstance(j, dict) and j.get("nick")}

    return {
        "time": data.get("time", ""),
        "jogadores": jogadores,
        "modelo": modelo or config.CLAUDE_MODEL,
    }


def analisar(contexto: str, modelo: Optional[str] = None, *,
             system_prompt: str = SYSTEM_PROMPT) -> str:
    """Gera UM texto (narrativa do time ou análise individual) a partir dos fatos.

    Caminho avulso: o fluxo normal usa `analisar_lote`, que resolve time e
    jogadores numa chamada só e cacheia tudo.
    """
    env = _chamar(contexto, system_prompt, modelo=modelo)
    return (env.get("result") or "").strip()


def narrador(modelo: Optional[str] = None):
    """Devolve um callable (fatos -> narrativa do time) pra injetar no post."""
    return lambda fatos: analisar(fatos, modelo)


def narrador_individual(alvo: str, modelo: Optional[str] = None):
    """Callable (fatos -> análise focada no jogador `alvo`)."""
    sp = SYSTEM_PROMPT_INDIVIDUAL.format(alvo=alvo)
    return lambda fatos: analisar(fatos, modelo, system_prompt=sp)

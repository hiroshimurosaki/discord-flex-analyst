"""A única fronteira com o modelo. Os fatos entram, a prosa sai.

Provedor: **Claude Code em modo headless** (`claude -p`), não a API HTTP. O CLI
autentica pela assinatura (OAuth), então o custo fica dentro do plano; em CI o
token vem de `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, validade de 1 ano).

Três flags fazem o `claude` deixar de ser agente e virar chamada de modelo:

  --tools ""      nenhuma ferramenta. Ele não lê arquivo, não roda comando, não
                  tem como "ir conferir" nada. É o que torna "a LLM não calcula"
                  verificável em vez de combinado.
  --safe-mode     ignora CLAUDE.md, skills, hooks, plugins e MCP do ambiente. O
                  prompt é só o que está aqui, rode onde rodar.
  --json-schema   a saída é validada contra o schema pelo próprio CLI.

NÃO use `--bare`: ele ignora CLAUDE_CODE_OAUTH_TOKEN e exige ANTHROPIC_API_KEY,
ou seja, desliga a assinatura.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Optional

from .. import config


class ErroLLM(Exception):
    pass


SISTEMA = """\
Você escreve a história de um time de League of Legends — cinco amigos que jogam
ranqueada flex juntos há anos. Não é análise de esports: é a história DELES, com
evolução, emoção e personalidade. Português do Brasil.

Você recebe UM CAPÍTULO por vez, na forma de um briefing determinístico. Todo
número já foi calculado. Seu trabalho é escrever prosa.

REGRAS INVIOLÁVEIS
1. NUNCA invente, calcule, estime ou arredonde número. Use SOMENTE os valores do
   briefing. Se não está lá, não existe.
2. Respeite a seção "Limites". Ela diz o que a amostra não permite afirmar, e ela
   vence qualquer frase bonita que você queira escrever.
3. Motivação e estado mental NÃO são dados. "Os números apontam que" é permitido;
   "ele estava tiltado" não é.
4. A seção "Bíblia" lista o que já foi contado. Não reconte fato, não reuse
   imagem/metáfora de lá. Pague ou adie as promessas em aberto — explicitamente.
5. A "forma" da era (`ascensao`, `queda`, `plato`...) foi CALCULADA. Escreva sobre
   a curva que está lá, não sobre a que daria um texto melhor.
6. Personalidade vem do cânone. Onde o cânone estiver vazio, fale só de números —
   não invente jeito de ser de pessoa real.
7. Onde o briefing marcar `virou_verdade`, você está diante de evolução MEDIDA.
   Esse é o material mais valioso do capítulo: use.

COMO ESCREVER
- O `titulo` é SEU: não copie o cabeçalho do briefing, não escreva "Capítulo N",
  não use o rótulo interno da forma. Um nome curto, concreto, que só sirva para
  este capítulo.
- 400 a 700 palavras de prosa corrida, com subtítulos quando ajudar.
- Cena antes de estatística: abra por uma partida, não por um winrate.
- Cada pessoa citada tem que soar como ela, não como "o jungler".
- Termine deixando algo em aberto para o próximo capítulo, a não ser que seja o
  último.
- Não escreva "nesta era" nem "o briefing diz". Você está contando uma história.
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "subtitulo": {"type": "string"},
        "frase_de_abertura": {"type": "string"},
        "texto": {"type": "string"},
        "estado_emocional": {"type": "string"},
        "promessas_abertas": {"type": "array", "items": {"type": "string"}},
        "imagens_usadas": {"type": "array", "items": {"type": "string"}},
        "fatos_contados": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulo", "subtitulo", "frase_de_abertura", "texto",
                 "estado_emocional", "promessas_abertas", "imagens_usadas",
                 "fatos_contados"],
    "additionalProperties": False,
}


def disponivel() -> bool:
    return shutil.which(config.CLAUDE_BIN) is not None


def _ambiente() -> dict:
    env = os.environ.copy()
    # ANTHROPIC_API_KEY tem precedência sobre o token da assinatura: se ela
    # estiver no ambiente, a chamada cai em créditos de API sem avisar ninguém.
    env.pop("ANTHROPIC_API_KEY", None)
    # `CLAUDE_EFFORT` já é exportado pelo próprio Claude Code: rodar este script
    # de dentro de uma sessão herdaria o effort dela silenciosamente.
    env.pop("CLAUDE_EFFORT", None)
    return env


def _extrair_json(saida: str) -> dict:
    try:
        return json.loads(saida)
    except json.JSONDecodeError:
        # O CLI às vezes envolve o JSON em cerca de código.
        ini, fim = saida.find("{"), saida.rfind("}")
        if ini >= 0 and fim > ini:
            return json.loads(saida[ini:fim + 1])
        raise


def narrar(briefing: str, voz: str = "", modelo: Optional[str] = None,
           tentativas: int = 3) -> dict:
    """Briefing -> capítulo. Devolve o dict validado contra `_SCHEMA`.

    Tem retry porque a chamada falha de vez em quando sem nem escrever em
    stderr, e uma falha transitória no capítulo 1 não pode derrubar uma
    execução de doze. O backoff é curto: se for erro real, falha rápido.
    """
    if not disponivel():
        raise ErroLLM(
            f"'{config.CLAUDE_BIN}' não encontrado no PATH. "
            "Instale com: npm install -g @anthropic-ai/claude-code")

    sistema = SISTEMA
    if voz:
        sistema += f"\n\nVOZ DESTE GRUPO (do cânone — respeite):\n{voz}\n"

    cmd = [config.CLAUDE_BIN, "-p", "--tools", "", "--safe-mode",
           "--model", modelo or config.CLAUDE_MODEL,
           "--append-system-prompt", sistema,
           "--json-schema", json.dumps(_SCHEMA)]

    ultimo = ""
    for i in range(tentativas):
        try:
            r = subprocess.run(cmd, input=briefing, capture_output=True,
                               text=True, timeout=config.CLAUDE_TIMEOUT_S,
                               env=_ambiente())
        except subprocess.TimeoutExpired:
            ultimo = f"timeout de {config.CLAUDE_TIMEOUT_S}s"
            r = None
        if r is not None:
            if r.returncode == 0:
                try:
                    return _extrair_json(r.stdout.strip())
                except json.JSONDecodeError:
                    ultimo = f"saída não é JSON: {r.stdout.strip()[:200]}"
            else:
                ultimo = (f"código {r.returncode}"
                          + (f": {r.stderr.strip()[:300]}" if r.stderr.strip()
                             else " (sem stderr — costuma ser transitório)"))
        if i < tentativas - 1:
            time.sleep(3 * (i + 1))
    raise ErroLLM(f"claude falhou em {tentativas} tentativas — {ultimo}")

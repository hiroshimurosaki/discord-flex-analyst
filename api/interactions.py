"""Casca do Vercel: recebe o POST do Discord e delega pra bot_lol.interactions.

Fina de propósito — tudo o que dá pra testar sem servidor mora no módulo, não
aqui. O Vercel roteia por caminho de arquivo, então este arquivo responde em
/api/interactions, que é a URL a colar em "Interactions Endpoint URL" no
Discord Developer Portal.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# O bundle do Vercel não põe a raiz do projeto no sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot_lol import interactions  # noqa: E402

MAX_CORPO = 1 << 20  # 1 MiB: interaction do Discord é muito menor que isso


class handler(BaseHTTPRequestHandler):   # noqa: N801 — o Vercel exige este nome

    def _responder(self, status: int, corpo: dict | str) -> None:
        dados = (json.dumps(corpo) if isinstance(corpo, dict) else corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_POST(self) -> None:      # noqa: N802 — assinatura da stdlib
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = 0
        if tamanho <= 0 or tamanho > MAX_CORPO:
            self._responder(400, {"error": "corpo inválido"})
            return

        corpo = self.rfile.read(tamanho)

        # A verificação vem ANTES de qualquer parse: ao registrar a URL o Discord
        # manda requests deliberadamente mal assinados e recusa o endpoint se
        # algum deles receber 2xx.
        try:
            interactions.verificar_assinatura(
                os.environ.get("DISCORD_PUBLIC_KEY", ""),
                self.headers.get("X-Signature-Ed25519", ""),
                self.headers.get("X-Signature-Timestamp", ""),
                corpo,
            )
        except interactions.AssinaturaInvalida:
            self._responder(401, "invalid request signature")
            return

        try:
            payload = json.loads(corpo)
        except ValueError:
            self._responder(400, {"error": "json inválido"})
            return

        try:
            self._responder(200, interactions.responder(payload))
        except Exception as e:
            # Erro aqui vira "aplicação não respondeu" pro usuário. Melhor
            # devolver uma mensagem visível e logar o motivo.
            print(f"[interactions] {type(e).__name__}: {e}", file=sys.stderr)
            self._responder(200, {
                "type": interactions.CHANNEL_MESSAGE,
                "data": {"content": "Deu ruim aqui do meu lado. Tenta de novo?",
                         "flags": 64},
            })

    def do_GET(self) -> None:       # noqa: N802
        """Healthcheck — útil pra confirmar que o deploy subiu."""
        self._responder(200, {"ok": True, "servico": "bot-lol interactions"})

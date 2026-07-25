"""Uma rodada completa do bot, sem gateway — o entrypoint do GitHub Actions.

Faz o que `discord_bot._poll_loop` fazia, mas num processo que nasce, trabalha e
morre: busca partidas novas, ingere, narra e posta via **webhook** do canal.
Webhook em vez de bot conectado é o que torna isto possível sem manter processo
de pé — e sem precisar sequer do `discord.py`.

Uso:
    python -m scripts.ciclo              # roda de verdade
    python -m scripts.ciclo --dry-run    # não posta nem grava análise; só mostra

Variáveis (ver .env.example): RIOT_API_KEY, DISCORD_WEBHOOK_URL e, em CI,
CLAUDE_CODE_OAUTH_TOKEN.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

import requests

from bot_lol import analise, config, embeds, llm, poller, post, records
from bot_lol.db import database as db

# Guarda-costas de estreia (ARQUITETURA 6.1). O poller devolve TODAS as partidas
# novas que achou; num ciclo que roda em CI isso é pior que localmente, porque um
# workflow desabilitado por um dia volta e despeja tudo de uma vez no canal.
# Partida mais velha que isto é ingerida (o histórico importa) mas não é postada.
JANELA_POST_H = int(os.environ.get("BOT_LOL_JANELA_POST_H", "6"))

TIMEOUT_HTTP = 20


def _postar(webhook: str, texto: str, dry_run: bool = False) -> None:
    """Manda o post pro canal. Um embed por pedaço; nada é truncado."""
    payload = {"embeds": embeds.construir(texto, embeds.cor_do_resultado(texto))}
    if dry_run:
        print(f"\n{'='*64}\n[dry-run] {len(payload['embeds'])} embed(s):\n{texto}\n")
        return
    r = requests.post(webhook, json=payload, timeout=TIMEOUT_HTTP)
    if r.status_code == 429:  # rate limit do webhook: respeita e tenta de novo
        espera = float(r.json().get("retry_after", 2))
        time.sleep(espera + 0.5)
        r = requests.post(webhook, json=payload, timeout=TIMEOUT_HTTP)
    r.raise_for_status()


def _recente(conn, partida_id: int, janela_h: int) -> bool:
    """A partida acabou dentro da janela? Fora dela, ingere mas não posta."""
    row = conn.execute("SELECT inicio_ts FROM partidas WHERE id=?",
                       (partida_id,)).fetchone()
    if not row or not row["inicio_ts"]:
        return False
    idade_h = (time.time() - row["inicio_ts"] / 1000.0) / 3600.0
    return idade_h <= janela_h


def _texto_do_post(conn, partida_id: int) -> Optional[str]:
    """Fatos + narrativa. Sem LLM disponível, posta só os fatos (não some nada).

    Um post por PARTIDA, não por jogador. Além de ser o certo, isso corrige de
    graça o caso em que dois membros caem na mesma SoloQ em times opostos e o
    bot antigo mandava dois posts do mesmo jogo.
    """
    fatos = post.fatos_partida(conn, partida_id)

    if not llm.disponivel():
        print("[ciclo] claude indisponível — postando só os fatos")
        return fatos

    try:
        analises = analise.obter_analises(conn, partida_id)
    except Exception as e:
        # Narrativa é enfeite; os fatos são o produto. Uma falha da LLM não
        # pode custar o post — nem virar uma partida "nova" no próximo ciclo.
        print(f"[ciclo] narrativa da partida {partida_id} falhou: {e}")
        return fatos

    if analises and analises.get("time"):
        return fatos + "\n\n**🎙️ A leitura**\n" + analises["time"]
    return fatos


def rodar(dry_run: bool = False, janela_h: int = JANELA_POST_H) -> int:
    """Executa uma rodada. Devolve quantas partidas foram postadas."""
    webhook = config.DISCORD_WEBHOOK_URL
    if not webhook and not dry_run:
        print("DISCORD_WEBHOOK_URL ausente — sem para onde postar.", file=sys.stderr)
        return 0
    if not config.RIOT_API_KEY:
        print("RIOT_API_KEY ausente — nada a fazer.", file=sys.stderr)
        return 0

    from bot_lol.riot_api import RiotAPIError, RiotClient

    config.ensure_dirs()
    conn = db.get_connection()
    db.init_db(conn)          # idempotente: aplica tabelas novas (ex.: momentos)

    try:
        rclient = RiotClient()
    except RiotAPIError as e:
        print(f"Riot API indisponível: {e}", file=sys.stderr)
        conn.close()
        return 0

    postadas = 0
    for g in conn.execute("SELECT id FROM grupos").fetchall():
        try:
            novos = poller.poll_grupo(conn, rclient, g["id"],
                                      config.POLL_PARTIDAS_POR_JOGADOR)
        except RiotAPIError as e:
            # Chave expirada, 429, 5xx: pula o grupo. O próximo ciclo reencontra
            # as partidas, porque nada foi marcado como processado.
            print(f"[ciclo] grupo {g['id']}: {e}", file=sys.stderr)
            continue

        print(f"[ciclo] grupo {g['id']}: {len(novos)} partida(s) nova(s)")

        if novos:
            # Recalcula o Hall da Fama agora, com tempo de sobra, pra que o
            # /recordes no Vercel seja uma query indexada e não uma varredura
            # de todo o histórico dentro do prazo de 3s do Discord.
            try:
                records.materializar(conn, g["id"])
            except Exception as e:
                print(f"[ciclo] materializar recordes falhou: {e}", file=sys.stderr)

        for partida_id in novos:
            if not _recente(conn, partida_id, janela_h):
                print(f"[ciclo] partida {partida_id} fora da janela de "
                      f"{janela_h}h — ingerida, não postada")
                continue
            try:
                texto = _texto_do_post(conn, partida_id)
                if texto:
                    _postar(webhook, texto, dry_run)
                    postadas += 1
            except Exception as e:
                print(f"[ciclo] falha ao postar partida {partida_id}: {e}",
                      file=sys.stderr)

    # O banco roda em WAL: escritas recentes podem estar no arquivo -wal, que o
    # workflow NÃO commita. Sem este checkpoint, um ciclo commitaria um .db sem
    # as partidas que acabou de ingerir — e o próximo ciclo as trataria como
    # novas, repostando tudo. Consolida antes de fechar.
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as e:
        print(f"[ciclo] checkpoint do WAL falhou: {e}", file=sys.stderr)
    conn.close()

    print(f"[ciclo] {postadas} post(s) enviado(s)")
    return postadas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="não posta no Discord; imprime o que enviaria")
    ap.add_argument("--janela-h", type=int, default=JANELA_POST_H,
                    help=f"só posta partidas das últimas N horas (default {JANELA_POST_H})")
    args = ap.parse_args()
    rodar(dry_run=args.dry_run, janela_h=args.janela_h)


if __name__ == "__main__":
    main()

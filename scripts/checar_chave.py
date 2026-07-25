"""Diz se a RIOT_API_KEY funciona e se ela é de desenvolvimento ou produção.

Todas as chaves têm o MESMO formato (`RGAPI-...`), então olhar a chave não
responde nada. O que dá pra medir é o header `X-App-Rate-Limit` da resposta, onde
a Riot informa os limites concedidos:

    dev / pessoal ->  20:1,100:120        (20/s e 100 a cada 2min)
    produção      ->  500:10,30000:600    (ordens de grandeza acima)

LIMITE DESTE SCRIPT: chave de **desenvolvimento** e chave **pessoal** têm os
MESMOS limites, então este teste NÃO distingue as duas. Ele separa apenas o tier
20 req/s (dev ou pessoal) do tier de produção. A diferença entre dev e pessoal é
a validade, e ela só aparece em dois lugares:

  - no Developer Portal: a chave de dev fica no dashboard com contador regressivo;
  - a chave pessoal fica listada sob o produto registrado, sem contador.

Isso importa porque a chave de dev **expira a cada 24h**. Localmente dá pra
conviver (você renova e reinicia); no GitHub Actions não há ninguém pra renovar,
e o poller morre em silêncio todo dia. A chave pessoal não expira.

Uso:
    python -m scripts.checar_chave
    RIOT_API_KEY=RGAPI-... python -m scripts.checar_chave
"""
from __future__ import annotations

import sys

import requests

from bot_lol import config

# Status da plataforma: não exige parâmetro nenhum e aceita qualquer chave
# válida, então isola "a chave presta?" de "o dado existe?".
URL = "https://{platform}.api.riotgames.com/lol/status/v4/platform-data"

# Teto de requests/segundo abaixo do qual tratamos a chave como de desenvolvimento.
LIMIAR_DEV_RPS = 100


def _parse_limite(header: str) -> list[tuple[int, int]]:
    """'20:1,100:120' -> [(20, 1), (100, 120)]."""
    faixas = []
    for parte in (header or "").split(","):
        if ":" in parte:
            req, _, seg = parte.partition(":")
            try:
                faixas.append((int(req), int(seg)))
            except ValueError:
                pass
    return faixas


def main() -> None:
    chave = config.RIOT_API_KEY
    if not chave:
        print("RIOT_API_KEY não encontrada (nem no .env, nem no ambiente).\n"
              "  cp .env.example .env   # e preencha RIOT_API_KEY", file=sys.stderr)
        raise SystemExit(2)

    print(f"chave: {chave[:9]}…{chave[-4:]}  ({len(chave)} chars)")
    url = URL.format(platform=config.RIOT_PLATFORM)
    print(f"testando: {url}\n")

    try:
        r = requests.get(url, headers={"X-Riot-Token": chave}, timeout=15)
    except requests.RequestException as e:
        print(f"❌ falha de rede: {e}", file=sys.stderr)
        raise SystemExit(1)

    if r.status_code == 401:
        print("❌ 401 — chave inválida ou malformada.")
        raise SystemExit(1)
    if r.status_code == 403:
        print("❌ 403 — chave EXPIRADA (ou sem permissão para esta rota).\n"
              "   Chave de desenvolvimento expira 24h após ser gerada.\n"
              "   Renove em https://developer.riotgames.com/")
        raise SystemExit(1)
    if r.status_code == 429:
        print("⚠️  429 — chave válida, mas você estourou o rate limit agora.")
    elif not r.ok:
        print(f"⚠️  HTTP {r.status_code}: {r.text[:200]}")
        raise SystemExit(1)
    else:
        print(f"✅ chave VÁLIDA (HTTP {r.status_code}, plataforma "
              f"{config.RIOT_PLATFORM} respondendo)")

    header = r.headers.get("X-App-Rate-Limit", "")
    faixas = _parse_limite(header)
    print(f"\nX-App-Rate-Limit: {header or '(ausente)'}")
    for req, seg in faixas:
        print(f"  • {req} requests a cada {seg}s")

    if not faixas:
        print("\n⚠️  Sem header de rate limit — não dá pra classificar a chave.")
        return

    pico = max(req / seg for req, seg in faixas)
    print(f"\npico permitido: ~{pico:.0f} req/s")

    if pico < LIMIAR_DEV_RPS:
        print("\n🔶 Tier de DESENVOLVIMENTO ou PESSOAL (mesmos limites).")
        print("   Este teste não separa os dois — só o portal separa:")
        print("     • dashboard com contador regressivo -> DEV, expira em 24h;")
        print("     • listada sob um produto registrado -> PESSOAL, não expira.")
        print("\n   Se for DEV, o ciclo no GitHub Actions para amanhã sem avisar.")
        print("   Registre um produto com PERSONAL API KEY em")
        print("   https://developer.riotgames.com/ (Register Product → Personal).")
        print("   Personal serve a 'bot de Discord do seu próprio servidor',")
        print("   não expira, e é aprovada sem processo de verificação.")
        print("   20 req/s é de sobra pro poller (~8 requests a cada 5 min).")
        raise SystemExit(3)

    print("\n🟢 Tier de PRODUÇÃO — não expira sozinha.")
    print("   Pode colocar como secret RIOT_API_KEY no repositório.")


if __name__ == "__main__":
    main()

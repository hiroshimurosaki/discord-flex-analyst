"""Slash commands via HTTP Interactions — a metade do bot que o cron não cobre.

O ciclo do GitHub Actions resolve os posts automáticos, mas slash command é
disparado pelo usuário e exige resposta em **3 segundos**: não dá pra agendar.
A saída sem manter processo de pé é o endpoint HTTP de Interactions — o Discord
faz POST numa URL quando alguém digita o comando.

Este módulo é a lógica pura (verificar assinatura, rotear, montar resposta), sem
saber de Vercel nem de framework. `api/interactions.py` é a casca fina que o
Vercel executa. Assim isto é testável sem subir servidor nenhum.

Duas restrições moldam tudo aqui:

  1. **3 segundos.** Por isso `/recordes` lê a tabela materializada por
     `records.materializar()` no ciclo, em vez de varrer o histórico inteiro
     (ARQUITETURA 6.2). Nada aqui pode chamar a Riot API ou a LLM.
  2. **Filesystem read-only.** O banco vem no bundle do deploy e é aberto em
     modo `ro`. Ler é tudo o que se pode fazer — e é tudo o que se precisa,
     porque a narrativa já foi gerada e cacheada pelo ciclo.
"""
from __future__ import annotations

from typing import Any, Optional

from . import embeds, records
from .db import database as db

# Tipos de interaction e de resposta (constantes da API do Discord).
PING = 1
APPLICATION_COMMAND = 2
AUTOCOMPLETE = 4

PONG = 1
CHANNEL_MESSAGE = 4
AUTOCOMPLETE_RESULT = 8

# Mapeia a escolha de recorte para (filas, em_grupo) — espelha o bot com gateway.
_RECORTES = {
    "flex": (records.FLEX, 1),
    "normais": (records.NORMAIS, 1),
    "solo": (records.SOLO, None),
}


class AssinaturaInvalida(Exception):
    """Assinatura Ed25519 ausente ou incorreta — responder 401, sempre.

    O Discord manda requests deliberadamente mal assinados ao registrar a URL e
    recusa o endpoint se ele responder 2xx a qualquer um deles.
    """


def verificar_assinatura(chave_publica: str, assinatura: str, timestamp: str,
                         corpo: bytes) -> None:
    """Valida a assinatura Ed25519 do Discord. Levanta AssinaturaInvalida."""
    from nacl.exceptions import BadSignatureError
    from nacl.signing import VerifyKey

    if not (chave_publica and assinatura and timestamp):
        raise AssinaturaInvalida("faltam headers de assinatura")
    try:
        VerifyKey(bytes.fromhex(chave_publica)).verify(
            timestamp.encode() + corpo, bytes.fromhex(assinatura))
    except (BadSignatureError, ValueError) as e:
        raise AssinaturaInvalida(str(e)) from e


# ----------------------------------------------------------------------
# Helpers de leitura
# ----------------------------------------------------------------------
def _opcoes(data: dict) -> dict[str, Any]:
    """[{name, value}, ...] -> {name: value}."""
    return {o["name"]: o.get("value") for o in data.get("options") or []}


def _grupo(conn, guild_id: Optional[str]):
    """Grupo do servidor; cai pro primeiro (fase single-tenant, como no bot)."""
    if guild_id:
        row = conn.execute("SELECT * FROM grupos WHERE discord_guild_id=?",
                           (str(guild_id),)).fetchone()
        if row:
            return row
    return conn.execute("SELECT * FROM grupos ORDER BY id LIMIT 1").fetchone()


def _jogador_por_nick(conn, grupo_id: int, nick: str):
    return conn.execute(
        "SELECT * FROM jogadores WHERE grupo_id=? AND nick_display=? COLLATE NOCASE",
        (grupo_id, nick)).fetchone()


def _resposta(texto: str, efemera: bool = False) -> dict:
    """Mensagem de resposta com o texto partido em embeds (nada truncado)."""
    data: dict[str, Any] = {
        "embeds": embeds.construir(texto, embeds.cor_do_resultado(texto))}
    if efemera:
        data["flags"] = 64      # EPHEMERAL: só quem chamou vê
    return {"type": CHANNEL_MESSAGE, "data": data}


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------
def _cmd_recordes(conn, g, opts: dict) -> dict:
    queues, em_grupo = _RECORTES.get(opts.get("recorte", "flex"), _RECORTES["flex"])
    return _resposta(records.formatar_recordes(
        conn, g["id"], g["nome"], queues, em_grupo))


def _cmd_perfil(conn, g, opts: dict) -> dict:
    nick = opts.get("jogador") or ""
    j = _jogador_por_nick(conn, g["id"], nick)
    if not j:
        return _resposta(f"Não achei o jogador **{nick}** neste grupo.", efemera=True)
    queues, em_grupo = _RECORTES.get(opts.get("recorte", "flex"), _RECORTES["flex"])
    return _resposta(records.formatar_perfil(
        conn, g["id"], j["id"], j["nick_display"], queues, em_grupo))


def _cmd_time(conn, g, opts: dict) -> dict:
    """Última partida em grupo (ou a informada), com a narrativa já cacheada."""
    from . import post

    partida_id = opts.get("partida")
    if not partida_id:
        row = conn.execute(
            "SELECT id FROM partidas WHERE grupo_id=? AND em_grupo=1 "
            "ORDER BY inicio_ts DESC LIMIT 1", (g["id"],)).fetchone()
        if not row:
            return _resposta("Nenhuma partida em grupo registrada ainda.",
                             efemera=True)
        partida_id = row["id"]

    texto = post.fatos_partida(conn, partida_id)
    # A narrativa NÃO é gerada aqui: 3s não dão pra chamar a LLM, e o ciclo já
    # gerou e guardou. Se não houver, o post sai só com os fatos.
    an = db.get_analises(conn, partida_id)
    if an and an.get("time"):
        texto += "\n\n**🎙️ A leitura**\n" + an["time"]
    return _resposta(texto)


def _cmd_jogador(conn, g, opts: dict) -> dict:
    """Análise individual de um jogador numa partida (a última, por padrão)."""
    from . import post

    nick = opts.get("jogador") or ""
    j = _jogador_por_nick(conn, g["id"], nick)
    if not j:
        return _resposta(f"Não achei o jogador **{nick}** neste grupo.", efemera=True)

    partida_id = opts.get("partida")
    if not partida_id:
        row = conn.execute(
            "SELECT pt.id FROM partidas pt JOIN participacoes pa ON pa.partida_id=pt.id "
            "WHERE pt.grupo_id=? AND pa.jogador_id=? ORDER BY pt.inicio_ts DESC LIMIT 1",
            (g["id"], j["id"])).fetchone()
        if not row:
            return _resposta(f"**{nick}** não tem partidas registradas.",
                             efemera=True)
        partida_id = row["id"]

    texto = post.fatos_jogador(conn, partida_id, j["id"])
    if texto is None:
        return _resposta("Esse jogador não participou dessa partida.", efemera=True)
    an = db.get_analises(conn, partida_id)
    individual = (an or {}).get("jogadores", {}).get(j["nick_display"])
    if individual:
        texto += "\n\n**🎙️ Análise individual**\n" + individual
    return _resposta(texto)


_COMANDOS = {
    "recordes": _cmd_recordes,
    "perfil": _cmd_perfil,
    "time": _cmd_time,
    "jogador": _cmd_jogador,
}


def _autocomplete(conn, g, data: dict) -> dict:
    """Sugestões de nick. Precisa ser rápido: o Discord dá 3s aqui também."""
    focado = next((o for o in data.get("options") or [] if o.get("focused")), None)
    if not g or not focado or focado.get("name") != "jogador":
        return {"type": AUTOCOMPLETE_RESULT, "data": {"choices": []}}
    atual = (focado.get("value") or "").lower()
    nomes = [r["nick_display"] for r in db.jogadores_do_grupo(conn, g["id"])]
    escolhas = [{"name": n, "value": n} for n in nomes if atual in n.lower()][:25]
    return {"type": AUTOCOMPLETE_RESULT, "data": {"choices": escolhas}}


def responder(payload: dict, conn=None) -> dict:
    """Interaction do Discord -> resposta JSON. É o ponto de entrada da lógica."""
    tipo = payload.get("type")
    if tipo == PING:
        return {"type": PONG}

    if tipo not in (APPLICATION_COMMAND, AUTOCOMPLETE):
        return _resposta("Tipo de interação não suportado.", efemera=True)

    fechar = conn is None
    conn = conn or db.get_connection(somente_leitura=True)
    try:
        data = payload.get("data") or {}
        g = _grupo(conn, payload.get("guild_id"))

        if tipo == AUTOCOMPLETE:
            return _autocomplete(conn, g, data)

        if not g:
            return _resposta("Nenhum grupo cadastrado ainda.", efemera=True)

        handler = _COMANDOS.get(data.get("name") or "")
        if not handler:
            return _resposta(f"Comando `{data.get('name')}` desconhecido.",
                             efemera=True)
        return handler(conn, g, _opcoes(data))
    finally:
        if fechar:
            conn.close()

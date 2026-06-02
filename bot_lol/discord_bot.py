"""Bot do Discord (marco "saída mínima") — borda fina sobre o núcleo.

Conecta no Discord e expõe os comandos slash (separados por assunto):
  /time [partida]            -> análise de uma partida EM GRUPO (post do time;
                                vazio = a última em grupo)
  /jogador <jogador> [partida] -> análise de UM jogador numa partida (solo/duo/
                                flex; vazio = a última dele) — onde o solo aparece
  /perfil <jogador> [recorte]-> ficha + tendências (Flex, Normais ou Solo/Duo)
  /recordes [recorte]        -> Hall da Fama (Flex, Normais ou Solo/Duo)

Além dos comandos, roda um POLLER (marco 3): a cada N min checa partidas
novas dos membros (poller.py), ingere e posta no canal automaticamente —
jogo em grupo vira post do time; solo vira post individual.

A geração de texto vem de post.py e records.py (determinístico, já testado).
Este arquivo só liga isso ao Discord — trocar de plataforma não toca no núcleo.

Rodar:  python -m bot_lol.discord_bot   (precisa de DISCORD_BOT_TOKEN no .env)
"""
from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import tasks

from . import analise, config, poller, post, records, tendencias
from .db import database as db

VERDE, VERMELHO, AZUL = 0x2ECC71, 0xE74C3C, 0x3498DB

# Rótulo curto de fila para os autocompletes.
_FILA_LABEL = {440: "Flex", 420: "Solo", 400: "Normal", 430: "Normal",
               490: "Normal", 450: "ARAM"}

# Escolhas de recorte compartilhadas por /recordes e /perfil.
_RECORTE_CHOICES = [
    app_commands.Choice(name="Flex", value="flex"),
    app_commands.Choice(name="Normais", value="normais"),
    app_commands.Choice(name="Solo/Duo", value="solo"),
]


def _resolver_recorte(recorte: "app_commands.Choice[str] | None"):
    """(queues, em_grupo) a partir da escolha. Solo/Duo ignora em_grupo
    (jogo individual por natureza); Flex/Normais só contam time fechado."""
    valor = recorte.value if recorte else "flex"
    if valor == "solo":
        return records.SOLO, None
    if valor == "normais":
        return records.NORMAIS, 1
    return records.FLEX, 1


def _embed(texto: str, cor: int = AZUL) -> discord.Embed:
    """Empacota o texto determinístico num embed (limite 4096)."""
    return discord.Embed(description=texto[:4096], color=cor)


def _grupo(conn, guild_id) -> "db.sqlite3.Row | None":
    """Grupo do servidor atual; cai pro primeiro grupo (fase single-tenant)."""
    if guild_id:
        row = conn.execute("SELECT * FROM grupos WHERE discord_guild_id=?",
                           (str(guild_id),)).fetchone()
        if row:
            return row
    return conn.execute("SELECT * FROM grupos ORDER BY id LIMIT 1").fetchone()


class FlexBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Garante que o schema atual existe (ex.: tabela analises).
        conn = db.get_connection()
        db.init_db(conn)
        conn.close()
        # Sincroniza os comandos: por guild (instantâneo) se configurado.
        if config.DISCORD_GUILD_ID:
            guild = discord.Object(id=int(config.DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        # Ingestão automática: só liga se houver chave da Riot.
        if config.RIOT_API_KEY and not _poll_loop.is_running():
            _poll_loop.start()
            print(f"Poller ligado: checando a cada {config.POLL_INTERVALO_MIN} min.")


client = FlexBot()


@client.event
async def on_ready() -> None:
    print(f"Bot online como {client.user} — comandos sincronizados.")


# ----------------------------------------------------------------------
# /recordes
# ----------------------------------------------------------------------
@client.tree.command(name="recordes", description="Hall da Fama do grupo")
@app_commands.describe(recorte="Flex (sério), Normais (zoeira) ou Solo/Duo")
@app_commands.choices(recorte=_RECORTE_CHOICES)
async def recordes_cmd(interaction: discord.Interaction,
                       recorte: app_commands.Choice[str] | None = None) -> None:
    await interaction.response.defer()  # ganha 15min; cálculo pesado vai p/ thread
    queues, em_grupo = _resolver_recorte(recorte)

    def _build():
        c = db.get_connection()
        try:
            g = _grupo(c, interaction.guild_id)
            if not g:
                return None
            return records.formatar_recordes(c, g["id"], g["nome"], queues, em_grupo)
        finally:
            c.close()

    txt = await asyncio.to_thread(_build)
    if txt is None:
        await interaction.followup.send("Nenhum grupo cadastrado ainda.", ephemeral=True)
        return
    await interaction.followup.send(embed=_embed(txt, AZUL))


# ----------------------------------------------------------------------
# /perfil  (com autocomplete dos nicks)
# ----------------------------------------------------------------------
async def _autocomplete_jogador(interaction: discord.Interaction, atual: str):
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    nomes = []
    if g:
        nomes = [r["nick_display"] for r in db.jogadores_do_grupo(conn, g["id"])]
    conn.close()
    return [app_commands.Choice(name=n, value=n)
            for n in nomes if atual.lower() in n.lower()][:25]


@client.tree.command(name="perfil", description="Ficha individual de um jogador")
@app_commands.describe(jogador="Nome do jogador", recorte="Flex, Normais ou Solo/Duo")
@app_commands.choices(recorte=_RECORTE_CHOICES)
@app_commands.autocomplete(jogador=_autocomplete_jogador)
async def perfil_cmd(interaction: discord.Interaction, jogador: str,
                     recorte: app_commands.Choice[str] | None = None) -> None:
    await interaction.response.defer()  # ganha 15min; cálculo pesado vai p/ thread
    queues, em_grupo = _resolver_recorte(recorte)

    def _build():
        c = db.get_connection()
        try:
            g = _grupo(c, interaction.guild_id)
            row = c.execute(
                "SELECT id, nick_display FROM jogadores WHERE grupo_id=? AND nick_display=? COLLATE NOCASE",
                (g["id"], jogador)).fetchone() if g else None
            if not row:
                return None
            txt = records.formatar_perfil(c, g["id"], row["id"], row["nick_display"], queues, em_grupo)
            # Detector de tendências (sempre sobre ranqueada — solo/duo + flex).
            txt += tendencias.formatar(tendencias.perfil_vivo(c, g["id"], row["id"]))
            return txt
        finally:
            c.close()

    txt = await asyncio.to_thread(_build)
    if txt is None:
        await interaction.followup.send(f"Não achei o jogador **{jogador}**.", ephemeral=True)
        return
    await interaction.followup.send(embed=_embed(txt, AZUL))


# ----------------------------------------------------------------------
# Autocompletes de partida — um pro /time (jogos em grupo), outro pro
# /jogador (partidas de um jogador, qualquer fila, incl. solo).
# ----------------------------------------------------------------------
def _ultima_partida_grupo(conn, grupo_id: int):
    row = conn.execute(
        "SELECT id FROM partidas WHERE grupo_id=? AND em_grupo=1 ORDER BY inicio_ts DESC LIMIT 1",
        (grupo_id,)).fetchone()
    return row["id"] if row else None


def _ultima_partida_jogador(conn, grupo_id: int, jogador: str):
    row = conn.execute(
        "SELECT pt.id FROM participacoes pa JOIN partidas pt ON pt.id=pa.partida_id "
        "JOIN jogadores j ON j.id=pa.jogador_id "
        "WHERE pt.grupo_id=? AND j.nick_display=? COLLATE NOCASE "
        "ORDER BY pt.inicio_ts DESC LIMIT 1", (grupo_id, jogador)).fetchone()
    return row["id"] if row else None


async def _autocomplete_partida_grupo(interaction: discord.Interaction, atual: str):
    """Jogos EM GRUPO do histórico (pro /time) — rotulados pelos campeões do time."""
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    out = []
    if g:
        from datetime import datetime
        rows = conn.execute(
            "SELECT id, inicio_ts, duracao_seg, vencedor_team, queue_id FROM partidas "
            "WHERE grupo_id=? AND em_grupo=1 ORDER BY inicio_ts DESC LIMIT 25", (g["id"],)).fetchall()
        for r in rows:
            membros = conn.execute(
                "SELECT pa.campeao, pa.team_id FROM participacoes pa JOIN jogadores j ON j.id=pa.jogador_id "
                "WHERE pa.partida_id=? ORDER BY pa.dano DESC", (r["id"],)).fetchall()
            res = "V" if (membros and r["vencedor_team"] == membros[0]["team_id"]) else "D"
            quando = datetime.fromtimestamp((r["inicio_ts"] or 0)/1000).strftime("%d/%m %H:%M")
            champs = "/".join(m["campeao"] for m in membros[:3])
            fila = _FILA_LABEL.get(r["queue_id"], "?")
            label = f"{quando} · {res} {(r['duracao_seg'] or 0)//60}min · {fila} · {champs}"[:100]
            if atual.lower() in label.lower():
                out.append(app_commands.Choice(name=label, value=r["id"]))
    conn.close()
    return out[:25]


async def _autocomplete_partida_jogador(interaction: discord.Interaction, atual: str):
    """Partidas do jogador escolhido (pro /jogador) — QUALQUER fila, incl. solo."""
    jogador = getattr(interaction.namespace, "jogador", None)
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    out = []
    if g and jogador:
        from datetime import datetime
        rows = conn.execute(
            "SELECT pt.id, pt.inicio_ts, pt.duracao_seg, pt.vencedor_team, pt.queue_id, "
            "pa.team_id, pa.campeao FROM participacoes pa "
            "JOIN partidas pt ON pt.id = pa.partida_id "
            "JOIN jogadores j ON j.id = pa.jogador_id "
            "WHERE pt.grupo_id=? AND j.nick_display=? COLLATE NOCASE "
            "ORDER BY pt.inicio_ts DESC LIMIT 25", (g["id"], jogador)).fetchall()
        for r in rows:
            res = "V" if r["vencedor_team"] == r["team_id"] else "D"
            quando = datetime.fromtimestamp((r["inicio_ts"] or 0)/1000).strftime("%d/%m %H:%M")
            fila = _FILA_LABEL.get(r["queue_id"], "?")
            label = (f"{quando} · {res} {(r['duracao_seg'] or 0)//60}min · "
                     f"{fila} · {r['campeao']}")[:100]
            if atual.lower() in label.lower():
                out.append(app_commands.Choice(name=label, value=r["id"]))
    conn.close()
    return out[:25]


def _garantir_cache_partida(partida_id: int) -> None:
    """Baixa match+timeline pro cache se faltarem (best-effort; precisa de
    RIOT_API_KEY). Jogos solo entram no backfill SEM timeline — aqui ela é
    puxada sob demanda, destravando ouro@10/lane diff/momentos no post."""
    if not config.RIOT_API_KEY:
        return
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT match_id FROM partidas WHERE id=?", (partida_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        return
    mid = row["match_id"]
    if (config.CACHE_DIR / f"{mid}_timeline.json").exists():
        return  # já temos — no-op barato (caso comum dos jogos em grupo)
    try:
        from .riot_api import RiotClient
        client = RiotClient()
        client.get_match(mid)     # garante o match JSON em cache
        client.get_timeline(mid)  # baixa e cacheia a timeline
    except Exception as e:  # chave de dev expira em 24h — não derruba o comando
        print(f"[jogador] timeline sob demanda falhou para {mid}: {e}")


def _gerar_analises(partida_id: int):
    """Gera/lê o lote de narrativas da LLM (conexão própria — roda em thread)."""
    c = db.get_connection()
    try:
        return analise.obter_analises(c, partida_id)
    finally:
        c.close()


def _texto_time(conn, partida_id, analises) -> tuple[str, int]:
    fatos = post.fatos_partida(conn, partida_id)
    narr = (analises or {}).get("time")
    txt = fatos + (f"\n\n**🎙️ A leitura**\n{narr}" if narr
                   else "\n\n🎙️ *(narrativa indisponível — configure a LLM)*")
    return txt, (VERDE if "Vitória" in fatos else VERMELHO)


def _texto_individual(conn, partida_id, jogador_id, nick, analises) -> "tuple[str, int] | None":
    fatos = post.fatos_jogador(conn, partida_id, jogador_id)
    if fatos is None:
        return None
    narr = (analises or {}).get("jogadores", {}).get(nick)
    txt = fatos + (f"\n\n**🎙️ Análise individual**\n{narr}" if narr
                   else "\n\n🎙️ *(análise indisponível — configure a LLM)*")
    return txt, (VERDE if "Vitória" in fatos else VERMELHO)


async def _enviar_partida(interaction, conn, g, partida_id, jogador_nick=None) -> None:
    """Responde com o post (time ou individual). TODO o trabalho pesado (LLM +
    montagem de fatos) roda em thread com conexão própria — nunca trava o loop
    (senão a interação estoura os 3s do Discord)."""
    await interaction.response.defer()
    grupo_id = g["id"]

    # garante timeline no cache (jogos solo não a têm) antes de montar os fatos
    await asyncio.to_thread(_garantir_cache_partida, partida_id)

    def _build():
        c = db.get_connection()
        try:
            analises = analise.obter_analises(c, partida_id) if config.GEMINI_API_KEY else None
            if jogador_nick:
                row = c.execute(
                    "SELECT id, nick_display FROM jogadores WHERE grupo_id=? AND nick_display=? COLLATE NOCASE",
                    (grupo_id, jogador_nick)).fetchone()
                if not row:
                    return "erro", f"Não achei o jogador **{jogador_nick}**."
                r = _texto_individual(c, partida_id, row["id"], row["nick_display"], analises)
                return ("erro", f"**{jogador_nick}** não jogou essa partida.") if r is None else ("ok", r)
            return "ok", _texto_time(c, partida_id, analises)
        finally:
            c.close()

    status, payload = await asyncio.to_thread(_build)
    if status == "erro":
        await interaction.followup.send(payload)
        return
    txt, cor = payload
    await interaction.followup.send(embed=_embed(txt, cor))


@client.tree.command(name="time",
                     description="Análise de uma partida EM GRUPO (post do time)")
@app_commands.describe(partida="Escolha a partida (vazio = a última em grupo)")
@app_commands.autocomplete(partida=_autocomplete_partida_grupo)
async def time_cmd(interaction: discord.Interaction, partida: int | None = None) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    if not g:
        await interaction.response.send_message("Nenhum grupo cadastrado ainda.", ephemeral=True)
        conn.close()
        return
    if partida is None:  # default: última partida em grupo
        partida = _ultima_partida_grupo(conn, g["id"])
        if partida is None:
            await interaction.response.send_message("Sem partidas em grupo ainda.", ephemeral=True)
            conn.close()
            return
    elif not conn.execute("SELECT 1 FROM partidas WHERE id=? AND grupo_id=?",
                          (partida, g["id"])).fetchone():
        await interaction.response.send_message("Partida não encontrada.", ephemeral=True)
        conn.close()
        return
    await _enviar_partida(interaction, conn, g, partida)  # sem jogador -> post do time
    conn.close()


@client.tree.command(
    name="jogador",
    description="Análise de UM jogador numa partida (solo, duo ou flex)")
@app_commands.describe(
    jogador="Nome do jogador",
    partida="Escolha a partida (vazio = a última dele)")
@app_commands.autocomplete(jogador=_autocomplete_jogador, partida=_autocomplete_partida_jogador)
async def jogador_cmd(interaction: discord.Interaction, jogador: str,
                      partida: int | None = None) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    if not g:
        await interaction.response.send_message("Nenhum grupo cadastrado ainda.", ephemeral=True)
        conn.close()
        return
    if partida is None:  # default: última partida do jogador (qualquer fila)
        partida = _ultima_partida_jogador(conn, g["id"], jogador)
        if partida is None:
            await interaction.response.send_message(
                f"Não achei partidas de **{jogador}**.", ephemeral=True)
            conn.close()
            return
    elif not conn.execute(
            "SELECT 1 FROM participacoes pa JOIN jogadores j ON j.id=pa.jogador_id "
            "JOIN partidas pt ON pt.id=pa.partida_id "
            "WHERE pt.id=? AND pt.grupo_id=? AND j.nick_display=? COLLATE NOCASE",
            (partida, g["id"], jogador)).fetchone():
        await interaction.response.send_message(
            f"Não achei essa partida de **{jogador}**.", ephemeral=True)
        conn.close()
        return
    await _enviar_partida(interaction, conn, g, partida, jogador)  # post individual
    conn.close()


# ----------------------------------------------------------------------
# Poller — ingestão automática (marco 3): a cada N min checa partidas novas
# e posta no canal (jogo em grupo -> post do time; solo -> post individual).
# ----------------------------------------------------------------------
def _poll_cycle() -> list[tuple[int, int]]:
    """Uma rodada de polling em TODOS os grupos (roda em thread). Retorna
    [(grupo_id, partida_id)] das partidas novas ingeridas."""
    if not config.RIOT_API_KEY:
        return []
    from .riot_api import RiotAPIError, RiotClient
    try:
        rclient = RiotClient()
    except RiotAPIError:
        return []
    conn = db.get_connection()
    out: list[tuple[int, int]] = []
    try:
        for g in conn.execute("SELECT id FROM grupos").fetchall():
            try:
                pids = poller.poll_grupo(conn, rclient, g["id"],
                                         config.POLL_PARTIDAS_POR_JOGADOR)
            except RiotAPIError as e:  # chave expirada etc. — não derruba o loop
                print(f"[poller] grupo {g['id']}: {e}")
                continue
            out.extend((g["id"], pid) for pid in pids)
    finally:
        conn.close()
    return out


async def _postar_automatico(grupo_id: int, partida_id: int) -> None:
    """Monta e envia o(s) post(s) de uma partida nova no canal do grupo."""
    conn = db.get_connection()
    try:
        g = conn.execute("SELECT * FROM grupos WHERE id=?", (grupo_id,)).fetchone()
        canal_id = (g["discord_canal_id"] if g else None) or config.DISCORD_CANAL_ID
        if not canal_id:
            return
        canal = client.get_channel(int(canal_id))
        if canal is None:
            try:
                canal = await client.fetch_channel(int(canal_id))
            except Exception as e:
                print(f"[poller] canal {canal_id} inacessível: {e}")
                return

        await asyncio.to_thread(_garantir_cache_partida, partida_id)
        analises = (await asyncio.to_thread(_gerar_analises, partida_id)
                    if config.GEMINI_API_KEY else None)

        p = conn.execute("SELECT em_grupo FROM partidas WHERE id=?", (partida_id,)).fetchone()
        textos: list[tuple[str, int]] = []
        if p and p["em_grupo"]:
            textos.append(_texto_time(conn, partida_id, analises))
        else:  # solo/avulso: um post individual por membro presente na partida
            membros = conn.execute(
                "SELECT pa.jogador_id, j.nick_display FROM participacoes pa "
                "JOIN jogadores j ON j.id=pa.jogador_id WHERE pa.partida_id=?",
                (partida_id,)).fetchall()
            for m in membros:
                r = _texto_individual(conn, partida_id, m["jogador_id"],
                                      m["nick_display"], analises)
                if r:
                    textos.append(r)
    finally:
        conn.close()
    for txt, cor in textos:
        await canal.send(embed=_embed(txt, cor))


@tasks.loop(minutes=config.POLL_INTERVALO_MIN)
async def _poll_loop() -> None:
    try:
        novos = await asyncio.to_thread(_poll_cycle)
    except Exception as e:
        print(f"[poller] rodada falhou: {e}")
        return
    if novos:
        print(f"[poller] {len(novos)} partida(s) nova(s) — postando.")
    for grupo_id, pid in novos:
        try:
            await _postar_automatico(grupo_id, pid)
        except Exception as e:
            print(f"[poller] falha ao postar partida {pid}: {e}")


@_poll_loop.before_loop
async def _before_poll() -> None:
    await client.wait_until_ready()


def main() -> None:
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN ausente — defina no .env (ver .env.example).")
    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()

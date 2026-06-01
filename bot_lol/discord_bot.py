"""Bot do Discord (marco "saída mínima") — borda fina sobre o núcleo.

Conecta no Discord e expõe os comandos slash:
  /recordes [recorte]   -> Hall da Fama (Flex ou Normais)
  /perfil <jogador>     -> ficha individual
  /ultima               -> posta a última partida em grupo (testa o pipeline)

A geração de texto vem de post.py e records.py (determinístico, já testado).
Este arquivo só liga isso ao Discord — trocar de plataforma não toca no núcleo.

Rodar:  python -m bot_lol.discord_bot   (precisa de DISCORD_BOT_TOKEN no .env)
"""
from __future__ import annotations

import asyncio

import discord
from discord import app_commands

from . import analise, config, post, records
from .db import database as db

VERDE, VERMELHO, AZUL = 0x2ECC71, 0xE74C3C, 0x3498DB


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


client = FlexBot()


@client.event
async def on_ready() -> None:
    print(f"Bot online como {client.user} — comandos sincronizados.")


# ----------------------------------------------------------------------
# /recordes
# ----------------------------------------------------------------------
@client.tree.command(name="recordes", description="Hall da Fama do grupo")
@app_commands.describe(recorte="Flex (sério) ou Normais (zoeira)")
@app_commands.choices(recorte=[
    app_commands.Choice(name="Flex", value="flex"),
    app_commands.Choice(name="Normais", value="normais"),
])
async def recordes_cmd(interaction: discord.Interaction,
                       recorte: app_commands.Choice[str] | None = None) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    if not g:
        await interaction.response.send_message("Nenhum grupo cadastrado ainda.", ephemeral=True)
        return
    queues = records.NORMAIS if (recorte and recorte.value == "normais") else records.FLEX
    txt = records.formatar_recordes(conn, g["id"], g["nome"], queues)
    await interaction.response.send_message(embed=_embed(txt, AZUL))
    conn.close()


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
@app_commands.describe(jogador="Nome do jogador")
@app_commands.autocomplete(jogador=_autocomplete_jogador)
async def perfil_cmd(interaction: discord.Interaction, jogador: str) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    row = conn.execute(
        "SELECT id, nick_display FROM jogadores WHERE grupo_id=? AND nick_display=? COLLATE NOCASE",
        (g["id"], jogador)).fetchone() if g else None
    if not row:
        await interaction.response.send_message(
            f"Não achei o jogador **{jogador}**.", ephemeral=True)
        conn.close()
        return
    txt = records.formatar_perfil(conn, g["id"], row["id"], row["nick_display"])
    await interaction.response.send_message(embed=_embed(txt, AZUL))
    conn.close()


# ----------------------------------------------------------------------
# Autocomplete: jogadores de UMA partida específica (não a lista toda)
# ----------------------------------------------------------------------
def _membros_da_partida(conn, partida_id: int) -> list[str]:
    return [r["nick_display"] for r in conn.execute(
        "SELECT j.nick_display FROM participacoes pa JOIN jogadores j ON j.id=pa.jogador_id "
        "WHERE pa.partida_id=? ORDER BY pa.dano DESC", (partida_id,))]


def _ultima_partida_id(conn, grupo_id: int):
    row = conn.execute(
        "SELECT id FROM partidas WHERE grupo_id=? AND em_grupo=1 ORDER BY inicio_ts DESC LIMIT 1",
        (grupo_id,)).fetchone()
    return row["id"] if row else None


async def _autocomplete_membros_ultima(interaction: discord.Interaction, atual: str):
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    nomes = _membros_da_partida(conn, _ultima_partida_id(conn, g["id"])) if g else []
    conn.close()
    return [app_commands.Choice(name=n, value=n) for n in nomes if atual.lower() in n.lower()][:25]


async def _autocomplete_partida(interaction: discord.Interaction, atual: str):
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
            fila = "Flex" if r["queue_id"] == 440 else "Norm"
            label = f"{quando} · {res} {(r['duracao_seg'] or 0)//60}min · {fila} · {champs}"[:100]
            if atual.lower() in label.lower():
                out.append(app_commands.Choice(name=label, value=r["id"]))
    conn.close()
    return out[:25]


async def _autocomplete_membros_partida(interaction: discord.Interaction, atual: str):
    pid = getattr(interaction.namespace, "partida", None)
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    if pid:
        nomes = _membros_da_partida(conn, pid)
    else:
        nomes = [r["nick_display"] for r in db.jogadores_do_grupo(conn, g["id"])] if g else []
    conn.close()
    return [app_commands.Choice(name=n, value=n) for n in nomes if atual.lower() in n.lower()][:25]


async def _enviar_partida(interaction, conn, g, partida_id, jogador_nick=None) -> None:
    """Responde com o post (time ou individual), usando o cache de análises.
    A geração da LLM (quando falta cache) roda fora do event loop."""
    await interaction.response.defer()

    # gera/lê o lote de análises numa thread (não bloqueia o bot)
    def _gerar():
        c = db.get_connection()
        try:
            return analise.obter_analises(c, partida_id)
        finally:
            c.close()
    analises = await asyncio.to_thread(_gerar) if config.GEMINI_API_KEY else None

    if jogador_nick:
        row = conn.execute(
            "SELECT id, nick_display FROM jogadores WHERE grupo_id=? AND nick_display=? COLLATE NOCASE",
            (g["id"], jogador_nick)).fetchone()
        if not row:
            await interaction.followup.send(f"Não achei o jogador **{jogador_nick}**.")
            return
        fatos = post.fatos_jogador(conn, partida_id, row["id"])
        if fatos is None:
            await interaction.followup.send(f"**{jogador_nick}** não jogou essa partida.")
            return
        narr = (analises or {}).get("jogadores", {}).get(row["nick_display"])
        txt = fatos + (f"\n\n**🎙️ Análise individual**\n{narr}" if narr
                       else "\n\n🎙️ *(análise indisponível — configure a LLM)*")
    else:
        fatos = post.fatos_partida(conn, partida_id)
        narr = (analises or {}).get("time")
        txt = fatos + (f"\n\n**🎙️ A leitura**\n{narr}" if narr
                       else "\n\n🎙️ *(narrativa indisponível — configure a LLM)*")

    cor = VERDE if "Vitória" in fatos else VERMELHO
    await interaction.followup.send(embed=_embed(txt, cor))


@client.tree.command(name="ultima",
                     description="Posta a última partida em grupo (ou foca num jogador)")
@app_commands.describe(jogador="Opcional: análise individual desse jogador")
@app_commands.autocomplete(jogador=_autocomplete_membros_ultima)
async def ultima_cmd(interaction: discord.Interaction, jogador: str | None = None) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    pid = _ultima_partida_id(conn, g["id"]) if g else None
    if not pid:
        await interaction.response.send_message("Sem partidas em grupo ainda.", ephemeral=True)
        conn.close()
        return
    await _enviar_partida(interaction, conn, g, pid, jogador)
    conn.close()


@client.tree.command(name="partida",
                     description="Analisa QUALQUER partida em grupo do histórico")
@app_commands.describe(partida="Escolha a partida", jogador="Opcional: foco num jogador")
@app_commands.autocomplete(partida=_autocomplete_partida, jogador=_autocomplete_membros_partida)
async def partida_cmd(interaction: discord.Interaction, partida: int,
                      jogador: str | None = None) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    ok = conn.execute("SELECT 1 FROM partidas WHERE id=? AND grupo_id=?",
                      (partida, g["id"])).fetchone() if g else None
    if not ok:
        await interaction.response.send_message("Partida não encontrada.", ephemeral=True)
        conn.close()
        return
    await _enviar_partida(interaction, conn, g, partida, jogador)
    conn.close()


def main() -> None:
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN ausente — defina no .env (ver .env.example).")
    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()

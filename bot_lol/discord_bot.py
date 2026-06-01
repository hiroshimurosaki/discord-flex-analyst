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

import discord
from discord import app_commands

from . import config, post, records
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
# /ultima — posta a última partida em grupo (simula o que o poller fará)
# ----------------------------------------------------------------------
@client.tree.command(name="ultima", description="Posta a última partida em grupo")
async def ultima_cmd(interaction: discord.Interaction) -> None:
    conn = db.get_connection()
    g = _grupo(conn, interaction.guild_id)
    p = conn.execute(
        "SELECT id, vencedor_team FROM partidas WHERE grupo_id=? AND em_grupo=1 "
        "ORDER BY inicio_ts DESC LIMIT 1", (g["id"],)).fetchone() if g else None
    if not p:
        await interaction.response.send_message("Sem partidas em grupo ainda.", ephemeral=True)
        conn.close()
        return
    txt = post.montar_post(conn, p["id"])
    cor = VERDE if "Vitória" in txt else VERMELHO
    await interaction.response.send_message(embed=_embed(txt, cor))
    conn.close()


def main() -> None:
    if not config.DISCORD_BOT_TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN ausente — defina no .env (ver .env.example).")
    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()

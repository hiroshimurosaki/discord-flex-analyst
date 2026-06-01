"""Camada de acesso a dados — fina e portável, em cima do SQLite.

Por que uma camada própria (bot-lol.md, seção 4): não amarrar o projeto ao
SQLite. Se um dia escalar para Postgres, troca-se esta camada, não o resto.

Regras:
  - Entidades (grupos, jogadores) podem ser atualizadas (upsert).
  - Fatos (partidas, participacoes) só são inseridos, nunca editados.
  - Toda leitura de jogo é por grupo (multi-tenant).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .. import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Abre conexão SQLite com chaves estrangeiras e rows como dict."""
    path = Path(db_path) if db_path else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Aplica o schema (idempotente — usa CREATE IF NOT EXISTS)."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


# ----------------------------------------------------------------------
# Entidades (podem ser atualizadas)
# ----------------------------------------------------------------------
def ensure_grupo(
    conn: sqlite3.Connection,
    nome: str,
    discord_guild_id: Optional[str] = None,
    discord_canal_id: Optional[str] = None,
    regional: str = "americas",
    platform: str = "br1",
) -> int:
    """Cria o grupo (ou devolve o existente pelo discord_guild_id)."""
    if discord_guild_id:
        row = conn.execute(
            "SELECT id FROM grupos WHERE discord_guild_id = ?",
            (discord_guild_id,),
        ).fetchone()
        if row:
            return row["id"]
    cur = conn.execute(
        "INSERT INTO grupos (nome, discord_guild_id, discord_canal_id, regional, platform) "
        "VALUES (?, ?, ?, ?, ?)",
        (nome, discord_guild_id, discord_canal_id, regional, platform),
    )
    conn.commit()
    return int(cur.lastrowid)


def ensure_jogador(
    conn: sqlite3.Connection,
    grupo_id: int,
    puuid: str,
    nick_display: str,
    riot_id: Optional[str] = None,
) -> int:
    """Cadastra o jogador no grupo; se já existir (grupo+puuid), atualiza nick/riot_id."""
    conn.execute(
        "INSERT INTO jogadores (grupo_id, puuid, riot_id, nick_display) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(grupo_id, puuid) DO UPDATE SET "
        "  riot_id = excluded.riot_id, nick_display = excluded.nick_display",
        (grupo_id, puuid, riot_id, nick_display),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM jogadores WHERE grupo_id = ? AND puuid = ?",
        (grupo_id, puuid),
    ).fetchone()
    return int(row["id"])


def jogadores_do_grupo(conn: sqlite3.Connection, grupo_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM jogadores WHERE grupo_id = ? ORDER BY id", (grupo_id,)
    ).fetchall()


# ----------------------------------------------------------------------
# Fatos (só inserem; nunca editam)
# ----------------------------------------------------------------------
def partida_existe(conn: sqlite3.Connection, grupo_id: int, match_id: str) -> bool:
    """Dedupe: a mesma partida aparece para vários membros — processa 1x só."""
    row = conn.execute(
        "SELECT 1 FROM partidas WHERE grupo_id = ? AND match_id = ?",
        (grupo_id, match_id),
    ).fetchone()
    return row is not None


def insert_partida(
    conn: sqlite3.Connection,
    grupo_id: int,
    match_id: str,
    queue_id: Optional[int],
    duracao_seg: Optional[int],
    inicio_ts: Optional[int],
    vencedor_team: Optional[int],
    em_grupo: bool,
    tem_timeline: bool,
) -> int:
    cur = conn.execute(
        "INSERT INTO partidas "
        "(grupo_id, match_id, queue_id, duracao_seg, inicio_ts, vencedor_team, em_grupo, tem_timeline) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (grupo_id, match_id, queue_id, duracao_seg, inicio_ts, vencedor_team,
         int(em_grupo), int(tem_timeline)),
    )
    conn.commit()
    return int(cur.lastrowid)


# Colunas de participacoes na ordem do INSERT (sem id).
_PART_COLS: Sequence[str] = (
    "partida_id", "jogador_id", "puuid", "team_id", "role", "campeao", "win",
    "kills", "deaths", "assists", "dano", "dano_recebido", "ouro", "visao",
    "farm", "kp", "ouro_10", "ouro_15", "lanediff_10", "challenges_json",
)


def insert_participacoes(conn: sqlite3.Connection, linhas: Iterable[dict[str, Any]]) -> int:
    """Insere participações em lote. Cada dict usa as chaves de _PART_COLS
    (faltantes viram NULL). Retorna quantas linhas inseriu."""
    placeholders = ", ".join("?" for _ in _PART_COLS)
    sql = f"INSERT INTO participacoes ({', '.join(_PART_COLS)}) VALUES ({placeholders})"
    tuplas = [tuple(linha.get(col) for col in _PART_COLS) for linha in linhas]
    conn.executemany(sql, tuplas)
    conn.commit()
    return len(tuplas)

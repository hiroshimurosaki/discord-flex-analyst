"""Acesso ao banco de fatos. Camada fina de propósito.

Fina porque o valor deste projeto está nas camadas 2 e 3 (cronologia e
roteiro), e elas trabalham em cima de listas de dicts, não de ORM. Aqui só
mora: abrir, migrar, inserir fato, e as poucas leituras cruas que a cronologia
precisa.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .. import config

SCHEMA = Path(__file__).with_name("schema.sql")


def conectar(caminho: Optional[Path] = None) -> sqlite3.Connection:
    caminho = Path(caminho) if caminho else config.BANCO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrar(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


# ------------------------------------------------------------------ escrita

def upsert_membro(conn, mid: str, puuid: str, riot_id: str, nome: str,
                  titular: bool, role: Optional[str]) -> None:
    """Membro é ENTIDADE, não fato: nick muda, conta muda, role muda."""
    conn.execute(
        "INSERT INTO membros (id, puuid, riot_id, nome, titular, role) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET puuid=excluded.puuid, "
        "riot_id=excluded.riot_id, nome=excluded.nome, "
        "titular=excluded.titular, role=excluded.role",
        (mid, puuid, riot_id, nome, int(titular), role))


def partida_existe(conn, match_id: str) -> bool:
    return conn.execute("SELECT 1 FROM partidas WHERE match_id=?",
                        (match_id,)).fetchone() is not None


def inserir_partida(conn, partida: dict, participacoes: Iterable[dict]) -> int:
    """Insere partida + suas participações numa transação. Idempotente por
    match_id: chamar duas vezes não duplica nem levanta."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO partidas (match_id, fila, inicio_ts, duracao_seg,"
        " vencedor_team, patch, n_membros, em_grupo) VALUES (?,?,?,?,?,?,?,?)",
        (partida["match_id"], partida["fila"], partida["inicio_ts"],
         partida["duracao_seg"], partida.get("vencedor_team"),
         partida.get("patch"), partida.get("n_membros", 0),
         int(partida.get("em_grupo", 0))))
    if cur.rowcount == 0:  # já existia
        row = conn.execute("SELECT id FROM partidas WHERE match_id=?",
                           (partida["match_id"],)).fetchone()
        return int(row["id"])
    pid = int(cur.lastrowid)
    conn.executemany(
        "INSERT OR IGNORE INTO participacoes (partida_id, puuid, membro_id,"
        " team_id, role, campeao, win, kills, deaths, assists, dano,"
        " dano_recebido, ouro, visao, farm, kp, ouro_10, ouro_15, lanediff_10,"
        " challenges_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(pid, p["puuid"], p.get("membro_id"), p["team_id"], p.get("role"),
          p.get("campeao"), int(p["win"]), p.get("kills"), p.get("deaths"),
          p.get("assists"), p.get("dano"), p.get("dano_recebido"), p.get("ouro"),
          p.get("visao"), p.get("farm"), p.get("kp"), p.get("ouro_10"),
          p.get("ouro_15"), p.get("lanediff_10"), p.get("challenges_json"))
         for p in participacoes])
    return pid


def salvar_timeline_derivada(conn, partida_id: int, derivado: dict) -> None:
    """Derivado é regravável (ao contrário de fato): reprocessar a timeline com
    um `formato` novo deve substituir, não acumular."""
    import json
    conn.execute(
        "INSERT INTO timeline_derivada (partida_id, formato, deficit_max,"
        " pico_max, minuto_deficit, dados_json) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(partida_id) DO UPDATE SET formato=excluded.formato,"
        " deficit_max=excluded.deficit_max, pico_max=excluded.pico_max,"
        " minuto_deficit=excluded.minuto_deficit, dados_json=excluded.dados_json",
        (partida_id, derivado.get("formato", 1), derivado.get("deficit_max"),
         derivado.get("pico_max"), derivado.get("minuto_deficit"),
         json.dumps(derivado, ensure_ascii=False)))


# ------------------------------------------------------------------ leitura

def membros(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM membros ORDER BY titular DESC, id")]


def puuid_por_membro(conn) -> dict[str, str]:
    return {r["id"]: r["puuid"] for r in conn.execute("SELECT id, puuid FROM membros")}


def partidas_do_grupo(conn, fila: Optional[int] = config.FILA_FLEX,
                      min_membros: int = 2) -> list[dict]:
    """O fio principal: partidas com `min_membros`+ do elenco no MESMO time,
    em ordem cronológica. É a série que a cronologia segmenta em eras."""
    sql = ("SELECT * FROM partidas WHERE n_membros >= ? "
           + ("AND fila = ? " if fila is not None else "")
           + "ORDER BY inicio_ts")
    args = (min_membros, fila) if fila is not None else (min_membros,)
    return [dict(r) for r in conn.execute(sql, args)]


def participacoes_de(conn, partida_ids: Iterable[int]) -> dict[int, list[dict]]:
    """Todas as participações das partidas dadas, agrupadas por partida.

    Em lote porque o padrão de acesso da cronologia é 'me dá os 10 de cada uma
    destas 300 partidas': uma query por partida seria 300 roundtrips para
    montar um único capítulo.
    """
    ids = list(partida_ids)
    if not ids:
        return {}
    out: dict[int, list[dict]] = {i: [] for i in ids}
    LOTE = 500   # abaixo do limite de variáveis de host do SQLite
    for i in range(0, len(ids), LOTE):
        fatia = ids[i:i + LOTE]
        marcas = ",".join("?" * len(fatia))
        for r in conn.execute(
                f"SELECT p.*, m.nome AS membro_nome FROM participacoes p "
                f"LEFT JOIN membros m ON m.id = p.membro_id "
                f"WHERE p.partida_id IN ({marcas})", fatia):
            out[r["partida_id"]].append(dict(r))
    return out


def participacoes_do_membro(conn, membro_id: str, fila: Optional[int] = None,
                            min_membros: Optional[int] = None) -> list[dict]:
    """Histórico individual, cronológico. Com `min_membros=None` pega tudo —
    é assim que a subtrama de SoloQ chega ao dossiê de personagem."""
    sql = ("SELECT p.*, t.inicio_ts, t.fila, t.duracao_seg, t.n_membros, t.patch "
           "FROM participacoes p JOIN partidas t ON t.id = p.partida_id "
           "WHERE p.membro_id = ?")
    args: list = [membro_id]
    if fila is not None:
        sql += " AND t.fila = ?"
        args.append(fila)
    if min_membros is not None:
        sql += " AND t.n_membros >= ?"
        args.append(min_membros)
    sql += " ORDER BY t.inicio_ts"
    return [dict(r) for r in conn.execute(sql, args)]


def timelines_derivadas(conn, partida_ids: Iterable[int]) -> dict[int, dict]:
    import json
    ids = list(partida_ids)
    if not ids:
        return {}
    out: dict[int, dict] = {}
    LOTE = 500
    for i in range(0, len(ids), LOTE):
        fatia = ids[i:i + LOTE]
        marcas = ",".join("?" * len(fatia))
        for r in conn.execute(
                f"SELECT partida_id, dados_json FROM timeline_derivada "
                f"WHERE partida_id IN ({marcas})", fatia):
            out[r["partida_id"]] = json.loads(r["dados_json"])
    return out

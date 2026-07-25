"""Handler de slash commands via HTTP (o que roda no Vercel).

Duas coisas precisam estar certas ou o endpoint não funciona:
 1. assinatura Ed25519 — o Discord recusa a URL se ela aceitar request mal
    assinado;
 2. resposta dentro do prazo, o que aqui significa: ler o banco e nada mais
    (sem Riot API, sem LLM, sem varrer histórico).
"""
import json

import pytest
from nacl.signing import SigningKey

from bot_lol import interactions, records
from bot_lol.db import database as db


def _chaves():
    sk = SigningKey.generate()
    return sk, sk.verify_key.encode().hex()


def _assinar(sk, timestamp: str, corpo: bytes) -> str:
    return sk.sign(timestamp.encode() + corpo).signature.hex()


# ---------------------------------------------------------------- assinatura
def test_assinatura_valida_passa():
    sk, pub = _chaves()
    corpo, ts = b'{"type":1}', "1700000000"
    interactions.verificar_assinatura(pub, _assinar(sk, ts, corpo), ts, corpo)


def test_assinatura_de_outra_chave_e_recusada():
    sk, _ = _chaves()
    _, pub_outra = _chaves()
    corpo, ts = b'{"type":1}', "1700000000"
    with pytest.raises(interactions.AssinaturaInvalida):
        interactions.verificar_assinatura(pub_outra, _assinar(sk, ts, corpo), ts, corpo)


def test_corpo_adulterado_e_recusado():
    """Assinatura cobre timestamp+corpo: mexeu no corpo, quebra."""
    sk, pub = _chaves()
    ts = "1700000000"
    assinatura = _assinar(sk, ts, b'{"type":1}')
    with pytest.raises(interactions.AssinaturaInvalida):
        interactions.verificar_assinatura(pub, assinatura, ts, b'{"type":2}')


def test_headers_ausentes_sao_recusados():
    _, pub = _chaves()
    with pytest.raises(interactions.AssinaturaInvalida):
        interactions.verificar_assinatura(pub, "", "", b"{}")


# ---------------------------------------------------------------- roteamento
def _banco():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "Grupo", discord_guild_id="42")
    j = db.ensure_jogador(conn, g, "P-H", "Hiroshi")
    pid = db.insert_partida(conn, g, "BR1_1", 440, 1800, 1, 100, True, False)
    db.insert_participacoes(conn, [
        {"partida_id": pid, "jogador_id": j, "puuid": "P-H", "team_id": 100,
         "role": "MIDDLE", "campeao": "Naafiri", "win": 1, "kills": 9,
         "deaths": 4, "assists": 9, "dano": 30000, "ouro": 14000, "visao": 20,
         "farm": 200, "kp": 0.5, "challenges_json": json.dumps({})},
        {"partida_id": pid, "jogador_id": None, "puuid": "E1", "team_id": 200,
         "role": "MIDDLE", "campeao": "Zed", "win": 0, "kills": 3, "deaths": 8,
         "assists": 4, "dano": 18000, "ouro": 9000, "visao": 8, "farm": 150,
         "kp": 0.3, "challenges_json": json.dumps({})},
    ])
    db.salvar_analises(conn, pid, "Foi um massacre.", {j: "Hiroshi carregou."}, "sonnet")
    return conn, g, j, pid


def test_ping_responde_pong():
    assert interactions.responder({"type": 1}) == {"type": interactions.PONG}


def test_recordes_usa_a_tabela_materializada():
    """O caminho que precisa caber nos 3s: uma query, não uma varredura."""
    conn, g, j, pid = _banco()
    records.materializar(conn, g)
    r = interactions.responder(
        {"type": 2, "guild_id": "42", "data": {"name": "recordes", "options": []}},
        conn=conn)
    assert r["type"] == interactions.CHANNEL_MESSAGE
    assert "HALL DA FAMA" in r["data"]["embeds"][0]["description"]


def test_time_devolve_a_narrativa_ja_cacheada():
    """A LLM não é chamada aqui — o ciclo já gerou e guardou."""
    conn, g, j, pid = _banco()
    r = interactions.responder(
        {"type": 2, "guild_id": "42", "data": {"name": "time", "options": []}},
        conn=conn)
    texto = " ".join(e["description"] for e in r["data"]["embeds"])
    assert "Escalação" in texto
    assert "Foi um massacre." in texto


def test_jogador_traz_a_analise_individual():
    conn, g, j, pid = _banco()
    r = interactions.responder(
        {"type": 2, "guild_id": "42",
         "data": {"name": "jogador",
                  "options": [{"name": "jogador", "value": "hiroshi"}]}},
        conn=conn)
    texto = " ".join(e["description"] for e in r["data"]["embeds"])
    assert "Hiroshi carregou." in texto


def test_jogador_inexistente_responde_efemero():
    """Erro do usuário não polui o canal."""
    conn, g, j, pid = _banco()
    r = interactions.responder(
        {"type": 2, "guild_id": "42",
         "data": {"name": "jogador",
                  "options": [{"name": "jogador", "value": "ninguem"}]}},
        conn=conn)
    assert r["data"]["flags"] == 64


def test_autocomplete_filtra_por_prefixo():
    conn, g, j, pid = _banco()
    r = interactions.responder(
        {"type": 4, "guild_id": "42",
         "data": {"name": "perfil",
                  "options": [{"name": "jogador", "value": "hir", "focused": True}]}},
        conn=conn)
    assert r["type"] == interactions.AUTOCOMPLETE_RESULT
    assert r["data"]["choices"] == [{"name": "Hiroshi", "value": "Hiroshi"}]


def test_comando_desconhecido_nao_explode():
    conn, g, j, pid = _banco()
    r = interactions.responder(
        {"type": 2, "guild_id": "42", "data": {"name": "sei_la"}}, conn=conn)
    assert r["data"]["flags"] == 64

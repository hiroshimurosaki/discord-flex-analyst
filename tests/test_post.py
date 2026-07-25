"""Teste leve do gerador de post (sem cache -> seção de momentos é pulada)."""
import json

from bot_lol import post
from bot_lol.db import database as db


def _setup():
    conn = db.get_connection(":memory:")
    db.init_db(conn)
    g = db.ensure_grupo(conn, "G", discord_guild_id="1")
    j1 = db.ensure_jogador(conn, g, "P-A", "Hiroshi")
    j2 = db.ensure_jogador(conn, g, "P-B", "Qiak")
    pid = db.insert_partida(conn, g, "BR1_SEMCACHE", 440, 1800, 0, 100, True, False)
    linhas = [
        {"partida_id": pid, "jogador_id": j1, "puuid": "P-A", "team_id": 100,
         "role": "MIDDLE", "campeao": "Naafiri", "win": 1, "kills": 9, "deaths": 4,
         "assists": 9, "dano": 50000, "ouro": 14000, "visao": 20, "farm": 200,
         "lanediff_10": 1233, "challenges_json": json.dumps({"soloKills": 5})},
        {"partida_id": pid, "jogador_id": j2, "puuid": "P-B", "team_id": 100,
         "role": "BOTTOM", "campeao": "Caitlyn", "win": 1, "kills": 14, "deaths": 5,
         "assists": 8, "dano": 52000, "ouro": 15000, "visao": 30, "farm": 250,
         "lanediff_10": -355, "challenges_json": json.dumps({})},
        # oponente direto do mid (não-membro)
        {"partida_id": pid, "jogador_id": None, "puuid": "E-1", "team_id": 200,
         "role": "MIDDLE", "campeao": "Lissandra", "win": 0, "kills": 2, "deaths": 9,
         "assists": 3, "dano": 20000, "ouro": 8000, "visao": 10, "farm": 157,
         "challenges_json": json.dumps({})},
    ]
    db.insert_participacoes(conn, linhas)
    return conn, pid


def test_post_tem_blocos_essenciais():
    conn, pid = _setup()
    txt = post.montar_post(conn, pid)
    assert "Vitória" in txt
    assert "Escalação" in txt
    assert "Duelo de rota" in txt
    # maior dano deve ser o Qiak (52k)
    assert "Maior dano: **Qiak**" in txt
    # duelo de rota do mid achou o oponente Lissandra
    assert "vs Lissandra" in txt
    # conquista de challenge (soloKills do Hiroshi)
    assert "abates solo" in txt
    # sem narrador -> placeholder do marco 5
    assert "marco 5" in txt


def test_post_injeta_narrador():
    """O narrador (callable fatos->texto) preenche a 🎙️ e recebe os fatos."""
    conn, pid = _setup()
    capturado = {}

    def narrador_fake(fatos):
        capturado["fatos"] = fatos
        return "NARRATIVA DE TESTE"

    txt = post.montar_post(conn, pid, narrador=narrador_fake)
    assert "🎙️ A leitura" in txt
    assert "NARRATIVA DE TESTE" in txt
    assert "marco 5" not in txt
    # o narrador recebeu os fatos determinísticos (não vazio, com a escalação)
    assert "Escalação" in capturado["fatos"]


def test_momentos_vem_do_banco_sem_cache():
    """A seção 🔑 é renderizada do banco — sem tocar em cache/.

    É o que permite montar o post no GitHub Actions e no Vercel, onde o
    diretório cache/ simplesmente não existe. Antes, a seção sumia em silêncio
    (ARQUITETURA 6.3).
    """
    conn, pid = _setup()

    db.salvar_momentos(conn, pid, {
        "v": 1,
        "swing": {"lider_team": 200, "delta": -4000, "de_min": 2, "ate_min": 3},
        "briga_decisiva": {"ini": 175.0, "fim": 185.0, "n_kills": 3,
                           "vencedor_team": 100},
        "dragoes": {"100": 3, "200": 1},
        "barao": {"100": 1450.0, "200": None},
        "multikills": [{"puuid": "P-A", "campeao": "Naafiri",
                        "tamanho": 3, "t": 1200.0}],
        "pickoffs": [{"puuid": "P-B", "campeao": "Caitlyn",
                      "regiao": "meio/rio", "t": 1400.0}],
    })

    txt = post.montar_post(conn, pid)
    assert "Momentos-chave" in txt
    # o time 100 venceu, mas o maior swing foi do 200 -> comeback
    assert "Virada" in txt
    assert "Briga decisiva 2:55–3:05" in txt
    assert "3 dragão(ões)" in txt and "Barão 24:10" in txt
    # puuid resolvido para o nick do membro
    assert "Hiroshi (Naafiri) — Triple Kill 20:00" in txt
    assert "Qiak pego sozinho no meio/rio" in txt


def test_sem_momentos_no_banco_secao_some_sem_quebrar():
    """Partida sem timeline: o post sai completo, só sem a seção 🔑."""
    conn, pid = _setup()
    txt = post.montar_post(conn, pid)
    assert "Momentos-chave" not in txt
    assert "Escalação" in txt        # o resto continua inteiro

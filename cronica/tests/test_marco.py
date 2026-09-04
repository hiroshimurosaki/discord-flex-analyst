"""O marco: mede se cada pessoa respondeu ao que foi apontado nela.

Este módulo emite frases sobre gente real ("o dossiê não pegou nele"), então o
que se testa aqui é sobretudo o que ele se RECUSA a afirmar: amostra curta vira
silêncio, e melhora dentro do ruído vira indício, nunca veredito.
"""
import datetime as dt

import pytest

from cronica.canone import Apontamento, Canone, Marco, Membro
from cronica.cronologia import marco as M
from cronica.cronologia.series import Cena

EL = frozenset({"a", "b"})


def cena(i, dia, mortes_a, venceu=True):
    d = dt.date(2025, 1, 1) + dt.timedelta(days=dia)
    return Cena(partida_id=i, match_id=f"M{i}",
                ts=int(dt.datetime.combine(d, dt.time(20),
                                           tzinfo=dt.timezone.utc).timestamp() * 1000),
                data=d, venceu=venceu, duracao_seg=1800, patch="15.01", elenco=EL,
                campeoes={m: "Ahri" for m in EL}, roles={m: "MIDDLE" for m in EL},
                kda={"a": (5, mortes_a, 8), "b": (5, 4, 8)},
                ouro={m: 12000 for m in EL}, dano={"a": 20000, "b": 20000},
                visao={m: 30 for m in EL}, farm={m: 150 for m in EL},
                lanediff_10={m: 0 for m in EL}, kp={m: 0.5 for m in EL})


CORTE = int(dt.datetime(2025, 2, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def avaliar(mortes_antes, mortes_depois, direcao="alto"):
    cenas = [cena(i, i, m) for i, m in enumerate(mortes_antes)]
    cenas += [cena(100 + i, 40 + i, m) for i, m in enumerate(mortes_depois)]
    return M.avaliar_apontamento(cenas, "a", "morre_pouco", direcao,
                                 "você morre demais", CORTE, iteracoes=2000)


def test_morrer_menos_depois_do_corte_e_atendeu():
    # 9 mortes -> 2 mortes: separação total, o acaso não produz isso.
    r = avaliar([9, 8, 9, 10, 9, 8, 9, 10], [2, 3, 2, 1, 2, 3, 2, 1])
    assert r.veredito == "atendeu"
    assert r.delta < 0            # morreu MENOS: o número desce
    assert r.p <= M.P_FORTE


def test_morrer_mais_depois_do_corte_e_piorou():
    r = avaliar([2, 3, 2, 1, 2, 3, 2, 1], [9, 8, 9, 10, 9, 8, 9, 10])
    assert r.veredito == "piorou"
    assert r.delta > 0


def test_sem_mudanca_e_inerte():
    r = avaliar([5, 4, 5, 6, 5, 4, 5, 6], [5, 6, 5, 4, 5, 6, 5, 4])
    assert r.veredito == "inerte"


def test_amostra_curta_de_um_lado_e_sem_dado():
    r = avaliar([9, 8, 9, 10, 9, 8, 9, 10], [2, 3])
    assert r.veredito == "sem_dado"
    assert r.media_antes is None and r.p is None
    assert r.n_depois == 2        # o número aparece: silêncio explicado, não vazio


def test_melhora_pequena_nao_vira_veredito():
    """5.0 -> 4.5 com dispersão alta é ruído. Tem de sair de 'atendeu'."""
    r = avaliar([5, 3, 7, 4, 6, 5, 3, 7], [4, 6, 3, 5, 5, 4, 6, 3])
    assert r.veredito in ("inerte", "indicio")
    assert r.veredito != "atendeu"


def test_direcao_baixo_inverte_o_julgamento():
    """`direcao='baixo'` em morre_pouco = 'era pra morrer MAIS' (agressividade).
    A dupla inversão tem de se cancelar: morrer mais passa a ser atender."""
    r = avaliar([2, 3, 2, 1, 2, 3, 2, 1], [9, 8, 9, 10, 9, 8, 9, 10],
                direcao="baixo")
    assert r.veredito == "atendeu"


def test_p_e_reprodutivel():
    """O p-valor vai para um slide: rodar duas vezes tem de dar o mesmo número."""
    a = avaliar([9, 8, 9, 10, 9, 8, 9, 10], [2, 3, 2, 1, 2, 3, 2, 1])
    b = avaliar([9, 8, 9, 10, 9, 8, 9, 10], [2, 3, 2, 1, 2, 3, 2, 1])
    assert a.p == b.p


def test_avaliar_percorre_os_apontamentos_do_marco():
    cenas = [cena(i, i, 9) for i in range(8)]
    cenas += [cena(100 + i, 40 + i, 2) for i in range(8)]
    c = Canone(
        time="T", desde=None,
        membros={m: Membro(id=m, nome=m.upper(), riot_ids=(f"{m}#BR1",))
                 for m in ("a", "b")},
        personagens={}, eventos=(),
        marcos=(Marco(id="dossie", data=dt.date(2025, 2, 1), titulo="O dossiê",
                      apontamentos=(Apontamento(membro="a", texto="morre demais",
                                                metrica="morre_pouco"),)),))
    (r,) = M.avaliar(cenas, c, "dossie", iteracoes=2000)
    assert r.membro == "a" and r.veredito == "atendeu"


def test_marco_inexistente_falha_alto():
    c = Canone(time="T", desde=None, membros={}, personagens={}, eventos=())
    with pytest.raises(KeyError):
        M.avaliar([], c, "nao_existe")


# ----------------------------------------------------------------------
# Tipos que os dossiês de verdade cobram: role, pool e volume.
# ----------------------------------------------------------------------

def cena_rp(i, dia, role, campeao):
    d = dt.date(2025, 1, 1) + dt.timedelta(days=dia)
    return Cena(partida_id=i, match_id=f"R{i}",
                ts=int(dt.datetime.combine(d, dt.time(20),
                                           tzinfo=dt.timezone.utc).timestamp() * 1000),
                data=d, venceu=True, duracao_seg=1800, patch="15.01", elenco=EL,
                campeoes={"a": campeao, "b": "Ahri"},
                roles={"a": role, "b": "MIDDLE"},
                kda={m: (5, 4, 8) for m in EL}, ouro={m: 12000 for m in EL},
                dano={"a": 20000, "b": 20000}, visao={m: 30 for m in EL},
                farm={m: 150 for m in EL}, lanediff_10={m: 0 for m in EL},
                kp={m: 0.5 for m in EL})


def _ap(**kw):
    return Apontamento(membro="a", texto="t", **kw)


def test_role_evitada_atendida_quando_a_fatia_cai():
    """'Pare de jogar ADC': 8 de 8 jogos de BOTTOM viram 0 de 8."""
    cenas = [cena_rp(i, i, "BOTTOM", "Jinx") for i in range(8)]
    cenas += [cena_rp(100 + i, 40 + i, "JUNGLE", "Zac") for i in range(8)]
    r = M.avaliar_ap(cenas, _ap(tipo="role_evitada", role="BOTTOM"), CORTE,
                     iteracoes=2000)
    assert r.veredito == "atendeu"
    assert r.media_antes == 1.0 and r.media_depois == 0.0


def test_role_evitada_piorou_quando_a_fatia_sobe():
    cenas = [cena_rp(i, i, "JUNGLE", "Zac") for i in range(8)]
    cenas += [cena_rp(100 + i, 40 + i, "BOTTOM", "Jinx") for i in range(8)]
    r = M.avaliar_ap(cenas, _ap(tipo="role_evitada", role="BOTTOM"), CORTE,
                     iteracoes=2000)
    assert r.veredito == "piorou"


def test_role_alvo_e_o_espelho_de_role_evitada():
    cenas = [cena_rp(i, i, "JUNGLE", "Zac") for i in range(8)]
    cenas += [cena_rp(100 + i, 40 + i, "MIDDLE", "Ahri") for i in range(8)]
    r = M.avaliar_ap(cenas, _ap(tipo="role_alvo", role="MIDDLE"), CORTE,
                     iteracoes=2000)
    assert r.veredito == "atendeu" and r.media_depois == 1.0


def test_pool_mede_concentracao_nos_campeoes_pedidos():
    """'One-trick Gnar': 1 em 8 vira 7 em 8."""
    antes = ["Gnar"] + ["Sett", "Darius", "Aatrox", "Yone", "Jax", "Olaf", "Teemo"]
    depois = ["Gnar"] * 7 + ["Sett"]
    cenas = [cena_rp(i, i, "TOP", c) for i, c in enumerate(antes)]
    cenas += [cena_rp(100 + i, 40 + i, "TOP", c) for i, c in enumerate(depois)]
    r = M.avaliar_ap(cenas, _ap(tipo="pool", campeoes=("Gnar",)), CORTE,
                     iteracoes=2000)
    assert r.veredito == "atendeu"
    assert r.media_antes == 0.12 and r.media_depois == 0.88


def test_pool_ignora_caixa_do_nome_do_campeao():
    cenas = [cena_rp(i, i, "TOP", "Sett") for i in range(8)]
    cenas += [cena_rp(100 + i, 40 + i, "gnar", "gnar") for i in range(8)]
    r = M.avaliar_ap(cenas, _ap(tipo="pool", campeoes=("Gnar",)), CORTE,
                     iteracoes=2000)
    assert r.media_depois == 1.0


def test_volume_conta_semanas_e_nao_partidas():
    """Uma partida por semana durante 8 semanas -> 7 por semana em 8 semanas."""
    # dias negativos mantêm as 8 semanas do "antes" inteiramente antes do corte
    cenas = [cena_rp(i, -70 + i * 7, "TOP", "Sett") for i in range(8)]
    cenas += [cena_rp(100 + i, 100 + i, "TOP", "Sett") for i in range(56)]
    r = M.avaliar_ap(cenas, _ap(tipo="volume"), CORTE, iteracoes=2000)
    assert r.veredito == "atendeu"
    assert r.media_antes == 1.0 and r.media_depois > 5


def test_volume_conta_semana_vazia_como_zero():
    """Sumir dois meses tem de puxar a média para baixo, não desaparecer."""
    from cronica.cronologia.marco import _por_semana
    cenas = [cena_rp(0, 0, "TOP", "Sett"), cena_rp(1, 56, "TOP", "Sett")]
    semanas = _por_semana(cenas, "a")
    assert len(semanas) == 9 and sum(semanas) == 2
    assert semanas.count(0.0) == 7


def test_apontamento_livre_nao_recebe_veredito():
    cenas = [cena_rp(i, i, "TOP", "Sett") for i in range(20)]
    r = M.avaliar_ap(cenas, _ap(tipo="livre"), CORTE, iteracoes=2000)
    assert r.veredito == "sem_dado" and r.p is None

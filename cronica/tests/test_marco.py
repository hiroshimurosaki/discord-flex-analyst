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

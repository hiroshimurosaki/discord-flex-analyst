"""Testa a escalação: os seletores existem para escolher cenas por FUNÇÃO
narrativa. Se eles escolherem errado, o capítulo conta a história errada com
números certos — o defeito mais difícil de perceber lendo o texto."""
import datetime as dt

from cronica.roteiro import momentos as M
from cronica.cronologia.series import Cena


def cena(i, venceu, champs=None, elenco=("a", "b", "c"), dias=0,
         deficit=None, pico=None, dur=1800, oponentes=None):
    el = frozenset(elenco)
    d = dt.date(2025, 1, 1) + dt.timedelta(days=dias or i)
    champs = champs or {m: "Ahri" for m in el}
    return Cena(partida_id=i, match_id=f"M{i}",
                ts=int(dt.datetime.combine(d, dt.time(20)).timestamp() * 1000),
                data=d, venceu=venceu, duracao_seg=dur, patch="15.01", elenco=el,
                campeoes=champs, roles={m: "MIDDLE" for m in el},
                kda={m: (5, 2, 8) for m in el},
                ouro={m: 12000 for m in el}, dano={m: 20000 for m in el},
                visao={m: 30 for m in el}, farm={m: 150 for m in el},
                lanediff_10={m: 100 for m in el}, kp={m: 0.5 for m in el},
                oponentes=oponentes or {"MIDDLE": "Zed"},
                deficit_max=deficit, pico_max=pico)


def test_fundo_do_poco_pega_a_maior_sequencia():
    cenas = ([cena(i, True) for i in range(5)]
             + [cena(i, False) for i in range(5, 10)]   # 5 derrotas
             + [cena(10, True)]
             + [cena(i, False) for i in range(11, 14)])  # 3 derrotas
    m = M.fundo_do_poco(cenas, {})
    assert m and m[0].dados["tamanho"] == 5
    assert len(m[0].partida_ids) == 5


def test_seca_curta_nao_vira_fundo_do_poco():
    cenas = [cena(0, True), cena(1, False), cena(2, False), cena(3, True)]
    assert M.fundo_do_poco(cenas, {}) == []


def test_catarse_e_a_vitoria_seguinte_a_seca():
    cenas = [cena(i, False) for i in range(4)] + [cena(4, True)]
    m = M.catarse(cenas, {})
    assert m and m[0].partida_ids == [4]


def test_catarse_nao_existe_se_a_era_termina_na_seca():
    cenas = [cena(i, True) for i in range(3)] + [cena(i, False) for i in range(3, 8)]
    assert M.catarse(cenas, {}) == []


def test_virada_exige_timeline_e_nao_improvisa():
    """Sem `deficit_max` o seletor devolve vazio em vez de inventar uma virada
    a partir do placar — cena falsa custa mais que cena ausente."""
    assert M.virada([cena(0, True), cena(1, True)], {}) == []
    cenas = [cena(0, True, deficit=1000), cena(1, True, deficit=9000)]
    m = M.virada(cenas, {})
    assert m and m[0].partida_ids == [1]


def test_espelho_exige_resultado_oposto_e_distancia_no_tempo():
    comp = {"a": "Ahri", "b": "Jinx", "c": "Thresh"}
    antiga = cena(1, False, champs=comp, dias=0)
    atual = cena(2, True, champs=comp, dias=400)
    m = M.espelho([atual], {"passado": [antiga]})
    assert m and m[0].dados["direcao"] == "derrota -> vitória"
    assert m[0].partida_ids == [1, 2]
    # mesmo resultado: não é espelho
    assert M.espelho([cena(3, False, champs=comp, dias=400)],
                     {"passado": [antiga]}) == []
    # perto demais no tempo: não prova evolução
    assert M.espelho([cena(4, True, champs=comp, dias=10)],
                     {"passado": [antiga]}) == []


def test_espelho_recusa_composicao_diferente():
    antiga = cena(1, False, champs={"a": "Ahri", "b": "Jinx", "c": "Thresh"})
    atual = cena(2, True, champs={"a": "Zed", "b": "Ezreal", "c": "Leona"},
                 dias=400)
    assert M.espelho([atual], {"passado": [antiga]}) == []


def test_recorde_so_e_noticia_na_era_em_que_cai():
    ctx = {}
    # A era 1 fixa os extremos dos DOIS recordes de duração (mais longa e
    # vitória mais rápida); a era 2 fica inteira no meio e não bate nada.
    era1 = [cena(0, True, dur=1200), cena(1, True, dur=3000),
            cena(2, True, dur=2000), cena(3, True, dur=2100),
            cena(4, True, dur=1900)]
    assert M.recorde(era1, ctx)          # o recorde nasce aqui
    era2 = [cena(i, True, dur=2000) for i in range(5, 10)]
    assert M.recorde(era2, ctx) == []    # nada foi batido: silêncio


def test_escalar_respeita_o_maximo_e_um_papel_por_capitulo():
    cenas = ([cena(i, False) for i in range(6)]
             + [cena(i, True, deficit=9000) for i in range(6, 20)])
    ms = M.escalar(cenas, {"titulares": {"a", "b", "c"}, "substitutos": set()},
                   maximo=4)
    assert len(ms) <= 4
    nao_pico = [m.papel for m in ms if m.papel != "pico_de_personagem"]
    assert len(nao_pico) == len(set(nao_pico))


class _Anot:
    def __init__(self, destacar=True, titulo=""):
        self.destacar, self.titulo = destacar, titulo


def test_partida_marcada_entra_mesmo_sem_criterio_nenhum():
    """A válvula de escape: o código escala por função narrativa, mas o dono da
    história é o usuário."""
    cenas = [cena(i, True) for i in range(5)]
    ctx = {"anotacoes": {"M3": _Anot(titulo="A partida da febre")}}
    ms = M.marcado_por_voce(cenas, ctx)
    assert len(ms) == 1
    assert ms[0].partida_ids == [3] and ms[0].titulo == "A partida da febre"


def test_anotacao_sem_destacar_nao_escala_a_cena():
    cenas = [cena(i, True) for i in range(5)]
    ms = M.marcado_por_voce(cenas, {"anotacoes": {"M3": _Anot(destacar=False)}})
    assert ms == []


def test_marcada_nao_e_escalada_duas_vezes_em_capitulos_diferentes():
    ctx = {"anotacoes": {"M3": _Anot()}}
    cenas = [cena(i, True) for i in range(5)]
    assert M.marcado_por_voce(cenas, ctx)
    assert M.marcado_por_voce(cenas, ctx) == []   # já usada


def test_marcada_tem_prioridade_maxima_na_escalacao():
    cenas = ([cena(i, False) for i in range(6)]
             + [cena(i, True, deficit=9000) for i in range(6, 20)])
    ms = M.escalar(cenas, {"titulares": {"a"}, "substitutos": set(),
                           "anotacoes": {"M9": _Anot()}}, maximo=3)
    assert ms[0].papel == "marcado_por_voce"

"""Testa a detecção de eras — a peça que, se estiver errada, faz TODOS os
capítulos ficarem errados sem levantar exceção nenhuma."""
import datetime as dt

from cronica.cronologia import eras as E
from cronica.cronologia.series import Cena


def cena(i, venceu, elenco=("a", "b", "c"), dia=None, patch="15.01", dur=1800):
    d = dia or (dt.date(2025, 1, 1) + dt.timedelta(days=i))
    el = frozenset(elenco)
    return Cena(partida_id=i, match_id=f"M{i}",
                ts=int(dt.datetime.combine(d, dt.time(20)).timestamp() * 1000),
                data=d, venceu=venceu, duracao_seg=dur, patch=patch, elenco=el,
                campeoes={m: "Ahri" for m in el}, roles={m: "MIDDLE" for m in el},
                kda={m: (3, 3, 3) for m in el}, ouro={m: 10000 for m in el},
                dano={m: 20000 for m in el}, visao={m: 30 for m in el},
                farm={m: 150 for m in el}, lanediff_10={m: 0 for m in el},
                kp={m: 0.5 for m in el})


def test_z_detecta_diferenca_real_e_ignora_ruido():
    _z, p = E._z_duas_proporcoes(18, 20, 4, 20)
    assert p < 0.001
    _z, p = E._z_duas_proporcoes(10, 20, 11, 20)
    assert p > 0.5


def test_quebra_de_winrate_cai_no_lugar_certo():
    vit = [0] * 30 + [1] * 30
    cortes = E._segmentar(vit)
    assert cortes, "não achou a quebra óbvia"
    assert abs(cortes[0][0] - 30) <= 3


def test_serie_homogenea_nao_inventa_fronteira():
    # Alternado: winrate estável em 50%. Qualquer corte aqui seria ruído.
    vit = [i % 2 for i in range(80)]
    assert E._segmentar(vit) == []


def test_hiato_vira_fronteira():
    cenas = [cena(i, i % 2 == 0) for i in range(20)]
    cenas += [cena(i, True, dia=dt.date(2025, 6, 1) + dt.timedelta(days=i - 20))
              for i in range(20, 40)]
    fs = E._fronteiras_hiato(cenas)
    assert [f.indice for f in fs] == [20]
    assert fs[0].forca == "certa"


def test_troca_de_elenco_persistente_vira_fronteira():
    cenas = [cena(i, True, elenco=("a", "b", "c")) for i in range(20)]
    cenas += [cena(i, True, elenco=("a", "b", "d")) for i in range(20, 40)]
    fs = E._fronteiras_elenco(cenas)
    assert fs and abs(fs[0].indice - 20) <= 2
    assert "d" in fs[0].detalhe and "c" in fs[0].detalhe


def test_substituicao_pontual_nao_vira_fronteira():
    """Uma partida com substituto NÃO é uma era nova — senão a história teria
    um capítulo por jogo."""
    cenas = [cena(i, True, elenco=("a", "b", "c")) for i in range(40)]
    cenas[17] = cena(17, True, elenco=("a", "b", "d"))
    assert E._fronteiras_elenco(cenas) == []


def test_eras_respeitam_o_minimo_de_partidas():
    cenas = ([cena(i, False) for i in range(40)]
             + [cena(i, True) for i in range(40, 80)])
    eras, _ = E.detectar(cenas, min_partidas=12)
    assert all(e.jogos >= 12 for e in eras)
    assert sum(e.jogos for e in eras) == 80


def test_forma_segue_o_delta_e_nao_a_vontade():
    assert E._forma(None, None, [], [], True)[0] == "estreia"
    assert E._forma(25.0, None, [], [], False)[0] == "ascensao"
    assert E._forma(-25.0, None, [], [], False)[0] == "queda"
    assert E._forma(1.0, None, [], [], False)[0] == "plato"
    assert E._forma(30.0, None, ["x"], [], False)[0] == "reconstrucao"
    assert E._forma(30.0, 90, [], [], False)[0] == "retomada"


def test_historico_curto_nao_e_segmentado():
    cenas = [cena(i, i % 3 == 0) for i in range(10)]
    eras, fronteiras = E.detectar(cenas, min_partidas=12)
    assert len(eras) == 1 and not fronteiras


def test_segmento_curto_funde_com_o_vizinho_menor():
    """Absorver um trecho curto na era enorme ao lado apagaria a fase inteira;
    juntar os dois pequenos tende a dar um capítulo do tamanho certo."""
    # segmentos: 100, 5, 15  -> o de 5 deve ir para o de 15, não para o de 100
    assert E._absorver_curtas([0, 100, 105, 120], 12) == [0, 100, 120]
    # segmentos: 15, 5, 100  -> espelho do caso acima
    assert E._absorver_curtas([0, 15, 20, 120], 12) == [0, 20, 120]


def test_absorver_nunca_apaga_as_bordas():
    assert E._absorver_curtas([0, 3, 40], 12)[0] == 0
    assert E._absorver_curtas([0, 37, 40], 12)[-1] == 40

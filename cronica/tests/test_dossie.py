"""O dossiê emite VEREDITO sobre pessoas reais. Um veredito errado é pior que
nenhum: ele vira uma frase confiante e falsa dentro da história."""
import datetime as dt

from cronica.canone.modelo import Canone, Membro, Personagem
from cronica.cronologia import dossie as D
from cronica.cronologia.series import Cena


def cena(i, venceu, dano, elenco=("a", "b", "c"), mortes=None, visao=None):
    el = frozenset(elenco)
    d = dt.date(2025, 1, 1) + dt.timedelta(days=i)
    return Cena(partida_id=i, match_id=f"M{i}",
                ts=int(dt.datetime.combine(d, dt.time(20)).timestamp() * 1000),
                data=d, venceu=venceu, duracao_seg=1800, patch="15.01", elenco=el,
                campeoes={m: "Ahri" for m in el}, roles={m: "MIDDLE" for m in el},
                kda={m: (5, (mortes or {}).get(m, 3), 8) for m in el},
                ouro={m: 12000 for m in el}, dano=dict(dano),
                visao=dict(visao) if visao else {m: 30 for m in el},
                farm={m: 150 for m in el}, lanediff_10={m: 0 for m in el},
                kp={m: 0.5 for m in el})


def canone(afirma):
    membros = {m: Membro(id=m, nome=m.upper(), riot_ids=(f"{m}#BR1",))
               for m in ("a", "b", "c")}
    return Canone(time="T", desde=None, membros=membros,
                  personagens={"a": Personagem(id="a", se_acha="eu carrego",
                                               afirma=tuple(afirma))},
                  eventos=())


ALTO = {"a": 40000, "b": 10000, "c": 10000}
BAIXO = {"a": 8000, "b": 26000, "c": 26000}
AFIRMA_DANO = [{"metrica": "dano", "direcao": "alto", "texto": "eu dou o dano"}]


def _veredito(inicio_dano, agora_dano, n=12):
    inicio = [cena(i, True, inicio_dano) for i in range(n)]
    agora = [cena(i, True, agora_dano) for i in range(n, 2 * n)]
    d = D.dossie_da_era(agora, inicio, canone(AFIRMA_DANO), "a")
    return d.vereditos[0].veredito


def test_sempre_foi_alto_e_confirmado():
    assert _veredito(ALTO, ALTO) == "confirmado"


def test_nunca_foi_alto_e_contradito():
    assert _veredito(BAIXO, BAIXO) == "contradito"


def test_era_baixo_e_ficou_alto_e_virou_verdade():
    """O veredito que existe para mostrar EVOLUÇÃO medida."""
    assert _veredito(BAIXO, ALTO) == "virou_verdade"


def test_era_alto_e_caiu_e_desmentido_pelo_tempo():
    assert _veredito(ALTO, BAIXO) == "desmentido_pelo_tempo"


def test_amostra_pequena_nao_gera_veredito():
    assert _veredito(ALTO, ALTO, n=3) == "sem_dado"


def test_mediana_dos_pares_exclui_o_proprio_avaliado():
    """Se o avaliado entrasse na própria mediana, num time pequeno o valor dele
    PODERIA ser a mediana e `valor >= mediana` seria verdadeiro por construção —
    'confirmado' sem evidência, justo nos casos medianos."""
    cenas = [cena(i, True, {"a": 20000, "b": 10000, "c": 30000})
             for i in range(12)]
    pares = D._metricas_do_time(cenas, ["a", "b", "c"], "dano", exceto="a")
    assert len(pares) == 2
    assert D._metricas_do_time(cenas, ["a", "b", "c"], "dano") != pares


def test_morre_pouco_inverte_a_direcao():
    """'morre pouco' é a única métrica em que MENOS é melhor. Sem a inversão,
    quem mais morre seria elogiado."""
    poucas = {"a": 1, "b": 8, "c": 8}
    assert D._sustenta(1, [8, 8], "alto", "morre_pouco") is True
    assert D._sustenta(9, [2, 2], "alto", "morre_pouco") is False
    assert D._sustenta(9, [2, 2], "alto", "dano") is True


def test_quem_nao_jogou_a_era_e_marcado_ausente():
    cenas = [cena(i, True, ALTO, elenco=("b", "c")) for i in range(12)]
    d = D.dossie_da_era(cenas, cenas, canone(AFIRMA_DANO), "a")
    assert d.presente is False and d.jogos == 0


def test_dano_e_normalizado_como_share_do_time():
    """Absoluto não compara jogo de 22 min com jogo de 41."""
    curta = [cena(i, True, {"a": 20000, "b": 10000, "c": 10000}) for i in range(4)]
    m = D.medir(curta, "a")
    assert m["dano"] == 50.0


def test_percentil_e_contra_os_dez_e_nao_contra_os_quatro():
    """O rótulo da métrica promete 'você vs os 10'. Medir contra os quatro
    companheiros responderia outra pergunta ('quem carregou o time?') e a
    chamaria pelo nome errado — inflando o percentil de quem joga em time fraco."""
    dano = {"a": 15000, "b": 30000, "c": 30000}
    dez = tuple(sorted([15000, 30000, 30000] + [40000] * 7))   # 'a' é o pior dos 10
    cenas = []
    for i in range(12):
        c = cena(i, True, dano)
        cenas.append(c.__class__(**{**c.__dict__, "dano_dos_dez": dez}))
    assert D.medir(cenas, "a")["carrega"] == 0.0     # último entre os dez

    sem_dez = [cena(i, True, dano) for i in range(12)]
    assert D.medir(sem_dez, "a")["carrega"] == 0.0   # fallback: último dos 3
    # e o do meio contra os dez não é o mesmo que contra os companheiros
    cs = [c.__class__(**{**c.__dict__, "dano_dos_dez": dez})
          for c in (cena(i, True, dano) for i in range(12))]
    assert D.medir(cs, "b")["carrega"] < D.medir(sem_dez, "b")["carrega"]

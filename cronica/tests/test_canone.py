"""O cânone é escrito à mão, então o validador é a única defesa contra um typo
que faria o dossiê de alguém sumir do briefing sem erro nenhum."""
import pytest
import yaml

from cronica.canone import ErroCanone, carregar

BASE = {
    "time": {"nome": "T", "desde": "2024-01"},
    "elenco": {"titulares": {"a": {"nome": "A", "riot_id": "A#BR1", "role": "TOP"}},
               "substitutos": {"b": {"nome": "B", "riot_id": "B#BR1",
                                     "entra_no_lugar_de": "a"}}},
    "personagens": {},
    "eventos": [],
}


def escrever(tmp_path, dados):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8")
    return p


def test_canone_minimo_carrega(tmp_path):
    c = carregar(escrever(tmp_path, BASE))
    assert [m.id for m in c.titulares] == ["a"]
    assert c.substitutos[0].entra_no_lugar_de == "a"


def test_riot_id_sem_tag_e_recusado(tmp_path):
    d = {**BASE, "elenco": {"titulares": {"a": {"riot_id": "SemTag"}}}}
    with pytest.raises(ErroCanone, match="#TAG"):
        carregar(escrever(tmp_path, d))


def test_personagem_fora_do_elenco_e_recusado(tmp_path):
    """O erro que este teste pega é o pior de todos: silencioso. Um id errado
    faria o dossiê da pessoa sumir do briefing sem nenhum aviso."""
    d = {**BASE, "personagens": {"typo": {"arquetipo": "x"}}}
    with pytest.raises(ErroCanone, match="não existe no elenco"):
        carregar(escrever(tmp_path, d))


def test_substituto_apontando_para_ninguem_e_recusado(tmp_path):
    d = {**BASE, "elenco": {"titulares": {"a": {"riot_id": "A#BR1"}},
                            "substitutos": {"b": {"riot_id": "B#BR1",
                                                  "entra_no_lugar_de": "zzz"}}}}
    with pytest.raises(ErroCanone, match="entra_no_lugar_de"):
        carregar(escrever(tmp_path, d))


def test_metrica_invalida_em_afirma_e_recusada(tmp_path):
    d = {**BASE, "personagens": {"a": {"afirma": [{"metrica": "carisma"}]}}}
    with pytest.raises(ErroCanone, match="metrica"):
        carregar(escrever(tmp_path, d))


def test_tipo_de_evento_invalido_e_recusado(tmp_path):
    d = {**BASE, "eventos": [{"data": "2025-01-01", "tipo": "fofoca",
                              "titulo": "x"}]}
    with pytest.raises(ErroCanone, match="tipo"):
        carregar(escrever(tmp_path, d))


def test_eventos_saem_ordenados_por_data(tmp_path):
    d = {**BASE, "eventos": [
        {"data": "2025-06-01", "tipo": "marco", "titulo": "b"},
        {"data": "2025-01-01", "tipo": "marco", "titulo": "a"}]}
    c = carregar(escrever(tmp_path, d))
    assert [e.titulo for e in c.eventos] == ["a", "b"]


def test_canone_vazio_nao_quebra_o_pipeline(tmp_path):
    """Dá para rodar sem personalidade preenchida — o briefing só avisa a
    narração para não inventar jeito de ser de ninguém."""
    c = carregar(escrever(tmp_path, BASE))
    assert not c.personagem("a").preenchido

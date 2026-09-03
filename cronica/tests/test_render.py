"""O render é a única parte que o grupo vê. Um SVG quebrado ou um frontmatter
mal lido não levanta exceção — só produz um slide vazio."""
from types import SimpleNamespace

from cronica.render import svg
from cronica.render.livro import ler_capitulo


def era(n, wr, jogos=30, forma="plato"):
    return SimpleNamespace(numero=n, wr=wr, jogos=jogos, forma=forma,
                           data_inicio="2025-01-01", data_fim="2025-03-01")


def test_linha_do_tempo_gera_svg_valido():
    s = svg.linha_do_tempo([era(1, 40), era(2, 65, forma="ascensao")])
    assert s.startswith("<svg") and s.endswith("</svg>")
    assert s.count("<rect") == 2
    assert 'viewBox="0 0 1000 260"' in s


def test_linha_do_tempo_sem_eras_nao_quebra():
    assert svg.linha_do_tempo([]) == "<svg/>"


def test_svg_escapa_texto_do_usuario():
    """Nome de jogador com '<' viraria markup e quebraria o slide inteiro."""
    s = svg.linha_do_tempo([era(1, 50)], titulo='<script>x</script>')
    assert "<script>" not in s and "&lt;script&gt;" in s


def test_sparkline_precisa_de_dois_pontos():
    assert svg.sparkline([5]) == "<svg/>"
    assert "<polyline" in svg.sparkline([1, 5, 3])


def test_barras_comparadas_ignora_pares_incompletos():
    s = svg.barras_comparadas(["x", "y"], [10, None], [20, 30])
    assert s.count("<rect") == 2      # só o par completo, 2 barras


def test_frontmatter_do_capitulo_e_lido_de_volta(tmp_path):
    p = tmp_path / "cap01.md"
    p.write_text('---\ncapitulo: 1\ntitulo: "A Volta"\nnucleo: ["a", "b"]\n---\n\n'
                 "# A Volta\n\ntexto\n", encoding="utf-8")
    fm, corpo = ler_capitulo(p)
    assert fm["capitulo"] == 1 and fm["titulo"] == "A Volta"
    assert fm["nucleo"] == ["a", "b"]
    assert corpo.startswith("# A Volta")


def test_capitulo_sem_frontmatter_nao_quebra(tmp_path):
    p = tmp_path / "cap01.md"
    p.write_text("# Só o texto\n", encoding="utf-8")
    fm, corpo = ler_capitulo(p)
    assert fm == {} and corpo.startswith("# Só o texto")

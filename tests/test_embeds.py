"""Partição de texto em embeds — o final do post não pode se perder."""
from bot_lol import embeds


def test_texto_curto_vira_um_embed_so():
    assert embeds.partir("oi") == ["oi"]
    assert len(embeds.construir("oi")) == 1


def test_texto_longo_preserva_o_final():
    """O bug que isto previne: `texto[:4096]` comia os recordes e a narrativa."""
    corpo = "\n\n".join(f"paragrafo {i} " + "x" * 200 for i in range(60))
    texto = corpo + "\n\n**🏆 Recordes**\n• RECORDE FINAL"

    partes = embeds.partir(texto)
    assert len(partes) > 1
    assert all(len(p) <= embeds.LIMITE_DESC for p in partes)
    assert "RECORDE FINAL" in partes[-1]
    # nada foi perdido no meio do caminho
    assert sum(p.count("paragrafo ") for p in partes) == 60


def test_corte_dentro_de_bloco_de_codigo_reabre_o_bloco():
    """Cortar dentro de ``` faria o Discord tratar o resto como código."""
    texto = "```\n" + "\n".join(f"linha {i} " + "y" * 60 for i in range(200)) + "\n```"
    partes = embeds.partir(texto)
    assert len(partes) > 1
    for p in partes:
        assert p.count("```") % 2 == 0, "pedaço deixou bloco de código aberto"


def test_nao_corta_no_meio_de_palavra():
    texto = " ".join(["palavra"] * 2000)
    for p in embeds.partir(texto):
        assert not p.endswith("palavr")


def test_cor_segue_o_resultado():
    assert embeds.cor_do_resultado("🏆 **Vitória** • Flex") == embeds.VERDE
    assert embeds.cor_do_resultado("❌ **Derrota** • Flex") == embeds.VERMELHO
    assert embeds.cor_do_resultado("sem resultado") == embeds.AZUL

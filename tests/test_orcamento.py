"""Testes de ai/orcamento.py: o alvo de palavras proporcional ao material, a divisão entre os personagens, o plano das
falas e o mínimo que o QA cobra."""
import pytest

from techdigest.ai import orcamento as modulo
from techdigest.ai.lados import Lado
from techdigest.ai.orcamento import Orcamento, minimo_do_qa, orcamento, palavras


def _lados(*mencoes) -> list[Lado]:
    return [Lado("p", (f"Ator {i}",), ("G1",), f"Resposta {i}" if len(mencoes) > 1 else "", (), m) for i, m in enumerate(mencoes)]


def test_o_total_e_o_fator_vezes_as_palavras_com_piso_e_teto_no_alvo_de_antes():
    assert orcamento(_lados(None), 201).total == 350          # 1,75 × 201, como no N86 de 17/10
    assert orcamento(_lados(None), 100).total == 300          # o piso
    assert orcamento(_lados(None), 2000).total == 780         # o teto: Helena e um analista, 390 cada
    assert orcamento(_lados(None)).total == 780               # sem a medida, o alvo de antes
    assert not orcamento(_lados(None), 2000).reduzido and orcamento(_lados(None), 201).reduzido
    assert orcamento(_lados(None, None), 5000).total == 3 * 360
    assert orcamento(_lados(4, 4, 4), 5000).total == 1150     # 4 × 285, com o arredondamento de cada analista à dezena


def test_a_helena_fica_com_a_parte_de_antes_entre_35_e_45_por_cento():
    assert [modulo.parte_da_helena(n) for n in (1, 2, 3)] == [0.45, 0.35, 0.35]
    um = orcamento(_lados(None), 2000)
    assert (um.helena, um.analistas) == (350, (430,))      # perto dos 390 de antes para cada um


def test_os_analistas_dividem_pelas_mencoes_com_120_no_minimo_e_430_no_maximo():
    # o lado com menos menções fica com o mínimo; o outro, com o resto, até o máximo
    assert orcamento(_lados(2, 12), 239).analistas == (120, 150)
    assert orcamento(_lados(2, 12), 5000).analistas == (120, 430)
    assert orcamento(_lados(4, 4), 5000).analistas == (350, 350)
    # lado sem contagem conta como a média dos outros
    assert orcamento(_lados(None, None), 5000).analistas == (350, 350)
    assert orcamento(_lados(None, 4), 5000).analistas == (350, 350)
    # pouco material e três lados: todos no mínimo, e o total passa do 1,75 × texto
    assert orcamento(_lados(2, 2, 2), 150).analistas == (120, 120, 120)


def test_com_dois_lados_o_alvo_do_analista_nao_passa_de_90_palavras_por_frase_do_lado():
    # decisão de 24/10/2026: com uma frase, o teto prevalece sobre o piso de 120 (o N92)
    assert orcamento(_lados(1, 6), 239).analistas == (90, 150)
    assert orcamento(_lados(1, 6), 5000).analistas == (90, 430)
    # o A79: 4 frases do ministro e 2 do comandante; o que o teto tira sai do total, e a Helena fica com a parte dela
    a79 = orcamento(_lados(4, 2), 755)
    assert (a79.helena, a79.analistas, a79.total, a79.reduzido) == (380, (360, 180), 920, False)   # o texto não é curto
    # lado com zero menções conta como uma, na divisão e no teto; lado sem contagem não tem teto
    assert orcamento(_lados(0, 1), 5000).analistas == (90, 90)
    assert orcamento(_lados(None, 1), 5000).analistas == (350, 90)
    assert orcamento(_lados(1, 1, 1), 150).analistas == (90, 90, 90)
    # quando o teto corta, a Helena não passa de 45% do total que fica
    pouco = orcamento(_lados(0, 1), 5000)
    assert pouco.helena == 150 and pouco.helena / pouco.total <= modulo.MAIOR_PARTE_DA_HELENA + 0.01
    # com um lado só, o analista explica a história inteira, e o alvo dele não muda
    assert orcamento(_lados(1), 2000).analistas == (430,)


def test_o_plano_diz_quantas_falas_cada_personagem_tem_de_que_tamanho_e_em_que_ordem():
    # um analista: Helena e analista alternados, começando e terminando com a Helena
    um = Orcamento(350, (430,), None).plano
    assert (um.falas, um.tamanhos, um.ordem, um.turnos) == ((6, 5), (60, 85), (0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0), 11)
    # dois analistas, como no N13 de 24/10/2026: a Helena fala entre as rodadas, e o lado fino tem o mínimo de falas
    n13 = Orcamento(260, (360, 120), None).plano
    assert (n13.falas, n13.tamanhos, n13.ordem) == ((5, 4, 2), (50, 90, 60), (0, 1, 2, 0, 1, 2, 0, 1, 0, 1, 0))
    # pouco material: cada analista fala pelo menos duas vezes, e as falas encolhem
    assert Orcamento(140, (120, 140), None).plano.falas == (3, 2, 2)
    assert Orcamento(160, (190,), None).plano == modulo.Plano((4, 3), (40, 65), (0, 1, 0, 1, 0, 1, 0))
    assert Orcamento(350, (430,), None).turnos == 11


@pytest.mark.parametrize("n", [1, 2, 3])
def test_o_plano_fecha_a_conta_do_alvo_e_comeca_e_termina_com_a_helena(n):
    for texto in range(50, 1500, 23):
        for mencoes in ([None], [1, 4], [2, 2], [1, 4, 2], [3, 3, 3]):
            if len(mencoes) != n:
                continue
            orc = orcamento(_lados(*mencoes), texto)
            plano = orc.plano
            assert plano.ordem[0] == plano.ordem[-1] == 0 and plano.turnos <= 20
            assert all(not (a == b == 0) for a, b in zip(plano.ordem, plano.ordem[1:]))   # a Helena nunca fala duas vezes seguidas
            for i, (alvo, falas, tamanho) in enumerate(zip((orc.helena, *orc.analistas), plano.falas, plano.tamanhos)):
                assert plano.ordem.count(i) == falas
                assert abs(falas * tamanho - alvo) <= 2.5 * falas                          # o tamanho arredondado a 5
                if i:
                    assert falas >= modulo.MIN_FALAS_DO_ANALISTA and alvo / falas <= modulo.MAX_FALA_DO_ANALISTA


def test_o_minimo_do_qa_fica_abaixo_do_alvo_e_nunca_acima_do_de_antes():
    # no N92 o alvo da Helena seria de uns 150: o piso de 180 da Helena com debate passaria do alvo
    assert minimo_do_qa(150, 180) == 90 < 150
    assert minimo_do_qa(430, 240) == 240 and minimo_do_qa(120, 120) == 72 and minimo_do_qa(90, 120) == 54
    for n in (1, 2, 3):
        for texto in range(50, 1200, 37):
            orc = orcamento(_lados(*([1, 4, 2][:n])), texto)
            for alvo in (orc.helena, *orc.analistas):
                assert minimo_do_qa(alvo, 240) <= 0.60 * alvo < alvo <= modulo.MAX_ALVO
            assert minimo_do_qa(orc.total, 600) < orc.total


def test_as_palavras_sao_as_dos_recortes_sem_o_titulo():
    assert palavras([{"titulo": "Um título comprido", "texto": "três palavras aqui"}, {"titulo": "x", "texto": "mais duas"}]) == 5

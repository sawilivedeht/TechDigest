"""Testes de ai/orcamento.py: o alvo de palavras proporcional ao material, a divisão entre os personagens, os turnos e o
mínimo que o QA cobra."""
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
    assert orcamento(_lados(3, 3), 5000).total == 3 * 360
    assert orcamento(_lados(3, 3, 3), 5000).total == 1150     # 4 × 285, com o arredondamento de cada analista à dezena


def test_a_helena_fica_com_a_parte_de_antes_entre_35_e_45_por_cento():
    assert [modulo.parte_da_helena(n) for n in (1, 2, 3)] == [0.45, 0.35, 0.35]
    um = orcamento(_lados(None), 2000)
    assert (um.helena, um.analistas) == (350, (430,))      # perto dos 390 de antes para cada um


def test_os_analistas_dividem_pelas_mencoes_com_120_no_minimo_e_430_no_maximo():
    # o lado fino (uma menção) fica com o mínimo; o outro, com o resto, até o máximo
    assert orcamento(_lados(1, 6), 239).analistas == (120, 150)
    assert orcamento(_lados(1, 6), 5000).analistas == (120, 430)
    assert orcamento(_lados(2, 2), 5000).analistas == (350, 350)
    # lado sem contagem conta como a média dos outros; lado com zero menções, como uma
    assert orcamento(_lados(None, None), 5000).analistas == (350, 350)
    assert orcamento(_lados(0, 1), 5000).analistas == (350, 350)
    # pouco material e três lados: todos no mínimo, e o total passa do 1,75 × texto
    assert orcamento(_lados(1, 1, 1), 150).analistas == (120, 120, 120)


@pytest.mark.parametrize("total, turnos, por_fala", [
    (350, 5, (70, 80)),       # 350 / 75 = 4,7: cinco turnos de 70 palavras
    (470, 6, (70, 80)),
    (780, 10, (70, 80)),      # material cheio: dez turnos de 78
    (1080, 14, (70, 80)),
])
def test_o_numero_de_turnos_e_um_so_calculado_com_falas_de_70_a_80(total, turnos, por_fala):
    orc = Orcamento(total // 2, (total - total // 2,), None)
    assert (orc.turnos, orc.por_fala) == (turnos, por_fala)
    assert 70 <= total / orc.turnos <= 80


def test_a_estrutura_pode_pedir_mais_turnos_e_as_falas_ficam_menores():
    # Helena abre, fecha e passa a palavra a cada analista duas vezes: 5, 7 ou 9 turnos no mínimo
    assert Orcamento(140, (160,), None).turnos == 5 and Orcamento(140, (160,), None).por_fala == (60, 60)
    tres = orcamento(_lados(1, 1, 1), 150)
    assert (tres.total, tres.turnos, tres.por_fala) == (470, 9, (52, 52))
    dois = orcamento(_lados(1, 6), 239)                            # o N92: 420 palavras em 7 turnos
    assert (dois.total, dois.turnos, dois.por_fala) == (420, 7, (60, 60))
    assert orcamento(_lados(3, 3, 3), 5000).turnos == 15 and Orcamento(9990, (9990,) * 3, None).turnos == 20   # o teto


def test_o_minimo_do_qa_fica_abaixo_do_alvo_e_nunca_acima_do_de_antes():
    # no N92 o alvo da Helena seria de uns 150: o piso de 180 da Helena com debate passaria do alvo
    assert minimo_do_qa(150, 180) == 112 < 150
    assert minimo_do_qa(430, 240) == 240 and minimo_do_qa(120, 120) == 90
    for n in (1, 2, 3):
        for texto in range(50, 1200, 37):
            orc = orcamento(_lados(*([1, 4, 2][:n])), texto)
            for alvo in (orc.helena, *orc.analistas):
                assert minimo_do_qa(alvo, 240) <= 0.75 * alvo < alvo <= modulo.MAX_ALVO
            assert minimo_do_qa(orc.total, 600) < orc.total


def test_as_palavras_sao_as_dos_recortes_sem_o_titulo():
    assert palavras([{"titulo": "Um título comprido", "texto": "três palavras aqui"}, {"titulo": "x", "texto": "mais duas"}]) == 5

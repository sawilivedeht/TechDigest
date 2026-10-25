"""Testes de ai/elenco.py (os nomes dos analistas, que o código dá) e da voz de cada nome em audio/tts.py."""
from techdigest.ai import elenco
from techdigest.ai.elenco import VAGAS, mesmo_nome, nomes_dos_analistas, vaga
from techdigest.ai.lados import Lado, lado_unico
from techdigest.audio.tts import VOZ_FIXA, VOZES_DIVERSIDADE, atribuir_vozes


def _lados(*atores) -> list[Lado]:
    return [Lado("p", tuple(a), ("G1",), f"Resposta {i}") for i, a in enumerate(atores)]


def test_um_nome_por_lado_o_primeiro_da_vaga_que_nao_coincide_com_um_ator():
    assert nomes_dos_analistas(lado_unico(["G1"])) == ["Otávio"]             # o lado neutro também tem um analista
    assert nomes_dos_analistas(_lados(["Ivo Brandão"], ["Marta Quaresma"])) == ["Otávio", "Patrícia"]
    assert nomes_dos_analistas(_lados(["A"], ["B"], ["C"])) == ["Otávio", "Patrícia", "Vinícius"]
    # o nome e o primeiro nome de um ator saem, de qualquer lado; o sobrenome não conta
    assert nomes_dos_analistas(_lados(["Otávio Lins"], ["Patrícia"])) == ["Mateus", "Sofia"]
    assert nomes_dos_analistas(_lados(["presidente Otávio Lins", "Mateus Prado"], ["B"])) == ["Caio", "Patrícia"]   # sem o cargo
    assert nomes_dos_analistas(_lados(["Ivo Otávio"], ["B"])) == ["Otávio", "Patrícia"]


def test_todos_coincidem_fica_o_ultimo_da_vaga():
    assert nomes_dos_analistas(_lados(["Otávio Lins", "Mateus Prado", "Caio Reis"], ["B"])) == ["Caio", "Patrícia"]


def test_mesmo_nome_compara_sem_titulos_acento_nem_caixa():
    assert mesmo_nome("Bruno", "Bruno Silva") == "o primeiro nome" and mesmo_nome("Bruno Costa", "Bruno Silva") == "o primeiro nome"
    assert mesmo_nome("Dr. Bruno Silva", "bruno silva") == "o nome" and mesmo_nome("Otavio", "Otávio") == "o nome"
    assert mesmo_nome("Dr. Silva", "Bruno Silva") == "" and mesmo_nome("Campanha", "campanha de Lula") == ""   # minúscula não é nome


def test_os_nomes_sao_de_pessoa_e_unicos_e_cada_um_tem_a_voz_da_sua_vaga():
    nomes = [n for v in VAGAS for n in v]
    assert len(nomes) == len(set(nomes)) and all(n[:1].isupper() and " " not in n for n in nomes)
    assert len(VAGAS) <= len(VOZES_DIVERSIDADE)                             # toda vaga tem voz
    for i, v in enumerate(VAGAS):
        for nome in v:
            assert vaga(nome) == i and atribuir_vozes([{"nome": "Helena"}, {"nome": nome}])[nome] == VOZES_DIVERSIDADE[i]
    # a voz é a do nome, não a da ordem: a analista única do lado 2 de antes falava com a primeira voz, masculina
    assert atribuir_vozes([{"nome": "Patrícia"}, {"nome": "Otávio"}]) == {"Patrícia": "pt-BR-ThalitaNeural", "Otávio": "pt-BR-AntonioNeural"}
    assert atribuir_vozes([{"nome": "Helena"}])["Helena"] == VOZ_FIXA["Helena"]


def test_nome_fora_da_lista_fica_com_uma_voz_que_sobrou():
    vozes = atribuir_vozes([{"nome": "Helena"}, {"nome": "Otávio"}, {"nome": "Analista"}, {"nome": "Bia"}])
    assert vozes["Otávio"] == VOZES_DIVERSIDADE[0] and vozes["Analista"] == VOZES_DIVERSIDADE[1] and vozes["Bia"] == VOZES_DIVERSIDADE[2]
    assert elenco.vaga("Analista") is None

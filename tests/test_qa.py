"""Testes da regra de fontes de ai/qa.py (as demais regras dependem dos limites QA_* do .env)."""
import math

from techdigest.ai import qa


def _episodio(fontes) -> dict:
    por_personagem = max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 2))
    fala = " ".join(["palavra"] * por_personagem)
    return {
        "resumo_didatico": "Uma frase. " * qa.MIN_FRASES_RESUMO,
        "personagens": [{"nome": "Helena"}, {"nome": "Ramos"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Ramos", "fala": fala}],
        "fontes_citadas": fontes,
    }


def test_episodio_de_uma_fonte_so_nao_muda():
    assert qa.problemas(_episodio([])) == []
    assert qa.problemas(_episodio([]), ["G1"]) == []
    assert qa.problemas(_episodio(["outra coisa"]), ["Agência Brasil", "agencia brasil"]) == []   # dois textos, um veículo


def test_com_dois_veiculos_todos_tem_de_estar_em_fontes_citadas():
    assert qa.problemas(_episodio(["G1", "Folha de S.Paulo"]), ["G1", "Folha de S.Paulo"]) == []
    [problema] = qa.problemas(_episodio(["G1"]), ["G1", "Folha de S.Paulo", "Estadão"])
    assert problema.startswith("fontes_citadas sem Folha de S.Paulo, Estadão (o episódio tem 3 veículos como fonte")
    assert len(qa.problemas(_episodio("G1 e Folha"), ["G1", "Folha"])) == 1                       # lista malformada não vale


def test_comparacao_de_veiculos_e_tolerante_mas_por_palavras_inteiras():
    assert qa.problemas(_episodio(["o globo", "AGENCIA BRASIL (EBC)", "Folha"]), ["O GLOBO", "Agência Brasil", "Folha de S.Paulo"]) == []
    assert qa.mesmo_veiculo("Valor", "Valor Econômico") and qa.mesmo_veiculo("g1", "G1")
    assert not qa.mesmo_veiculo("ge", "Agência Brasil")           # "ge" está dentro de "Agência", mas não é palavra
    assert not qa.mesmo_veiculo("G1", "") and not qa.mesmo_veiculo("Estadão", "O Estado de S. Paulo")
    assert qa.veiculos_distintos(["G1", "g1", "Folha", "Folha de S.Paulo", "ge"]) == ["G1", "Folha", "ge"]

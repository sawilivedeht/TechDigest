"""Testes das regras de ai/qa.py que não dependem dos limites QA_* do .env: fontes, título e analistas por lado."""
import math

import pytest

from techdigest.ai import qa
from techdigest.ai.lados import Lado, lado_unico
from techdigest.ai.verbos import FORMAS_DE_POSICAO, VERBOS_DE_POSICAO, verbos_de_posicao

# Os títulos dos cinco episódios gerados em 11/10/2026 (data/agrupamento/episodios/).
TITULOS_REAIS = {
    1: "O novo eixo diplomático: as projeções para a política externa de Flávio Bolsonaro",
    2: "Violência política contra mulheres cresce e atinge quase 60% das candidatas no primeiro turno",
    3: "Meta é acionada por suspeitas de favorecimento eleitoral nas redes sociais",
    4: "Força-tarefa federal é mobilizada para combater queimadas no Amazonas",
    5: "TSE suspende canal 'Exército de Lula' após pedido de Flávio Bolsonaro",
}

UM_LADO = lado_unico(["G1"])
# Os lados das pautas dos episódios 3 e 5, como a análise de lados deve devolvê-los.
LADOS_DA_META = [
    Lado("A campanha de Lula acusa a Meta de reduzir o alcance do presidente.", ("campanha de Lula", "PT"), ("CartaCapital", "Agência Brasil")),
    Lado("A Meta alega problemas técnicos e nega favorecimento.", ("Meta",), ("Agência Brasil",)),
]
LADOS_DO_CANAL = [
    Lado("Nunes Marques mandou suspender o canal a pedido de Flávio Bolsonaro.", ("Nunes Marques", "Flávio Bolsonaro"), ("O GLOBO", "G1")),
    Lado("Lula critica a decisão e diz que o PT vai à Justiça.", ("Lula", "PT"), ("G1", "Agência Brasil")),
]


def _episodio(fontes, **extras) -> dict:
    por_personagem = max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 2))
    fala = " ".join(["palavra"] * por_personagem)
    return {
        "titulo_reescrito": "Título sem dados",
        "resumo_didatico": "Uma frase. " * qa.MIN_FRASES_RESUMO,
        "personagens": [{"nome": "Helena"}, {"nome": "Ramos"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Ramos", "fala": fala}],
        "houve_divergencia": False,
        "fontes_citadas": fontes,
        **extras,
    }


def _debate(*turnos, houve_divergencia=True) -> dict:
    """Só o que a regra dos analistas lê: o roteiro (personagem, fala) e houve_divergencia."""
    return {"houve_divergencia": houve_divergencia,
            "roteiro_podcast": [{"personagem": personagem, "fala": fala} for personagem, fala in turnos]}


# Trechos reais dos episódios 3 e 5 de 11/10/2026: houve_divergencia true com um analista só.
EPISODIO_3 = _debate(
    ("Helena", "A Meta, empresa que controla o Facebook e o Instagram, está no centro de uma polêmica envolvendo a "
               "campanha do presidente Lula e o senador Flávio Bolsonaro."),
    ("Dr. Marcos", "A campanha de Lula, conforme reportado pela CartaCapital, apresenta relatórios técnicos que "
                   "indicam um tratamento desigual."),
    ("Helena", "A Agência Brasil trouxe a resposta oficial da Meta, e eles são categóricos ao dizer que essas "
               "acusações são falsas e não têm base nos fatos."),
    ("Dr. Marcos", "No entanto, a crítica da campanha, que aparece detalhada na Agência Brasil, é que a empresa não "
                   "apresentou nenhuma evidência concreta desse impacto global."),
)
EPISODIO_5 = _debate(
    ("Helena", "O presidente do Tribunal Superior Eleitoral, ministro Kassio Nunes Marques, determinou a suspensão "
               "do canal 'Exército de Lula' no WhatsApp."),
    ("Dr. Arnaldo", "Segundo o que foi reportado pelo jornal O Globo, o ministro Nunes Marques entendeu que o canal "
                    "não era apenas um espaço de mobilização política comum."),
    ("Helena", "O Globo e o G1 mencionam que o ministro Ricardo Villas Bôas Cueva, que é o corregedor do Tribunal, "
               "já estava com um processo sobre esse mesmo canal em mãos."),
    ("Dr. Arnaldo", "A Agência Brasil pontua que o ministro Nunes Marques foi indicado ao Supremo e ao TSE durante "
                    "o governo de Jair Bolsonaro."),
)


# ── Fontes ────────────────────────────────────────────────────────────────────────────────

def test_veiculos_e_lados_sao_obrigatorios():
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]))
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]), ["G1"])


def test_episodio_de_um_veiculo_so_nao_cobra_fontes_citadas():
    assert qa.problemas(_episodio([]), ["G1"], UM_LADO) == []
    assert qa.problemas(_episodio(["outra coisa"]), ["Agência Brasil", "agencia brasil"], UM_LADO) == []   # dois textos, um veículo


def test_com_dois_veiculos_todos_tem_de_estar_em_fontes_citadas():
    assert qa.problemas(_episodio(["G1", "Folha de S.Paulo"]), ["G1", "Folha de S.Paulo"], UM_LADO) == []
    [problema] = qa.problemas(_episodio(["G1"]), ["G1", "Folha de S.Paulo", "Estadão"], UM_LADO)
    assert problema.startswith("fontes_citadas sem Folha de S.Paulo, Estadão (o episódio tem 3 veículos como fonte")
    assert len(qa.problemas(_episodio("G1 e Folha"), ["G1", "Folha"], UM_LADO)) == 1               # lista malformada não vale


def test_comparacao_de_veiculos_e_tolerante_mas_por_palavras_inteiras():
    veiculos = ["O GLOBO", "Agência Brasil", "Folha de S.Paulo"]
    assert qa.problemas(_episodio(["o globo", "AGENCIA BRASIL (EBC)", "Folha"]), veiculos, UM_LADO) == []
    assert qa.mesmo_veiculo("Valor", "Valor Econômico") and qa.mesmo_veiculo("g1", "G1")
    assert not qa.mesmo_veiculo("ge", "Agência Brasil")           # "ge" está dentro de "Agência", mas não é palavra
    assert not qa.mesmo_veiculo("G1", "") and not qa.mesmo_veiculo("Estadão", "O Estado de S. Paulo")
    assert qa.veiculos_distintos(["G1", "g1", "Folha", "Folha de S.Paulo", "ge"]) == ["G1", "Folha", "ge"]


def test_veiculo_citado_aceita_o_nome_sem_artigo_sem_slogan_e_a_forma_curta():
    assert qa.veiculo_citado("O GLOBO", "segundo o jornal O Globo")
    assert qa.veiculo_citado("Folha de S.Paulo", "a Folha aponta o contrário")
    assert qa.veiculo_citado("HiperNotícias - Você bem informado", "diz o HiperNotícias")
    assert qa.veiculo_citado("G1", "o G1 destaca") and not qa.veiculo_citado("G1", "a cúpula do G20")
    assert not qa.veiculo_citado("Valor Econômico", "o valor do contrato")
    assert not qa.veiculo_citado("CartaCapital", "a carta do ministro")


# ── Título sem percentuais nem proporções ─────────────────────────────────────────────────

def test_titulo_do_episodio_2_reprova_e_os_outros_quatro_passam():
    assert qa.proporcoes_no_titulo(TITULOS_REAIS[2]) == ["quase 60%"]
    assert [qa.proporcoes_no_titulo(TITULOS_REAIS[n]) for n in (1, 3, 4, 5)] == [[], [], [], []]

    [problema] = qa.problemas(_episodio([], titulo_reescrito=TITULOS_REAIS[2]), ["G1"], UM_LADO)
    assert problema.startswith("título com percentual ou proporção (quase 60%): o título não leva percentuais")
    assert qa.problemas(_episodio([], titulo_reescrito=TITULOS_REAIS[5]), ["G1"], UM_LADO) == []


@pytest.mark.parametrize("titulo, bloqueado", [
    ("Raspberry Pi 4 de 2 GB fica 50% mais caro", ["50%"]),                           # percentuais
    ("Inflação sobe 3,5 pontos percentuais", ["3,5 pontos percentuais"]),
    ("Sessenta por cento aprovam o governo", ["Sessenta por cento"]),
    ("Mais de 40% dos eleitores seguem indecisos", ["Mais de 40%"]),
    ("Ataques a mulheres crescem 11 vezes", ["11 vezes"]),                            # "x vezes"
    ("Chineses compram três vezes mais que os americanos", ["três vezes"]),
    ("Violência política chega ao dobro de 2022", ["dobro"]),                         # valem por "x vezes"
    ("Preço da memória é o triplo do previsto", ["triplo"]),
    ("Queimadas atingem o quádruplo da área", ["quádruplo"]),
    ("Metade dos eleitores rejeita a proposta", ["Metade"]),                          # proporções
    ("Mulheres são um terço das candidaturas", ["um terço"]),
    ("Dois terços do Senado apoiam a PEC", ["Dois terços"]),
    ("Um quarto dos deputados falta à sessão", ["Um quarto dos"]),
    ("Três em cada quatro brasileiros usam o Pix", ["Três em cada quatro"]),
    ("Uma em cada três candidatas sofre ataque", ["Uma em cada três"]),
    ("Violência política: 1 em cada 3 vítimas é candidata", ["1 em cada 3"]),
    ("STF: 6 de 11 ministros votam contra", ["6 de 11"]),
    ("Um caso de violência a cada 9 horas", ["a cada 9"]),
])
def test_titulo_com_percentual_ou_proporcao_e_bloqueado(titulo, bloqueado):
    assert qa.proporcoes_no_titulo(titulo) == bloqueado


@pytest.mark.parametrize("titulo", [
    "Eleições 2026: Lula vai a ato no 1º turno",           # ano e ordinal
    "Disputa de 2026 chega ao primeiro turno",
    "Ataque deixa 12 mortos em Manaus",                    # quantidade absoluta, em algarismos ou por extenso
    "Doze mortos em ataque em Manaus",
    "Mais de 100 mortos em enchente no Sul",
    "Quase 200 pessoas protestam em Manaus",
    "Cerca de trinta e seis municípios em emergência",
    "Canal com mais de 3 milhões de seguidores é suspenso",
    "Senado aprova PEC em dois turnos",
    "Cem dias de governo",
    "Senado deve votar PEC do fim da escala 6x1",          # nome com algarismo
    "Galaxy S26 Ultra baixa de preço",
    "Pixel 9 de 128 GB cai de preço",                      # "9 de 128" é modelo e memória, não proporção
    "Hotel cobra caro por um quarto de casal",             # "um quarto de" não é fração
    "Às vezes, um acordo basta",                           # "um" é artigo, e "às vezes" não é "x vezes"
    "Senado dobra a aposta e triplica o fundo eleitoral",  # os verbos passam: só "dobro", "triplo" e "quádruplo" reprovam
    "Governo cria força-tarefa em setembro e dezembro",    # "sete" e "dez" dentro de outras palavras
])
def test_titulo_com_ano_ordinal_ou_quantidade_absoluta_passa(titulo):
    assert qa.proporcoes_no_titulo(titulo) == []


# ── Verbos de posição ─────────────────────────────────────────────────────────────────────

def test_verbos_de_posicao_sao_formas_inteiras_e_nao_radicais():
    assert len(VERBOS_DE_POSICAO) == 14 and len(FORMAS_DE_POSICAO) == 14 * 7
    assert verbos_de_posicao("A Meta nega, mas a campanha Acusou e segue cobrando.") == ["nega", "acusou", "cobrando"]
    assert verbos_de_posicao("O partido afirmava, e os aliados defendiam, rebatendo a crítica.") == ["afirmava", "defendiam", "rebatendo"]
    assert verbos_de_posicao("O negócio da empresa e a cobertura do jornal") == []      # "nega" e "cobra" não são radicais
    assert verbos_de_posicao("A crítica da campanha é dura.") == []                     # o acento conta: não é "critica"
    assert verbos_de_posicao("A campanha critica a empresa.") == ["critica"]


# ── Analistas por lado ────────────────────────────────────────────────────────────────────

def test_episodios_3_e_5_reprovam_por_terem_um_analista_para_dois_lados():
    [do_3] = qa.problemas_dos_analistas(EPISODIO_3, LADOS_DA_META)
    assert do_3 == ("1 analista(s) (Dr. Marcos) para 2 lado(s): o elenco é Helena e exatamente 2 analista(s), um por lado")
    [do_5] = qa.problemas_dos_analistas(EPISODIO_5, LADOS_DO_CANAL)
    assert do_5.startswith("1 analista(s) (Dr. Arnaldo) para 2 lado(s)")


def test_numero_de_analistas_diferente_do_de_lados_reprova():
    dois = _debate(("Helena", "Vamos ao tema."), ("Bia", "Explico o caso."), ("Dr. Ramos", "E eu completo."), houve_divergencia=False)
    [problema] = qa.problemas_dos_analistas(dois, UM_LADO)
    assert problema.startswith("2 analista(s) (Bia, Dr. Ramos) para 1 lado(s)")

    so_helena = _debate(("Helena", "Falo sozinha."), houve_divergencia=False)
    assert qa.problemas_dos_analistas(so_helena, UM_LADO)[0].startswith("0 analista(s) (nenhum) para 1 lado(s)")

    um = _debate(("Helena", "Vamos ao tema."), ("Bia", "Explico o caso."), houve_divergencia=False)
    assert qa.problemas_dos_analistas(um, UM_LADO) == []


def test_houve_divergencia_incoerente_com_os_lados_reprova():
    um = _debate(("Helena", "Vamos ao tema."), ("Bia", "Explico o caso."), houve_divergencia=True)
    assert qa.problemas_dos_analistas(um, UM_LADO) == [
        "houve_divergencia tem de ser false: a pauta tem 1 lado(s), e o campo é true se e só se houver 2 lados ou mais"
    ]
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Bia", "Segundo a CartaCapital, a campanha de Lula acusa a empresa de interferir."),
        ("Dr. Ramos", "Já a Agência Brasil registra que a Meta nega o favorecimento."),
        houve_divergencia=False,
    )
    assert qa.problemas_dos_analistas(debate, LADOS_DA_META) == [
        "houve_divergencia tem de ser true: a pauta tem 2 lado(s), e o campo é true se e só se houver 2 lados ou mais"
    ]
    assert qa.problemas_dos_analistas({**debate, "houve_divergencia": True}, LADOS_DA_META) == []
    assert len(qa.problemas_dos_analistas({**debate, "houve_divergencia": "true"}, LADOS_DA_META)) == 1   # só o booleano vale


def test_dois_lados_no_mesmo_veiculo_passam_quando_cada_analista_cita_o_seu_ator():
    lados = [Lado("O ministro diz que o governo agiu a tempo.", ("Waldez Góes",), ("Agência Brasil",)),
             Lado("O governador cobra mais aeronaves.", ("Wilson Lima",), ("Agência Brasil",))]
    debate = _debate(
        ("Helena", "A Agência Brasil ouviu os dois. Bia, o que diz o ministro?"),
        ("Bia", "Pelo que a Agência Brasil publicou, Waldez Góes sustenta que a ajuda saiu no mesmo dia."),
        ("Dr. Ramos", "Na mesma Agência Brasil, o governador Wilson Lima cobrava mais aeronaves."),
    )
    assert qa.lados_de_cada_analista(debate, lados) == {"Bia": [0], "Dr. Ramos": [1]}
    assert qa.problemas_dos_analistas(debate, lados) == []


def test_dois_analistas_citando_o_mesmo_ator_reprovam():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Bia", "Segundo a Agência Brasil, a Meta alega problemas técnicos."),
        ("Dr. Ramos", "A Agência Brasil mostra que a Meta nega qualquer favorecimento."),
    )
    [problema] = qa.problemas_dos_analistas(debate, LADOS_DA_META)
    assert problema.startswith("os analistas não apresentam os lados um a um (Bia: lado 2; Dr. Ramos: lado 2): cada analista precisa")
    assert "Lado 1: atores campanha de Lula, PT; veículos CartaCapital, Agência Brasil." in problema
    assert "Lado 2: atores Meta; veículos Agência Brasil." in problema
    assert "(afirmar, defender, apontar," in problema


def test_so_a_mencao_do_veiculo_sem_verbo_de_posicao_reprova():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Bia", "A campanha de Lula, conforme reportado pela CartaCapital, apresenta relatórios técnicos."),
        ("Dr. Ramos", "Segundo a Agência Brasil, a Meta nega o favorecimento."),
    )
    assert qa.lados_de_cada_analista(debate, LADOS_DA_META) == {"Bia": [], "Dr. Ramos": [1]}
    assert "(Bia: nenhum lado; Dr. Ramos: lado 2)" in qa.problemas_dos_analistas(debate, LADOS_DA_META)[0]


def test_negocio_nao_conta_como_nega():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Bia", "Segundo a CartaCapital, a campanha de Lula acusa a empresa de interferir."),
        ("Dr. Ramos", "A Agência Brasil descreve o negócio da Meta e a cobertura das redes."),
    )
    assert qa.lados_de_cada_analista(debate, LADOS_DA_META) == {"Bia": [0], "Dr. Ramos": []}
    assert len(qa.problemas_dos_analistas(debate, LADOS_DA_META)) == 1


def test_veiculo_verbo_e_ator_tem_de_estar_na_mesma_frase_e_o_ator_tem_de_ser_so_do_lado():
    espalhado = _debate(
        ("Helena", "Vamos ao debate."),
        ("Bia", "A CartaCapital publicou a denúncia. A campanha de Lula acusa a empresa."),          # veículo numa frase, verbo e ator na outra
        ("Dr. Ramos", "Segundo a Agência Brasil, o Dr. Zuck, da Meta, respondeu às acusações."),     # o ponto de "Dr." não parte a frase
    )
    assert qa.lados_de_cada_analista(espalhado, LADOS_DA_META) == {"Bia": [], "Dr. Ramos": [1]}

    lados = [Lado("O PT acusa.", ("PT", "Lula"), ("G1",)), Lado("O TSE decide.", ("TSE", "PT"), ("G1",))]   # o PT está nos dois lados
    assert qa.atores_exclusivos(lados) == [["Lula"], ["TSE"]]
    assert qa.lados_de_cada_analista(_debate(("Bia", "Segundo o G1, o PT afirma que vai recorrer.")), lados) == {"Bia": []}
    assert qa.mesmo_ator("Lula", "campanha de Lula") and qa.mesmo_ator("campanha do presidente Lula", "campanha de Lula")
    assert not qa.mesmo_ator("Flávio Bolsonaro", "Jair Bolsonaro") and not qa.mesmo_ator("", "Meta")
    assert qa.ator_citado("campanha de Lula", "a campanha do presidente Lula") and not qa.ator_citado("Meta", "a metade")


def test_particulas_nao_contam_como_palavras_do_nome():
    assert qa.palavras_do_ator("Luiz Inácio Lula da Silva") == {"luiz", "inacio", "lula", "silva"}
    assert qa.palavras_do_ator("Federação dos Bancos e das Financeiras do Brasil") == {"federacao", "bancos", "financeiras", "brasil"}
    # "Lula" contra "Luiz Inácio Lula da Silva": é o mesmo ator, porque um nome está dentro do outro...
    assert qa.mesmo_ator("Lula", "Luiz Inácio Lula da Silva")
    # ...mas "Lula" sozinho não nomeia o ator de nome completo: é 1 das 4 palavras, e é preciso mais da metade
    assert not qa.ator_citado("Luiz Inácio Lula da Silva", "Segundo o G1, Lula critica a decisão.")
    assert not qa.ator_citado("Luiz Inácio Lula da Silva", "Lula da Silva critica a decisão.")     # 2 de 4: o "da" não soma
    assert qa.ator_citado("Luiz Inácio Lula da Silva", "Luiz Inácio Lula critica a decisão.")      # 3 de 4
    assert qa.ator_citado("Lula", "Luiz Inácio Lula da Silva critica a decisão.")                  # no sentido contrário, vale


def test_ator_de_nome_comprido_pode_ser_citado_pela_forma_curta():
    # os atores que a análise de lados devolveu para a pauta do canal "Exército de Lula", em 11/10/2026
    lados = [Lado("a", ("Kassio Nunes Marques", "campanha de Flávio Bolsonaro"), ("O GLOBO",)),
             Lado("b", ("Luiz Inácio Lula da Silva", "campanha de Lula"), ("G1",)),
             Lado("c", ("André Janones",), ("Agência Brasil",))]
    debate = _debate(
        ("A", "Segundo O Globo, o ministro Nunes Marques sustenta que o canal espalhava desinformação."),
        ("B", "No G1, Lula critica a decisão e fala em censura."),
        ("C", "A Agência Brasil registra que André Janones rebateu a acusação."),
    )
    assert qa.lados_de_cada_analista(debate, lados) == {"A": [0], "B": [1], "C": [2]}

    assert qa.ator_citado("Kassio Nunes Marques", "o ministro Nunes Marques") and not qa.ator_citado("Kassio Nunes Marques", "Marques")
    assert not qa.ator_citado("Luiz Inácio Lula da Silva", "Lula critica")           # uma palavra de quatro é pouco
    assert not qa.ator_citado("campanha de Lula", "Lula critica")                    # nome de duas palavras: inteiro...
    assert qa.ator_citado("campanha de Lula", "Lula critica", ["campanha de Flávio Bolsonaro"])   # ...a não ser que "campanha" seja do outro lado
    assert not qa.ator_citado("André Janones", "Janones rebateu") and not qa.ator_citado("Lula", "a decisão", ["Lula"])


def test_tres_lados_pedem_uma_correspondencia_um_a_um():
    lados = [Lado("a", ("Nunes Marques",), ("O GLOBO",)), Lado("b", ("Lula",), ("G1",)), Lado("c", ("Cueva",), ("O GLOBO", "G1"))]
    falas = {
        "A": "Segundo O Globo, Nunes Marques defende a suspensão. No G1, Lula critica a decisão.",   # serve aos lados 1 e 2
        "B": "O G1 registra que Lula criticou o tribunal.",                                          # só ao lado 2
        "C": "Pelo que o G1 apurou, Cueva questionava a pressa.",                                    # só ao lado 3
    }
    debate = _debate(("Helena", "Vamos ao debate."), *falas.items())
    assert qa.lados_de_cada_analista(debate, lados) == {"A": [0, 1], "B": [1], "C": [2]}
    assert qa.problemas_dos_analistas(debate, lados) == []                                           # A fica com o lado 1

    sem_o_lado_3 = _debate(("Helena", "Vamos ao debate."), ("A", falas["A"]), ("B", falas["B"]), ("C", falas["B"]))
    assert "(A: lado 1 e lado 2; B: lado 2; C: lado 2)" in qa.problemas_dos_analistas(sem_o_lado_3, lados)[0]


def test_problemas_inclui_as_regras_dos_analistas():
    episodio = {**_episodio(["Agência Brasil", "CartaCapital"]), **EPISODIO_3,
                "personagens": [{"nome": "Helena"}, {"nome": "Dr. Marcos"}]}
    problemas = qa.problemas(episodio, ["Agência Brasil", "CartaCapital"], LADOS_DA_META)
    assert any(p.startswith("1 analista(s) (Dr. Marcos) para 2 lado(s)") for p in problemas)
    # o mesmo roteiro, numa pauta de um lado só, reprova pelo houve_divergencia
    assert any(p.startswith("houve_divergencia tem de ser false") for p in
               qa.problemas(episodio, ["Agência Brasil", "CartaCapital"], lado_unico(["Agência Brasil", "CartaCapital"])))

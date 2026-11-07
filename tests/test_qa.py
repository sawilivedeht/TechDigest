"""Testes das regras de ai/qa.py que não dependem dos limites QA_* do .env: fontes, título, analistas por lado e ressalvas."""
import math

import pytest

from techdigest.ai import numeros, qa
from techdigest.ai.elenco import nomes_dos_analistas
from techdigest.ai.lados import Lado, Ressalva, lado_unico
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
SEM_RESSALVAS: list = []
SEM_TEXTOS: list = []
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
        "personagens": [{"nome": "Helena"}, {"nome": "Otávio"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Otávio", "fala": fala}],
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

def test_veiculos_lados_ressalvas_e_textos_sao_obrigatorios():
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]))
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]), ["G1"])
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]), ["G1"], UM_LADO)
    with pytest.raises(TypeError):
        qa.problemas(_episodio([]), ["G1"], UM_LADO, SEM_RESSALVAS)


def test_episodio_de_um_veiculo_so_nao_cobra_fontes_citadas():
    assert qa.problemas(_episodio([]), ["G1"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) == []
    assert qa.problemas(_episodio(["outra coisa"]), ["Agência Brasil", "agencia brasil"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) == []   # dois textos, um veículo


def test_com_dois_veiculos_todos_tem_de_estar_em_fontes_citadas():
    assert qa.problemas(_episodio(["G1", "Folha de S.Paulo"]), ["G1", "Folha de S.Paulo"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) == []
    [problema] = qa.problemas(_episodio(["G1"]), ["G1", "Folha de S.Paulo", "Estadão"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS)
    assert problema.startswith("fontes_citadas sem Folha de S.Paulo, Estadão (o episódio tem 3 veículos como fonte")
    assert len(qa.problemas(_episodio("G1 e Folha"), ["G1", "Folha"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS)) == 1               # lista malformada não vale


def test_comparacao_de_veiculos_e_tolerante_mas_por_palavras_inteiras():
    veiculos = ["O GLOBO", "Agência Brasil", "Folha de S.Paulo"]
    assert qa.problemas(_episodio(["o globo", "AGENCIA BRASIL (EBC)", "Folha"]), veiculos, UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) == []
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

    [problema] = qa.problemas(_episodio([], titulo_reescrito=TITULOS_REAIS[2]), ["G1"], UM_LADO, SEM_RESSALVAS,
                              ["Mulheres são quase 60% das vítimas."])
    assert problema.startswith("título com percentual ou proporção (quase 60%): o título não leva percentuais")
    assert qa.problemas(_episodio([], titulo_reescrito=TITULOS_REAIS[5]), ["G1"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) == []


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
    ("Violência política atinge maioria das mulheres candidatas no primeiro turno", ["maioria"]),   # o título do ep. 2 de 12/10/2026
    ("Minoria no Senado barra a PEC", ["Minoria"]),
    ("A maior parte dos municípios segue em emergência", ["maior parte"]),
    ("Grande parte do canal já estava fora do ar", ["Grande parte"]),
    ("Mulheres são um terço das candidaturas", ["um terço"]),
    ("Dois terços do Senado apoiam a PEC", ["Dois terços"]),
    ("Um quarto dos deputados falta à sessão", ["Um quarto dos"]),
    ("Três em cada quatro brasileiros usam o Pix", ["Três em cada quatro"]),
    ("Uma em cada três candidatas sofre ataque", ["Uma em cada três"]),
    ("Violência política: 1 em cada 3 vítimas é candidata", ["1 em cada 3"]),
    ("STF: 6 de 11 ministros votam contra", ["6 de 11"]),
    ("Mulheres são alvo de 60 dos 102 episódios de violência política no primeiro turno", ["60 dos 102"]),   # título do ep. 2 de v4
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
    assert len(VERBOS_DE_POSICAO) == 27 and len(FORMAS_DE_POSICAO) == 27 * 8     # sete formas e o infinitivo de cada um
    # os de quem informa ou declara: a constatação de um órgão técnico ("informou que não identificou...")
    assert verbos_de_posicao("A assessoria informou e concluiu; o porta-voz disse e declarou.") == ["informou", "concluiu", "disse", "declarou"]
    assert verbos_de_posicao("Eles diziam, concluíram e vêm informando.") == ["diziam", "concluíram", "informando"]
    # verbo que apresenta a afirmação como verdadeira fica fora: numa disputa, ele toma partido
    assert verbos_de_posicao("O órgão constatou, revelou, reconheceu e admitiu.") == []
    assert verbos_de_posicao("O ministro entendeu, decidiu e determinou; a defesa argumenta e destaca.") == [
        "entendeu", "decidiu", "determinou", "argumenta", "destaca"]
    assert verbos_de_posicao("Analistas avaliam o risco, e o ministro ponderou.") == ["avaliam", "ponderou"]
    assert verbos_de_posicao("A Meta nega, mas a campanha Acusou e segue cobrando.") == ["nega", "acusou", "cobrando"]
    assert verbos_de_posicao("O partido afirmava, e os aliados defendiam, rebatendo a crítica.") == ["afirmava", "defendiam", "rebatendo"]
    assert verbos_de_posicao("O negócio da empresa e a cobertura do jornal") == []      # "nega" e "cobra" não são radicais
    assert verbos_de_posicao("A crítica da campanha é dura.") == []                     # o acento conta: não é "critica"
    assert verbos_de_posicao("A campanha critica a empresa.") == ["critica"]


def test_verbos_novos_o_infinitivo_e_o_preterito_composto():
    # classificar e ressaltar, de quem qualifica um fato ou põe ênfase numa parte dele
    assert verbos_de_posicao("O instituto classificou o vídeo como falso e ressaltou o prazo.") == ["classificou", "ressaltou"]
    # o infinitivo de qualquer verbo da lista
    assert verbos_de_posicao("A defesa vai alegar nulidade, e o ministro deve decidir hoje.") == ["alegar", "decidir"]
    # o pretérito composto vale como par: o auxiliar e o particípio
    assert verbos_de_posicao("O ministro havia classificado a ação, e a cooperativa tinha dito que não.") == [
        "havia classificado", "tinha dito"]
    assert verbos_de_posicao("A empresa teria negado o pedido e tem defendido o plano.") == ["teria negado", "tem defendido"]
    # o particípio sozinho é substantivo ou adjetivo: "o pedido", "o dito", "o acusado"
    assert verbos_de_posicao("O tribunal apreciou outro pedido da campanha, e o acusado não veio.") == []
    assert verbos_de_posicao("Foi um dia determinado; o ponto destacado no relatório.") == []
    # considerar, justificar, pedir e chamar ficaram fora (decisão de 23/10/2026)
    assert verbos_de_posicao("Ele considera, justifica, pede e chama.") == []


def test_verbos_de_decisao_sao_outra_lista_e_o_qa_so_aceita_a_passiva_com_agente():
    from techdigest.ai.verbos import FORMAS_DE_DECISAO, PARTICIPIOS_DE_DECISAO, agentes_da_decisao, verbos_de_decisao
    assert verbos_de_decisao("O ministro mandou suspender; a feira foi suspensa e a multa, determinada.") == [
        "mandou", "suspensa", "determinada"]
    assert {"suspendeu", "mandou", "suspensa", "mandado"}.isdisjoint(FORMAS_DE_POSICAO)
    assert {"determinou", "decidiu"} <= FORMAS_DE_DECISAO & FORMAS_DE_POSICAO   # determinar e decidir estão nas duas
    assert verbos_de_posicao("O ministro mandou suspender a feira.") == []
    # o particípio sai da mesma lista da análise de lados; o agente vai do "por" até o próximo verbo
    assert PARTICIPIOS_DE_DECISAO <= FORMAS_DE_DECISAO and {"determinada", "suspensos", "decidido", "mandadas"} <= PARTICIPIOS_DE_DECISAO
    assert agentes_da_decisao("A interdição da feira foi determinada por decisão da juíza Marta Quaresma.") == [
        "decisão da juíza Marta Quaresma"]
    assert agentes_da_decisao("A interdição, determinada na sexta pela prefeitura, foi criticada por Ivo Brandão.") == ["prefeitura"]
    assert agentes_da_decisao("A feira foi suspensa; o pedido foi feito por Ivo Brandão.") == []      # o "por" não segue o particípio
    assert agentes_da_decisao("Marta Quaresma suspendeu a feira.") == []                             # a ativa não é passiva


# ── Analistas por lado ────────────────────────────────────────────────────────────────────

def test_episodios_3_e_5_reprovam_por_terem_um_analista_para_dois_lados():
    [do_3] = qa.problemas_dos_analistas(EPISODIO_3, LADOS_DA_META)
    assert do_3 == ("1 analista(s) (Dr. Marcos) para 2 lado(s): o elenco é Helena e exatamente 2 analista(s), um por lado")
    [do_5] = qa.problemas_dos_analistas(EPISODIO_5, LADOS_DO_CANAL)
    assert do_5.startswith("1 analista(s) (Dr. Arnaldo) para 2 lado(s)")


def test_numero_de_analistas_diferente_do_de_lados_reprova():
    dois = _debate(("Helena", "Vamos ao tema."), ("Patrícia", "Explico o caso."), ("Otávio", "E eu completo."), houve_divergencia=False)
    [problema] = qa.problemas_dos_analistas(dois, UM_LADO)
    assert problema.startswith("2 analista(s) (Patrícia, Otávio) para 1 lado(s)")

    so_helena = _debate(("Helena", "Falo sozinha."), houve_divergencia=False)
    assert qa.problemas_dos_analistas(so_helena, UM_LADO)[0].startswith("0 analista(s) (nenhum) para 1 lado(s)")

    um = _debate(("Helena", "Vamos ao tema."), ("Patrícia", "Explico o caso."), houve_divergencia=False)
    assert qa.problemas_dos_analistas(um, UM_LADO) == []


def test_houve_divergencia_incoerente_com_os_lados_reprova():
    um = _debate(("Helena", "Vamos ao tema."), ("Patrícia", "Explico o caso."), houve_divergencia=True)
    assert qa.problemas_dos_analistas(um, UM_LADO) == [
        "houve_divergencia tem de ser false: a pauta tem 1 lado(s), e o campo é true se e só se houver 2 lados ou mais"
    ]
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Patrícia", "Segundo a CartaCapital, a campanha de Lula acusa a empresa de interferir."),
        ("Otávio", "Já a Agência Brasil registra que a Meta nega o favorecimento."),
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
        ("Helena", "A Agência Brasil ouviu os dois. Patrícia, o que diz o ministro?"),
        ("Patrícia", "Pelo que a Agência Brasil publicou, Waldez Góes sustenta que a ajuda saiu no mesmo dia."),
        ("Otávio", "Na mesma Agência Brasil, o governador Wilson Lima cobrava mais aeronaves."),
    )
    assert qa.lados_de_cada_analista(debate, lados) == {"Patrícia": [0], "Otávio": [1]}
    assert qa.problemas_dos_analistas(debate, lados) == []


def test_dois_analistas_citando_o_mesmo_ator_reprovam():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Patrícia", "Segundo a Agência Brasil, a Meta alega problemas técnicos."),
        ("Otávio", "A Agência Brasil mostra que a Meta nega qualquer favorecimento."),
    )
    [problema] = qa.problemas_dos_analistas(debate, LADOS_DA_META)
    assert problema.startswith("os analistas não apresentam os lados um a um (Patrícia: lado 2; Otávio: lado 2): cada analista precisa")
    assert "Lado 1: atores campanha de Lula, PT; veículos CartaCapital, Agência Brasil." in problema
    assert "Lado 2: atores Meta; veículos Agência Brasil." in problema
    assert "(afirmar, defender, apontar," in problema


def test_so_a_mencao_do_veiculo_sem_verbo_de_posicao_reprova():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Patrícia", "A campanha de Lula, conforme reportado pela CartaCapital, apresenta relatórios técnicos."),
        ("Otávio", "Segundo a Agência Brasil, a Meta nega o favorecimento."),
    )
    assert qa.lados_de_cada_analista(debate, LADOS_DA_META) == {"Patrícia": [], "Otávio": [1]}
    assert "(Patrícia: nenhum lado; Otávio: lado 2)" in qa.problemas_dos_analistas(debate, LADOS_DA_META)[0]


def test_negocio_nao_conta_como_nega():
    debate = _debate(
        ("Helena", "Vamos ao debate."),
        ("Patrícia", "Segundo a CartaCapital, a campanha de Lula acusa a empresa de interferir."),
        ("Otávio", "A Agência Brasil descreve o negócio da Meta e a cobertura das redes."),
    )
    assert qa.lados_de_cada_analista(debate, LADOS_DA_META) == {"Patrícia": [0], "Otávio": []}
    assert len(qa.problemas_dos_analistas(debate, LADOS_DA_META)) == 1


def test_veiculo_verbo_e_ator_tem_de_estar_na_mesma_frase_e_o_ator_tem_de_ser_so_do_lado():
    espalhado = _debate(
        ("Helena", "Vamos ao debate."),
        ("Patrícia", "A CartaCapital publicou a denúncia. A campanha de Lula acusa a empresa."),          # veículo numa frase, verbo e ator na outra
        ("Otávio", "Segundo a Agência Brasil, o Dr. Zuck, da Meta, respondeu às acusações."),     # o ponto de "Dr." não parte a frase
    )
    assert qa.lados_de_cada_analista(espalhado, LADOS_DA_META) == {"Patrícia": [], "Otávio": [1]}

    lados = [Lado("O PT acusa.", ("PT", "Lula"), ("G1",)), Lado("O TSE decide.", ("TSE", "PT"), ("G1",))]   # o PT está nos dois lados
    assert qa.atores_exclusivos(lados) == [["Lula"], ["TSE"]]
    assert qa.lados_de_cada_analista(_debate(("Patrícia", "Segundo o G1, o PT afirma que vai recorrer.")), lados) == {"Patrícia": []}
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
    problemas = qa.problemas(episodio, ["Agência Brasil", "CartaCapital"], LADOS_DA_META, SEM_RESSALVAS, SEM_TEXTOS)
    assert any(p.startswith("1 analista(s) (Dr. Marcos) para 2 lado(s)") for p in problemas)
    # o mesmo roteiro, numa pauta de um lado só, reprova pelo houve_divergencia
    assert any(p.startswith("houve_divergencia tem de ser false") for p in
               qa.problemas(episodio, ["Agência Brasil", "CartaCapital"], lado_unico(["Agência Brasil", "CartaCapital"]), SEM_RESSALVAS, SEM_TEXTOS))


# ── Ressalvas ─────────────────────────────────────────────────────────────────────────────

RESSALVA = Ressalva(("economistas",), "A flexibilização pode enfraquecer a Tarifa Externa Comum.", ("Gazeta do Povo",))
PERGUNTA = "Segundo a Gazeta do Povo, economistas alertam que a mudança pode enfraquecer a tarifa comum. Como você vê isso?"


def _conversa(*turnos) -> dict:
    """Um episódio de um lado só: só o que as regras de analistas e de ressalvas leem."""
    return _debate(*turnos, houve_divergencia=False)


def test_ressalva_trazida_pela_helena_como_pergunta_atribuida_passa():
    episodio = _conversa(("Helena", "Vamos ao tema. " + PERGUNTA), ("Otávio", "As fontes dizem que o risco existe."))
    assert qa.problemas_das_ressalvas(episodio, [RESSALVA]) == []
    assert qa.perguntas_das_ressalvas(episodio, [RESSALVA]) == [[
        ("Segundo a Gazeta do Povo, economistas alertam que a mudança pode enfraquecer a tarifa comum.", True),
    ]]
    assert qa.problemas_das_ressalvas(_conversa(("Helena", "Olá."), ("Otávio", "Olá.")), []) == []      # sem ressalva, nada a cobrar


@pytest.mark.parametrize("turnos, falta", [
    # a ressalva não aparece nas falas da Helena
    ([("Helena", "Como você vê a proposta?"), ("Otávio", "Ela muda a política externa.")],
     "não aparece numa frase da Helena com o veículo, o grupo e um verbo de posição"),
    # a frase da Helena tem o grupo e o verbo, mas não o veículo
    ([("Helena", "Economistas alertam que a mudança pode enfraquecer a tarifa comum. Como você vê isso?"), ("Otávio", "Há risco.")],
     "não aparece numa frase da Helena com o veículo, o grupo e um verbo de posição"),
    # a ressalva só está na fala do analista
    ([("Helena", "E os riscos?"), ("Otávio", PERGUNTA)],
     "não aparece numa frase da Helena com o veículo, o grupo e um verbo de posição"),
    # veículo, grupo e verbo em frases diferentes
    ([("Helena", "A Gazeta do Povo ouviu economistas. Eles alertam para o risco. Como você vê isso?"), ("Otávio", "Há risco.")],
     "não aparece numa frase da Helena com o veículo, o grupo e um verbo de posição"),
    # a frase está lá, mas a fala da Helena não tem pergunta
    ([("Helena", "Segundo a Gazeta do Povo, economistas alertam que a mudança pode enfraquecer a tarifa comum."), ("Otávio", "Há risco.")],
     "a fala da Helena que a traz não tem pergunta"),
    # a pergunta está em outra fala da Helena
    ([("Helena", "Segundo a Gazeta do Povo, economistas alertam para o risco."), ("Otávio", "Há risco."), ("Helena", "E o que vem agora?")],
     "a fala da Helena que a traz não tem pergunta"),
])
def test_ressalva_sem_pergunta_atribuida_da_helena_reprova(turnos, falta):
    [problema] = qa.problemas_das_ressalvas(_conversa(*turnos), [RESSALVA])
    assert problema.startswith(f"ressalva 1 (economistas; Gazeta do Povo): {falta}. Helena apresenta cada ressalva como pergunta atribuída")
    assert 'como em "Segundo <veículo>, <grupo> alertam que... Como você vê isso?"' in problema


def test_cada_ressalva_e_cobrada_e_a_regra_entra_em_problemas():
    outra = Ressalva(("especialistas em segurança",), "O plano não reduz o crime.", ("G1",))
    episodio = _conversa(("Helena", PERGUNTA), ("Otávio", "As fontes dizem que o risco existe."))
    [problema] = qa.problemas_das_ressalvas(episodio, [RESSALVA, outra])
    assert problema.startswith("ressalva 2 (especialistas em segurança; G1): não aparece numa frase da Helena")

    completo, textos = _episodio(["Gazeta do Povo"]), ["No entanto, economistas alertam para o fim da negociação unificada."]
    [problema] = qa.problemas_com_campo(completo, ["Gazeta do Povo"], UM_LADO, [RESSALVA], textos)
    assert problema.campo == qa.ROTEIRO and problema.texto.startswith("ressalva 1 (economistas; Gazeta do Povo)")
    completo["roteiro_podcast"][0]["fala"] += " " + PERGUNTA
    assert qa.problemas(completo, ["Gazeta do Povo"], UM_LADO, [RESSALVA], textos) == []


def test_termo_do_grupo_vale_em_qualquer_numero_e_genero():
    assert qa.termo_do_grupo("alguns especialistas em segurança") == "especialistas" and qa.termo_do_grupo("os") == ""
    for forma in ("pesquisador", "pesquisadora", "pesquisadores", "pesquisadoras"):
        assert qa.grupo_citado("pesquisadores", f"Segundo o G1, {forma} alertam para o risco.")
        assert qa.grupo_citado(forma, "os pesquisadores")
    assert qa.grupo_citado("economistas", "um economista") and qa.grupo_citado("Críticos", "as críticas")
    assert qa.grupo_citado("organizações", "a organização") and qa.grupo_citado("juízes", "a juíza")
    assert qa.grupo_citado("especialistas em segurança", "especialistas") and not qa.grupo_citado("especialistas em segurança", "a segurança")
    assert not qa.grupo_citado("críticos", "o candidato critica a medida")       # a forma do verbo de posição não é o termo do grupo
    assert not qa.grupo_citado("economistas", "a economia") and not qa.grupo_citado("", "economistas")


def test_ressalva_sem_grupo_pede_o_veiculo_o_verbo_e_a_pergunta():
    sem_grupo = Ressalva((), "A mudança pode enfraquecer a tarifa comum.", ("Gazeta do Povo",))
    com = _conversa(("Helena", "A Gazeta do Povo aponta que a mudança pode enfraquecer a tarifa comum. Como você vê isso?"), ("Otávio", "Há risco."))
    sem = _conversa(("Helena", "A mudança pode enfraquecer a tarifa comum. Como você vê isso?"), ("Otávio", "Há risco."))
    assert qa.problemas_das_ressalvas(com, [sem_grupo]) == []
    assert qa.problemas_das_ressalvas(sem, [sem_grupo])[0].startswith("ressalva 1 (sem grupo; Gazeta do Povo): não aparece")


# ── Atribuição a grupo que a pauta não cita ───────────────────────────────────────────────

# Os textos da pauta da Meta não falam em analistas; a frase é do episódio 3 gerado em 12/10/2026.
TEXTOS_DA_META = ["Meta alega problemas técnicos\nA campanha do PT acionou o TSE. A Meta nega favorecimento.",
                  "Campanha de Lula acusa Meta\nO Grupo Prerrogativas manifestou preocupação."]
PARA_OS_ANALISTAS = "Para os analistas, a opacidade dos sistemas impede que se saiba se houve uma falha real."


def test_atribuicao_a_grupo_que_nenhum_texto_da_pauta_cita_reprova():
    episodio = _episodio(["G1"])
    episodio["roteiro_podcast"][1]["fala"] += ". " + PARA_OS_ANALISTAS
    [problema] = qa.problemas_com_campo(episodio, ["G1"], UM_LADO, SEM_RESSALVAS, TEXTOS_DA_META)
    assert problema.campo == qa.ROTEIRO
    assert problema.texto == ('atribuição a um grupo que os textos da pauta não citam, na fala de Otávio ("Para os analistas"): '
                              "atribua a informação a quem as fontes nomeiam ou retire a frase")
    # o grupo aparece em algum texto da pauta: passa
    assert qa.problemas(episodio, ["G1"], UM_LADO, SEM_RESSALVAS, [*TEXTOS_DA_META, "Analistas avaliam que o caso segue aberto."]) == []


def test_atribuicao_a_grupo_e_cobrada_no_titulo_no_resumo_e_nos_pontos_chave():
    episodio = _episodio(["G1"], titulo_reescrito="Especialistas alertam para risco nas redes",
                         resumo_didatico="Segundo as análises, a Meta falhou. " + "Uma frase. " * 7,
                         pontos_chave=["Críticos dizem que a regra é frouxa.", "A Meta nega favorecimento."])
    campos = [p.campo for p in qa.problemas_das_atribuicoes(episodio, TEXTOS_DA_META)]
    assert campos == [qa.TITULO, qa.RESUMO, qa.PONTOS]


@pytest.mark.parametrize("fala", [
    "As decisões não são transparentes para as autoridades.",          # "para as autoridades" não abre a oração nem atribui nada
    "Nossos analistas explicam o caso em seguida.",                    # o elenco do episódio não é uma fonte
    "Os dois analistas divergem sobre a decisão.",
    "Há pontos críticos que precisam de atenção.",                     # adjetivo, e o verbo não é de atribuição
    "Segundo a CartaCapital, o Grupo Prerrogativas alerta para o risco.",
])
def test_frase_que_nao_atribui_nada_a_um_grupo_sem_nome_passa(fala):
    assert qa.problemas_das_atribuicoes(_conversa(("Helena", "Olá."), ("Otávio", fala)) | {"titulo_reescrito": "", "resumo_didatico": ""},
                                        TEXTOS_DA_META) == []


def _so_falas(*turnos) -> dict:
    """Um episódio só com falas: título e resumo vazios, para a regra das atribuições ler só o roteiro."""
    return _conversa(*turnos) | {"titulo_reescrito": "", "resumo_didatico": ""}


def test_pergunta_aberta_a_um_grupo_nao_e_atribuicao():
    # como no episódio do Muse Wonder de 14/10/2026: Helena pergunta, e o analista responde citando o veículo
    aberta = "O que os especialistas dizem sobre esse equilíbrio técnico?"
    assert qa.problemas_das_atribuicoes(_so_falas(("Helena", aberta), ("Otávio", "Segundo o G1, a Meta vai investigar.")), TEXTOS_DA_META) == []
    for pergunta in ("Como os especialistas avaliam o risco?", "E quais críticos questionam a regra?", "Por que os economistas alertam tanto?"):
        assert qa.problemas_das_atribuicoes(_so_falas(("Helena", pergunta)), TEXTOS_DA_META) == [], pergunta
    # a pergunta que carrega uma afirmação continua contando, e a afirmação seguida de uma pergunta também
    for frase in ("Os especialistas dizem que o risco é alto, não é?", "Os especialistas dizem que o risco é alto. Como você vê isso?",
                  "Segundo os analistas, por que isso acontece?"):
        [problema] = qa.problemas_das_atribuicoes(_so_falas(("Helena", frase)), TEXTOS_DA_META)
        assert problema.texto.startswith("atribuição a um grupo que os textos da pauta não citam"), frase


def test_a_regra_da_atribuicao_a_grupo_nao_herda_os_verbos_de_posicao_novos():
    # verbo novo na regra a faria reprovar mais: regra nova que reprova passa antes pelo diagnóstico
    from techdigest.ai.atribuicoes import VERBOS_DE_ATRIBUICAO
    assert {"informam", "declaram", "declararam", "informaram"}.isdisjoint(VERBOS_DE_ATRIBUICAO)
    assert {"dizem", "concluem", "afirmam", "alertam"} <= VERBOS_DE_ATRIBUICAO
    assert qa.problemas_das_atribuicoes(_so_falas(("Helena", "Especialistas informam que a regra mudou.")), TEXTOS_DA_META) == []


def test_cada_problema_tem_o_campo_em_que_esta():
    curto = " ".join(["palavra"] * (qa.MIN_POR_PERSONAGEM - 1))
    episodio = _episodio(["G1"], titulo_reescrito="Metade do Senado apoia", resumo_didatico="Uma frase. " * (qa.MIN_FRASES_RESUMO - 1),
                         houve_divergencia=True)
    episodio["roteiro_podcast"][1]["fala"] = curto
    campos = {p.campo for p in qa.problemas_com_campo(episodio, ["G1", "Folha"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS)}
    assert campos == {qa.TITULO, qa.RESUMO, qa.ROTEIRO, qa.FONTES, qa.DIVERGENCIA}
    dois_analistas = _episodio(["G1"])
    dois_analistas["roteiro_podcast"].append({"personagem": "Patrícia", "fala": curto + " palavra"})
    assert {p.campo for p in qa.problemas_com_campo(dois_analistas, ["G1"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS)} == {qa.ELENCO}


# ── Números que a pauta não traz ──────────────────────────────────────────────────────────

# O que a pauta da violência política traz, e a fala do episódio 2 gerado em 12/10/2026.
TEXTOS_DA_VIOLENCIA = ["Mulheres são 58,8% das vítimas\nForam 102 episódios, e 60 tiveram mulheres como vítimas. Elas são 34,85% das "
                       "candidaturas. A China compra 30,7% das exportações. Houve 1.564 denúncias no Disque 180 em 2026."]
FALA_372 = "Logo atrás, temos as mulheres brancas com trezentas e setenta e dois por cento das denúncias."


def _com_fala(fala: str) -> dict:
    episodio = _episodio(["G1"])
    episodio["roteiro_podcast"][1]["fala"] += ". " + fala
    return episodio


def test_percentual_que_nenhum_texto_da_pauta_traz_reprova():
    [problema] = qa.problemas_com_campo(_com_fala(FALA_372), ["G1"], UM_LADO, SEM_RESSALVAS, TEXTOS_DA_VIOLENCIA)
    assert problema.campo == qa.ROTEIRO
    assert problema.texto == ('número que os textos da pauta não trazem, na fala de Otávio ("trezentas e setenta e dois por cento"): '
                              "use o número da fonte ou retire-o")


@pytest.mark.parametrize("fala, passa", [
    ("Foram cento e dois episódios, e sessenta tiveram mulheres como vítimas.", True),           # por extenso vale pelo algarismo
    ("Elas são cinquenta e oito vírgula oito por cento das vítimas.", True),                     # decimal dito com "vírgula"
    ("Elas são trinta e quatro vírgula oitenta e cinco por cento das candidaturas.", True),
    ("Houve mil quinhentas e sessenta e quatro denúncias no Disque cento e oitenta em 2026.", True),
    ("Houve mil, quinhentas e sessenta e quatro denúncias no Disque 180.", True),               # a vírgula depois da escala (29/10)
    ("Quase 60% das vítimas são mulheres.", True),                                               # 58,8% está abaixo do dito e a até 5%
    ("Mais de 60% das vítimas são mulheres.", False),                                            # "mais de" pede a fonte acima do dito
    ("Mais de 58% das vítimas são mulheres.", True),
    ("Quase 58% das vítimas são mulheres.", False),                                              # "quase" pede a fonte abaixo do dito
    ("Cerca de 60% das vítimas são mulheres.", True), ("Aproximadamente 56% das vítimas.", True),
    ("Cerca de 50% das vítimas são mulheres.", False),                                           # mais de 5% de distância
    ("A China compra trinta por cento das exportações.", True),                                  # 30,7 truncado
    ("A China compra 31% das exportações.", True),                                               # 30,7 arredondado
    ("A China compra 32% das exportações.", False),
    ("Mulheres são 60% das vítimas.", False),                                                    # sem qualificador, 58,8 só vira 58 ou 59
    ("Foram 12 ataques na semana.", False),                                                      # número a partir de 10 sem fonte
    ("Cento e dois por cento de certeza.", False),                                               # 102 está na pauta, mas não como percentual
    ("Há dois lados e três pontos em aberto.", True),                                            # abaixo de 10, fica só no diagnóstico
    ("Só 8% apoiam.", False),                                                                    # percentual pede fonte em qualquer tamanho
])
def test_numero_vale_pelo_que_a_pauta_traz_e_arredonda_so_com_qualificador(fala, passa):
    assert (qa.problemas_dos_numeros(_com_fala(fala), TEXTOS_DA_VIOLENCIA) == []) is passa


def test_a_virgula_depois_da_escala_junta_o_numero_e_separa_a_enumeracao():
    # com 1.000 e 500 na pauta, "mil, quinhentas" é 1.500 (antes de 29/10, eram dois números com fonte)
    textos = ["Foram 1.000 inscritos e 500 vagas; depois, 10.000, 20.000 e 30.000 visitantes."]
    assert qa.problemas_dos_numeros(_com_fala("Houve mil, quinhentas inscrições."), textos) != []
    # a vírgula antes de outra escala do mesmo tamanho separa dois números: "dez mil, vinte mil"
    assert [n.valor for n in numeros.numeros("dez mil, vinte mil visitantes")] == [10000, 20000]
    assert qa.problemas_dos_numeros(_com_fala("Foram dez mil, vinte mil visitantes."), textos) == []


def test_numero_sem_fonte_e_cobrado_em_cada_campo_e_diz_o_mais_proximo():
    episodio = _episodio(["G1"], titulo_reescrito="Ataques crescem 40% em 2026", pontos_chave=["Foram 105 episódios."],
                         resumo_didatico="Mulheres são mais de 60% das vítimas. " + "Uma frase. " * 7)
    problemas = qa.problemas_dos_numeros(episodio, TEXTOS_DA_VIOLENCIA)
    assert [p.campo for p in problemas] == [qa.TITULO, qa.RESUMO, qa.PONTOS]
    assert problemas[1].texto == ('número que os textos da pauta não trazem, no resumo ("mais de 60%"; a pauta traz 58,8%): '
                                  "use o número da fonte ou retire-o")
    assert '("105"; a pauta traz 102)' in problemas[2].texto


# Uma pauta inventada com números grandes, escritos com e sem a palavra da escala.
TEXTOS_DO_ORCAMENTO = ["O fundo estadual recebeu R$ 312,4 milhões em 2025, e o porto movimentou 3,6 bilhões de reais. A obra custou "
                       "R$ 47.800.000, e a fábrica emprega 18.700 pessoas."]


@pytest.mark.parametrize("fala, passa", [
    ("O fundo recebeu trezentos e doze milhões de reais.", True),     # 312,4 truncado, na escala em que o episódio fala
    ("O fundo recebeu 312 milhões.", True),
    ("O fundo recebeu R$ 313 milhões.", False),                       # 312,4 só vira 312
    ("A obra custou quarenta e sete milhões.", True),                 # a fonte escreve 47.800.000: vale o valor
    ("A obra custou 48 milhões.", True),                              # 47,8 arredondado
    ("A obra custou 46 milhões.", False),
    ("A obra custou 47.000.000 de reais.", False),                    # em unidades, o episódio afirma o número exato
    ("A obra custou quarenta e sete mil reais.", False),              # na escala de mil, a fonte traz 47.800
    ("A fábrica emprega dezoito mil pessoas.", True),                 # 18,7 mil
    ("A fábrica emprega 19 mil pessoas.", True),
    ("O porto movimentou três bilhões.", False),                      # 3,6 na escala: abaixo de 10, a diferença seria de 17%
    ("O porto movimentou quatro bilhões.", False),
    ("O porto movimentou 3,6 bilhões.", True),
    ("O porto movimentou três bilhões e meio.", False),               # 3,5 bilhões não é 3,6
])
def test_numero_dito_em_milhoes_arredonda_o_da_fonte_nessa_escala(fala, passa):
    assert (qa.problemas_dos_numeros(_com_fala(fala), TEXTOS_DO_ORCAMENTO) == []) is passa


def test_dois_milhoes_e_meio_vale_pelo_valor_inteiro():
    textos = ["A cooperativa vendeu 2,5 milhões de mudas em 2025."]
    assert qa.problemas_dos_numeros(_com_fala("A cooperativa vendeu dois milhões e meio de mudas."), textos) == []
    assert qa.problemas_dos_numeros(_com_fala("A cooperativa vendeu 2 milhões e meio de mudas."), textos) == []


@pytest.mark.parametrize("fala", [
    "Segundo o Poder360, o ministro falou.", "O Poder 360 relata que o ministro falou.",
    "O Brasil 247 diz que o ministro falou.", "Para o brasil247, o ministro falou.",
])
def test_numero_do_nome_de_um_veiculo_da_pauta_nao_conta(fala):
    # o "360" do Poder360 na prévia de 25/10/2026 (86+71) era lido como número sem fonte
    textos = ["O ministro falou à imprensa na terça-feira."]
    assert qa.problemas_dos_numeros(_com_fala(fala), textos, ["Poder360 - Jornalismo e Política", "Brasil 247"]) == []
    episodio = _com_fala(fala)
    episodio["fontes_citadas"] = ["Poder360", "Brasil 247"]
    assert qa.problemas_com_campo(episodio, ["Poder360", "Brasil 247"], UM_LADO, SEM_RESSALVAS, textos) == []


def test_numero_fora_do_nome_ou_de_veiculo_que_nao_e_da_pauta_continua_contando():
    textos = ["O ministro falou à imprensa na terça-feira."]
    assert len(qa.problemas_dos_numeros(_com_fala("Segundo o Poder360, foram 360 votos."), textos, ["Poder360"])) == 1
    assert len(qa.problemas_dos_numeros(_com_fala("Segundo o Poder360, o ministro falou."), textos, ["G1"])) == 1
    assert len(qa.problemas_dos_numeros(_com_fala("Segundo o Poder360, o ministro falou."), textos)) == 1


@pytest.mark.parametrize("frases_de_verdade, passa", [
    (qa.MIN_FRASES_RESUMO, True), (qa.MAX_FRASES_RESUMO, True), (qa.MIN_FRASES_RESUMO - 1, False),
])
def test_ponto_dentro_de_uma_palavra_nao_fecha_frase_do_resumo(frases_de_verdade, passa):
    # o 26+69 da prévia de 25/10/2026: os pontos de "Hardware.com.br" contavam como fim de frase (8 frases viravam 12)
    textos = ["A placa custa R$ 1.200 no Brasil."]
    resumo = "Segundo o Hardware.com.br, a placa custa R$ 1.200. " + "Uma frase. " * (frases_de_verdade - 1)
    problemas = qa.problemas(_episodio(["G1"], resumo_didatico=resumo), ["G1"], UM_LADO, SEM_RESSALVAS, textos)
    assert problemas == ([] if passa else [f"resumo com {frases_de_verdade} frases (alvo {qa.MIN_FRASES_RESUMO}-{qa.MAX_FRASES_RESUMO})"])


# ── Papel dos analistas e lado fino ───────────────────────────────────────────────────────

def test_a_passiva_de_decisao_com_o_ator_como_agente_apresenta_o_lado():
    # o A63 de 24/10/2026: o texto só traz a decisão do Kassio na passiva, e a analista a apresentou assim
    lados = [Lado("A suspensão é intromissão.", ("Ivo Brandão",), ("Correio de Serra Quieta",), "Sim"),
             Lado("A suspensão é legal.", ("Marta Quaresma",), ("Correio de Serra Quieta",), "Não")]

    def debate(fala_da_bia: str) -> dict:
        return _debate(("Otávio", "Segundo o Correio de Serra Quieta, Ivo Brandão afirma que a suspensão é intromissão."),
                       ("Patrícia", fala_da_bia))

    passiva = "Segundo o Correio de Serra Quieta, a suspensão foi determinada por decisão da presidente do tribunal, Marta Quaresma."
    assert qa.lados_de_cada_analista(debate(passiva), lados) == {"Otávio": [0], "Patrícia": [1]}
    assert qa.problemas_dos_analistas(debate(passiva), lados) == []
    # sem veículo, ou com o ator fora do agente, a frase não apresenta o lado
    for fala in ("A suspensão foi determinada por decisão da presidente do tribunal, Marta Quaresma.",
                 "Segundo o Correio de Serra Quieta, a suspensão foi determinada pelo tribunal, e Marta Quaresma comentou o caso.",
                 "Segundo o Correio de Serra Quieta, a suspensão, determinada pelo tribunal, foi elogiada por Marta Quaresma."):
        assert qa.lados_de_cada_analista(debate(fala), lados)["Patrícia"] == []


def test_os_analistas_tem_os_nomes_que_o_bloco_da():
    # decisão de 24/10/2026: o código dá os nomes (ver ai/elenco.py), e o QA confere que o roteiro os usa
    lados = [Lado("A cooperativa quer fechar a feira.", ("Ivo Brandão",), ("G1",), "Sim"),
             Lado("A associação defende a praça.", ("Otávio Lins",), ("G1",), "Não")]
    assert nomes_dos_analistas(lados) == ["Mateus", "Patrícia"]          # "Otávio" é o primeiro nome de um ator
    debate = {**_episodio(["G1"]), "personagens": [{"nome": "Helena"}, {"nome": "Mateus"}, {"nome": "Patrícia"}],
              "roteiro_podcast": [{"personagem": "Helena", "fala": "a"}, {"personagem": "Mateus", "fala": "b"},
                                  {"personagem": "Patrícia", "fala": "c"}]}
    assert qa.problemas_dos_nomes(debate, lados) == []
    debate["roteiro_podcast"][1]["personagem"] = "Patrícia"                 # o nome, não o lado: dois "Patrícia" passam aqui
    assert qa.problemas_dos_nomes(debate, lados) == []
    for nome in ("Otávio", "Dr. Mateus", "Analista de Política", "Bia"):
        debate["roteiro_podcast"][1]["personagem"] = nome
        assert qa.problemas_dos_nomes(debate, lados) == [
            f'o analista {nome} não tem um dos nomes que o bloco LADOS DA PAUTA dá aos analistas (Mateus, Patrícia): use os nomes '
            f'do bloco, em "personagens" e no roteiro'], nome
    # o problema é do elenco: pede a revisão do episódio inteiro, que pode trocar o nome
    episodio = {**_episodio(["G1"]), "personagens": [{"nome": "Helena"}, {"nome": "Bia"}],
                "roteiro_podcast": [{"personagem": "Helena", "fala": "a"}, {"personagem": "Bia", "fala": "b"}]}
    [problema] = [p for p in qa.problemas_com_campo(episodio, ["G1"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS) if "nomes" in p.texto]
    assert problema.campo == qa.ELENCO and "(Otávio)" in problema.texto


def test_o_qa_confere_os_nomes_com_os_mesmos_textos_do_bloco():
    # decisão de 25/10/2026: a escolha evita também as pessoas citadas nos textos, e o QA recebe os mesmos textos
    textos = ["Título\nSegundo o engenheiro Otávio Prado, a obra atrasou."]
    episodio = {**_episodio(["G1"]), "personagens": [{"nome": "Helena"}, {"nome": "Otávio"}],
                "roteiro_podcast": [{"personagem": "Helena", "fala": "a"}, {"personagem": "Otávio", "fala": "b"}]}
    assert qa.problemas_dos_nomes(episodio, UM_LADO) == []
    assert qa.problemas_dos_nomes(episodio, UM_LADO, textos)[0].startswith(
        "o analista Otávio não tem um dos nomes que o bloco LADOS DA PAUTA dá aos analistas (Mateus)")
    [problema] = [p for p in qa.problemas_com_campo(episodio, ["G1"], UM_LADO, SEM_RESSALVAS, textos) if "nomes" in p.texto]
    assert "(Mateus)" in problema.texto


def test_papel_de_analista_com_nome_de_ator_dos_lados_reprova():
    episodio = _episodio(["G1"])
    episodio["personagens"] = [{"nome": "Helena", "papel": "apresentadora da Meta"}, {"nome": "Otávio", "papel": "analista da Meta"}]
    [problema] = qa.problemas_dos_papeis(episodio, LADOS_DA_META)
    assert problema == ('papel de Otávio com o nome de um ator dos lados ("analista da Meta"): o papel diz a especialidade do analista '
                        '("analista de regulação"), sem ligá-lo a Meta')
    for papel, reprova in (("analista da campanha de Lula", True), ("porta-voz do PT", True), ("analista de campanhas eleitorais", False),
                           ("analista de regulação", False), ("", False)):
        episodio["personagens"][1] = {"nome": "Otávio", "papel": papel}
        assert bool(qa.problemas_dos_papeis(episodio, LADOS_DA_META)) is reprova
    del episodio["personagens"][1]["papel"]                                             # personagem sem papel não quebra a regra
    assert qa.problemas_dos_papeis(episodio, LADOS_DA_META) == []


def test_verbo_de_quem_decide_conta_na_frase_do_analista():
    # os lados e a frase do Otávio no episódio 5 de v4 (12/10/2026), reprovado porque "entender" não estava na lista
    lados = [Lado("O canal deve ser suspenso.", ("Kassio Nunes Marques",), ("O GLOBO",), "Sim"),
             Lado("A suspensão é tendenciosa.", ("Lula", "André Janones"), ("O GLOBO", "G1", "Agência Brasil"), "Não")]
    debate = _debate(
        ("Otávio", "Segundo o O Globo, o ministro Kassio Nunes Marques entendeu que o canal, que saltou de 50 mil para mais de três "
                      "milhões de seguidores após o primeiro turno, se tornou um vetor de disseminação de conteúdos que a própria Corte "
                      "já reconheceu como desprovidos de lastro mínimo."),
        ("Patrícia", "Segundo o G1, o presidente Lula classificou a medida como absurda e afirmou que já percebe decisões tendenciosas."),
    )
    assert qa.lados_de_cada_analista(debate, lados) == {"Otávio": [0], "Patrícia": [1]}
    assert qa.problemas_dos_analistas(debate, lados) == []


def test_analista_de_lado_fino_fala_pelo_menos_120_palavras_e_o_total_nao_muda():
    grosso = Lado("A campanha acusa.", ("campanha de Lula",), ("CartaCapital",), "Sim", mencoes=5)
    fino = Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não", mencoes=1)
    cheio = " ".join(["palavra"] * qa.MIN_POR_PERSONAGEM)
    pouco = " ".join(["palavra"] * qa.MIN_LADO_FINO)

    def episodio(fala_da_bia: str, fala_do_ramos: str) -> dict:
        return {**_episodio(["G1"]), "houve_divergencia": True, "personagens": [{"nome": "Helena"}, {"nome": "Patrícia"}, {"nome": "Otávio"}],
                "roteiro_podcast": [
                    {"personagem": "Helena", "fala": cheio},
                    {"personagem": "Patrícia", "fala": fala_da_bia + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
                    {"personagem": "Otávio", "fala": fala_do_ramos + ". Já a Agência Brasil registra que a Meta nega."},
                ]}

    curto_no_fino = episodio(cheio, pouco)
    de_sempre = (qa.MIN_POR_PERSONAGEM, qa.MAX_POR_PERSONAGEM)
    assert qa.limites_de_cada_personagem(curto_no_fino, [grosso, fino]) == {
        "Helena": (qa.MIN_HELENA_COM_DEBATE, qa.MAX_POR_PERSONAGEM), "Patrícia": de_sempre, "Otávio": (qa.MIN_LADO_FINO, qa.MAX_POR_PERSONAGEM)}
    assert qa.analistas_de_lado_fino(curto_no_fino, [grosso, fino]) == {"Otávio"}
    assert qa.problemas(curto_no_fino, ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS) == []
    # o mesmo tamanho no analista do outro lado reprova, e sem lado fino o mínimo é o de sempre para os analistas
    problemas = qa.problemas(episodio(pouco, cheio), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS)
    assert problemas[0].startswith(f"Patrícia com {qa.MIN_LADO_FINO + 10} palavras (alvo {qa.MIN_POR_PERSONAGEM}-")
    assert qa.limites_de_cada_personagem(curto_no_fino, [grosso, grosso])["Otávio"] == de_sempre
    # o teto de MAX_LADO_FINO saiu do QA: o analista do lado fino pode falar o que os outros falam
    assert qa.problemas(episodio(cheio, cheio), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS) == []
    # abaixo do mínimo do lado fino reprova, com o mínimo dele na mensagem
    problemas = qa.problemas(episodio(cheio, "palavra"), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS)
    assert problemas[0] == (f"Otávio com 10 palavras (alvo {qa.MIN_LADO_FINO}-{qa.MAX_POR_PERSONAGEM}: é o analista de um lado fino, "
                            "que não amplia além do que as fontes trazem)")
    assert problemas[1].startswith("total de ")                                           # os limites totais não mudam


def test_com_o_orcamento_da_pauta_o_minimo_vem_do_alvo_de_cada_personagem():
    from techdigest.ai.orcamento import Orcamento, orcamento
    grosso = Lado("A campanha acusa.", ("campanha de Lula",), ("CartaCapital",), "Sim", mencoes=5)
    fino = Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não", mencoes=1)

    def falas(n: int) -> str:
        return " ".join(["palavra"] * n)

    def debate(helena: int, bia: int, ramos: int) -> dict:
        return {**_episodio(["G1"]), "houve_divergencia": True, "personagens": [{"nome": "Helena"}, {"nome": "Patrícia"}, {"nome": "Otávio"}],
                "roteiro_podcast": [
                    {"personagem": "Helena", "fala": falas(helena)},
                    {"personagem": "Patrícia", "fala": falas(bia) + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
                    {"personagem": "Otávio", "fala": falas(ramos) + ". Já a Agência Brasil registra que a Meta nega."},
                ]}

    # um texto curto (239 palavras, como o N92): Helena 150, o lado grosso 150, o fino 90 (uma frase do lado)
    orc = orcamento([grosso, fino], 239)
    assert (orc.helena, orc.analistas, orc.total) == (150, (150, 90), 390)
    curto = debate(130, 140, 100)
    assert qa.limites_de_cada_personagem(curto, [grosso, fino], orc) == {
        "Helena": (90, qa.MAX_POR_PERSONAGEM), "Patrícia": (90, qa.MAX_POR_PERSONAGEM), "Otávio": (54, qa.MAX_POR_PERSONAGEM)}
    assert qa.limites_do_total(orc) == (234, qa.MAX_TOTAL)
    assert qa.problemas(curto, ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS, orc) == []
    # sem o orçamento, o mesmo roteiro reprova pelos mínimos de antes
    assert len(qa.problemas(curto, ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS)) == 4
    # abaixo do mínimo, a mensagem diz o que é aceito, o alvo do bloco e o que falta pelo plano das falas
    assert qa.problemas(debate(130, 70, 100), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS, orc) == [
        f"Patrícia com 80 palavras (aceito de 90 a {qa.MAX_POR_PERSONAGEM}; o alvo do bloco é 150): 1 fala de uns 80 palavras; "
        f"o plano pede 2 falas de uns 75: faltam uns 70 palavras para o alvo; siga o plano e complete as falas com o que os "
        f"textos trazem"]
    assert qa.problemas(debate(40, 80, 80), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS, orc)[-1] == (
        f"total de 219 palavras (aceito de 234 a {qa.MAX_TOTAL}; o alvo do bloco é 390)")
    # os máximos não mudam: com o orçamento, 650 continua passando
    assert qa.problemas(debate(130, qa.MAX_POR_PERSONAGEM - 11, 100), ["G1"], [grosso, fino], SEM_RESSALVAS, SEM_TEXTOS, orc) == []
    # o mínimo nunca passa do de antes, mesmo com o alvo cheio
    cheio = Orcamento(430, (430, 430), None)
    assert set(qa.limites_de_cada_personagem(curto, [grosso, fino], cheio).values()) == {
        (qa.MIN_HELENA_COM_DEBATE, qa.MAX_POR_PERSONAGEM), (qa.MIN_POR_PERSONAGEM, qa.MAX_POR_PERSONAGEM),
        (qa.MIN_LADO_FINO, qa.MAX_POR_PERSONAGEM)}
    assert qa.limites_do_total(cheio) == (qa.MIN_TOTAL, qa.MAX_TOTAL)


def test_abaixo_do_minimo_a_mensagem_diz_o_que_falta_em_cada_fala_pelo_plano():
    # o N13 de 24/10/2026: o Otávio fez as 4 falas do plano com 49 palavras, para 4 de 90
    from techdigest.ai.orcamento import Orcamento
    orc = Orcamento(260, (360,), None)
    assert (orc.plano.falas, orc.plano.tamanhos) == ((5, 4), (50, 90))
    roteiro = []
    for _ in range(4):
        roteiro += [{"personagem": "Helena", "fala": " ".join(["palavra"] * 50)}, {"personagem": "Otávio", "fala": " ".join(["palavra"] * 49)}]
    roteiro.append({"personagem": "Helena", "fala": " ".join(["palavra"] * 50)})
    episodio = {**_episodio(["G1"]), "roteiro_podcast": roteiro}
    assert qa.o_que_falta(episodio, UM_LADO, orc, "Otávio") == (
        "4 falas de uns 49 palavras; o plano pede 4 falas de uns 90: acrescente uns 40 palavras a cada fala, com o que os textos trazem")
    assert f"Otávio com 196 palavras (aceito de 216 a {qa.MAX_POR_PERSONAGEM}; o alvo do bloco é 360): 4 falas de uns 49" in (
        qa.problemas(episodio, ["G1"], UM_LADO, SEM_RESSALVAS, SEM_TEXTOS, orc)[0])
    # com outro número de falas, a mensagem diz quanto falta para o alvo
    episodio["roteiro_podcast"] = roteiro[:5]
    assert qa.o_que_falta(episodio, UM_LADO, orc, "Otávio") == (
        "2 falas de uns 49 palavras; o plano pede 4 falas de uns 90: faltam uns 260 palavras para o alvo; siga o plano e "
        "complete as falas com o que os textos trazem")


def test_analista_sem_lado_leva_o_menor_alvo_e_com_um_lado_leva_o_do_lado():
    from techdigest.ai.orcamento import Orcamento
    orc = Orcamento(200, (300, 150), None)
    lados = [Lado("A campanha acusa.", ("campanha de Lula",), ("CartaCapital",), "Sim"), Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não")]
    sem_lado = {**_episodio(["G1"]), "roteiro_podcast": [{"personagem": "Helena", "fala": "a"}, {"personagem": "Patrícia", "fala": "b"},
                                                          {"personagem": "Otávio", "fala": "c"}]}
    assert qa.alvo_de_cada_personagem(sem_lado, lados, orc) == {"Helena": 200, "Patrícia": 150, "Otávio": 150}
    um = Orcamento(200, (380,), None)
    assert qa.alvo_de_cada_personagem(_episodio(["G1"]), UM_LADO, um) == {"Helena": 200, "Otávio": 380}


def test_com_dois_analistas_helena_pode_falar_menos():
    lados = [Lado("A campanha acusa.", ("campanha de Lula",), ("CartaCapital",), "Sim", mencoes=5),
             Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não", mencoes=5)]
    cheio = " ".join(["palavra"] * (qa.MIN_POR_PERSONAGEM + 60))
    helena = " ".join(["palavra"] * (qa.MIN_HELENA_COM_DEBATE - 1))

    def debate(fala_da_helena: str) -> dict:
        return {**_episodio(["G1"]), "houve_divergencia": True, "personagens": [{"nome": "Helena"}, {"nome": "Patrícia"}, {"nome": "Otávio"}],
                "roteiro_podcast": [
                    {"personagem": "Helena", "fala": fala_da_helena},
                    {"personagem": "Patrícia", "fala": cheio + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
                    {"personagem": "Otávio", "fala": cheio + ". Já a Agência Brasil registra que a Meta nega."},
                ]}

    assert qa.problemas(debate(helena + " palavra"), ["G1"], lados, SEM_RESSALVAS, SEM_TEXTOS) == []          # 180 palavras passam
    assert qa.problemas(debate(helena), ["G1"], lados, SEM_RESSALVAS, SEM_TEXTOS) == [
        f"Helena com {qa.MIN_HELENA_COM_DEBATE - 1} palavras (alvo {qa.MIN_HELENA_COM_DEBATE}-{qa.MAX_POR_PERSONAGEM})"]
    # com um analista só, Helena continua com o mínimo de sempre
    um = {**_episodio(["G1"]), "roteiro_podcast": [{"personagem": "Helena", "fala": helena + " palavra"}, {"personagem": "Otávio", "fala": cheio}]}
    assert qa.limites_de_cada_personagem(um, lados[:1])["Helena"] == (qa.MIN_POR_PERSONAGEM, qa.MAX_POR_PERSONAGEM)
    assert qa.problemas(um, ["G1"], lados[:1], SEM_RESSALVAS, SEM_TEXTOS)[0].startswith(
        f"Helena com {qa.MIN_HELENA_COM_DEBATE} palavras (alvo {qa.MIN_POR_PERSONAGEM}-")



# Decimais ditos (04/11): "zero vírgula…", "um vírgula…" e "ponto" como separador, medidos nos reprovados da simulação.
TEXTOS_DOS_JUROS = ["O Copom manteve a taxa. O mercado esperava um corte de 0,25 ponto percentual, e a projeção de crescimento "
                    "para 2026 caiu para 1,8%, com o Focus em 1,76%. A diferença para a Turquia subiu para 1,72 ponto percentual."]


@pytest.mark.parametrize("fala, passa", [
    ("O mercado esperava um corte de zero vírgula vinte e cinco ponto percentual.", True),
    ("A projeção caiu para um vírgula oito por cento.", True),
    ("O Focus projeta um vírgula setenta e seis por cento.", True),
    ("A diferença subiu para um ponto setenta e dois ponto percentual.", True),     # "ponto" também separa os decimais
    ("A diferença subiu para um vírgula setenta e três por cento.", False),         # 1,73 não está na fonte
    ("A projeção caiu para um vírgula nove por cento.", False),
])
def test_decimal_dito_com_zero_um_e_ponto_vale_pelo_valor(fala, passa):
    assert (qa.problemas_dos_numeros(_com_fala(fala), TEXTOS_DOS_JUROS) == []) is passa


@pytest.mark.parametrize("texto, esperado", [
    ("zero vírgula vinte e cinco", [(0.25, False)]),
    ("um vírgula oito por cento", [(1.8, True)]),
    ("uma vírgula cinco", [(1.5, False)]),
    ("zero ponto cinco por cento", [(0.5, True)]),
    ("um ponto setenta e dois", [(1.72, False)]),
    ("dois pontos percentuais", [(2, False)]),
    ("um ponto percentual", []),             # depois de "ponto" não vem número: não é decimal
    ("um ponto de vista", []),               # "um" artigo
    ("zero", []),                            # "zero" sozinho não é número a cobrar
    ("o ponto dois", [(2, False)]),
])
def test_numeros_le_zero_um_e_ponto_como_decimais(texto, esperado):
    from techdigest.ai.numeros import numeros
    assert [(n.valor, n.percentual) for n in numeros(texto)] == esperado


# Intervalos (07/11): a escala, ou o "por cento", dita no último número vale para os dois.
TEXTOS_DOS_INTERVALOS = ["A rival estima entre US$ 15 bilhões e US$ 16 bilhões no período, a fábrica entrega de 30 a 50 milhões "
                         "de peças e a inflação fica entre 15% e 20% no ano."]


@pytest.mark.parametrize("fala, passa", [
    ("A rival estima entre quinze e dezesseis bilhões de dólares.", True),
    ("A rival estima entre 15 e 16 bilhões de dólares.", True),
    ("A rival estima entre quinze e dezessete bilhões de dólares.", False),    # 17 não está na pauta
    ("A rival estima entre quatorze e dezesseis bilhões de dólares.", False),   # 14 bilhões também não
    ("A fábrica entrega de trinta a cinquenta milhões de peças.", True),
    ("A fábrica entrega de 30 a 50 milhões de peças.", True),
    ("A inflação fica entre quinze e vinte por cento.", True),
    ("A inflação fica entre 15 e 20%.", True),
    ("A inflação fica entre quinze e vinte e cinco por cento.", False),
])
def test_intervalo_leva_a_escala_e_o_percentual_do_ultimo_numero_para_os_dois(fala, passa):
    assert (qa.problemas_dos_numeros(_com_fala(fala), TEXTOS_DOS_INTERVALOS) == []) is passa


@pytest.mark.parametrize("texto, esperado", [
    ("entre quinze e dezesseis bilhões", [(15e9, False), (16e9, False)]),
    ("de 3 a 5 milhões", [(3, False), (5e6, False)]),                  # abaixo de 10 continua fora da conta
    ("entre dois e três bilhões", [(2, False), (3e9, False)]),
    ("entre 500 e 600 mil", [(500_000, False), (600_000, False)]),
    ("entre quinze e vinte por cento", [(15, True), (20, True)]),
    ("entre vinte e cinco mil", [(25_000, False)]),                    # um número só, não um intervalo
    ("quinze e dezesseis bilhões", [(15, False), (16e9, False)]),      # sem "entre" ou "de", são dois números
    ("entre quinze e dezesseis", [(15, False), (16, False)]),
])
def test_numeros_aplica_a_escala_do_intervalo_so_a_partir_de_dez(texto, esperado):
    from techdigest.ai.numeros import numeros
    assert [(n.valor, n.percentual) for n in numeros(texto)] == esperado

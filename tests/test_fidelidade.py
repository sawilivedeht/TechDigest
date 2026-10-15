"""Testes de scripts/checar_fidelidade.py: os extratores e as regras, com episódios e pautas de mentira."""
import checar_fidelidade as cf
from checar_fidelidade import Fonte

G1 = Fonte("G1", "Meta nega favorecimento a candidato", (
    "A Meta afirmou, em nota ao Tribunal Superior Eleitoral, que 290 contas e 30,7% dos anúncios foram afetados "
    "em 2026. Analistas ouvidos pelo G1 avaliam que o caso segue aberto, e a ANPD acompanha."
), id=7)
FOLHA = Fonte("Folha de S.Paulo", "Campanha contesta a Meta", "A campanha pediu explicações em 48 horas.", id=8)


def _valores(texto: str) -> list:
    return [(n.valor, n.percentual) for n in cf.numeros(texto)]


def _episodio(*falas, **extras) -> dict:
    """Episódio mínimo: as falas dadas, de Helena e de um analista em turnos alternados."""
    personagens = [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Dr. Ramos", "papel": "analista de Direito Eleitoral"}]
    roteiro = [{"personagem": personagens[i % 2]["nome"], "fala": fala} for i, fala in enumerate(falas)]
    return {"titulo_reescrito": "Título sem dados", "resumo_didatico": "Resumo sem dados.", "pontos_chave": [],
            "personagens": personagens, "roteiro_podcast": roteiro, "houve_divergencia": False,
            "fontes_citadas": ["G1"], **extras}


def _sem_fonte(*falas, fontes=(G1,), **extras) -> list:
    return [(a.tipo, a.rotulo, a.local) for a in cf.conferir(_episodio(*falas, **extras), list(fontes)).sem_fonte]


# ── Números ───────────────────────────────────────────────────────────────────────────────

def test_numeros_em_algarismos():
    assert _valores("R$ 1.200,50, depois 67,50 e 2026.") == [(1200.5, False), (67.5, False), (2026, False)]
    assert _valores("3,2 milhões de seguidores e 36 mil contas") == [(3_200_000, False), (36_000, False)]
    assert _valores("81% dos casos, ou 30 por cento do total") == [(81, True), (30, True)]
    assert _valores("a escala 6x1 e o KC-390") == [(6, False), (1, False), (390, False)]


def test_numero_por_extenso_vale_pelo_algarismo():
    assert _valores("duzentos e noventa") == [(290, False)]
    assert _valores("duzentos e setenta e um por cento") == [(271, True)]
    assert _valores("dois mil e vinte e seis") == [(2026, False)]
    assert _valores("mais de três milhões de seguidores") == [(3_000_000, False)]
    assert _valores("mil duzentos e trinta, e depois cento e vinte") == [(1230, False), (120, False)]
    assert _valores("um terço das candidaturas") == [(round(1 / 3, 6), False)]
    [numero] = cf.numeros("Foram quarenta e oito horas de prazo.")
    assert (numero.valor, numero.trecho) == (48, "quarenta e oito")


def test_artigo_e_enumeracao_nao_viram_numero():
    assert _valores("de um lado e de outro, uma empresa") == []          # "um" e "uma" sozinhos são artigos
    assert _valores("vinte e um casos e um milhão de votos") == [(21, False), (1_000_000, False)]
    assert _valores("entre dois e três dias") == [(2, False), (3, False)]   # não é 5
    assert _valores("três milhões e uma promessa") == [(3_000_000, False)]
    assert _valores("alguns por cento a mais") == []                     # "cento" de "por cento" não é 100


# ── Nomes próprios e atribuições vagas ────────────────────────────────────────────────────

def test_nomes_proprios_ignoram_a_maiuscula_de_comeco_de_frase():
    texto = ("Olá para você. A Meta falou com o Tribunal Superior Eleitoral. Segundo Lula, a Terra de Direitos errou. "
             "TSE decide hoje. WhatsApp fica fora. Zuckerberg não comentou. Meta recorre.")
    nomes = [n.trecho for n in cf.nomes_proprios(texto, cf.maiusculas_no_meio(texto))]
    assert nomes == ["Meta", "Tribunal Superior Eleitoral", "Lula", "Terra de Direitos", "TSE", "WhatsApp", "Meta"]
    # "Olá", "A" e "Segundo" são só começo de frase; "Zuckerberg" também, e por isso escapa (limite conhecido);
    # o último "Meta" conta porque o texto já o escreveu com maiúscula no meio de uma frase.
    [com_conector] = cf.nomes_proprios("Falou a Agência Nacional de Proteção de Dados.")
    assert com_conector.palavras == ("agencia", "nacional", "protecao", "dados")
    assert [n.trecho for n in cf.nomes_proprios("Ouvi o Dr. Marcos, da Folha.")] == ["Dr", "Marcos", "Folha"]


def test_atribuicoes_vagas_pedem_contexto_de_atribuicao():
    texto = ("Segundo as análises, o plano falha. Os economistas também alertam para o risco, e especialistas "
             "afirmam o mesmo. Para os analistas, é cedo.")
    assert [(grupo, expressao) for grupo, expressao, _ in cf.atribuicoes_vagas(texto)] == [
        ("análises", "Segundo as análises"), ("economistas", "economistas também alertam"),
        ("especialistas", "especialistas afirmam"), ("analistas", "Para os analistas"),
    ]
    assert cf.atribuicoes_vagas("Há minerais críticos, como as terras raras, e um especialista em regulação.") == []


# ── conferir ──────────────────────────────────────────────────────────────────────────────

def test_fato_com_fonte_nao_aparece_e_o_sem_fonte_vem_com_a_fala():
    assert _sem_fonte("Foram duzentos e noventa contas em 2026, segundo a Meta.") == []
    assert _sem_fonte("Olá.", "Foram quinhentas contas. E o caso segue.") == [("número", "quinhentas (= 500)", "fala 2 [Dr. Ramos]")]
    [achado] = cf.conferir(_episodio("Olá.", "Foram quinhentas contas. E o caso segue."), [G1]).sem_fonte
    assert achado.frase == "Foram quinhentas contas."


def test_titulo_resumo_e_pontos_chave_tambem_sao_conferidos():
    episodio = _episodio("Olá.", titulo_reescrito="Meta perde 500 contas", resumo_didatico="A Anatel foi acionada.",
                         pontos_chave=["Queda de 12% no alcance."])
    assert [(a.tipo, a.rotulo, a.local) for a in cf.conferir(episodio, [G1]).sem_fonte] == [
        ("número", "500", "título"), ("nome próprio", "Anatel", "resumo_didatico"), ("percentual", "12%", "ponto-chave 1"),
    ]


def test_percentual_so_casa_com_percentual():
    assert _sem_fonte("Subiu duzentos e noventa por cento, diz a Meta.") == [
        ("percentual", "duzentos e noventa por cento (= 290%)", "fala 1 [Helena]")]


def test_arredondamento_fica_a_parte_com_o_numero_da_pauta():
    resultado = cf.conferir(_episodio("Foram trinta por cento dos anúncios.", "E quarenta por cento das contas."), [G1])
    assert [(a.rotulo, a.local) for a in resultado.arredondados] == [
        ("trinta por cento (= 30%) · na pauta: 30,7%", "fala 1 [Helena]")]
    assert [a.rotulo for a in resultado.sem_fonte] == ["quarenta por cento (= 40%)"]     # longe demais de 30,7%
    assert cf.conferir(_episodio("Foram 31% dos anúncios."), [G1]).arredondados != []     # 31 também arredonda 30,7
    assert cf.conferir(_episodio("Foram 30,2% dos anúncios."), [G1]).arredondados == []   # tão preciso quanto: é outro número
    [contas] = cf.conferir(_episodio("Foram trezentas contas."), [G1]).arredondados       # sem "cerca de", mas à vista
    assert contas.rotulo == "trezentas (= 300) · na pauta: 290"


def test_nome_proprio_sem_fonte_e_o_que_fica_fora_da_conta():
    assert _sem_fonte("A reforma atinge o Itamaraty, disse a Meta.") == [("nome próprio", "Itamaraty", "fala 1 [Helena]")]
    # personagens (nome e papel), programa e substantivo institucional genérico não pedem fonte
    assert _sem_fonte("No PulsoBR, recebo o Dr. Ramos, analista de Direito Eleitoral.", "Obrigado, Helena. O Estado precisa agir.") == []


def test_sigla_e_nome_por_extenso_se_equivalem():
    assert _sem_fonte("A decisão cabe ao TSE.") == []                                           # a pauta traz o nome por extenso
    assert _sem_fonte("Falta a Autoridade Nacional de Proteção de Dados.") == []                # a pauta traz a sigla
    pronome = Fonte("G1", "Entrevista", "Ele disse: eu não comento o caso dos EUA.")
    assert _sem_fonte("Isso afeta os Estados Unidos.", fontes=[pronome]) == [
        ("nome próprio", "Estados Unidos", "fala 1 [Helena]")]                                  # "eu" não é a sigla de ninguém


def test_atribuicao_vaga_precisa_do_grupo_na_pauta():
    assert _sem_fonte("A tendência, segundo as análises, é de cautela.") == []                  # a pauta cita analistas
    assert _sem_fonte("Mas os economistas alertam para o risco.") == [
        ("atribuição vaga", "economistas alertam", "fala 1 [Helena]")]


def test_contagem_de_quem_fala_nao_e_fato():
    assert _sem_fonte("O caso envolve dois pilares e três frentes.") == []
    assert _sem_fonte("A votação terá dois turnos.") == [("número", "dois (= 2)", "fala 1 [Helena]")]


def test_fato_repetido_conta_uma_vez_e_lista_cada_fala():
    resultado = cf.conferir(_episodio("A Anatel foi acionada.", "Sim, a Anatel e 77 fiscais.", "A Anatel respondeu."), [G1])
    assert cf.distintos(resultado.sem_fonte) == {"nome próprio": 1, "número": 1}
    assert [a.local for a in resultado.sem_fonte if a.tipo == "nome próprio"] == [
        "fala 1 [Helena]", "fala 2 [Dr. Ramos]", "fala 3 [Helena]"]
    assert resultado.conferidos == {"número": 1, "percentual": 0, "nome próprio": 1, "atribuição vaga": 0}


def test_fato_que_so_esta_depois_do_corte_fica_separado():
    cortada = Fonte("G1", G1.titulo, G1.texto, enviado=G1.texto.index("290"))
    resultado = cf.conferir(_episodio("Foram 290 contas, e não 999."), [cortada])
    assert [a.rotulo for a in resultado.so_no_corte] == ["290"]
    assert [a.rotulo for a in resultado.sem_fonte] == ["999"]


def test_todo_veiculo_da_pauta_tem_de_estar_em_fontes_citadas():
    assert cf.conferir(_episodio("Olá."), [G1, FOLHA]).fontes_faltando == ["Folha de S.Paulo"]
    assert cf.conferir(_episodio("Olá.", fontes_citadas=["g1", "Folha"]), [G1, FOLHA]).fontes_faltando == []
    assert cf.conferir(_episodio("Olá.", fontes_citadas="G1"), [G1]).fontes_faltando == ["G1"]   # lista malformada não vale


# ── Divergência ───────────────────────────────────────────────────────────────────────────

def _debate(*falas_de_helena, analistas=("Dr. Ramos", "Bia")) -> dict:
    roteiro = [{"personagem": "Helena", "fala": fala} for fala in falas_de_helena]
    roteiro += [{"personagem": nome, "fala": "Vejo de outro modo."} for nome in analistas]
    return {"houve_divergencia": True, "roteiro_podcast": roteiro}


def test_divergencia_pede_um_analista_por_lado():
    assert cf.conferir_divergencia(_debate("Vamos ouvir os dois lados.")) == []
    [achado] = cf.conferir_divergencia(_debate("Vamos ouvir.", analistas=("Dr. Ramos",)))
    assert (achado.tipo, achado.rotulo) == ("analistas", "1 analista(s): Dr. Ramos")
    sem_debate = {**_debate("A decisão é absurda.", analistas=("Dr. Ramos",)), "houve_divergencia": False}
    assert cf.conferir_divergencia(sem_debate) == []                    # a regra só vale com houve_divergencia true


def test_helena_nao_toma_posicao_mas_pode_relatar_a_de_alguem():
    achados = cf.conferir_divergencia(_debate(
        "Boa noite. A decisão foi absurda, e o ministro saiu atropelando o rito.",
        "Lula classificou a decisão como absurda.",                     # juízo atribuído a uma das partes
        "A campanha fala em 'manobra' do tribunal.",                    # dentro de citação
    ))
    assert [(a.tipo, a.rotulo, a.local) for a in achados] == [
        ("posição de Helena", "absurda", "fala 1 [Helena]"), ("posição de Helena", "atropelando", "fala 1 [Helena]")]
    assert achados[0].frase == "A decisão foi absurda, e o ministro saiu atropelando o rito."


def test_com_o_recorte_por_relevancia_o_que_o_llm_recebeu_sao_os_paragrafos_do_relatorio():
    primeiro, segundo, terceiro = "Primeiro parágrafo, sobre a eleição.", "Segundo parágrafo, com 290 contas afetadas.", "Terceiro parágrafo, com 512 anúncios."
    texto = "\n".join([primeiro, segundo, terceiro])
    corte = {"incluido": 80, "paragrafos_que_entraram": [{"paragrafo": 1, "motivo": "lide", "caracteres": len(primeiro)},
                                                          {"paragrafo": 3, "motivo": "trecho do lado 1", "caracteres": len(terceiro)}]}
    recorte = cf.recorte_enviado(texto, corte)
    assert recorte == primeiro + "\n" + terceiro
    fonte = Fonte("G1", "Título", texto, enviado=80, recorte=recorte)
    assert "512 anúncios" in fonte.lido and "290 contas" not in fonte.lido and "290 contas" in fonte.completo
    # o número do parágrafo pulado só tem fonte fora do que o LLM recebeu; o do parágrafo do trecho, não
    episodio = _episodio("Olá.", "Foram 290 contas e 512 anúncios, diz o G1.")
    resultado = cf.conferir(episodio, [fonte])
    assert [a.rotulo for a in resultado.so_no_corte] == ["290"] and resultado.sem_fonte == []
    # parágrafo que entrou em parte vai só até onde entrou; relatório antigo, sem os parágrafos, vale o começo do texto
    assert cf.recorte_enviado(texto, {"paragrafos_que_entraram": [{"paragrafo": 2, "caracteres": 17}]}) == "Segundo parágrafo"
    assert cf.recorte_enviado(texto, {"incluido": 80}) is None and cf.recorte_enviado(texto, None) is None
    assert Fonte("G1", "Título", texto, enviado=36).lido.endswith("sobre a eleição.")


# ── Relatório ─────────────────────────────────────────────────────────────────────────────

def test_relatorio_traz_titulo_pauta_contagem_e_a_fala_de_cada_fato():
    episodio = _episodio("Olá.", "Foram quinhentas contas, e trinta por cento dos anúncios, diz a ANPD.",
                         titulo_reescrito="Meta admite falha em 290 contas")
    cortada = Fonte("G1", G1.titulo, G1.texto, enviado=100, id=7)
    caso = cf.Caso(1, "controle_fonte_unica", "aprovado", episodio, [cortada], cf.conferir(episodio, [cortada]))
    texto = cf.montar_relatorio("relatorio.json", [caso], "11/10/2026 21:00:00")

    assert "== Episódio 1 · controle_fonte_unica · aprovado ==\n  título: Meta admite falha em 290 contas\n" in texto
    assert f"    [id 7] G1 — Meta nega favorecimento a candidato ({len(G1.texto)} caracteres, 100 enviados ao LLM)" in texto
    assert '    290 · na pauta (G1): "…' in texto and "que 290 contas e 30,7% dos anúncios" in texto
    assert "  fatos sem fonte: 1 (1 número, 0 percentuais, 0 nomes próprios, 0 atribuições vagas)" in texto
    assert "  números arredondados: 1" in texto
    assert ('  fala 2 [Dr. Ramos]\n    "Foram quinhentas contas, e trinta por cento dos anúncios, diz a ANPD."\n'
            '    - número: quinhentas (= 500) · na frase:') in texto
    assert "    - percentual: trinta por cento (= 30%) · na pauta: 30,7% · na frase:" in texto
    assert "  -- Com fonte só depois do corte (o LLM não recebeu esse trecho) --" in texto and "    - nome próprio: ANPD ·" in texto
    assert "  episódio 1 (controle_fonte_unica): 1 fato(s) sem fonte · 1 arredondado(s) · 1 só depois do corte" in texto


# ── Atribuição a veículo (diagnóstico) ────────────────────────────────────────────────────

VALE = Fonte("Jornal do Vale", "Prefeitura multa construtora", (
    "A prefeitura de Curitiba multou a Construtora Alfa por atrasar a entrega da ponte. "
    "Segundo a prefeitura, o contrato previa a entrega em março, e a multa chega a dois milhões de reais."
), id=1)
LITORAL = Fonte("Diário do Litoral", "Construtora recorre da multa", (
    "A Construtora Alfa vai recorrer da multa na Justiça. A empresa culpa as chuvas pelo atraso da ponte "
    "e diz que os engenheiros trabalharam em turnos dobrados durante o inverno."
), id=2)


def test_frases_que_atribuem_algo_a_um_veiculo():
    veiculos = ["Jornal do Vale", "Diário do Litoral"]
    assert cf.veiculos_atribuidos("Segundo o Jornal do Vale, a prefeitura multou a construtora.", veiculos) == ["Jornal do Vale"]
    assert cf.veiculos_atribuidos("De acordo com o Diário do Litoral, a empresa vai recorrer.", veiculos) == ["Diário do Litoral"]
    assert cf.veiculos_atribuidos("O Diário do Litoral relata que a empresa culpa as chuvas.", veiculos) == ["Diário do Litoral"]
    assert cf.veiculos_atribuidos("A obra, conforme mencionado pelo Jornal do Vale, atrasou.", veiculos) == ["Jornal do Vale"]
    assert cf.veiculos_atribuidos("O Jornal do Vale e o Diário do Litoral cobriram a obra.", veiculos) == []   # sem marcador nem verbo de relato
    assert cf.raiz("derrubou") == cf.raiz("derrubada") == "derrub" and cf.raiz("subindo") == cf.raiz("subiram") == "sub"
    assert cf.raiz("publicações") != cf.raiz("publicacoes") and cf.raiz("publicacoes") == cf.raiz("publicou")   # a raiz recebe a palavra sem acento


def test_a_medida_compara_o_veiculo_citado_com_os_outros():
    episodio = _episodio(
        "Segundo o Diário do Litoral, a prefeitura afirma que o contrato previa a entrega em março.",   # o fato é do Jornal do Vale
        "O Diário do Litoral relata que os engenheiros trabalharam em turnos dobrados durante o inverno.",
        "Segundo o Jornal do Vale, a Construtora Alfa atrasou a ponte.",                      # só palavras que os dois textos têm
    )
    errada, certa, comum = cf.atribuicoes_a_veiculos(episodio, [VALE, LITORAL], atores=["Construtora Alfa", "prefeitura de Curitiba"])
    assert (errada.local, errada.veiculo) == ("fala 1 [Helena]", "Diário do Litoral")
    assert errada.medida.no_citado == 0 and errada.medida.outro == "Jornal do Vale" and errada.medida.no_outro == 1
    assert set(errada.medida.fora_do_citado) == {"contrato", "previa", "entrega", "marco"}
    assert certa.medida.no_citado == 1 and certa.medida.no_outro == 0
    # "atrasou", "ponte" e os nomes estão nos dois textos ou são nomes: não sobra palavra que distinga os veículos
    assert comum.medida.contadas == 0 and comum.medida.no_citado is None
    # com um veículo só não há o que comparar
    assert cf.atribuicoes_a_veiculos(episodio, [VALE]) == []


def test_a_frase_que_apresenta_cada_lado_vem_com_o_veiculo_citado_e_a_medida():
    lados = [cf.Lado("A prefeitura diz que houve atraso.", ("prefeitura de Curitiba",), ("Jornal do Vale",), "Sim"),
             cf.Lado("A construtora culpa as chuvas.", ("Construtora Alfa",), ("Diário do Litoral",), "Não")]
    episodio = {**_episodio("Abertura.", "Segundo o Jornal do Vale, a prefeitura de Curitiba afirma que o contrato previa a entrega em março."),
                "personagens": [{"nome": "Helena"}, {"nome": "Dr. Ramos"}, {"nome": "Bia"}]}
    episodio["roteiro_podcast"].append({"personagem": "Bia", "fala": "Segundo o Diário do Litoral, a Construtora Alfa alega que as chuvas causaram o atraso."})
    ramos, bia = cf.apresentacoes_dos_lados(episodio, [VALE, LITORAL], lados)
    assert (ramos.lado, ramos.personagem, ramos.veiculo, ramos.medida.no_citado) == (1, "Dr. Ramos", "Jornal do Vale", 1)
    assert (bia.lado, bia.personagem, bia.veiculo, bia.medida.no_citado) == (2, "Bia", "Diário do Litoral", 0.5)
    assert bia.medida.fora_do_citado == ("causaram",) and bia.medida.no_outro == 0          # "chuvas" está só no Diário do Litoral
    assert cf.apresentacoes_dos_lados(episodio, [VALE, LITORAL], lados[:1]) == []         # sem disputa, não há lados a apresentar


# ── Atribuição a grupo: a forma só do diagnóstico e as perguntas abertas ──────────────────

def test_para_os_grupo_com_qualificador_conta_so_no_diagnostico():
    # como no episódio da Nintendo de 14/10/2026: os textos não falam em especialistas
    frase = "Para os especialistas em preservação, isso é um problema."
    assert [(a.tipo, a.rotulo) for a in cf.conferir(_episodio("Olá.", frase), [G1]).sem_fonte] == [
        ("atribuição vaga", "Para os especialistas em preservação")]
    # o QA não pega essa forma (regra nova que reprova passa antes pelo diagnóstico)
    assert cf.qa.problemas_das_atribuicoes(_episodio("Olá.", frase), [G1.completo]) == []
    # sem o qualificador, a forma é a do QA, que o diagnóstico também conta
    assert [a.rotulo for a in cf.conferir(_episodio("Olá.", "Para os especialistas, isso é um problema."), [G1]).sem_fonte] == [
        "Para os especialistas"]


def test_pergunta_aberta_a_grupo_fica_fora_da_conta_e_listada_a_parte():
    pergunta = "O que os especialistas dizem sobre esse equilíbrio técnico?"
    r = cf.conferir(_episodio(pergunta, "Segundo o G1, a Meta vai investigar."), [G1])
    assert r.sem_fonte == [] and [(a.tipo, a.rotulo, a.local, a.frase) for a in r.perguntas_abertas] == [
        ("pergunta aberta", "especialistas dizem", "fala 1 [Helena]", pergunta)]
    caso = cf.Caso(1, "controle", "aprovado", _episodio(pergunta), [G1], r)
    texto = cf.montar_relatorio("relatorio.json", [caso], "14/10/2026 21:00:00")
    assert "  -- Perguntas abertas a grupo sem nome (isentas, fora da conta) --\n    fala 1 [Helena]: \"" + pergunta in texto
    assert "1 pergunta(s) aberta(s) isenta(s)" in texto


def test_a_regra_estrita_pede_cinco_palavras_e_quarenta_pontos_de_diferenca():
    medida = cf.Medida(contadas=6, no_citado=0.0, outro="O GLOBO", no_outro=0.67, fora_do_citado=())
    assert cf.outro_tem_mais(medida) and cf.pela_regra_estrita(medida)
    assert not cf.pela_regra_estrita(cf.Medida(4, 0.0, "O GLOBO", 1.0, ()))              # poucas palavras
    assert not cf.pela_regra_estrita(cf.Medida(8, 0.25, "O GLOBO", 0.5, ()))             # diferença pequena
    assert cf.outro_tem_mais(cf.Medida(8, 0.25, "O GLOBO", 0.5, ()))
    assert not cf.outro_tem_mais(cf.Medida(0, None, "", None, ()))

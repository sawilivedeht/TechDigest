"""Testes das funções puras de processing/agrupamento.py (sem rede, banco ou LLM)."""
from techdigest.processing import agrupamento as ag

CHARS_TEXTO = 1500
PESO_TITULO = 0.4
LIMIAR_DUPLICATA = 0.95


def _candidato(titulo: str, veiculo: str, texto: str = "") -> ag.Candidato:
    slug = ag.normalizar(titulo).replace(" ", "-")
    return ag.Candidato(titulo=titulo, veiculo=veiculo, url=f"https://feed.example/{slug}",
                        url_veiculo=f"https://{ag.normalizar(veiculo).replace(' ', '')}.example/{slug}", texto=texto)


def _par(a: ag.Candidato, b: ag.Candidato, score: float, duplicata: bool = False) -> ag.ParPontuado:
    return ag.ParPontuado(a=a, b=b, sim_trigramas=score, sim_entidades=score, sim_titulo=score,
                          sim_texto=score, score=score, duplicata=duplicata)


def _pontuar(candidatos: list[ag.Candidato]) -> dict[frozenset, ag.ParPontuado]:
    titulos = ag.comparar_titulos(candidatos, CHARS_TEXTO)
    textos = ag.comparar_textos(candidatos, CHARS_TEXTO)
    pares = ag.pontuar_pares(candidatos, titulos, textos, PESO_TITULO, LIMIAR_DUPLICATA)
    return {frozenset((p.a, p.b)): p for p in pares}


# ── Normalização ──────────────────────────────────────────────────────────────────────────

def test_normalizar_tira_caixa_acentos_pontuacao_e_stopwords():
    assert ag.normalizar("Itamaraty vive ‘temor Flávio’ e embaixadores cogitam antecipar aposentadoria!") == \
        "itamaraty vive temor flavio embaixadores cogitam antecipar aposentadoria"
    assert ag.normalizar("O que é a PEC do fim da escala 6×1?") == "pec fim escala 6x1"


def test_normalizar_mantem_o_numero_inteiro():
    assert ag.tokenizar("Dólar sobe 2,3% e vai a R$ 5,42; índice já vale 1.200 pontos") == \
        ["dolar", "sobe", "2,3", "5,42", "indice", "vale", "1.200", "pontos"]


def test_stopword_nao_engole_sigla_nem_nome_proprio():
    # sem acento e em minúsculas, IA, IR e Pro seriam "ia", "ir" e "pro"; e o Pará seria "para"
    assert ag.tokenizar("IA calcula o IR no iPhone 17 Pro") == ["ia", "calcula", "ir", "iphone", "17", "pro"]
    assert ag.tokenizar("Governador do Pará vai para Belém") == ["governador", "para", "belem"]
    assert "para" in ag.entidades("Chuva isola cidades do Pará", ag.vocabulario_minusculo(["foi para casa"]))


def test_trigramas_ignoram_ordem_das_palavras_caixa_e_stopwords():
    assert ag.sim_trigramas("Lula sanciona lei", "LULA SANCIONA A LEI!") == 1.0
    assert ag.sim_trigramas("Senado aprova a PEC", "PEC é aprovada no Senado") > 0.7
    assert ag.sim_trigramas("Lula sanciona lei", "Dólar fecha em queda") == 0.0


# ── Sufixo do veículo ─────────────────────────────────────────────────────────────────────

def test_sufixo_vira_veiculo_quando_o_feed_nao_informa_o_veiculo():
    assert ag.separar_veiculo("Senado aprova PEC do fim da escala 6x1 - Agência Brasil") == \
        ("Senado aprova PEC do fim da escala 6x1", "Agência Brasil")
    assert ag.separar_veiculo("Lula sanciona lei - veja o que muda - G1", '"política when:2d" - Google Notícias') == \
        ("Lula sanciona lei - veja o que muda", "G1")


def test_sufixo_igual_ao_veiculo_conhecido_e_cortado():
    assert ag.separar_veiculo("Candidatos disputam votos católicos | HiperNotícias - Você bem informado",
                              "HiperNotícias - Você bem informado") == \
        ("Candidatos disputam votos católicos", "HiperNotícias - Você bem informado")
    assert ag.separar_veiculo("Bolsa fecha em alta - VALOR ECONOMICO", "Valor Econômico") == \
        ("Bolsa fecha em alta", "Valor Econômico")


def test_titulo_ja_limpo_nao_e_cortado():
    titulo = "Agenda de política - Senado deve votar PEC do fim da escala 6x1"
    assert ag.separar_veiculo(titulo, "Valor Econômico") == (titulo, "Valor Econômico")
    assert ag.separar_veiculo("Convey, um novo cliente de e-mail para Linux", "Diolinux") == \
        ("Convey, um novo cliente de e-mail para Linux", "Diolinux")


# ── Entidades ─────────────────────────────────────────────────────────────────────────────

def test_entidades_sao_nomes_proprios_siglas_e_numeros():
    assert ag.entidades("Lula faz comício em Natal e Flávio participa de moto-carreata no Rio") == \
        {"lula", "natal", "flavio", "rio"}
    assert ag.entidades("TV TCL C7L 65” registra o menor preço desde lançamento em oferta no Magalu") == \
        {"tv", "tcl", "c7l", "65", "magalu"}
    assert ag.entidades("Agenda: Senado deve votar PEC do fim da escala 6x1 em 2026") == \
        {"agenda", "senado", "pec", "6x1", "2026"}


def test_palavra_comum_no_inicio_da_frase_nao_e_entidade():
    minusculas = ag.vocabulario_minusculo(["O governo anunciou ontem a nova agenda; a meta fiscal foi mantida."])
    assert ag.entidades("Governo anuncia pacote de R$ 30 bilhões para o Nordeste", minusculas) == {"30", "nordeste"}
    assert ag.entidades("Agenda: Senado deve votar PEC do fim da escala 6x1", minusculas) == {"senado", "pec", "6x1"}
    # no meio da frase a maiúscula é do nome próprio, mesmo que a palavra exista em minúsculas
    assert ag.entidades("O lucro da Meta sobe com anúncios", minusculas) == {"meta"}
    # sigla é sigla em qualquer posição
    assert ag.entidades("IA do Google resolve problema em aberto", frozenset({"ia"})) == {"ia", "google"}


def test_manchete_com_todas_as_iniciais_maiusculas_nao_vira_so_entidade():
    minusculas = ag.vocabulario_minusculo(["o presidente sanciona a nova lei do salário mínimo"])
    assert ag.entidades("Lula Sanciona Nova Lei Do Salário Mínimo", minusculas) == {"lula"}
    assert ag.entidades("LULA SANCIONA NOVA LEI DO SALÁRIO MÍNIMO", minusculas) == {"lula"}


def test_entidade_comum_pesa_menos_que_entidade_rara():
    documentos = [{"lula", "stf"}] * 6 + [{"lula", "embrapa"}, {"embrapa", "soja"}, {"clima"}, {"futebol"}]
    pesos, fantasma = ag.pesos_de_raridade(documentos)
    assert pesos["lula"] < pesos["embrapa"] < fantasma
    so_lula = ag.sim_entidades({"lula"}, {"lula"}, pesos, fantasma)
    so_embrapa = ag.sim_entidades({"embrapa"}, {"embrapa"}, pesos, fantasma)
    assert 0 < so_lula < so_embrapa < 1
    assert ag.sim_entidades({"lula"}, {"embrapa"}, pesos, fantasma) == 0.0


# ── URL canônica ──────────────────────────────────────────────────────────────────────────

def test_url_canonica_tira_utm_fragmento_e_barra_final():
    canonica = "https://www.canaltech.com.br/ia/claude-teste"
    assert ag.url_canonica("https://www.canaltech.com.br/ia/claude-teste/?utm_source=google&utm_medium=rss#comentarios") == canonica
    assert ag.url_canonica("HTTPS://WWW.Canaltech.com.br/ia/claude-teste") == canonica
    assert ag.url_canonica(canonica) == canonica


def test_url_canonica_mantem_os_outros_parametros():
    assert ag.url_canonica("https://site.example/materia/?id=42&utm_campaign=x&pagina=2") == \
        "https://site.example/materia?id=42&pagina=2"
    assert ag.url_canonica("https://site.example/") == "https://site.example"


# ── Score: mesmo fato × mesma entidade ────────────────────────────────────────────────────

IR_AGENCIA = _candidato(
    "Lula sanciona lei que isenta do Imposto de Renda quem ganha até R$ 5 mil", "Agência Brasil",
    "O presidente Luiz Inácio Lula da Silva sancionou nesta quarta-feira a lei que isenta do Imposto de Renda "
    "os trabalhadores que ganham até R$ 5 mil por mês. A cerimônia ocorreu no Palácio do Planalto, com a presença "
    "do ministro da Fazenda. Segundo o governo, cerca de 15 milhões de brasileiros deixarão de pagar o tributo a "
    "partir de janeiro. Para compensar a perda de arrecadação, a lei cria uma alíquota mínima para quem recebe "
    "mais de R$ 600 mil por ano. O texto foi aprovado por unanimidade na Câmara e no Senado.",
)
IR_G1 = _candidato(
    "Isenção do IR para quem recebe até R$ 5 mil vira lei; veja quem ganha", "G1",
    "A isenção do Imposto de Renda para quem recebe até R$ 5 mil mensais virou lei nesta quarta. O presidente "
    "assinou a sanção em evento no Palácio do Planalto, ao lado do ministro da Fazenda. A medida vale a partir de "
    "janeiro e deve beneficiar 15 milhões de contribuintes. Quem ganha entre R$ 5 mil e R$ 7.350 terá desconto "
    "parcial. A compensação virá de uma alíquota mínima cobrada dos contribuintes de alta renda, que recebem acima "
    "de R$ 600 mil por ano. O projeto passou por unanimidade no Congresso.",
)
JUROS_PODER = _candidato(
    "Lula critica juros altos e cobra o Banco Central em evento com empresários", "Poder360",
    "O presidente Luiz Inácio Lula da Silva voltou a criticar a taxa básica de juros nesta quarta-feira, durante "
    "encontro com empresários da indústria em São Paulo. Lula afirmou que não há explicação para a Selic em 15% ao "
    "ano e cobrou do Banco Central uma redução já na próxima reunião do Copom. Representantes do setor reclamaram "
    "do custo do crédito e da queda nos investimentos. O presidente do Banco Central não comentou as declarações.",
)
OUTRAS = [
    _candidato("Senado adia votação do novo Código Eleitoral para depois do segundo turno", "Valor Econômico",
               "O presidente do Senado adiou a votação do novo Código Eleitoral. Os líderes partidários pediram mais "
               "tempo para analisar o relatório, que muda regras de inelegibilidade e de propaganda na internet. A "
               "nova data ainda não foi marcada, mas a expectativa é que o texto volte à pauta depois do segundo turno."),
    _candidato("Nova versão do GNOME chega com suporte melhorado a telas HDR", "Diolinux",
               "O projeto GNOME lançou a nova versão do ambiente de trabalho para Linux. Entre as novidades estão o "
               "suporte melhorado a telas HDR, um novo visualizador de documentos e ajustes de desempenho no "
               "compositor. As distribuições devem receber a atualização nas próximas semanas."),
    _candidato("Brasil perde da China e fecha o Mundial de judô sem medalhas por equipes", "ge",
               "A seleção brasileira de judô foi eliminada pela China na estreia da disputa por equipes e encerrou o "
               "Mundial sem medalhas na prova. O Brasil ficou fora do pódio depois de perder quatro dos seis combates. "
               "A comissão técnica avaliou que a equipe sentiu o desgaste das lutas individuais."),
]


def test_mesmo_fato_com_titulos_diferentes_pontua_mais_que_fatos_diferentes_com_a_mesma_entidade():
    pares = _pontuar([IR_AGENCIA, IR_G1, JUROS_PODER, *OUTRAS])
    mesmo_fato = pares[frozenset((IR_AGENCIA, IR_G1))]
    mesma_entidade = pares[frozenset((IR_AGENCIA, JUROS_PODER))]

    # os títulos do mesmo fato quase não se parecem; os do par de fatos diferentes dividem "Lula"
    assert mesmo_fato.sim_trigramas < 0.5
    assert "lula" in mesma_entidade.entidades_comuns
    assert "lula" not in mesmo_fato.entidades_comuns

    assert mesmo_fato.sim_texto > mesma_entidade.sim_texto
    assert mesmo_fato.score > mesma_entidade.score
    assert mesmo_fato.score > pares[frozenset((IR_G1, JUROS_PODER))].score


def test_score_e_a_media_ponderada_de_titulo_e_texto():
    for par in _pontuar([IR_AGENCIA, IR_G1, JUROS_PODER]).values():
        assert abs(par.score - (PESO_TITULO * par.sim_titulo + (1 - PESO_TITULO) * par.sim_texto)) < 1e-12
        assert 0.0 <= par.score <= 1.0


# ── Duplicatas e pautas ───────────────────────────────────────────────────────────────────

def test_republicacao_e_duplicata_e_nao_conta_como_fonte():
    republicado = _candidato("Lula sanciona isenção do IR até R$ 5 mil", "Sul 21", IR_AGENCIA.texto)
    candidatos = [IR_AGENCIA, republicado, IR_G1, JUROS_PODER, *OUTRAS]
    pares = list(_pontuar(candidatos).values())
    copia = next(p for p in pares if {p.a, p.b} == {IR_AGENCIA, republicado})
    assert copia.duplicata and copia.sim_texto >= LIMIAR_DUPLICATA
    assert not any(p.duplicata for p in pares if p is not copia)

    # limiar do teste, não o padrão: o par do mesmo fato desta amostra pontua perto de 0,25
    pautas, _ = ag.formar_pautas(candidatos, pares, limiar=0.20, max_artigos=2)
    pauta = next(p for p in pautas if IR_AGENCIA in p.artigos)
    assert set(pauta.artigos) == {IR_AGENCIA, IR_G1}      # a republicação não ocupou a segunda vaga
    assert pauta.duplicatas == (republicado,)
    assert pauta.veiculos == ("Agência Brasil", "G1")
    assert set(pauta.links) == {IR_AGENCIA.url, IR_G1.url, republicado.url}
    assert not any(republicado in p.artigos for p in pautas)


def test_pauta_respeita_o_teto_e_guarda_o_par_barrado():
    a, b, c, d, e = (_candidato(f"Notícia {n}", f"Veículo {n}", "x" * n) for n in range(1, 6))
    pares = [_par(a, b, 0.9), _par(b, c, 0.8), _par(c, d, 0.7), _par(a, c, 0.5), _par(a, d, 0.2), _par(d, e, 0.1)]

    pautas, barrados = ag.formar_pautas([a, b, c, d, e], pares, limiar=0.30, max_artigos=3)

    assert [set(p.artigos) for p in pautas] == [{a, b, c}, {d}, {e}]
    assert barrados == [pares[2]]                          # c×d passa do limiar, mas a pauta já tem 3
    assert pautas[0].principal is c                        # o texto mais longo
    assert pautas[0].relacionados == (b, a)                # do mais parecido com o principal para o menos
    assert [p.score for p in pautas[0].pares] == [0.9, 0.8, 0.5]


def test_par_abaixo_do_limiar_nao_forma_pauta():
    a, b = _candidato("Notícia 1", "Veículo 1"), _candidato("Notícia 2", "Veículo 2")
    pautas, barrados = ag.formar_pautas([a, b], [_par(a, b, 0.29)], limiar=0.30, max_artigos=3)
    assert [p.artigos for p in pautas] == [(a,), (b,)]
    assert barrados == []

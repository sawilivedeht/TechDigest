"""Testes de ai/recorte.py: o lide, os parágrafos dos trechos de evidência e o recorte por relevância."""
import pytest

from techdigest.ai import recorte
from techdigest.ai.recorte import cortar_em_paragrafo, lide, literal, paragrafos, paragrafos_com, procurado, recortar

CONTEXTO = "Um parágrafo de contexto sobre a eleição, com uma frase. E outra frase, para o parágrafo ter corpo."   # 99 caracteres
ACUSACAO = "Em nota, a campanha de Lula acusou a empresa de favorecer um candidato na reta final."
DEFESA = "A Meta respondeu que houve um problema técnico e negou qualquer favorecimento."
TEXTO = "\n".join([CONTEXTO] * 6 + [ACUSACAO] + [CONTEXTO] * 3 + [DEFESA, CONTEXTO])     # 12 parágrafos
TRECHOS = [("trecho do lado 1", "a campanha de Lula acusou a empresa"), ("trecho do lado 2", "negou qualquer favorecimento")]


def _numeros(feito) -> list[int]:
    return [e["paragrafo"] for e in feito.entraram]


# ── O lide ────────────────────────────────────────────────────────────────────────────────

def test_paragrafo_e_cada_linha_que_nao_esta_vazia():
    texto = "Primeiro.\n\n  \nSegundo, mais comprido.\nTerceiro."
    assert [(p.numero, texto[p.inicio:p.fim]) for p in paragrafos(texto)] == [(1, "Primeiro."), (2, "Segundo, mais comprido."), (3, "Terceiro.")]
    assert paragrafos("") == [] and paragrafos("\n \n") == []


def test_lide_junta_os_primeiros_paragrafos_ate_somar_400_caracteres():
    assert lide("\n".join([CONTEXTO] * 8)) == [1, 2, 3, 4, 5]             # 99 × 4 = 396 ainda não chega: entra o quinto
    assert lide("\n".join(["x" * 450, CONTEXTO])) == [1]                  # o primeiro já passa de 400
    assert lide(CONTEXTO) == [1] and lide("") == []                       # texto curto: o que houver


# Os começos dos textos 13 (Gazeta do Povo), 21 (G1) e 30 (CNN Brasil) da amostra de 12/10/2026.
GAZETA = (
    "Ouça este conteúdo\n"
    "O presidente Luiz Inácio Lula da Silva (PT) afirmou nesta segunda-feira (12) que o presidente do Tribunal Superior "
    "Eleitoral (TSE), Nunes Marques, não pode ter “lado na política” após a suspensão do canal “Exército do Lula” no WhatsApp. "
    "A declaração foi dada a jornalistas em Brasília, na saída de uma cerimônia religiosa no Palácio da Alvorada.\n"
    "“Eu acho que eles estão extrapolando em algumas decisões contra a minha campanha. Isso é visível e já foi denunciado”, disse.\n"
    "Lula atendeu a imprensa após assistir a uma missa na capela do Palácio da Alvorada."
)
G1 = (
    "Flávio Bolsonaro e Lula — Foto: Afonso Ferreira/TV Globo e Divulgação/Ricardo Stuckert\n"
    "O programa eleitoral do candidato à Presidência Flávio Bolsonaro (PL) foi ao ar sem áudio nesta segunda-feira (12). A campanha "
    "informou que ainda apura o que aconteceu. Flávio publicou um vídeo nas redes sociais em que criticou a falha.\n"
    "A peça foi aberta com uma homenagem a Nossa Senhora Aparecida, padroeira do Brasil, cuja data é celebrada nesta segunda. O "
    "programa também contou com a participação do escritor Augusto Cury, que disputou a Presidência.\n"
    "Na abertura, a peça fez referência à data como um momento para o Brasil lembrar de sua padroeira e reconhecer a fé de seu povo."
)
TITULO_DA_CNN = "Brasil x Argentina: horário e onde assistir ao 2º jogo da Seleção Feminina"
CNN = (
    "Brasil x Argentina: horário e onde assistir ao 2º jogo da Seleção Feminina\n"
    "Equipes disputam amistoso preparatório para o Mundial de 2027 nesta terça-feira (13), na Arena Pernambuco, em Recife\n"
    "Compartilhar matéria\n"
    "O Brasil encara a Argentina nesta terça-feira (13), às 20h30 (de Brasília), em amistoso do ciclo preparatório para a Copa do "
    "Mundo Feminina de 2027.\n"
    "O confronto será realizado na Arena Pernambuco, em Recife.\n"
    "No primeiro confronto, a Seleção Brasileira feminina venceu a Argentina por 3 a 1 neste sábado (10), no Beira-Rio, em Porto "
    "Alegre, em amistoso preparatório para a Copa do Mundo de 2027.\n"
    "Leia Mais \n"
    "Com um primeiro tempo dominante, o Brasil construiu a vantagem com gols de Luany, Geyse e Angelina."
)


@pytest.mark.parametrize("texto, titulo, do_lide", [
    (GAZETA, "Presidente do TSE não pode ter lado na política, diz Lula", [2, 3]),   # pula "Ouça este conteúdo"
    (G1, "Programa de Flávio vai ao ar sem áudio", [2, 3]),                          # pula a legenda da foto, que tem 86 caracteres
    (CNN, TITULO_DA_CNN, [2, 4, 6]),             # pula o título repetido, "Compartilhar matéria" e a linha de 58 caracteres
])
def test_lide_pula_linha_curta_legenda_chamada_e_titulo_repetido(texto, titulo, do_lide):
    assert lide(texto, titulo) == do_lide


@pytest.mark.parametrize("linha", [
    "Ouça este conteúdo e fique por dentro das principais notícias de política desta segunda-feira",
    "Compartilhar matéria com os seus contatos nas redes sociais e nos aplicativos de mensagem",
    "O presidente Lula durante cerimônia no Palácio do Planalto, em Brasília — Foto: Ricardo Stuckert/PR",
    "Plenário do Tribunal Superior Eleitoral durante a sessão desta quinta (Imagem: Divulgação/TSE)",
    "Leia também: o que muda com a decisão do tribunal sobre os canais de campanha no aplicativo",
    "Siga o canal do veículo no aplicativo de mensagens e receba as principais notícias do dia",
])
def test_linha_que_parece_legenda_ou_chamada_nao_entra_no_lide(linha):
    assert len(linha) >= recorte.MIN_LINHA_DO_LIDE and lide(f"{linha}\n{CONTEXTO}") == [2]


def test_frase_comum_com_as_mesmas_palavras_no_meio_entra_no_lide():
    comum = "O ministro pediu que os eleitores ouçam os dois lados e compartilhem só o que for verdadeiro, disse a assessoria."
    assert lide(f"{comum}\n{CONTEXTO}")[0] == 1


# ── Os parágrafos de um trecho ────────────────────────────────────────────────────────────

def test_paragrafos_com_acha_o_trecho_pela_comparacao_literal():
    assert paragrafos_com("a campanha de Lula acusou a empresa", TEXTO) == [7]
    assert paragrafos_com("  “A CAMPANHA de Lula\nacusou a empresa”...", TEXTO) == [7]       # espaços, aspas, caixa e reticências não contam
    assert paragrafos_com("com uma frase. E outra frase", TEXTO) == [1, 2, 3, 4, 5, 6, 8, 9, 10, 12]   # o que se repete traz todos os lugares
    assert paragrafos_com("para o parágrafo ter corpo. Em nota, a campanha de Lula", TEXTO) == [6, 7]   # atravessa dois parágrafos
    assert paragrafos_com("a campanha de Lula processou a empresa", TEXTO) == [] and paragrafos_com("...", TEXTO) == []
    assert procurado("“Um trecho.”…") == "um trecho" and literal("  Dois   espaços\ne ‘aspas’ ") == "dois espaços e 'aspas'"


# ── O recorte ─────────────────────────────────────────────────────────────────────────────

def test_texto_que_cabe_entra_inteiro_e_cada_paragrafo_diz_por_que_entrou():
    feito = recortar(TEXTO, len(TEXTO), TRECHOS)
    assert feito.texto == TEXTO and feito.total == 12 and feito.fora == []
    assert [e["motivo"] for e in feito.entraram] == (
        ["lide"] * 5 + ["ordem do texto", "trecho do lado 1"] + ["ordem do texto"] * 3 + ["trecho do lado 2", "ordem do texto"])
    assert feito.entraram[6] == {"paragrafo": 7, "motivo": "trecho do lado 1", "caracteres": len(ACUSACAO)}


def test_com_pouco_espaco_entram_o_lide_os_paragrafos_dos_trechos_e_depois_o_resto_em_ordem():
    feito = recortar(TEXTO, 800, TRECHOS)
    # o lide (5 parágrafos, 499 caracteres), os parágrafos dos dois trechos e, do resto, o que ainda coube na ordem do texto
    assert _numeros(feito) == [1, 2, 3, 4, 5, 6, 7, 11] and len(feito.texto) <= 800 and feito.fora == []
    assert feito.texto == "\n".join([CONTEXTO] * 6 + [ACUSACAO, recorte.MARCA, DEFESA])    # na ordem do texto, com a marca no salto
    assert [e["motivo"] for e in feito.entraram][5:] == ["ordem do texto", "trecho do lado 1", "trecho do lado 2"]

    apertado = recortar(TEXTO, 700, TRECHOS)                              # o resto não cabe: só o lide e os trechos
    assert _numeros(apertado) == [1, 2, 3, 4, 5, 7, 11]
    assert apertado.texto == "\n".join([CONTEXTO] * 5 + [recorte.MARCA, ACUSACAO, recorte.MARCA, DEFESA])


def test_paragrafo_com_trecho_que_nao_cabe_fica_registrado_como_fora():
    feito = recortar(TEXTO, 600, TRECHOS)                                 # depois do lide, só cabe o parágrafo de um trecho
    assert _numeros(feito) == [1, 2, 3, 4, 5, 7] and len(feito.texto) <= 600
    assert feito.fora == [{"paragrafo": 11, "motivo": "trecho do lado 2", "caracteres": len(DEFESA)}]
    nada = recortar(TEXTO, 0, TRECHOS)                                    # fonte que saiu da entrada: tudo o que tem trecho fica de fora
    assert nada.texto == "" and nada.entraram == [] and [f["paragrafo"] for f in nada.fora] == [7, 11]


def test_o_mesmo_paragrafo_pode_ter_mais_de_um_motivo():
    feito = recortar(TEXTO, len(TEXTO), [("trecho do lado 1", "Um parágrafo de contexto sobre a eleição"), *TRECHOS,
                                         ("trecho da ressalva 1", "negou qualquer favorecimento")])
    assert feito.entraram[0]["motivo"] == "lide; trecho do lado 1" and feito.entraram[10]["motivo"] == "trecho do lado 2; trecho da ressalva 1"
    # e o que fica de fora leva todos os motivos que tinha para entrar
    fora = recortar(TEXTO, 520, [("trecho do lado 2", "negou qualquer favorecimento"), ("trecho da ressalva 1", "A Meta respondeu que houve")]).fora
    assert fora == [{"paragrafo": 11, "motivo": "trecho do lado 2; trecho da ressalva 1", "caracteres": len(DEFESA)}]


def test_sem_trechos_o_recorte_e_o_comeco_do_texto_em_fim_de_paragrafo():
    for cabe in (150, 420, 700, 1000, len(TEXTO)):
        feito = recortar(TEXTO, cabe)
        assert feito.texto == cortar_em_paragrafo(TEXTO, cabe) and recorte.MARCA not in feito.texto
    com_linhas_curtas = "Ouça este conteúdo\n" + TEXTO                    # a linha que o lide pula entra depois, na ordem do texto
    assert recortar(com_linhas_curtas, 700).texto == cortar_em_paragrafo(com_linhas_curtas, 700)
    assert recortar(com_linhas_curtas, 700).entraram[0] == {"paragrafo": 1, "motivo": "ordem do texto", "caracteres": 18}


def test_paragrafo_enorme_entra_em_parte_ate_um_fim_de_frase():
    enorme = "Uma frase qualquer sobre o assunto. " * 40                  # um parágrafo só, de 1440 caracteres
    feito = recortar(enorme.strip(), 500)
    assert feito.texto == cortar_em_paragrafo(enorme.strip(), 500) and feito.texto.endswith("o assunto.") and 450 < len(feito.texto) <= 500
    assert feito.entraram == [{"paragrafo": 1, "motivo": "lide; ordem do texto", "caracteres": len(feito.texto), "cortado": True}]
    sem_frase = recortar("palavra " * 200, 100)                           # sem fim de frase, vale o fim de palavra
    assert sem_frase.texto.endswith("palavra") and 90 < len(sem_frase.texto) <= 100

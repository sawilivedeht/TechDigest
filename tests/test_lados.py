"""Testes de ai/lados.py sem LLM: a validação da resposta, as respostas por ator, as ressalvas, a nova tentativa, o lado
neutro, os textos que cabem na chamada e o bloco da entrada."""
import json
import logging

import pytest

from techdigest.ai import lados as modulo
from techdigest.ai.lados import (
    Evidencia, Lado, Ressalva, analisar_lados, analise_da_resposta, ator_generico, bloco_dos_lados, com_mencoes,
    entrada_dos_lados, lado_unico, lados_finos, mencoes, outro_com_o_sobrenome, pedido_das_respostas, pedido_de_correcao,
    reserva_do_bloco, sobrenome, sobrenomes_que_contam, textos_que_cabem, trechos_de_evidencia,
)
from techdigest.ai.orcamento import orcamento
from techdigest.ai.prompt import PROMPT_LADOS

VEICULOS = ["Agência Brasil", "CartaCapital"]
TEXTOS = [
    {"fonte": "Agência Brasil", "titulo": "Meta alega problemas técnicos",
     "texto": "A Meta respondeu às acusações da campanha e negou favorecimento."},
    {"fonte": "CartaCapital", "titulo": "Campanha de Lula acusa Meta",
     "texto": "A campanha acusou a empresa de favorecer um candidato."},
]
# Um trecho de cada texto, para servir de evidência nas respostas por ator.
DA_AB, DA_CARTA = "A Meta respondeu às acusações da campanha", "A campanha acusou a empresa de favorecer"
EMERGENCIA = [Lado("relato dos fatos, sem lados definidos", (), ("Agência Brasil", "CartaCapital"))]


def _lado(posicao="Uma posição.", atores=("Meta",), veiculos=("Agência Brasil",), resposta=None, grupos=None, trecho=None) -> dict:
    lado = {"posicao": posicao, "atores": list(atores), "veiculos": list(veiculos)}
    if grupos is not None:
        lado["grupos"] = list(grupos)
    if trecho is not None:
        lado["trecho"] = trecho
    return lado if resposta is None else {"resposta": resposta, **lado}


def _evidencia(ator, resposta, trecho=DA_AB, veiculo="Agência Brasil") -> dict:
    return {"ator": ator, "resposta": resposta, "trecho": trecho, "veiculo": veiculo}


def _com_evidencias(resposta: dict) -> dict:
    """A resposta com "respostas_por_ator": cada ator dá a resposta do seu lado, com um trecho que existe no texto."""
    return {**resposta, "respostas_por_ator": [
        _evidencia(ator, lado.get("resposta", "")) for lado in resposta["lados"] for ator in lado["atores"]
    ]}


def _disputa(*lados, questao="A Meta favoreceu um candidato?") -> dict:
    """Uma resposta com questão: os lados sem resposta ganham "Resposta 1", "Resposta 2"..., e cada ator, a sua evidência."""
    return _com_evidencias({"questao": questao, "lados": [{"resposta": f"Resposta {i}", **lado} for i, lado in enumerate(lados, 1)]})


DOIS_LADOS = {
    "questao": " A Meta favoreceu um candidato? ",
    "respostas_por_ator": [_evidencia("campanha de Lula", "Sim", DA_CARTA, "cartacapital"), _evidencia("PT", "sim"),
                           _evidencia("Meta", "Não")],
    "lados": [_lado("A campanha acusa a Meta.", ["campanha de Lula", "PT"], ["cartacapital", "Agencia Brasil"], "Sim"),
              _lado("A Meta nega.", ["Meta"], ["AGÊNCIA BRASIL"], "Não.")],
    "motivo": " Acusação contra defesa. ",
}
UM_LADO = {"questao": "", "lados": [_lado(veiculos=VEICULOS, resposta="")], "motivo": "Não há disputa."}
QUATRO_LADOS = _disputa(*(_lado(atores=[a], veiculos=VEICULOS) for a in ("Nunes Marques", "Lula", "Flávio Bolsonaro", "Janones")),
                        questao="O canal deve ser suspenso?")


class Chamada:
    """Faz o papel do chat_json: guarda o que recebeu e devolve (ou levanta) as respostas, uma por chamada.

    A última resposta vale para as chamadas seguintes.
    """

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.recebido = []

    def __call__(self, system, user, **opcoes):
        self.recebido.append((system, user, opcoes))
        resposta = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


# ── Validação ─────────────────────────────────────────────────────────────────────────────

def test_resposta_valida_vira_a_questao_e_os_lados_com_a_grafia_da_pauta():
    chamada = Chamada(DOIS_LADOS)
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.questao == "A Meta favoreceu um candidato?"
    assert analise.lados == [
        # um veículo pode relatar dois lados, e cada ator comprovado deixa o seu trecho
        Lado("A campanha acusa a Meta.", ("campanha de Lula", "PT"), ("Agência Brasil", "CartaCapital"), "Sim", (DA_CARTA, DA_AB)),
        Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não.", (DA_AB,)),
    ]
    # a contagem das frases em que os atores aparecem vem depois, sobre os textos que a geração recebe
    assert [lado.mencoes for lado in com_mencoes(analise.lados, TEXTOS)] == [1, 3]
    assert analise.respostas == [
        Evidencia("campanha de Lula", "Sim", DA_CARTA, "cartacapital", True, prova="verbo de posição no trecho (acusou)"),
        Evidencia("PT", "sim", DA_AB, "Agência Brasil", True, prova="verbo de posição no trecho (respondeu)"),
        Evidencia("Meta", "Não", DA_AB, "Agência Brasil", True, prova="verbo de posição no trecho (respondeu)"),
    ]
    assert analise.motivo == "Acusação contra defesa." and analise.problemas == [] and analise.faltam == []
    assert analise.primeira is None and analise.segunda is None and len(chamada.recebido) == 1   # resposta válida não pede nova tentativa


def test_sem_disputa_a_questao_fica_vazia_e_ha_um_lado_so():
    assert analise_da_resposta(UM_LADO, TEXTOS).problemas == []
    so_os_lados = {"lados": [_lado(veiculos=VEICULOS, resposta="Sim")]}       # sem a chave da questão é o mesmo que questão vazia
    analise = analise_da_resposta(so_os_lados, TEXTOS)
    assert analise.lados == [Lado("Uma posição.", ("Meta",), ("Agência Brasil", "CartaCapital"))] and analise.questao == ""



# ── O veículo que a resposta deixa fora de todos os lados (decisão de 25/10/2026) ──────────

def test_com_um_lado_so_o_veiculo_que_ficou_de_fora_entra_nele():
    # o 90+79+43 da prévia de 25/10: o lado do Zuckerberg só com o NeoFeed, e os outros dois veículos de fora
    analise = analise_da_resposta({"questao": "", "lados": [_lado()]}, TEXTOS)
    assert analise.problemas == []
    assert analise.lados == [Lado("Uma posição.", ("Meta",), ("Agência Brasil", "CartaCapital"))]
    assert "veículo da pauta em nenhum lado da resposta: entra no lado único (CartaCapital)" in analise.ajustes
    assert analise.contexto == []


def test_sem_lado_com_ator_o_veiculo_que_ficou_de_fora_fica_no_lado_neutro():
    ressalva = _lado("Há risco.", [], ["Agência Brasil"], grupos=["economistas"], trecho=DA_AB)
    analise = analise_da_resposta({"lados": [ressalva]}, TEXTOS)
    assert analise.problemas == [] and analise.lados == EMERGENCIA and analise.ressalvas == []


def test_com_dois_lados_o_veiculo_sem_ator_de_nenhum_lado_entra_como_contexto():
    textos = [*TEXTOS, {"fonte": "G1", "titulo": "Eleição tem debate na quinta", "texto": "O debate da eleição ocorre na quinta-feira."}]
    analise = analise_da_resposta(_disputa(_lado(), _lado(atores=["PT"], veiculos=["CartaCapital"])), textos)
    assert analise.problemas == []
    assert [l.atores for l in analise.lados] == [("Meta",), ("PT",)]
    assert [l.veiculos for l in analise.lados] == [("Agência Brasil",), ("CartaCapital",)]
    assert analise.contexto == ["G1"]
    assert "veículo da pauta em nenhum lado, sem ator de nenhum lado no texto: entra como contexto (G1)" in analise.ajustes

@pytest.mark.parametrize("resposta, problema", [
    (QUATRO_LADOS, "resposta com 4 lados (vale de 1 a 3)"),
    ({"lados": []}, "resposta com 0 lados (vale de 1 a 3)"),
    ({"lados": "dois"}, "resposta sem a lista de lados"),
    (_disputa(_lado(atores=["Lula"], veiculos=VEICULOS), _lado(atores=["campanha de Lula"], veiculos=VEICULOS)),
     "lado 1 sem ator que não esteja em outro lado"),                                      # um nome dentro do outro é o mesmo ator
    (_disputa(_lado(veiculos=["Agência Brasil", "Folha de S.Paulo"]), _lado(atores=["PT"], veiculos=["CartaCapital"])),
     "lado 1 com veículo fora da pauta (Folha de S.Paulo)"),
    # com dois lados, o veículo fora de todos os lados cujo texto cita um ator ("Campanha de Lula acusa Meta")
    (_disputa(_lado(), _lado(atores=["PT"])), "veículo da pauta em nenhum lado, com ator de um lado no texto (CartaCapital)"),
    ({"lados": [_lado(posicao=" ", veiculos=VEICULOS)]}, "lado 1 sem posição"),
    ({"lados": [{**_lado(veiculos=VEICULOS), "atores": "Meta"}]}, 'lado 1 com "atores" fora do formato (é uma lista de nomes)'),
    ({"lados": [_lado(veiculos=VEICULOS, grupos=[1])]}, 'lado 1 com "grupos" fora do formato (é uma lista de nomes)'),
    ({"lados": [_lado(veiculos=[])]}, "lado 1 sem veículo"),
    # cada ressalva precisa de pelo menos um veículo da pauta
    ({"lados": [_lado(veiculos=VEICULOS), _lado(atores=[], veiculos=[], grupos=["economistas"])]}, "lado 2 sem veículo"),
    ({"lados": [_lado(veiculos=VEICULOS), _lado(atores=[], veiculos=["Folha"], grupos=["economistas"])]},
     "lado 2 com veículo fora da pauta (Folha)"),
    ({"lados": ["Meta contra Lula"]}, "lado 1 não é um objeto"),
    # ressalva sem grupo não vale: quem não nomeia ator nem grupo não sustenta posição nenhuma
    ({"lados": [_lado(veiculos=VEICULOS), _lado("Há quem veja risco.", [], ["CartaCapital"])]},
     "lado 2 sem ator nem grupo (a ressalva tem de nomear o grupo que a sustenta)"),
    ({"lados": [_lado(veiculos=VEICULOS), _lado("Há quem veja risco.", [], ["CartaCapital"], grupos=["alguns"])]},
     "lado 2 sem ator nem grupo (a ressalva tem de nomear o grupo que a sustenta)"),
    # a questão e os lados andam juntos
    ({"questao": "", "lados": [_lado(veiculos=VEICULOS), _lado(atores=["PT"], veiculos=VEICULOS)]},
     "questão vazia com 2 lados (questão vazia exige exatamente 1 lado)"),
    (_com_evidencias({"questao": "Houve favorecimento?",
                      "lados": [_lado(veiculos=VEICULOS, resposta="Não."), _lado(atores=["PT"], veiculos=VEICULOS, resposta="nao")]}),
     "lados 1 e 2 com a mesma resposta à questão (Não.)"),
    # com questão, a resposta de cada ator e o trecho que a comprova são obrigatórios
    ({"questao": "Houve favorecimento?", "lados": [_lado(veiculos=VEICULOS, resposta="Sim"), _lado(atores=["PT"], veiculos=VEICULOS, resposta="Não")]},
     'resposta com questão e sem "respostas_por_ator" (cada ator tem a sua resposta e um trecho literal)'),
])
def test_resposta_invalida_nas_duas_tentativas_vira_o_lado_neutro(resposta, problema, caplog):
    assert problema in analise_da_resposta(resposta, TEXTOS).problemas
    chamada = Chamada(resposta)
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    # o lado único não vai vazio para a geração: leva a posição de emergência (e nenhuma ressalva)
    assert analise.lados == EMERGENCIA == lado_unico(VEICULOS) and analise.questao == "" and analise.ressalvas == []
    assert problema in analise.problemas and analise.resposta is resposta
    assert len(chamada.recebido) == 2 and problema in analise.primeira.problemas
    assert "Nova tentativa, com o erro anexado." in caplog.text
    assert "inválida nas duas tentativas" in caplog.text and "a pauta segue com um lado só, sem lados definidos" in caplog.text


# ── Nova tentativa ────────────────────────────────────────────────────────────────────────

def test_resposta_invalida_ganha_nova_tentativa_com_o_erro_anexado():
    chamada = Chamada(QUATRO_LADOS, DOIS_LADOS)
    analise = analisar_lados(chamada, TEXTOS)
    assert len(analise.lados) == 2 and analise.problemas == [] and analise.resposta is DOIS_LADOS
    assert analise.primeira.problemas == ["resposta com 4 lados (vale de 1 a 3)"] and analise.primeira.resposta is QUATRO_LADOS

    (sistema, primeira, opcoes), (sistema2, segunda, opcoes2) = chamada.recebido
    assert sistema == sistema2 == PROMPT_LADOS and opcoes == opcoes2
    assert segunda == primeira + "\n\n" + pedido_de_correcao(analise.primeira) == primeira + (
        "\n\nCORREÇÃO: a sua resposta anterior não valeu: resposta com 4 lados (vale de 1 a 3).\n"
        "Resposta anterior: " + json.dumps(QUATRO_LADOS, ensure_ascii=False)[:modulo.MAX_ANTERIOR] + "\n"
        + modulo.LEMBRETE_DA_CORRECAO
    )
    assert 'com questão, "respostas_por_ator" traz a resposta de cada ator e um trecho copiado ao pé da letra' in modulo.LEMBRETE_DA_CORRECAO


def test_chamada_que_falha_tambem_ganha_nova_tentativa():
    chamada = Chamada(ValueError("Modelo retornou resposta VAZIA."), UM_LADO)
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.problemas == [] and len(analise.lados) == 1
    assert analise.primeira.problemas == ["a chamada falhou (ValueError: Modelo retornou resposta VAZIA.)"]
    assert chamada.recebido[1][1].endswith(
        "\n\nCORREÇÃO: a sua resposta anterior não valeu: a chamada falhou (ValueError: Modelo retornou resposta VAZIA.).\n"
        + modulo.LEMBRETE_DA_CORRECAO
    )


def test_duas_chamadas_que_falham_viram_o_lado_de_emergencia(caplog):
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(ValueError("Modelo retornou resposta VAZIA.")), TEXTOS)
    assert analise.lados == EMERGENCIA and analise.resposta is None
    assert analise.problemas == analise.primeira.problemas == ["a chamada falhou (ValueError: Modelo retornou resposta VAZIA.)"]
    assert "a pauta segue com um lado só, sem lados definidos" in caplog.text


def test_o_pedido_de_correcao_corta_a_resposta_comprida():
    comprida = {"lados": [_lado(posicao="x" * 5000, veiculos=[])]}
    assert len(pedido_de_correcao(analise_da_resposta(comprida, TEXTOS))) < modulo.MAX_ANTERIOR + 600


# ── Atores genéricos ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ator", [
    "economistas", "especialistas", "analistas", "críticos", "observadores",    # coletivo sem nome
    "o governo", "a empresa", "O Governo",                                      # designação vaga sem qualificador
    "Especialistas e analistas", "alguns economistas", "um especialista",
])
def test_coletivo_sem_nome_e_designacao_vaga_sao_atores_genericos(ator):
    assert ator_generico(ator)


@pytest.mark.parametrize("ator", [
    "Governo federal", "governo do Amazonas", "governo Lula",                   # com qualificador, vale
    "Meta", "campanha de Lula", "Nunes Marques", "Grupo Prerrogativas",
    "comandante do Corpo de Bombeiros do Amazonas", "Comunidade Europeia",
])
def test_nome_ou_designacao_com_qualificador_nao_e_generico(ator):
    assert not ator_generico(ator)


def test_termos_genericos_vao_sem_acento_e_em_minusculas():
    assert all(termo == termo.lower() and termo.isascii() for termo in modulo.TERMOS_GENERICOS)
    assert all(termo == termo.lower() and termo.isascii() for termo in modulo.COLETIVOS_DE_PESSOAS)
    assert {"economistas", "especialistas", "analistas", "criticos", "observadores", "governo", "empresa"} <= modulo.TERMOS_GENERICOS


@pytest.mark.parametrize("ator", [
    "comunidade de programação", "usuários do fórum Vila Byte", "economistas do Ipea", "moradores do Jardim Sereno",
    "alguns desenvolvedores de jogos", "os eleitores de Porto Quieto",
])
def test_coletivo_de_pessoas_e_grupo_mesmo_com_qualificador(ator):
    # como na pauta N55 de 17/10/2026: a "comunidade de programação" virou um lado e inventou a disputa
    assert ator_generico(ator)


@pytest.mark.parametrize("ator", ["Comunidade Europeia", "Usuários Unidos", "a Comunidade Vila Byte"])
def test_coletivo_com_maiuscula_e_nome_proprio_e_continua_ator(ator):
    assert not ator_generico(ator)


def test_instituicao_so_e_grupo_sem_qualificador():
    assert ator_generico("a campanha") and ator_generico("o ministério") and ator_generico("o tribunal") and ator_generico("a Corte")
    assert not ator_generico("campanha de Lula") and not ator_generico("Ministério da Saúde")
    assert not ator_generico("Coligação Força do Vale") and not ator_generico("Sindicato dos Metalúrgicos de Joinville")


# ── Respostas por ator ────────────────────────────────────────────────────────────────────

SIM = _lado("O canal espalha desinformação.", ["Nunes Marques"], VEICULOS, "Sim")
NAO = _lado("A suspensão é censura.", ["Lula", "campanha de Flávio Bolsonaro"], VEICULOS, "Não")


def _canal(*evidencias) -> dict:
    return {"questao": "O canal deve ser suspenso?", "respostas_por_ator": list(evidencias), "lados": [SIM, NAO]}


def test_ator_em_lado_de_resposta_diferente_da_dele_vai_para_o_lado_certo():
    # como na pauta do canal: a campanha que pediu a suspensão veio no lado contrário a ela
    resposta = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não"),
                      _evidencia("campanha de Flávio Bolsonaro", "Sim, a campanha pediu a suspensão", DA_CARTA, "CartaCapital"))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques", "campanha de Flávio Bolsonaro"), ("Lula",)]
    assert analise.lados[0].trechos == (DA_AB, DA_CARTA) and analise.problemas == [] and analise.questao
    assert analise.ajustes == [
        "ator passou do lado 2 para o lado 1, o da resposta dele (campanha de Flávio Bolsonaro: Sim, a campanha pediu a suspensão)"
    ]


def test_ator_sem_trecho_comprovado_ou_sem_resposta_sai_do_lado():
    resposta = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não", "Lula disse que a decisão é um absurdo"),
                      _evidencia("campanha de Flávio Bolsonaro", "Talvez"))
    analise = analise_da_resposta(resposta, TEXTOS)
    # o trecho de Lula não está no texto e nenhum lado responde "Talvez": o lado 2 fica sem ator e é descartado
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques",)] and analise.questao == ""
    assert analise.ressalvas == [] and analise.descartadas == [] and analise.problemas == [] and analise.faltam == []
    assert analise.ajustes == [
        "ator do lado 2 saiu: o trecho não está no texto de Agência Brasil (Lula)",
        "ator do lado 2 saiu: nenhum lado tem a resposta dele (campanha de Flávio Bolsonaro: Talvez)",
        "lado 2 saiu: ficou sem ator nomeado",
    ]
    assert [e.comprovada for e in analise.respostas] == [True, False, True]

    sem_entrada = analise_da_resposta(_canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não")), TEXTOS)
    assert [lado.atores for lado in sem_entrada.lados] == [("Nunes Marques",), ("Lula",)]
    assert sem_entrada.ajustes == ["ator do lado 2 saiu: não está em respostas_por_ator (campanha de Flávio Bolsonaro)"]
    assert sem_entrada.faltam == ["campanha de Flávio Bolsonaro"] and sem_entrada.problemas == []   # falta a entrada: pede nova tentativa


def test_lado_que_perde_todos_os_atores_nomeados_e_descartado_e_nunca_vira_ressalva():
    # como na pauta da Nintendo de 12/10/2026: a Sony veio num lado, sem trecho que comprovasse a resposta
    com_grupo = {**NAO, "grupos": ["analistas"], "trecho": DA_AB}
    resposta = {"questao": "O canal deve ser suspenso?", "lados": [SIM, com_grupo], "respostas_por_ator": [
        _evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não", "um trecho que não está em texto nenhum"),
        _evidencia("campanha de Flávio Bolsonaro", "Não", "outro trecho que ninguém escreveu"),
    ]}
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques",)] and analise.ressalvas == [] and analise.descartadas == []
    assert analise.ajustes[-1] == "lado 2 saiu: ficou sem ator nomeado" and analise.problemas == []


@pytest.mark.parametrize("trecho, veiculo, vale", [
    (DA_AB, "Agência Brasil", True),
    ("  a meta  respondeu às\nacusações da campanha...", "agencia brasil", True),      # espaços, maiúsculas e reticências não contam
    ("“A Meta respondeu às acusações da campanha”", "Agência Brasil", True),           # nem as aspas em volta
    ("Meta alega problemas técnicos", "Agência Brasil", True),                         # o título também é texto do veículo
    (DA_AB, "CartaCapital", False),                                                    # o trecho é de outro veículo
    (DA_AB, "Folha", False),                                                           # veículo fora da pauta
    ("A Meta respondeu", "Agência Brasil", False),                                     # curto demais para comprovar
    ("A Meta rebateu as acusações da campanha", "Agência Brasil", False),              # paráfrase não é trecho literal
])
def test_o_trecho_tem_de_estar_ao_pe_da_letra_no_texto_do_veiculo(trecho, veiculo, vale):
    resposta = _canal(_evidencia("Nunes Marques", "Sim", trecho, veiculo), _evidencia("Lula", "Não"))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert analise.respostas[0].comprovada is vale and (("Nunes Marques",) in [lado.atores for lado in analise.lados]) is vale


# ── O trecho traz a resposta do ator ──────────────────────────────────────────────────────

# Uma pauta inventada: a cooperativa decidiu fechar a feira, os feirantes protestam, e um texto descreve a conduta dela.
FEIRA = [{"fonte": "Folha de Vila Serena", "titulo": "Cooperativa fecha a feira de domingo", "texto": (
    "A Cooperativa Raízes do Campo decidiu fechar a feira de domingo a partir de novembro.\n"
    "Segundo a cooperativa, a decisão foi tomada por falta de verba.\n"
    "A Associação dos Feirantes protestou na porta da sede. “A feira sustenta duzentas famílias.\n"
    "Fechar agora é abandonar quem produz”, disse a presidente da associação, Marta Quaresma.\n"
    "— Não vamos sair da praça sem resposta — completou Marta Quaresma.\n"
    "A cooperativa tem admitido atrasos no repasse aos produtores desde o ano passado.\n"
    "O conselho da cooperativa, presidido por Edson Lacerda, determinou o fechamento em reunião fechada.\n"
    "Na avaliação dela, o prazo dado aos feirantes é curto demais para reorganizar as vendas.\n"
    "A prefeitura havia classificado a feira como patrimônio do bairro em 2019."
)}]
VILA = "Folha de Vila Serena"


@pytest.mark.parametrize("ator, trecho, prova", [
    ("Cooperativa Raízes do Campo", "A Cooperativa Raízes do Campo decidiu fechar a feira de domingo", "verbo de posição no trecho (decidiu)"),
    ("Associação dos Feirantes", "A Associação dos Feirantes protestou na porta da sede", ""),        # descreve a conduta, não responde
    ("Marta Quaresma", "A feira sustenta duzentas famílias", "verbo de posição no trecho (sustenta)"),
    ("Marta Quaresma", "Fechar agora é abandonar quem produz", "verbo de posição na frase (disse)"),
    ("Marta Quaresma", "Não vamos sair da praça sem resposta", "citação direta"),                    # fala com travessão
    ("Edson Lacerda", "o fechamento em reunião fechada", "verbo de posição na frase (determinou)"),
    ("Marta Quaresma", "o prazo dado aos feirantes é curto demais para reorganizar as vendas", "marcador de atribuição (na avaliacao dela)"),
    ("prefeitura", "a feira como patrimônio do bairro em 2019", "verbo de posição na frase (havia classificado)"),
    ("Cooperativa Raízes do Campo", "atrasos no repasse aos produtores desde o ano passado", ""),        # "admitir" não é verbo de posição
])
def test_o_trecho_tem_de_trazer_a_resposta_do_ator(ator, trecho, prova):
    assert modulo.traz_a_resposta(ator, trecho, FEIRA, VILA) == prova


def test_a_citacao_entre_aspas_vale_mesmo_continuada_de_outro_paragrafo():
    # a citação que abre num parágrafo e fecha no seguinte continua aberta, e a frase sem verbo ainda é fala de alguém
    sem_verbo = [{"fonte": VILA, "titulo": "Feira", "texto": "A presidente falou na praça. “A feira é o sustento do bairro.\nSem ela, a praça morre”."}]
    assert modulo.traz_a_resposta("Marta Quaresma", "Sem ela, a praça morre", sem_verbo, VILA) == "citação direta"
    retas = [{"fonte": VILA, "titulo": "Feira", "texto": 'A presidente falou na praça: "a feira é o sustento do bairro todo".'}]
    assert modulo.traz_a_resposta("Marta Quaresma", "a feira é o sustento do bairro todo", retas, VILA) == "citação direta"
    fora = [{"fonte": VILA, "titulo": "Feira", "texto": "“Fechou.” A feira é o sustento do bairro todo, mostram os dados."}]
    assert modulo.traz_a_resposta("Marta Quaresma", "A feira é o sustento do bairro todo", fora, VILA) == ""


def test_o_verbo_de_decisao_so_vale_na_frase_que_nomeia_o_ator():
    texto = [{"fonte": VILA, "titulo": "Feira", "texto": (
        "O fechamento da feira foi mandado pelo conselho presidido por Edson Lacerda.\n"
        "A feira foi suspensa por tempo indeterminado, sem data para voltar."
    )}]
    assert modulo.traz_a_resposta("Edson Lacerda", "O fechamento da feira foi mandado pelo conselho", texto, VILA) == (
        "verbo de decisão de quem decidiu (mandado)")
    assert modulo.traz_a_resposta("Edson Lacerda", "A feira foi suspensa por tempo indeterminado", texto, VILA) == ""


def test_ator_cujo_trecho_nao_traz_a_resposta_sai_e_fica_entre_os_recusados():
    resposta = {"questao": "A feira deve fechar?", "respostas_por_ator": [
        _evidencia("Cooperativa Raízes do Campo", "Sim", "A Cooperativa Raízes do Campo decidiu fechar a feira de domingo", VILA),
        _evidencia("Associação dos Feirantes", "Não", "A Associação dos Feirantes protestou na porta da sede", VILA),
    ], "lados": [_lado("Fecha.", ["Cooperativa Raízes do Campo"], [VILA], "Sim"), _lado("Não fecha.", ["Associação dos Feirantes"], [VILA], "Não")]}
    analise = analise_da_resposta(resposta, FEIRA)
    assert [lado.atores for lado in analise.lados] == [("Cooperativa Raízes do Campo",)] and analise.questao == ""
    motivo = "o trecho não traz a resposta dele (sem verbo de posição, citação direta, decisão dele nem marcador de atribuição)"
    assert analise.ajustes[0] == f"ator do lado 2 saiu: {motivo} (Associação dos Feirantes)"
    assert analise.recusados == [modulo.Recusado("Associação dos Feirantes", "A Associação dos Feirantes protestou na porta da sede", motivo)]
    assert [e.comprovada for e in analise.respostas] == [True, True] and [e.vale for e in analise.respostas] == [True, False]
    # outra entrada do mesmo ator, com a fala dele, basta para ele ficar
    com_a_fala = {**resposta, "respostas_por_ator": [*resposta["respostas_por_ator"],
                                                     _evidencia("Associação dos Feirantes", "Não", "Fechar agora é abandonar quem produz", VILA)]}
    assert len(analise_da_resposta(com_a_fala, FEIRA).lados) == 2 and analise_da_resposta(com_a_fala, FEIRA).recusados == []


def test_sem_questao_os_atores_ficam_como_vieram():
    # pauta sem disputa: ninguém confere respostas nem trechos
    um = analise_da_resposta({"questao": "", "lados": [_lado(atores=["Terra de Direitos", "Justiça Global"], veiculos=VEICULOS)]}, TEXTOS)
    assert um.problemas == [] and um.ajustes == [] and um.respostas == []
    assert um.lados == [Lado("Uma posição.", ("Terra de Direitos", "Justiça Global"), ("Agência Brasil", "CartaCapital"))]


def test_um_ator_pode_trazer_mais_de_um_trecho_comprovado():
    resposta = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Nunes Marques", "Sim", "Meta alega problemas técnicos"),
                      _evidencia("Nunes Marques", "Sim"),                                  # trecho repetido não conta duas vezes
                      _evidencia("Nunes Marques", "Sim", "um trecho que não está em texto nenhum"),
                      _evidencia("Lula", "Não", DA_CARTA, "CartaCapital"))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.trechos for lado in analise.lados] == [(DA_AB, "Meta alega problemas técnicos"), (DA_CARTA,)]
    assert analise.ajustes == ["ator do lado 2 saiu: não está em respostas_por_ator (campanha de Flávio Bolsonaro)"]
    # os trechos vão para a geração um de cada lado por vez
    assert trechos_de_evidencia(analise.lados, [Ressalva(("economistas",), "Alerta.", ("G1",), "o trecho da ressalva")]) == [
        ("trecho do lado 1", DA_AB), ("trecho do lado 2", DA_CARTA), ("trecho da ressalva 1", "o trecho da ressalva"),
        ("trecho do lado 1", "Meta alega problemas técnicos"),
    ]
    # a resposta do ator vem escrita de um jeito em cada entrada: os dois trechos contam para o lado em que ele ficou
    variada = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Nunes Marques", "É preciso suspender", "Meta alega problemas técnicos"),
                     _evidencia("Lula", "Não", DA_CARTA, "CartaCapital"))
    assert analise_da_resposta(variada, TEXTOS).lados[0].trechos == (DA_AB, "Meta alega problemas técnicos")


# Como na pauta das queimadas: o ministro aparece em várias frases, e o comandante, numa só.
QUEIMADAS = [{"fonte": "Agência Brasil", "titulo": "Força-tarefa federal combate queimadas no Amazonas", "texto": (
    "O ministro Waldez Góes anunciou a força-tarefa. Durante a coletiva, Waldez Góes respondeu às declarações do comandante do "
    "Corpo de Bombeiros do Amazonas, que havia afirmado que o governo federal estaria negando ajuda ao estado. O ministro "
    "argumentou que a União dependia do decreto estadual. Para Waldez Góes, a crise não deve ser politizada."
)}]


# Nomes inventados, fora das amostras: o sobrenome sozinho conta, a não ser que outra pessoa tenha o mesmo.
BAIRRO = [{"fonte": VILA, "titulo": "Quaresma cobra a cooperativa", "texto": (
    "A presidente da associação, Marta Quaresma, cobrou a cooperativa. Segundo Quaresma, o prazo é curto. "
    "A cooperativa não respondeu. Para a Presidente Quaresma, a praça é dos feirantes. A vereadora cobrou "
    "explicações. Edson Lacerda, Quaresma e Dalva Brandão estiveram na reunião."
)}]


def test_a_contagem_aceita_o_sobrenome_sozinho_de_quem_e_nome_de_pessoa():
    assert [sobrenome(a) for a in ("Marta Quaresma", "Kassio Nunes Marques", "Edson Lacerda")] == ["Quaresma", "Marques", "Lacerda"]
    # nome de uma palavra, designação e instituição não têm sobrenome
    for ator in ("Lula", "campanha de Marta Quaresma", "Associação dos Feirantes", "Corpo de Bombeiros do Amazonas", "Ivo van Rijn"):
        assert sobrenome(ator) == "", ator
    # começo de frase, cargo e vírgula não fazem outra pessoa: o título, "Segundo Quaresma", "Presidente Quaresma" e
    # "Lacerda, Quaresma" contam
    assert outro_com_o_sobrenome("Marta Quaresma", BAIRRO) == ""
    assert mencoes(["Marta Quaresma"], BAIRRO) == 5                     # pela regra do QA sozinha, só a 1ª frase contaria
    # outra pessoa com o mesmo sobrenome, citada no texto ou num ator de outro lado: o sobrenome sozinho não conta
    com_ivo = [{**BAIRRO[0], "texto": BAIRRO[0]["texto"] + " O vice, Ivo Quaresma, não comentou."}]
    assert outro_com_o_sobrenome("Marta Quaresma", com_ivo) == "Ivo Quaresma"
    assert mencoes(["Marta Quaresma"], com_ivo) == 1 and sobrenomes_que_contam(["Marta Quaresma"], com_ivo) == []
    assert outro_com_o_sobrenome("Marta Quaresma", BAIRRO, ["Ivo Quaresma"]) == "Ivo Quaresma"
    assert mencoes(["Marta Quaresma"], BAIRRO, ["Ivo Quaresma"]) == 1
    # a partícula entre o prenome e o sobrenome não esconde a outra pessoa
    assert outro_com_o_sobrenome("Ana Brandão", BAIRRO) == "Dalva Brandão"
    # o cargo não conta pela pessoa
    assert mencoes(["Edson Lacerda"], BAIRRO) == 1
    # com_mencoes passa os atores dos outros lados
    lados = [Lado("p", ("Marta Quaresma",), (VILA,), "Sim"), Lado("p", ("Ivo Quaresma",), (VILA,), "Não")]
    assert [lado.mencoes for lado in com_mencoes(lados, BAIRRO)] == [1, 0]


# Nomes inventados: a menção dentro de aspas, a de outro ator e a do nome citado como título, não conta.
PRACA = [{"fonte": VILA, "titulo": "Marta Quaresma cobra a cooperativa", "texto": (
    "A cooperativa respondeu à presidente da associação, Marta Quaresma. “Seria prudente que Marta Quaresma ouvisse os "
    "feirantes”, declarou o diretor Ivo Brandão. O grupo “Amigos de Marta Quaresma” reuniu 300 pessoas.\n"
    "“Não vamos sair da praça”, afirmou Marta Quaresma. Em nota, a cooperativa disse: “A conversa com\n"
    "“Marta Quaresma continua.” A Sant’Ana, padaria da praça, apoia Marta Quaresma."
)}]


def test_a_mencao_que_so_aparece_dentro_de_aspas_nao_conta():
    # decisão de 24/10/2026: no A79, a segunda frase do comandante era o ministro falando dele; no N13, uma das de Lula era
    # a área técnica sobre o canal "Exército de Lula"
    assert modulo.fora_das_aspas("O canal “Exército de Lula” e o 'X'.") == "O canal                    e o 'X'."
    assert modulo.fora_das_aspas('Disse "Lula" e ‘Lula’; Sant’Ana fica.') == "Disse        e       ; Sant’Ana fica."
    # a curva aberta continua no parágrafo seguinte só quando ele abre com aspas
    assert modulo.fora_das_aspas("“Começo\n“meio” fim") == "       \n       fim"
    assert modulo.fora_das_aspas("“Sem fechar\nLula fala") == " " * 11 + "\nLula fala"
    contadas = [f for f, fora in zip(modulo._frases_dos_textos(PRACA), modulo._frases_fora_das_aspas(PRACA))
                if modulo.ator_citado("Marta Quaresma", fora)]
    assert [f[:26] for f in contadas] == [
        "Marta Quaresma cobra a coo",   # o título
        "A cooperativa respondeu à ",   # fora das aspas
        "“Não vamos sair da praça”,",   # a fala do próprio ator conta quando o texto o nomeia fora das aspas
        "A Sant’Ana, padaria da pra",   # o apóstrofo não abre aspas
    ]
    assert mencoes(["Marta Quaresma"], PRACA) == 4
    # no A79, o lado do comandante fica com uma frase só: a fala do ministro sobre ele não conta
    a79 = [{"fonte": "Agência Brasil", "titulo": "Ministro rebate críticas", "texto": (
        "Waldez Góes respondeu às declarações do comandante do Corpo de Bombeiros do Amazonas. “Seria prudente que o "
        "comandante do Corpo de Bombeiros do Amazonas apagasse fogo”, declarou.")}]
    assert mencoes(["comandante do Corpo de Bombeiros do Amazonas"], a79) == 1


def test_o_sobrenome_sozinho_so_conta_para_nome_de_pessoa():
    # decisão de 24/10/2026: no N92, "Unificado" contou como sobrenome do "Sindipetro Unificado"
    sindicato = [{"fonte": VILA, "titulo": "Feira fecha", "texto": (
        "O Sindifeira Unido protestou. Para o Sindifeira Unido, a decisão é censura. Unido, o bairro foi à praça.")}]
    assert sobrenome("Sindifeira Unido") == "Unido" and not modulo.nome_de_pessoa("Sindifeira Unido", sindicato)
    assert sobrenomes_que_contam(["Sindifeira Unido"], sindicato) == [] and mencoes(["Sindifeira Unido"], sindicato) == 2
    # palavra de organização no nome: não é pessoa, com ou sem artigo no texto
    for ator in ("Agência Serena", "Banco Popular", "Justiça Comunitária", "Terra Viva e Justiça Comunitária"):
        assert not modulo.nome_de_pessoa(ator, BAIRRO), ator
    # pessoa: sem artigo antes do nome, ou com o artigo do cargo ("a presidente da associação, Marta Quaresma")
    assert modulo.nome_de_pessoa("Marta Quaresma", BAIRRO) and modulo.nome_de_pessoa("Marta Quaresma", PRACA)
    # o "a" preposição conta como artigo: com mais menções sem ele, o nome continua de pessoa
    assert modulo.nome_de_pessoa("Ivo Brandão", [{"fonte": VILA, "titulo": "Ivo Brandão fala", "texto": "O pedido foi a Ivo Brandão."}]) is False
    assert modulo.nome_de_pessoa("Ivo Brandão", [{"fonte": VILA, "titulo": "Ivo Brandão fala", "texto": "Ivo Brandão pediu a Ivo Brandão."}])


def test_lado_fino_e_o_que_tem_os_atores_em_no_maximo_uma_frase_dos_textos():
    assert mencoes(["Waldez Góes"], QUEIMADAS) == 3 and mencoes(["comandante do Corpo de Bombeiros do Amazonas"], QUEIMADAS) == 1
    assert mencoes(["Meta"], TEXTOS) == 3                               # o título de cada texto conta como uma frase
    assert mencoes(["Waldez Góes", "governo federal"], QUEIMADAS) == 3  # a frase que cita dois atores do lado conta uma vez
    assert mencoes(["Nunes Marques"], QUEIMADAS) == 0 and mencoes([], QUEIMADAS) == 0

    trecho_dele, trecho_do_ministro = "o governo federal estaria negando ajuda ao estado", "Waldez Góes respondeu às declarações do comandante"
    resposta = {"questao": "O governo federal nega ajuda ao Amazonas?", "respostas_por_ator": [
        _evidencia("comandante do Corpo de Bombeiros do Amazonas", "Sim", trecho_dele), _evidencia("Waldez Góes", "Não", trecho_do_ministro),
    ], "lados": [_lado("Nega.", ["comandante do Corpo de Bombeiros do Amazonas"], resposta="Sim"), _lado("Não nega.", ["Waldez Góes"], resposta="Não")]}
    analise = analise_da_resposta(resposta, QUEIMADAS)
    assert [lado.mencoes for lado in analise.lados] == [None, None] and lados_finos(analise.lados) == [False, False]   # ainda não contado
    contados = com_mencoes(analise.lados, QUEIMADAS)                    # a conta é feita nos textos que a geração recebe
    assert [lado.mencoes for lado in contados] == [1, 3] and [lado.fino for lado in contados] == [True, False]
    assert lados_finos(contados) == [True, False]                       # a conta é do código: os dois lados têm um trecho listado cada
    assert lados_finos(contados[:1]) == [False]                         # só há lado fino com 2 lados ou mais
    assert com_mencoes(lado_unico(["G1"]), QUEIMADAS) == lado_unico(["G1"])   # o lado sem atores não é contado
    assert not Lado("p", ("Meta",), ("G1",)).fino                       # lado que não passou pela contagem não é fino


# ── Trecho quase literal ──────────────────────────────────────────────────────────────────

# Uma pauta inventada, com frases de mais de dez palavras: a cópia quase literal pode diferir em uma palavra a cada dez.
OBRA = [
    {"fonte": "Jornal do Vale", "titulo": "Prefeitura multa construtora",
     "texto": ("A prefeitura de Curitiba decidiu multar a Construtora Alfa por atrasar a entrega da ponte em mais de seis meses.\n"
               "A construtora afirmou em nota que o atraso foi causado pelas chuvas e que vai recorrer da multa na Justiça.")},
    {"fonte": "Diário do Litoral", "titulo": "Engenheiros veem risco na obra",
     "texto": ("Engenheiros ouvidos pelo jornal alertam que a pressa para terminar a ponte pode comprometer a segurança da estrutura.\n"
               "A Construtora Alfa sustenta que a obra segue todas as normas técnicas e que não há risco para os motoristas.")},
]
MULTOU = "A prefeitura de Curitiba decidiu multar a Construtora Alfa por atrasar a entrega da ponte em mais de seis meses."
RECORRE = "A construtora afirmou em nota que o atraso foi causado pelas chuvas e que vai recorrer da multa na Justiça."
ALERTAM = "Engenheiros ouvidos pelo jornal alertam que a pressa para terminar a ponte pode comprometer a segurança da estrutura."
SUSTENTA = "A Construtora Alfa sustenta que a obra segue todas as normas técnicas e que não há risco para os motoristas."


def _obra(trecho_da_construtora=RECORRE, trecho_da_prefeitura=MULTOU, *ressalvas) -> dict:
    return {"questao": "A construtora descumpriu o contrato?", "respostas_por_ator": [
        _evidencia("prefeitura de Curitiba", "Sim", trecho_da_prefeitura, "Jornal do Vale"),
        _evidencia("Construtora Alfa", "Não", trecho_da_construtora, "Jornal do Vale"),
    ], "lados": [_lado("A prefeitura diz que a construtora atrasou.", ["prefeitura de Curitiba"], ["Jornal do Vale"], "Sim"),
                 _lado("A construtora culpa as chuvas.", ["Construtora Alfa"], ["Jornal do Vale", "Diário do Litoral"], "Não"),
                 *ressalvas]}


def test_trecho_quase_literal_do_ator_vale_como_esta_no_veiculo():
    quase = "A construtora afirmou, em nota, que o atraso foi provocado pelas chuvas e que vai recorrer da multa na Justiça."   # 1 em 21
    analise = analise_da_resposta(_obra(quase), OBRA)
    assert [lado.atores for lado in analise.lados] == [("prefeitura de Curitiba",), ("Construtora Alfa",)] and analise.problemas == []
    assert analise.lados[1].trechos == ("A construtora afirmou em nota que o atraso foi causado pelas chuvas e que vai recorrer da multa na Justiça",)
    construtora = analise.respostas[1]
    assert (construtora.comprovada, construtora.trecho_do_llm, construtora.diferencas) == (True, quase, 1)
    assert analise.ajustes == [
        "trecho de Construtora Alfa aceito como quase literal (1 palavra(s) diferente(s) do texto de Jornal do Vale): vale o do veículo"
    ]
    # o trecho literal continua como veio, sem ajuste
    literal = analise_da_resposta(_obra(), OBRA)
    assert literal.lados[1].trechos == (RECORRE,) and literal.respostas[1].trecho_do_llm == "" and literal.ajustes == []


def test_trecho_quase_literal_com_negacao_tira_o_ator():
    com_nao = RECORRE.replace("vai recorrer", "não vai recorrer")
    analise = analise_da_resposta(_obra(com_nao), OBRA)
    assert [lado.atores for lado in analise.lados] == [("prefeitura de Curitiba",)] and analise.respostas[1].comprovada is False
    assert analise.ajustes[0] == "ator do lado 2 saiu: o trecho não está no texto de Jornal do Vale (Construtora Alfa)"


def test_trecho_quase_literal_da_ressalva_vale_como_esta_no_veiculo():
    quase = "Engenheiros ouvidos pelo jornal alertam que a pressa de terminar a ponte pode comprometer a segurança da estrutura."
    ressalva = _lado("A pressa pode comprometer a segurança.", [], ["Diário do Litoral"], grupos=["engenheiros"], trecho=quase)
    analise = analise_da_resposta(_obra(RECORRE, MULTOU, ressalva), OBRA)
    assert [r.trecho for r in analise.ressalvas] == [ALERTAM.removesuffix(".")] and analise.descartadas == []
    assert analise.ajustes == ["trecho da ressalva do lado 3 aceito como quase literal (1 palavra(s) diferente(s)): vale o do veículo"]


def test_ressalva_cujo_grupo_e_ator_de_um_lado_sai_e_o_trecho_vai_para_o_lado():
    # como na pauta Lula/TSE de 13/10/2026: a campanha, que já é ator de um lado, veio como "grupo" de uma ressalva
    do_ator = _lado("A obra segue as normas.", [], ["Diário do Litoral"], grupos=["Construtora Alfa"], trecho=SUSTENTA)
    analise = analise_da_resposta(_obra(RECORRE, MULTOU, do_ator), OBRA)
    assert analise.ressalvas == [] and analise.descartadas == [] and analise.problemas == []
    construtora = analise.lados[1]
    assert construtora.trechos == (RECORRE, SUSTENTA) and construtora.veiculos == ("Jornal do Vale", "Diário do Litoral")
    assert analise.ajustes == ["ressalva do lado 3 saiu: o grupo dela é ator do lado 2 (Construtora Alfa); o trecho passou para esse lado"]
    # os veículos da ressalva entram no lado que recebe o trecho
    so_no_jornal = _obra(RECORRE, MULTOU, do_ator)
    so_no_jornal["lados"][1]["veiculos"] = ["Jornal do Vale"]
    assert analise_da_resposta(so_no_jornal, OBRA).lados[1].veiculos == ("Jornal do Vale", "Diário do Litoral")
    # sem o trecho no texto, a ressalva sai do mesmo jeito, e o lado fica como estava
    inventada = _lado("A obra segue as normas.", [], ["Diário do Litoral"], grupos=["a Construtora Alfa"], trecho="A Construtora Alfa garante que a ponte é segura.")
    sem_trecho = analise_da_resposta(_obra(RECORRE, MULTOU, inventada), OBRA)
    assert sem_trecho.ressalvas == [] and sem_trecho.lados[1].trechos == (RECORRE,)
    assert sem_trecho.ajustes == ["ressalva do lado 3 saiu: o grupo dela é ator do lado 2 (a Construtora Alfa); o trecho não está no texto e não passou"]
    # grupo que não é ator de nenhum lado continua ressalva
    engenheiros = _lado("A pressa pode comprometer a segurança.", [], ["Diário do Litoral"], grupos=["engenheiros"], trecho=ALERTAM)
    assert [r.grupos for r in analise_da_resposta(_obra(RECORRE, MULTOU, engenheiros), OBRA).ressalvas] == [("engenheiros",)]


# ── Ressalvas ─────────────────────────────────────────────────────────────────────────────

FLAVIO = _lado("Flávio propõe flexibilizar o Mercosul.", ["Flávio Bolsonaro", "Milei"], ["Agência Brasil"], "Sim")
ALERTA = "A flexibilização pode enfraquecer a tarifa comum."


def test_lado_com_atores_vazios_e_grupos_vira_ressalva_e_a_questao_sai(caplog):
    resposta = _com_evidencias({"questao": "A flexibilização é boa para o Brasil?", "motivo": "Proposta contra alerta.",
                                "lados": [FLAVIO, _lado(ALERTA, [], ["CartaCapital"], "Não", grupos=["economistas"], trecho=DA_CARTA)]})
    chamada = Chamada(resposta)
    with caplog.at_level(logging.INFO, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    # sobrou um lado com ator nomeado: a questão e a resposta dele saem, e a ressalva guarda o grupo e o veículo
    [lado] = analise.lados
    assert (lado.posicao, lado.atores, lado.veiculos, lado.resposta) == (
        "Flávio propõe flexibilizar o Mercosul.", ("Flávio Bolsonaro", "Milei"), ("Agência Brasil",), "")
    assert analise.ressalvas == [Ressalva(("economistas",), ALERTA, ("CartaCapital",), DA_CARTA)]   # o veículo só da ressalva conta como coberto
    assert analise.questao == "" and analise.problemas == [] and analise.ajustes == []
    assert len(chamada.recebido) == 1                                                       # não é resposta inválida: não há nova tentativa
    assert "Lados da pauta: 1 (Flávio Bolsonaro, Milei) · ressalvas: economistas" in caplog.text


def test_lado_so_com_atores_genericos_vira_ressalva_com_os_termos_em_grupos():
    resposta = _disputa(FLAVIO, _lado(ALERTA, ["economistas", "o governo"], VEICULOS, grupos=["analistas", "economistas"], trecho=DA_CARTA))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Flávio Bolsonaro", "Milei")]
    assert analise.ressalvas == [Ressalva(("analistas", "economistas", "o governo"), ALERTA, ("Agência Brasil", "CartaCapital"), DA_CARTA)]
    assert analise.ajustes == ["ator genérico do lado 2 passou a grupo (economistas, o governo)"] and analise.problemas == []


@pytest.mark.parametrize("trecho, motivo", [
    (None, "sem trecho de evidência"),
    ("", "sem trecho de evidência"),
    ("os economistas veem risco para a tarifa comum", "o trecho não está no texto de CartaCapital"),   # paráfrase não comprova
    (DA_AB, "o trecho não está no texto de CartaCapital"),                                             # o trecho é de outro veículo
    ("A campanha acusou", "o trecho não está no texto de CartaCapital"),                               # curto demais
])
def test_ressalva_sem_trecho_comprovado_e_descartada_com_o_motivo(trecho, motivo, caplog):
    ressalva = _lado(ALERTA, [], ["CartaCapital"], grupos=["economistas"], trecho=trecho)
    chamada = Chamada({"lados": [_lado(veiculos=VEICULOS), ressalva]})
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    assert analise.ressalvas == [] and len(analise.lados) == 1 and analise.problemas == [] and len(chamada.recebido) == 1
    assert analise.descartadas == [(Ressalva(("economistas",), ALERTA, ("CartaCapital",), trecho or ""), motivo)]
    assert analise.ajustes == [f"ressalva do lado 2 saiu: {motivo} (economistas)"]
    assert f"1 ressalva(s) descartada(s): {motivo}." in caplog.text


def test_o_trecho_da_ressalva_vale_em_qualquer_veiculo_dela_e_no_titulo():
    em_outro = _lado(ALERTA, [], VEICULOS, grupos=["economistas"], trecho="“Campanha de Lula acusa Meta”...")
    analise = analise_da_resposta({"lados": [_lado(veiculos=VEICULOS), em_outro]}, TEXTOS)
    assert [r.trecho for r in analise.ressalvas] == ["“Campanha de Lula acusa Meta”..."] and analise.descartadas == []


def test_lado_unico_sem_ator_nem_grupo_e_o_relato_dos_fatos_sem_nova_tentativa():
    # como na pauta da seleção feminina: a notícia não tem quem sustente posição nenhuma
    resposta = {"questao": "", "lados": [_lado("O Brasil enfrenta a Argentina.", [], VEICULOS, "", grupos=[])], "motivo": "Sem disputa."}
    chamada = Chamada(resposta)
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.lados == EMERGENCIA and analise.problemas == [] and analise.motivo == "Sem disputa." and len(chamada.recebido) == 1
    assert analise.ajustes == ["lado único sem ator nem grupo: a pauta fica com o lado neutro"] and analise.descartadas == []


def test_em_lado_misto_o_grupo_sai_e_nao_vira_ressalva():
    resposta = _disputa(_lado("A Meta nega.", ["Meta", "especialistas"], grupos=["analistas"]),
                        _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"]))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert analise.ressalvas == [] and analise.problemas == [] and analise.questao        # com dois lados nomeados, a questão fica
    assert analise.ajustes == ["ator genérico do lado 1 passou a grupo (especialistas)"]


def test_com_mais_de_duas_ressalvas_ficam_as_duas_primeiras(caplog):
    resposta = {"lados": [_lado(veiculos=VEICULOS), *(_lado(f"Ressalva {g}.", [], VEICULOS, grupos=[g], trecho=DA_AB)
                                                      for g in ("economistas", "juristas", "moradores"))]}
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(resposta), TEXTOS)
    assert [r.grupos for r in analise.ressalvas] == [("economistas",), ("juristas",)]
    assert [(r.grupos, motivo) for r, motivo in analise.descartadas] == [(("moradores",), "a pauta já tem 2 ressalvas")]
    assert analise.ajustes == ["1 ressalva(s) a mais: ficam as 2 primeiras"] and analise.problemas == []
    assert "1 ressalva(s) descartada(s): a pauta já tem 2 ressalvas." in caplog.text


def test_sem_nenhum_lado_nomeado_fica_o_lado_neutro_e_as_ressalvas_sao_descartadas():
    resposta = _disputa(_lado("O governo defende a medida.", ["o governo"], VEICULOS, trecho=DA_AB),
                        _lado("Criticam a medida.", [], VEICULOS, grupos=["especialistas"], trecho=DA_CARTA))
    chamada = Chamada(resposta)
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.lados == EMERGENCIA and analise.questao == "" and analise.problemas == [] and len(chamada.recebido) == 1
    assert analise.ressalvas == [] and analise.descartadas == [
        (Ressalva(("o governo",), "O governo defende a medida.", ("Agência Brasil", "CartaCapital"), DA_AB), "nenhum lado tem ator nomeado"),
        (Ressalva(("especialistas",), "Criticam a medida.", ("Agência Brasil", "CartaCapital"), DA_CARTA), "nenhum lado tem ator nomeado"),
    ]
    assert analise.ajustes == ["ator genérico do lado 1 passou a grupo (o governo)",
                               "nenhum lado com ator nomeado: a pauta fica com o lado neutro, sem ressalvas"]


def test_a_questao_so_fica_com_dois_lados_nomeados_ou_mais():
    # um lado nomeado, com ou sem ressalva: a questão sai, sem recusa
    um = analise_da_resposta(_com_evidencias({"questao": "A Meta favoreceu um candidato?", "lados": [_lado(veiculos=VEICULOS, resposta="Não")]}), TEXTOS)
    assert um.problemas == [] and um.questao == "" and [(lado.atores, lado.resposta) for lado in um.lados] == [(("Meta",), "")]
    # dois lados nomeados e uma ressalva: a questão fica
    tres = analise_da_resposta(_disputa(_lado("A Meta nega.", ["Meta"]), _lado("Veem risco.", ["críticos"], VEICULOS, trecho=DA_AB),
                                        _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"])), TEXTOS)
    assert tres.questao == "A Meta favoreceu um candidato?" and [lado.resposta for lado in tres.lados] == ["Resposta 1", "Resposta 3"]
    assert [r.grupos for r in tres.ressalvas] == [("críticos",)] and tres.problemas == []


def test_os_lados_nomeados_ainda_passam_pela_validacao():
    # quatro lados, um deles só de grupo: ficam três lados e uma ressalva, e a resposta vale
    quatro = _disputa(*(_lado(atores=[a], veiculos=VEICULOS, trecho=DA_AB) for a in ("Meta", "PT", "analistas", "TSE")))
    analise = analise_da_resposta(quatro, TEXTOS)
    assert len(analise.lados) == 3 and len(analise.ressalvas) == 1 and analise.problemas == []
    # o número do lado na mensagem é o da resposta do LLM
    repetido = _disputa(_lado(atores=["fontes"], veiculos=VEICULOS), _lado(atores=["Meta", "Lula"], veiculos=VEICULOS),
                        _lado(atores=["campanha de Lula"], veiculos=VEICULOS))
    assert analise_da_resposta(repetido, TEXTOS).problemas == ["lado 3 sem ator que não esteja em outro lado"]


# ── A chamada ─────────────────────────────────────────────────────────────────────────────

def test_a_chamada_leva_os_textos_com_veiculo_e_titulo_e_temperatura_baixa():
    chamada = Chamada(DOIS_LADOS)
    analisar_lados(chamada, TEXTOS)
    [(system, user, opcoes)] = chamada.recebido
    assert system == PROMPT_LADOS
    assert user == entrada_dos_lados(TEXTOS) == (
        "TEXTO 1\nVeículo: Agência Brasil\nTítulo: Meta alega problemas técnicos\nTexto:\n"
        "A Meta respondeu às acusações da campanha e negou favorecimento.\n\n"
        "TEXTO 2\nVeículo: CartaCapital\nTítulo: Campanha de Lula acusa Meta\nTexto:\n"
        "A campanha acusou a empresa de favorecer um candidato.\n\n"
        "VEÍCULOS DA PAUTA: Agência Brasil, CartaCapital"
    )
    assert opcoes == {"chaves": ("lados",), "temperatura": 0.1, "max_saida": modulo.MAX_SAIDA_LADOS}


def test_o_prompt_pede_a_questao_antes_dos_lados():
    assert (PROMPT_LADOS.index('{"questao":') < PROMPT_LADOS.index('"respostas_por_ator": [{"ator":')
            < PROMPT_LADOS.index('"lados": [{"resposta":') < PROMPT_LADOS.index('"motivo":'))
    # a questão é a do fato novo, e a ressalva traz o grupo e um trecho literal
    assert "A questão trata do FATO NOVO da pauta" in PROMPT_LADOS and "são contexto, não a questão" in PROMPT_LADOS
    assert "outra questão em que atores nomeados tomam posições opostas" in PROMPT_LADOS
    assert '"trecho": "<só na ressalva: trecho literal do texto>"' in PROMPT_LADOS
    assert "posição sem ator nem grupo não entra" in PROMPT_LADOS


# ── Os textos inteiros e o espaço da chamada ──────────────────────────────────────────────

LONGOS = [
    {"fonte": "Agência Brasil", "titulo": "Meta alega problemas técnicos",
     "texto": "\n".join([("Um parágrafo de contexto sobre a eleição. " * 5).strip()] * 8 + ["No fim, a Meta negou o favorecimento apontado."])},
    {"fonte": "CartaCapital", "titulo": "Campanha de Lula acusa Meta",
     "texto": "\n".join([("Outro parágrafo de contexto, bem comprido. " * 5).strip()] * 4 + ["No fim, a campanha de Lula acusou a empresa."])},
]


def test_os_textos_so_sao_cortados_se_a_entrada_passa_do_espaco_da_chamada():
    inteira = entrada_dos_lados(LONGOS)
    assert textos_que_cabem(LONGOS, None) == textos_que_cabem(LONGOS, len(inteira)) == (LONGOS, [])
    lidos, cortes = textos_que_cabem(LONGOS, len(inteira) - 1000)
    assert len(entrada_dos_lados(lidos)) <= len(inteira) - 1000
    assert cortes == [{"fonte": t["fonte"], "texto": len(t["texto"]), "lido": len(lido["texto"])} for t, lido in zip(LONGOS, lidos)]
    for inteiro, lido in zip(LONGOS, lidos):                         # cada um perde na proporção do tamanho, em fim de parágrafo
        assert inteiro["texto"].startswith(lido["texto"] + "\n") and 0.4 < len(lido["texto"]) / len(inteiro["texto"]) < 0.8


def test_o_trecho_e_conferido_no_texto_inteiro_mesmo_quando_a_chamada_leu_um_corte(caplog):
    resposta = {"questao": "A Meta favoreceu um candidato?", "respostas_por_ator": [
        _evidencia("campanha de Lula", "Sim", "a campanha de Lula acusou a empresa", "CartaCapital"),
        _evidencia("Meta", "Não", "a Meta negou o favorecimento apontado"),
    ], "lados": [_lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"], "Sim"), _lado("A Meta nega.", ["Meta"], resposta="Não")]}
    chamada = Chamada(resposta)
    limite = len(entrada_dos_lados(LONGOS)) - 1000
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, LONGOS, limite)
    [(_, lida, _)] = chamada.recebido
    assert len(lida) <= limite and "a Meta negou o favorecimento" not in lida      # o fim dos textos ficou fora da chamada
    assert len(analise.lados) == 2 and all(e.comprovada for e in analise.respostas)
    assert [c["fonte"] for c in analise.cortes] == ["Agência Brasil", "CartaCapital"]
    assert "os textos não cabem inteiros na chamada e foram cortados (Agência Brasil: " in caplog.text
    assert analisar_lados(Chamada(resposta), LONGOS, len(entrada_dos_lados(LONGOS))).cortes == []   # cabendo, vão inteiros e sem aviso


def test_a_nova_tentativa_cabe_no_mesmo_espaco():
    chamada = Chamada({"lados": []}, UM_LADO)
    limite = len(entrada_dos_lados(LONGOS))
    analise = analisar_lados(chamada, LONGOS, limite)
    (_, primeira, _), (_, segunda, _) = chamada.recebido
    assert len(primeira) == limite and len(segunda) <= limite                    # o pedido de correção toma o lugar de texto
    assert segunda.endswith("\n\n" + pedido_de_correcao(analise.primeira)) and analise.cortes and not analise.primeira.cortes


# ── Ator sem entrada em respostas_por_ator ────────────────────────────────────────────────

SEM_A_CAMPANHA = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não"))
COM_A_CAMPANHA = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não"),
                        _evidencia("campanha de Flávio Bolsonaro", "Não", DA_CARTA, "CartaCapital"))


def test_ator_sem_entrada_ganha_nova_tentativa_que_pede_a_entrada_dele(caplog):
    chamada = Chamada(SEM_A_CAMPANHA, COM_A_CAMPANHA)
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques",), ("Lula", "campanha de Flávio Bolsonaro")]
    assert analise.faltam == [] and analise.ajustes == [] and analise.resposta is COM_A_CAMPANHA and analise.segunda is None
    assert analise.primeira.faltam == ["campanha de Flávio Bolsonaro"] and analise.primeira.problemas == []
    (_, primeira, _), (_, segunda, _) = chamada.recebido
    assert segunda == primeira + "\n\n" + pedido_das_respostas(analise.primeira) == primeira + (
        '\n\nCORREÇÃO: na sua resposta anterior, estes atores estão num lado e não têm entrada em "respostas_por_ator": '
        "campanha de Flávio Bolsonaro.\nResposta anterior: " + json.dumps(SEM_A_CAMPANHA, ensure_ascii=False) + "\n"
        + modulo.LEMBRETE_DAS_RESPOSTAS
    )
    assert 'ator sem entrada em "respostas_por_ator" (campanha de Flávio Bolsonaro). Nova tentativa, pedindo a entrada.' in caplog.text


def test_se_a_entrada_do_ator_nao_vem_ele_sai_e_nao_ha_terceira_tentativa():
    chamada = Chamada(SEM_A_CAMPANHA)                                  # a nova tentativa repete a resposta, sem a entrada
    analise = analisar_lados(chamada, TEXTOS)
    assert len(chamada.recebido) == 2 and analise.problemas == []
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques",), ("Lula",)]
    assert analise.faltam == ["campanha de Flávio Bolsonaro"] and analise.primeira.faltam == analise.faltam


def test_se_a_nova_tentativa_nao_vale_fica_a_primeira_resposta_sem_o_ator(caplog):
    for segunda in (QUATRO_LADOS, ValueError("Modelo retornou resposta VAZIA.")):
        chamada = Chamada(SEM_A_CAMPANHA, segunda)
        with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
            analise = analisar_lados(chamada, TEXTOS)
        assert [lado.atores for lado in analise.lados] == [("Nunes Marques",), ("Lula",)] and analise.problemas == []
        assert analise.resposta is SEM_A_CAMPANHA and analise.primeira is None and analise.segunda.problemas
        assert "a nova tentativa não valeu" in caplog.text and "Fica a primeira resposta, sem o ator." in caplog.text


def test_o_verbo_de_outro_ator_depois_do_ponto_e_virgula_nao_vale():
    # como no N27 de 23/10/2026: o "defende" do Flávio, no mesmo título, valia para o trecho do Lula
    titulo = [{"fonte": VILA, "titulo": "Cooperativa Raízes do Campo quer fechar a feira; Associação dos Feirantes defende a praça",
               "texto": "Um texto qualquer sobre a feira de domingo e o bairro."}]
    assert modulo.frase_do_trecho("Cooperativa Raízes do Campo quer fechar a feira", titulo, VILA) == (
        "cooperativa raízes do campo quer fechar a feira;")
    assert modulo.traz_a_resposta("Cooperativa Raízes do Campo", "Cooperativa Raízes do Campo quer fechar a feira", titulo, VILA) == ""
    assert modulo.traz_a_resposta("Associação dos Feirantes", "Associação dos Feirantes defende a praça", titulo, VILA) == (
        "verbo de posição no trecho (defende)")
    # o trecho que atravessa o ponto e vírgula fica com as duas partes
    assert modulo.frase_do_trecho("a feira; Associação dos Feirantes", titulo, VILA) == (
        "cooperativa raízes do campo quer fechar a feira; associação dos feirantes defende a praça")


def test_a_questao_da_disputa_e_de_sim_ou_nao():
    feira = {"respostas_por_ator": [
        _evidencia("Cooperativa Raízes do Campo", "Fechar", "A Cooperativa Raízes do Campo decidiu fechar a feira de domingo", VILA),
        _evidencia("Associação dos Feirantes", "Manter", "Fechar agora é abandonar quem produz", VILA),
    ], "lados": [_lado("Fecha.", ["Cooperativa Raízes do Campo"], [VILA], "Fechar"),
                 _lado("Mantém.", ["Associação dos Feirantes"], [VILA], "Manter")]}
    # a questão aberta leva ao lado neutro, sem ressalvas e sem nova tentativa, com qualquer número de lados
    alerta = _lado("A feira pode fechar de vez.", [], [VILA], grupos=["economistas"], trecho="A feira sustenta duzentas famílias")
    for aberta in ("Qual deve ser o destino da feira?", "O que fazer com a feira?", "Como fica a feira de domingo?", "quem decide?"):
        analise = analise_da_resposta({**feira, "questao": aberta, "lados": [*feira["lados"], alerta]}, FEIRA)
        assert analise.problemas == [] and analise.lados == lado_unico([VILA]) and analise.ressalvas == [], aberta
        assert analise.ajustes == [f'questão que não é de sim ou não ("{aberta}"): a pauta fica com o lado neutro, sem ressalvas']
        assert [motivo for _, motivo in analise.descartadas] == ["a questão não é de sim ou não"]
    assert analise_da_resposta({**feira, "questao": "A feira deve fechar?"}, FEIRA).lados[0].atores == ("Cooperativa Raízes do Campo",)
    # como no N27 de 24/10/2026: a conferência tirou um dos dois atores, e o lado único ficaria só com o outro
    um = {**feira, "questao": "Qual deve ser o destino da feira?", "lados": feira["lados"][:1]}
    assert analise_da_resposta(um, FEIRA).lados == lado_unico([VILA])
    chamada = Chamada({**feira, "questao": "Qual deve ser o destino da feira?"})
    assert analisar_lados(chamada, FEIRA).lados == lado_unico([VILA]) and len(chamada.recebido) == 1


def test_com_um_lado_so_o_trecho_basta_estar_no_texto():
    # como no A14 de 23/10/2026: "a OpenAI admitiu..." não traz resposta, mas não havia disputa a inventar
    um = {"questao": "A feira deve fechar?", "respostas_por_ator": [
        _evidencia("Associação dos Feirantes", "Não", PROTESTOU, VILA)],
        "lados": [_lado("Os feirantes protestam.", ["Associação dos Feirantes"], [VILA], "Não")]}
    analise = analise_da_resposta(um, FEIRA)
    assert [lado.atores for lado in analise.lados] == [("Associação dos Feirantes",)] and analise.recusados == []
    assert analise.ajustes == ["trecho de Associação dos Feirantes vale sem trazer a resposta: com um lado só com ator nomeado, "
                               "não há disputa a conferir"]
    assert analisar_lados(Chamada(um), FEIRA).primeira is None                # sem recusado, sem nova tentativa
    # o trecho que não está no texto continua recusado
    fora = {**um, "respostas_por_ator": [_evidencia("Associação dos Feirantes", "Não", "Os feirantes ocuparam a prefeitura ontem", VILA)]}
    assert [r.ator for r in analise_da_resposta(fora, FEIRA).recusados] == ["Associação dos Feirantes"]
    # com dois lados nomeados, a conferência vale (o caso de test_ator_cujo_trecho_nao_traz_a_resposta_sai...)
    assert analise_da_resposta(_feira(), FEIRA).recusados


# ── Ator cujo trecho não vale: a mesma nova tentativa ─────────────────────────────────────

PROTESTOU = "A Associação dos Feirantes protestou na porta da sede"


def _feira(trecho_da_associacao=PROTESTOU, *, com_marta=False) -> dict:
    entradas = [_evidencia("Cooperativa Raízes do Campo", "Sim", "A Cooperativa Raízes do Campo decidiu fechar a feira de domingo", VILA),
                _evidencia("Associação dos Feirantes", "Não", trecho_da_associacao, VILA)]
    atores_do_nao = ["Associação dos Feirantes", "Marta Quaresma"] if com_marta else ["Associação dos Feirantes"]
    return {"questao": "A feira deve fechar?", "respostas_por_ator": entradas,
            "lados": [_lado("Fecha.", ["Cooperativa Raízes do Campo"], [VILA], "Sim"), _lado("Não fecha.", atores_do_nao, [VILA], "Não")]}


def test_ator_cujo_trecho_nao_vale_ganha_nova_tentativa_com_o_trecho_e_o_motivo(caplog):
    corrigida = _feira("Fechar agora é abandonar quem produz")
    chamada = Chamada(_feira(), corrigida)
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, FEIRA)
    assert [lado.atores for lado in analise.lados] == [("Cooperativa Raízes do Campo",), ("Associação dos Feirantes",)]
    assert analise.resposta is corrigida and analise.recusados == [] and analise.primeira.recusados and analise.segunda is None
    (_, primeira, _), (_, segunda, _) = chamada.recebido
    motivo = "o trecho não traz a resposta dele (sem verbo de posição, citação direta, decisão dele nem marcador de atribuição)"
    assert segunda == primeira + "\n\n" + pedido_das_respostas(analise.primeira) == primeira + (
        "\n\nCORREÇÃO: na sua resposta anterior, o trecho destes atores não comprova a resposta deles:\n"
        f'- Associação dos Feirantes: "{PROTESTOU}" ({motivo}).\n'
        "Resposta anterior: " + json.dumps(_feira(), ensure_ascii=False) + "\n" + modulo.LEMBRETE_DAS_RESPOSTAS
    )
    assert "a frase em que o texto traz essa resposta" in modulo.LEMBRETE_DAS_RESPOSTAS
    assert "ator com trecho que não vale (Associação dos Feirantes: o trecho não traz a resposta dele" in caplog.text


def test_o_pedido_junta_o_ator_sem_entrada_e_o_de_trecho_recusado():
    analise = analise_da_resposta(_feira(com_marta=True), FEIRA)
    assert analise.faltam == ["Marta Quaresma"] and [r.ator for r in analise.recusados] == ["Associação dos Feirantes"]
    pedido = pedido_das_respostas(analise)
    assert pedido.startswith('CORREÇÃO: na sua resposta anterior, estes atores estão num lado e não têm entrada em '
                             '"respostas_por_ator": Marta Quaresma.\nAlém disso: na sua resposta anterior, o trecho destes '
                             f'atores não comprova a resposta deles:\n- Associação dos Feirantes: "{PROTESTOU}"')
    chamada = Chamada(_feira(com_marta=True))                              # uma vaga só: a mesma nova tentativa para os dois
    analisar_lados(chamada, FEIRA)
    assert len(chamada.recebido) == 2


def test_se_o_trecho_continua_sem_valer_o_ator_sai_e_nao_ha_terceira_tentativa():
    chamada = Chamada(_feira())                                            # a nova tentativa repete o mesmo trecho
    analise = analisar_lados(chamada, FEIRA)
    assert len(chamada.recebido) == 2 and analise.problemas == [] and analise.questao == ""
    assert [lado.atores for lado in analise.lados] == [("Cooperativa Raízes do Campo",)] and analise.recusados


def test_se_a_nova_tentativa_pelo_trecho_nao_vale_fica_a_primeira():
    chamada = Chamada(_feira(), {"lados": []})
    analise = analisar_lados(chamada, FEIRA)
    assert analise.resposta == _feira() and analise.segunda.problemas and analise.primeira is None
    assert [lado.atores for lado in analise.lados] == [("Cooperativa Raízes do Campo",)]


def test_resposta_invalida_usa_a_vaga_e_nao_ha_tentativa_pelo_trecho():
    # a vaga é uma por análise: depois da correção de uma resposta inválida, o trecho recusado não pede outra
    chamada = Chamada({"lados": []}, _feira())
    analise = analisar_lados(chamada, FEIRA)
    assert len(chamada.recebido) == 2 and analise.recusados and analise.primeira.problemas


# ── As respostas de sim ou não ────────────────────────────────────────────────────────────

def _descritiva(do_lado_1="Uma acusação", do_lado_2="Uma defesa") -> dict:
    """DOIS_LADOS com respostas que não são "Sim" e "Não", como no A63 de 17/10/2026 ("Não vamos aceitar..." × "Sim")."""
    def resposta(ator):
        return do_lado_2 if ator == "Meta" else do_lado_1
    return {**DOIS_LADOS, "respostas_por_ator": [{**e, "resposta": resposta(e["ator"])} for e in DOIS_LADOS["respostas_por_ator"]],
            "lados": [{**DOIS_LADOS["lados"][0], "resposta": do_lado_1}, {**DOIS_LADOS["lados"][1], "resposta": do_lado_2}]}


def test_numa_disputa_de_dois_lados_as_respostas_sao_sim_e_nao():
    assert analise_da_resposta(DOIS_LADOS, TEXTOS).sem_sim_e_nao == ""     # "Sim" e "Não." valem: caixa e ponto final não contam
    analise = analise_da_resposta(_descritiva(), TEXTOS)
    assert analise.problemas == [] and len(analise.lados) == 2            # a análise vale: a regra só pede a nova tentativa
    assert analise.sem_sim_e_nao == ('as respostas dos lados são "Uma acusação" e "Uma defesa": numa disputa de dois lados, '
                                     'são "Sim" e "Não", opostas')
    assert analise_da_resposta(_descritiva("Não vamos aceitar a interferência", "Sim"), TEXTOS).sem_sim_e_nao
    # com um lado ou com três, a regra não vale
    assert analise_da_resposta(UM_LADO, TEXTOS).sem_sim_e_nao == ""
    tres = _disputa(*(_lado(atores=[a], veiculos=VEICULOS) for a in ("Meta", "PT", "Lula")))
    assert len(analise_da_resposta(tres, TEXTOS).lados) == 3 and analise_da_resposta(tres, TEXTOS).sem_sim_e_nao == ""


def test_sem_sim_e_nao_a_nova_tentativa_pede_as_duas_e_fica_se_trouxer():
    chamada = Chamada(_descritiva(), DOIS_LADOS)
    analise = analisar_lados(chamada, TEXTOS)
    assert len(chamada.recebido) == 2 and analise.resposta == DOIS_LADOS and analise.sem_sim_e_nao == ""
    assert analise.primeira.sem_sim_e_nao and analise.segunda is None
    pedido = chamada.recebido[1][1]
    assert 'CORREÇÃO: na sua resposta anterior, as respostas dos lados são "Uma acusação" e "Uma defesa"' in pedido
    assert pedido.endswith(modulo.LEMBRETE_DO_SIM_E_NAO) and modulo.LEMBRETE_DAS_RESPOSTAS not in pedido
    assert '"Sim" se o trecho dele afirma o que a questão pergunta, "Não" se o trecho dele nega' in pedido


@pytest.mark.parametrize("nova", [
    {"lados": []},                                       # a nova não vale
    ValueError("resposta cortada"),                      # a chamada falha
    "descritiva",                                        # vale, mas continua sem "Sim" e "Não"
    UM_LADO,                                             # vale, mas sem disputa
])
def test_se_a_nova_tentativa_nao_traz_sim_e_nao_em_dois_lados_fica_a_primeira(nova):
    primeira = _descritiva()
    chamada = Chamada(primeira, _descritiva("Acusa", "Nega") if nova == "descritiva" else nova)
    analise = analisar_lados(chamada, TEXTOS)
    assert len(chamada.recebido) == 2 and analise.resposta == primeira and analise.segunda is not None
    assert len(analise.lados) == 2 and analise.problemas == [] and analise.sem_sim_e_nao   # a regra não derruba a primeira


def test_o_pedido_junta_as_entradas_que_faltam_e_o_sim_e_nao():
    sem_entrada = _descritiva()
    sem_entrada = {**sem_entrada, "respostas_por_ator": [e for e in sem_entrada["respostas_por_ator"] if e["ator"] != "PT"]}
    analise = analise_da_resposta(sem_entrada, TEXTOS)
    assert analise.faltam == ["PT"] and analise.sem_sim_e_nao
    pedido = pedido_das_respostas(analise)
    assert "não têm entrada em \"respostas_por_ator\": PT." in pedido
    assert 'Além disso: na sua resposta anterior, as respostas dos lados são "Uma acusação" e "Uma defesa"' in pedido
    assert pedido.endswith(f"{modulo.LEMBRETE_DAS_RESPOSTAS} {modulo.REGRA_DO_SIM_E_NAO}")
    # com "Sim" e "Não" já na primeira, a nova tentativa pelas entradas fica como antes, mesmo sem "Sim" e "Não"
    so_falta = {**DOIS_LADOS, "respostas_por_ator": [e for e in DOIS_LADOS["respostas_por_ator"] if e["ator"] != "PT"]}
    chamada = Chamada(so_falta, _descritiva())
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.resposta == _descritiva() and analise.primeira.faltam == ["PT"] and analise.sem_sim_e_nao


def test_o_prompt_diz_que_estrategias_diferentes_nao_criam_disputa():
    # como no N69 de 17/10/2026: a decisão de outra empresa sobre o próprio negócio virou o lado "Sim"
    assert "estratégias, planos ou decisões diferentes de atores diferentes, cada um sobre o próprio negócio" in PROMPT_LADOS
    assert "esse lado precisaria de um ator que afirme que a Rede Sul vai suspender a linha" in PROMPT_LADOS


# ── O bloco da entrada ────────────────────────────────────────────────────────────────────

def test_bloco_diz_a_questao_os_lados_o_elenco_exato_e_o_alvo_de_palavras():
    analise = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    sem_contar = bloco_dos_lados(analise.lados, analise.questao)
    assert "lado fino" not in sem_contar                                # antes da contagem das menções, nenhum lado é fino
    analise.lados = com_mencoes(analise.lados, TEXTOS)
    # a reserva é o tamanho do bloco com todos os lados finos: cobre o bloco antes e depois da contagem
    assert reserva_do_bloco(analise.lados, analise.questao) >= len(bloco_dos_lados(analise.lados, analise.questao)) > len(sem_contar)
    assert bloco_dos_lados(analise.lados, analise.questao) == (
        "\nLADOS DA PAUTA: 2 lados.\n"
        "QUESTÃO: A Meta favoreceu um candidato?\n"
        "Lado 1 (resposta: Sim; lado fino): A campanha acusa a Meta. Atores: campanha de Lula, PT. Veículos: Agência Brasil, CartaCapital.\n"
        "Lado 2 (resposta: Não): A Meta nega. Atores: Meta. Veículos: Agência Brasil.\n"
        'ELENCO: Helena e exatamente 2 analistas, um por lado: Otávio, do lado 1, e Patrícia, do lado 2; "houve_divergencia": '
        "true. Helena apresenta a questão "
        "uma vez, na abertura, com palavras naturais, e não atribui as posições aos atores; cada analista sustenta a "
        "posição do seu lado, numa frase que nomeia um ator do lado, cita um veículo do lado e usa um verbo de posição, "
        'como em "segundo <veículo>, <ator> afirma que...". Lado fino tem pouco material nas fontes: o analista dele não '
        "amplia além do que as fontes trazem. Alvo de palavras: Helena, 290; Otávio (lado 1), 90; Patrícia (lado 2), "
        "270; total, 650. Plano das falas: Helena, 4 falas de uns 75 palavras; Otávio, 2 falas de uns 45; "
        "Patrícia, 3 falas de uns 90. Ordem dos 9 turnos: Helena, Otávio, Patrícia, Helena, Otávio, Patrícia, Helena, "
        "Patrícia, Helena."
    )   # sem as palavras do texto, o total seria o de antes, mas os lados têm 1 e 3 frases: 90 palavras por frase, no máximo
    sem_fino = [Lado("A campanha acusa.", ("PT",), ("G1",), "Sim", ("um trecho", "outro trecho")), Lado("A Meta nega.", ("Meta",), ("G1",), "Não")]
    assert "lado fino" not in bloco_dos_lados(sem_fino, "Q?")
    assert bloco_dos_lados(sem_fino, "Q?").endswith(
        "Alvo de palavras: Helena, 380; Otávio (lado 1), 350; Patrícia (lado 2), 350; total, 1080. Plano das falas: Helena, "
        "5 falas de uns 75 palavras; Otávio, 4 falas de uns 90; Patrícia, 4 falas de uns 90. Ordem dos 13 turnos: Helena, "
        "Otávio, Patrícia, Helena, Otávio, Patrícia, Helena, Otávio, Patrícia, Helena, Otávio, Patrícia, Helena.")
    um = analise_da_resposta(UM_LADO, TEXTOS)
    assert reserva_do_bloco(um.lados) >= len(bloco_dos_lados(um.lados))  # a reserva cobre o orçamento com os números mais compridos
    assert bloco_dos_lados(um.lados, um.questao) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: Uma posição. Atores: Meta. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, Otávio, que explica o tema com ela, sem advogar; "houve_divergencia": false. '
        "Alvo de palavras: Helena, 350; Otávio, 430; total, 780. Plano das falas: Helena, 6 falas de uns 60 palavras; "
        "Otávio, 5 falas de uns 85. Ordem dos 11 turnos: Helena, Otávio, Helena, Otávio, Helena, Otávio, Helena, "
        "Otávio, Helena, Otávio, Helena."
    )
    # com o orçamento da pauta, o bloco pede menos e avisa que o material é pouco
    curto = bloco_dos_lados(um.lados, um.questao, (), orcamento(um.lados, 201))
    assert curto.endswith("Alvo de palavras: Helena, 160; Otávio, 190; total, 350. Plano das falas: Helena, 4 falas de uns 40 "
                          "palavras; Otávio, 3 falas de uns 65. Ordem dos 7 turnos: Helena, Otávio, Helena, Otávio, Helena, "
                          "Otávio, Helena. Os textos trazem pouco material, e o alvo já é menor: cumpra-o com o que as fontes "
                          "trazem, sem argumento novo.")
    # o lado fino fica com o mínimo de falas, e o plano diz o tamanho de cada personagem
    dois = [Lado("p", ("Ator A",), ("G1",), "Sim", (), 1), Lado("p", ("Ator B",), ("G1",), "Não", (), 6)]
    assert ("Plano das falas: Helena, 3 falas de uns 50 palavras; Otávio, 2 falas de uns 45; Patrícia, 2 "
            "falas de uns 75. Ordem dos 7 turnos: Helena, Otávio, Patrícia, Helena, Otávio, Patrícia, Helena.") in bloco_dos_lados(
        dois, "Q?", (), orcamento(dois, 239))
    assert reserva_do_bloco(um.lados) >= len(curto)
    tres = [Lado("p", (f"Ator {i}",), ("G1",), f"Resposta {i}") for i in range(3)]
    assert ("exatamente 3 analistas, um por lado: Otávio, do lado 1, Patrícia, do lado 2, e Vinícius, do lado 3;" in bloco_dos_lados(tres, "Q?")
            and "Vinícius (lado 3), 250; total, 1150" in bloco_dos_lados(tres, "Q?"))


def test_bloco_traz_as_ressalvas_logo_depois_dos_lados():
    lados = [Lado("Flávio propõe flexibilizar o Mercosul.", ("Flávio Bolsonaro", "Milei"), ("Gazeta do Povo",))]
    ressalvas = [Ressalva(("economistas",), ALERTA, ("Gazeta do Povo",)), Ressalva((), "Há risco fiscal", ("Gazeta do Povo",))]
    assert bloco_dos_lados(lados, "", ressalvas) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: Flávio propõe flexibilizar o Mercosul. Atores: Flávio Bolsonaro, Milei. Veículos: Gazeta do Povo.\n"
        "Ressalva 1: A flexibilização pode enfraquecer a tarifa comum. Grupos: economistas. Veículos: Gazeta do Povo.\n"
        "Ressalva 2: Há risco fiscal. Veículos: Gazeta do Povo.\n"
        "ELENCO: Helena e exatamente 1 analista, Otávio, que explica a posição e responde às ressalvas com o que as fontes dizem, "
        'sem tomar partido; "houve_divergencia": false. Ressalva não é lado nem ganha analista: Helena traz cada uma como '
        "pergunta atribuída, sem avaliá-la nem reformulá-la, numa frase com o veículo, o grupo e um verbo de posição, "
        'seguida de uma pergunta aberta, como em "Segundo <veículo>, <grupo> alertam que... Como você vê isso?". '
        "Alvo de palavras: Helena, 350; Otávio, 430; total, 780. Plano das falas: Helena, 6 falas de uns 60 palavras; "
        "Otávio, 5 falas de uns 85. Ordem dos 11 turnos: Helena, Otávio, Helena, Otávio, Helena, Otávio, Helena, "
        "Otávio, Helena, Otávio, Helena."
    )
    dois = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    com_ressalva = bloco_dos_lados(dois.lados, dois.questao, ressalvas[:1])
    assert "Veículos: Agência Brasil.\nRessalva 1: A flexibilização" in com_ressalva                   # depois do último lado
    assert "Ressalva não é lado nem ganha analista: Helena traz cada uma" in com_ressalva


def test_bloco_do_lado_neutro_leva_a_posicao_e_os_veiculos():
    assert bloco_dos_lados(lado_unico(VEICULOS)) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: relato dos fatos, sem lados definidos. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, Otávio, que explica o tema com ela, sem advogar; "houve_divergencia": false. '
        "Alvo de palavras: Helena, 350; Otávio, 430; total, 780. Plano das falas: Helena, 6 falas de uns 60 palavras; "
        "Otávio, 5 falas de uns 85. Ordem dos 11 turnos: Helena, Otávio, Helena, Otávio, Helena, Otávio, Helena, "
        "Otávio, Helena, Otávio, Helena."
    )


def test_bloco_nunca_passa_do_espaco_reservado():
    longos = [Lado("Posição muito comprida. " * 40, ("Ator Um", "Ator Dois", "Ator Três"), ("O GLOBO", "G1", "Agência Brasil"),
                   "Uma resposta comprida demais para caber inteira no bloco de lados da pauta. " * 3) for _ in range(3)]
    bloco = bloco_dos_lados(longos, "Uma questão comprida demais? " * 20)
    # as posições encolhem até o mínimo; o que ainda não cabe sai do fim da última linha, e o elenco, com o plano, fica
    assert len(bloco) == modulo.MAX_BLOCO and "Ordem dos 13 turnos: Helena, Otávio, Patrícia, Vinícius, Helena" in bloco
    assert reserva_do_bloco(longos, "Uma questão comprida demais? " * 20) == modulo.MAX_BLOCO                        # a reserva nunca passa do teto do bloco
    assert all(f"Lado {i} (resposta: Uma resposta comprida" in bloco and "): Posição muito comprida." in bloco for i in (1, 2, 3))

    exagerados = [Lado("Posição.", tuple(f"Ator de nome bem comprido número {i}" for i in range(30)), ("G1",), "Sim") for _ in range(3)]
    cortado = bloco_dos_lados(exagerados, "O canal deve ser suspenso?")
    assert len(cortado) <= modulo.MAX_BLOCO
    assert cortado.startswith("\nLADOS DA PAUTA: 3 lados.\nQUESTÃO: O canal deve ser suspenso?\nELENCO: Helena e exatamente 3 analistas")   # o elenco nunca é cortado

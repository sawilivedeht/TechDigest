"""Testes de ai/lados.py sem LLM: a validação da resposta, as respostas por ator, as ressalvas, a nova tentativa, o lado
neutro e o bloco da entrada."""
import json
import logging

import pytest

from techdigest.ai import lados as modulo
from techdigest.ai.lados import (
    Evidencia, Lado, Ressalva, analisar_lados, analise_da_resposta, ator_generico, bloco_dos_lados, entrada_dos_lados,
    lado_unico, lados_finos, pedido_de_correcao,
)
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


def _lado(posicao="Uma posição.", atores=("Meta",), veiculos=("Agência Brasil",), resposta=None, grupos=None) -> dict:
    lado = {"posicao": posicao, "atores": list(atores), "veiculos": list(veiculos)}
    if grupos is not None:
        lado["grupos"] = list(grupos)
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
    assert analise.respostas == [
        Evidencia("campanha de Lula", "Sim", DA_CARTA, "cartacapital", True), Evidencia("PT", "sim", DA_AB, "Agência Brasil", True),
        Evidencia("Meta", "Não", DA_AB, "Agência Brasil", True),
    ]
    assert analise.motivo == "Acusação contra defesa." and analise.problemas == []
    assert analise.primeira is None and len(chamada.recebido) == 1          # resposta válida não pede nova tentativa


def test_sem_disputa_a_questao_fica_vazia_e_ha_um_lado_so():
    assert analise_da_resposta(UM_LADO, TEXTOS).problemas == []
    so_os_lados = {"lados": [_lado(veiculos=VEICULOS, resposta="Sim")]}       # sem a chave da questão é o mesmo que questão vazia
    analise = analise_da_resposta(so_os_lados, TEXTOS)
    assert analise.lados == [Lado("Uma posição.", ("Meta",), ("Agência Brasil", "CartaCapital"))] and analise.questao == ""


@pytest.mark.parametrize("resposta, problema", [
    (QUATRO_LADOS, "resposta com 4 lados (vale de 1 a 3)"),
    ({"lados": []}, "resposta com 0 lados (vale de 1 a 3)"),
    ({"lados": "dois"}, "resposta sem a lista de lados"),
    (_disputa(_lado(atores=["Lula"], veiculos=VEICULOS), _lado(atores=["campanha de Lula"], veiculos=VEICULOS)),
     "lado 1 sem ator que não esteja em outro lado"),                                      # um nome dentro do outro é o mesmo ator
    (_disputa(_lado(veiculos=["Agência Brasil", "Folha de S.Paulo"]), _lado(atores=["PT"], veiculos=["CartaCapital"])),
     "lado 1 com veículo fora da pauta (Folha de S.Paulo)"),
    (_disputa(_lado(), _lado(atores=["PT"])), "veículo da pauta em nenhum lado (CartaCapital)"),
    ({"lados": [_lado(posicao=" ", veiculos=VEICULOS)]}, "lado 1 sem posição"),
    ({"lados": [{**_lado(veiculos=VEICULOS), "atores": "Meta"}]}, 'lado 1 com "atores" fora do formato (é uma lista de nomes)'),
    ({"lados": [_lado(veiculos=VEICULOS, grupos=[1])]}, 'lado 1 com "grupos" fora do formato (é uma lista de nomes)'),
    ({"lados": [_lado(veiculos=[])]}, "lado 1 sem veículo"),
    # cada ressalva precisa de pelo menos um veículo da pauta
    ({"lados": [_lado(veiculos=VEICULOS), _lado(atores=[], veiculos=[], grupos=["economistas"])]}, "lado 2 sem veículo"),
    ({"lados": [_lado(veiculos=VEICULOS), _lado(atores=[], veiculos=["Folha"], grupos=["economistas"])]},
     "lado 2 com veículo fora da pauta (Folha)"),
    ({"lados": ["Meta contra Lula"]}, "lado 1 não é um objeto"),
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
    assert len(pedido_de_correcao(analise_da_resposta(comprida, TEXTOS))) < modulo.MAX_ANTERIOR + 500


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
    "comandante do Corpo de Bombeiros do Amazonas", "economistas do Ipea",
])
def test_nome_ou_designacao_com_qualificador_nao_e_generico(ator):
    assert not ator_generico(ator)


def test_termos_genericos_vao_sem_acento_e_em_minusculas():
    assert all(termo == termo.lower() and termo.isascii() for termo in modulo.TERMOS_GENERICOS)
    assert {"economistas", "especialistas", "analistas", "criticos", "observadores", "governo", "empresa"} <= modulo.TERMOS_GENERICOS


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
    # o trecho de Lula não está no texto e nenhum lado responde "Talvez": o lado 2 fica sem ator e vira ressalva
    assert [lado.atores for lado in analise.lados] == [("Nunes Marques",)] and analise.questao == ""
    assert analise.ressalvas == [Ressalva((), "A suspensão é censura.", ("Agência Brasil", "CartaCapital"))]
    assert analise.ajustes == [
        "ator do lado 2 saiu: o trecho não está no texto de Agência Brasil (Lula)",
        "ator do lado 2 saiu: nenhum lado tem a resposta dele (campanha de Flávio Bolsonaro: Talvez)",
        "lado 2, sem ator nem grupo, virou ressalva",
    ]
    assert [e.comprovada for e in analise.respostas] == [True, False, True]

    sem_entrada = analise_da_resposta(_canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Lula", "Não")), TEXTOS)
    assert [lado.atores for lado in sem_entrada.lados] == [("Nunes Marques",), ("Lula",)]
    assert sem_entrada.ajustes == ["ator do lado 2 saiu: não está em respostas_por_ator (campanha de Flávio Bolsonaro)"]


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
def test_o_trecho_tem_de_estar_ao_pe_da_letra_no_texto_que_a_analise_recebeu(trecho, veiculo, vale):
    resposta = _canal(_evidencia("Nunes Marques", "Sim", trecho, veiculo), _evidencia("Lula", "Não"))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert analise.respostas[0].comprovada is vale and (("Nunes Marques",) in [lado.atores for lado in analise.lados]) is vale


def test_sem_questao_os_atores_ficam_como_vieram():
    # pauta sem disputa: ninguém confere respostas nem trechos
    um = analise_da_resposta({"questao": "", "lados": [_lado(atores=["Terra de Direitos", "Justiça Global"], veiculos=VEICULOS)]}, TEXTOS)
    assert um.problemas == [] and um.ajustes == [] and um.respostas == []
    assert um.lados == [Lado("Uma posição.", ("Terra de Direitos", "Justiça Global"), ("Agência Brasil", "CartaCapital"))]


def test_um_ator_pode_trazer_mais_de_um_trecho_e_o_lado_deixa_de_ser_fino():
    resposta = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Nunes Marques", "Sim", "Meta alega problemas técnicos"),
                      _evidencia("Nunes Marques", "Sim"),                                  # trecho repetido não conta duas vezes
                      _evidencia("Nunes Marques", "Sim", "um trecho que não está em texto nenhum"),
                      _evidencia("Lula", "Não", DA_CARTA, "CartaCapital"))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.trechos for lado in analise.lados] == [(DA_AB, "Meta alega problemas técnicos"), (DA_CARTA,)]
    assert lados_finos(analise.lados) == [False, True]
    assert analise.ajustes == ["ator do lado 2 saiu: não está em respostas_por_ator (campanha de Flávio Bolsonaro)"]
    # a resposta do ator vem escrita de um jeito em cada entrada: os dois trechos contam para o lado em que ele ficou
    variada = _canal(_evidencia("Nunes Marques", "Sim"), _evidencia("Nunes Marques", "É preciso suspender", "Meta alega problemas técnicos"),
                     _evidencia("Lula", "Não", DA_CARTA, "CartaCapital"))
    assert analise_da_resposta(variada, TEXTOS).lados[0].trechos == (DA_AB, "Meta alega problemas técnicos")


def test_lado_com_um_so_trecho_de_evidencia_e_fino():
    analise = analise_da_resposta(DOIS_LADOS, TEXTOS)
    assert [lado.fino for lado in analise.lados] == [False, True] == lados_finos(analise.lados)     # dois trechos de um lado, um do outro
    assert lados_finos(analise.lados[1:]) == [False]                                                # só há lado fino com 2 lados ou mais
    assert not Lado("p", ("Meta",), ("G1",)).fino                                                   # sem conferência de trechos, não é fino


# ── Ressalvas ─────────────────────────────────────────────────────────────────────────────

FLAVIO = _lado("Flávio propõe flexibilizar o Mercosul.", ["Flávio Bolsonaro", "Milei"], ["Agência Brasil"], "Sim")
ALERTA = "A flexibilização pode enfraquecer a tarifa comum."


def test_lado_com_atores_vazios_e_grupos_vira_ressalva_e_a_questao_sai(caplog):
    resposta = _com_evidencias({"questao": "A flexibilização é boa para o Brasil?", "motivo": "Proposta contra alerta.",
                                "lados": [FLAVIO, _lado(ALERTA, [], ["CartaCapital"], "Não", grupos=["economistas"])]})
    chamada = Chamada(resposta)
    with caplog.at_level(logging.INFO, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    # sobrou um lado com ator nomeado: a questão e a resposta dele saem, e a ressalva guarda o grupo e o veículo
    [lado] = analise.lados
    assert (lado.posicao, lado.atores, lado.veiculos, lado.resposta) == (
        "Flávio propõe flexibilizar o Mercosul.", ("Flávio Bolsonaro", "Milei"), ("Agência Brasil",), "")
    assert analise.ressalvas == [Ressalva(("economistas",), ALERTA, ("CartaCapital",))]     # o veículo só da ressalva conta como coberto
    assert analise.questao == "" and analise.problemas == [] and analise.ajustes == []
    assert len(chamada.recebido) == 1                                                       # não é resposta inválida: não há nova tentativa
    assert "Lados da pauta: 1 (Flávio Bolsonaro, Milei) · ressalvas: economistas" in caplog.text


def test_lado_so_com_atores_genericos_vira_ressalva_com_os_termos_em_grupos():
    resposta = _disputa(FLAVIO, _lado(ALERTA, ["economistas", "o governo"], VEICULOS, grupos=["analistas", "economistas"]))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Flávio Bolsonaro", "Milei")]
    assert analise.ressalvas == [Ressalva(("analistas", "economistas", "o governo"), ALERTA, ("Agência Brasil", "CartaCapital"))]
    assert analise.ajustes == ["ator genérico do lado 2 passou a grupo (economistas, o governo)"] and analise.problemas == []


def test_lado_sem_ator_nem_grupo_tambem_vira_ressalva():
    analise = analise_da_resposta(_disputa(FLAVIO, _lado(ALERTA, [], ["CartaCapital"])), TEXTOS)
    assert analise.ressalvas == [Ressalva((), ALERTA, ("CartaCapital",))] and len(analise.lados) == 1
    assert analise.ajustes == ["lado 2, sem ator nem grupo, virou ressalva"]


def test_em_lado_misto_o_grupo_sai_e_nao_vira_ressalva():
    resposta = _disputa(_lado("A Meta nega.", ["Meta", "especialistas"], grupos=["analistas"]),
                        _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"]))
    analise = analise_da_resposta(resposta, TEXTOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert analise.ressalvas == [] and analise.problemas == [] and analise.questao        # com dois lados nomeados, a questão fica
    assert analise.ajustes == ["ator genérico do lado 1 passou a grupo (especialistas)"]


def test_com_mais_de_duas_ressalvas_ficam_as_duas_primeiras(caplog):
    resposta = {"lados": [_lado(veiculos=VEICULOS), *(_lado(f"Ressalva {g}.", [], VEICULOS, grupos=[g])
                                                      for g in ("economistas", "juristas", "moradores"))]}
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(resposta), TEXTOS)
    assert [r.grupos for r in analise.ressalvas] == [("economistas",), ("juristas",)]
    assert [r.grupos for r in analise.descartadas] == [("moradores",)] and analise.problemas == []
    assert analise.ajustes == ["1 ressalva(s) a mais: ficam as 2 primeiras"]
    assert "1 ressalva(s) a mais na pauta; ficam as 2 primeiras" in caplog.text


def test_sem_nenhum_lado_nomeado_fica_o_lado_neutro_com_as_ressalvas():
    resposta = _disputa(_lado("O governo defende a medida.", ["o governo"], VEICULOS), _lado("Criticam a medida.", [], VEICULOS, grupos=["especialistas"]))
    chamada = Chamada(resposta)
    analise = analisar_lados(chamada, TEXTOS)
    assert analise.lados == EMERGENCIA and analise.questao == "" and analise.problemas == [] and len(chamada.recebido) == 1
    assert analise.ressalvas == [
        Ressalva(("o governo",), "O governo defende a medida.", ("Agência Brasil", "CartaCapital")),
        Ressalva(("especialistas",), "Criticam a medida.", ("Agência Brasil", "CartaCapital")),
    ]
    assert analise.ajustes == ["ator genérico do lado 1 passou a grupo (o governo)", "nenhum lado com ator nomeado: a pauta fica com o lado neutro"]


def test_a_questao_so_fica_com_dois_lados_nomeados_ou_mais():
    # um lado nomeado, com ou sem ressalva: a questão sai, sem recusa
    um = analise_da_resposta(_com_evidencias({"questao": "A Meta favoreceu um candidato?", "lados": [_lado(veiculos=VEICULOS, resposta="Não")]}), TEXTOS)
    assert um.problemas == [] and um.questao == "" and [(lado.atores, lado.resposta) for lado in um.lados] == [(("Meta",), "")]
    # dois lados nomeados e uma ressalva: a questão fica
    tres = analise_da_resposta(_disputa(_lado("A Meta nega.", ["Meta"]), _lado("Veem risco.", ["críticos"], VEICULOS),
                                        _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"])), TEXTOS)
    assert tres.questao == "A Meta favoreceu um candidato?" and [lado.resposta for lado in tres.lados] == ["Resposta 1", "Resposta 3"]
    assert [r.grupos for r in tres.ressalvas] == [("críticos",)] and tres.problemas == []


def test_os_lados_nomeados_ainda_passam_pela_validacao():
    # quatro lados, um deles só de grupo: ficam três lados e uma ressalva, e a resposta vale
    quatro = _disputa(*(_lado(atores=[a], veiculos=VEICULOS) for a in ("Meta", "PT", "analistas", "TSE")))
    analise = analise_da_resposta(quatro, TEXTOS)
    assert len(analise.lados) == 3 and len(analise.ressalvas) == 1 and analise.problemas == []
    # o número do lado na mensagem é o da resposta do LLM
    repetido = _disputa(_lado(atores=["fontes"], veiculos=VEICULOS), _lado(atores=["Meta", "Lula"], veiculos=VEICULOS),
                        _lado(atores=["campanha de Lula"], veiculos=VEICULOS))
    assert analise_da_resposta(repetido, TEXTOS).problemas == ["lado 3 sem ator que não esteja em outro lado"]


# ── A chamada ─────────────────────────────────────────────────────────────────────────────

def test_a_chamada_leva_os_trechos_com_veiculo_e_titulo_e_temperatura_baixa():
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


# ── O bloco da entrada ────────────────────────────────────────────────────────────────────

def test_bloco_diz_a_questao_os_lados_o_elenco_exato_e_o_alvo_de_palavras():
    analise = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    assert bloco_dos_lados(analise.lados, analise.questao) == (
        "\nLADOS DA PAUTA: 2 lados.\n"
        "QUESTÃO: A Meta favoreceu um candidato?\n"
        "Lado 1 (resposta: Sim): A campanha acusa a Meta. Atores: campanha de Lula, PT. Veículos: Agência Brasil, CartaCapital.\n"
        "Lado 2 (resposta: Não; lado fino): A Meta nega. Atores: Meta. Veículos: Agência Brasil.\n"
        'ELENCO: Helena e exatamente 2 analistas, um por lado; "houve_divergencia": true. Helena apresenta a questão '
        "uma vez, na abertura, com palavras naturais, e não atribui as posições aos atores; cada analista sustenta a "
        "posição do seu lado, numa frase que nomeia um ator do lado, cita um veículo do lado e usa um verbo de posição, "
        'como em "segundo <veículo>, <ator> afirma que...". Lado fino tem pouco material nas fontes: o analista dele fala '
        "de 120 a 200 palavras e não amplia além do que as fontes trazem. Alvo: 320 a 400 palavras por personagem, fora o "
        "de lado fino."
    )
    sem_fino = [Lado("A campanha acusa.", ("PT",), ("G1",), "Sim", ("um trecho", "outro trecho")), Lado("A Meta nega.", ("Meta",), ("G1",), "Não")]
    assert "lado fino" not in bloco_dos_lados(sem_fino, "Q?") and bloco_dos_lados(sem_fino, "Q?").endswith("Alvo: 320 a 400 palavras por personagem.")
    um = analise_da_resposta(UM_LADO, TEXTOS)
    assert bloco_dos_lados(um.lados, um.questao) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: Uma posição. Atores: Meta. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, que explica o tema com ela, sem advogar; "houve_divergencia": false. '
        "Alvo: 360 a 420 palavras por personagem."
    )
    tres = [Lado("p", (f"Ator {i}",), ("G1",), f"Resposta {i}") for i in range(3)]
    assert "exatamente 3 analistas, um por lado" in bloco_dos_lados(tres, "Q?") and "Alvo: 260 a 310" in bloco_dos_lados(tres, "Q?")


def test_bloco_traz_as_ressalvas_logo_depois_dos_lados():
    lados = [Lado("Flávio propõe flexibilizar o Mercosul.", ("Flávio Bolsonaro", "Milei"), ("Gazeta do Povo",))]
    ressalvas = [Ressalva(("economistas",), ALERTA, ("Gazeta do Povo",)), Ressalva((), "Há risco fiscal", ("Gazeta do Povo",))]
    assert bloco_dos_lados(lados, "", ressalvas) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: Flávio propõe flexibilizar o Mercosul. Atores: Flávio Bolsonaro, Milei. Veículos: Gazeta do Povo.\n"
        "Ressalva 1: A flexibilização pode enfraquecer a tarifa comum. Grupos: economistas. Veículos: Gazeta do Povo.\n"
        "Ressalva 2: Há risco fiscal. Veículos: Gazeta do Povo.\n"
        "ELENCO: Helena e exatamente 1 analista, que explica a posição e responde às ressalvas com o que as fontes dizem, "
        'sem tomar partido; "houve_divergencia": false. Ressalva não é lado nem ganha analista: Helena traz cada uma como '
        "pergunta atribuída, sem avaliá-la nem reformulá-la, numa frase com o veículo, o grupo e um verbo de posição, "
        'seguida de uma pergunta aberta, como em "Segundo <veículo>, <grupo> alertam que... Como você vê isso?". '
        "Alvo: 360 a 420 palavras por personagem."
    )
    dois = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    com_ressalva = bloco_dos_lados(dois.lados, dois.questao, ressalvas[:1])
    assert "Veículos: Agência Brasil.\nRessalva 1: A flexibilização" in com_ressalva                   # depois do último lado
    assert "Ressalva não é lado nem ganha analista: Helena traz cada uma" in com_ressalva


def test_bloco_do_lado_neutro_leva_a_posicao_e_os_veiculos():
    assert bloco_dos_lados(lado_unico(VEICULOS)) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: relato dos fatos, sem lados definidos. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, que explica o tema com ela, sem advogar; "houve_divergencia": false. '
        "Alvo: 360 a 420 palavras por personagem."
    )


def test_bloco_nunca_passa_do_espaco_reservado():
    longos = [Lado("Posição muito comprida. " * 40, ("Ator Um", "Ator Dois", "Ator Três"), ("O GLOBO", "G1", "Agência Brasil"),
                   "Uma resposta comprida demais para caber inteira no bloco de lados da pauta. " * 3) for _ in range(3)]
    bloco = bloco_dos_lados(longos, "Uma questão comprida demais? " * 20)
    assert len(bloco) <= modulo.MAX_BLOCO and bloco.count("…") == 7 and bloco.endswith("palavras por personagem.")   # questão, 3 respostas e 3 posições
    assert all(f"Lado {i} (resposta: Uma resposta comprida" in bloco and "): Posição muito comprida." in bloco for i in (1, 2, 3))

    exagerados = [Lado("Posição.", tuple(f"Ator de nome bem comprido número {i}" for i in range(30)), ("G1",), "Sim") for _ in range(3)]
    cortado = bloco_dos_lados(exagerados, "O canal deve ser suspenso?")
    assert len(cortado) <= modulo.MAX_BLOCO
    assert cortado.startswith("\nLADOS DA PAUTA: 3 lados.\nQUESTÃO: O canal deve ser suspenso?\nELENCO: Helena e exatamente 3 analistas")   # o elenco nunca é cortado

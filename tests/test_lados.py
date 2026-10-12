"""Testes de ai/lados.py sem LLM: a validação da resposta, a nova tentativa, o lado de emergência e o bloco da entrada."""
import json
import logging

import pytest

from techdigest.ai import lados as modulo
from techdigest.ai.lados import (
    Lado, analisar_lados, analise_da_resposta, ator_generico, bloco_dos_lados, entrada_dos_lados, lado_unico,
    pedido_de_correcao,
)
from techdigest.ai.prompt import PROMPT_LADOS

VEICULOS = ["Agência Brasil", "CartaCapital"]
TEXTOS = [
    {"fonte": "Agência Brasil", "titulo": "Meta alega problemas técnicos", "texto": "A Meta respondeu."},
    {"fonte": "CartaCapital", "titulo": "Campanha de Lula acusa Meta", "texto": "A campanha acusou."},
]
EMERGENCIA = [Lado("relato dos fatos, sem lados definidos", (), ("Agência Brasil", "CartaCapital"))]


def _lado(posicao="Uma posição.", atores=("Meta",), veiculos=("Agência Brasil",), resposta=None) -> dict:
    lado = {"posicao": posicao, "atores": list(atores), "veiculos": list(veiculos)}
    return lado if resposta is None else {"resposta": resposta, **lado}


def _disputa(*lados, questao="A Meta favoreceu um candidato?") -> dict:
    """Uma resposta com questão; os lados sem resposta ganham "Resposta 1", "Resposta 2"..."""
    return {"questao": questao, "lados": [{"resposta": f"Resposta {i}", **lado} for i, lado in enumerate(lados, 1)]}


DOIS_LADOS = {
    "questao": " A Meta favoreceu um candidato? ",
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
        Lado("A campanha acusa a Meta.", ("campanha de Lula", "PT"), ("Agência Brasil", "CartaCapital"), "Sim"),   # um veículo pode relatar dois lados
        Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não."),
    ]
    assert analise.motivo == "Acusação contra defesa." and analise.problemas == []
    assert analise.primeira is None and len(chamada.recebido) == 1          # resposta válida não pede nova tentativa


def test_sem_disputa_a_questao_fica_vazia_e_ha_um_lado_so():
    assert analise_da_resposta(UM_LADO, VEICULOS).problemas == []
    so_os_lados = {"lados": [_lado(veiculos=VEICULOS, resposta="Sim")]}       # sem a chave da questão é o mesmo que questão vazia
    analise = analise_da_resposta(so_os_lados, VEICULOS)
    assert analise.lados == [Lado("Uma posição.", ("Meta",), ("Agência Brasil", "CartaCapital"))] and analise.questao == ""


@pytest.mark.parametrize("resposta, problema", [
    (QUATRO_LADOS, "resposta com 4 lados (vale de 1 a 3)"),
    ({"lados": []}, "resposta com 0 lados (vale de 1 a 3)"),
    ({"lados": "dois"}, "resposta sem a lista de lados"),
    (_disputa(_lado(atores=["Meta", "PT"], veiculos=VEICULOS), _lado(atores=["PT"], veiculos=VEICULOS)),
     "lado 2 sem ator que não esteja em outro lado"),
    (_disputa(_lado(atores=["Lula"], veiculos=VEICULOS), _lado(atores=["campanha de Lula"], veiculos=VEICULOS)),
     "lado 1 sem ator que não esteja em outro lado"),                                      # um nome dentro do outro é o mesmo ator
    (_disputa(_lado(veiculos=["Agência Brasil", "Folha de S.Paulo"]), _lado(atores=["PT"], veiculos=["CartaCapital"])),
     "lado 1 com veículo fora da pauta (Folha de S.Paulo)"),
    (_disputa(_lado(), _lado(atores=["PT"])), "veículo da pauta em nenhum lado (CartaCapital)"),
    ({"lados": [_lado(posicao=" ", veiculos=VEICULOS)]}, "lado 1 sem posição"),
    ({"lados": [_lado(atores=[], veiculos=VEICULOS)]}, "lado 1 sem ator"),
    ({"lados": [_lado(veiculos=[])]}, "lado 1 sem veículo"),
    ({"lados": ["Meta contra Lula"]}, "lado 1 não é um objeto"),
    # a questão e os lados andam juntos
    ({"questao": "", "lados": [_lado(veiculos=VEICULOS), _lado(atores=["PT"], veiculos=VEICULOS)]},
     "questão vazia com 2 lados (questão vazia exige exatamente 1 lado)"),
    ({"questao": "A Meta favoreceu um candidato?", "lados": [_lado(veiculos=VEICULOS)]},
     "questão preenchida com 1 lado (questão preenchida exige de 2 a 3 lados; sem disputa, a questão fica vazia)"),
    ({"questao": "Houve favorecimento?", "lados": [_lado(veiculos=VEICULOS, resposta="Sim"), _lado(atores=["PT"], veiculos=VEICULOS)]},
     "lado 2 sem resposta à questão"),
    ({"questao": "Houve favorecimento?",
      "lados": [_lado(veiculos=VEICULOS, resposta="Não."), _lado(atores=["PT"], veiculos=VEICULOS, resposta="nao")]},
     "lados 1 e 2 com a mesma resposta à questão (Não.)"),
])
def test_resposta_invalida_nas_duas_tentativas_vira_o_lado_de_emergencia(resposta, problema, caplog):
    assert problema in analise_da_resposta(resposta, VEICULOS).problemas
    chamada = Chamada(resposta)
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    # o lado único não vai vazio para a geração: leva a posição de emergência
    assert analise.lados == EMERGENCIA == lado_unico(VEICULOS) and analise.questao == ""
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
        "Resposta anterior: " + json.dumps(QUATRO_LADOS, ensure_ascii=False) + "\n"
        "Responda de novo, com o JSON completo. Uma questão só; cada lado é uma resposta diferente a ela; agrupe os "
        "atores pela resposta que dão à questão, nunca um lado por ator; sem disputa, a questão fica vazia e há um lado só."
    )


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


def test_o_pedido_de_correcao_diz_o_que_nao_conta_como_ator_e_corta_a_resposta_comprida():
    so_genericos = _disputa(_lado(atores=["o governo"], veiculos=VEICULOS), _lado(atores=["especialistas"], veiculos=VEICULOS))
    pedido = pedido_de_correcao(analise_da_resposta(so_genericos, VEICULOS))
    assert "não valeu: nenhum lado com ator específico.\nNão contam como atores: lado 1, só com ator genérico (o governo); " in pedido
    comprida = {"lados": [_lado(posicao="x" * 5000, veiculos=[])]}
    assert len(pedido_de_correcao(analise_da_resposta(comprida, VEICULOS))) < modulo.MAX_ANTERIOR + 500


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


def test_lado_so_com_ator_generico_e_removido_e_os_demais_ficam(caplog):
    resposta = {**_disputa(_lado("Flávio propõe.", ["Flávio Bolsonaro"]), _lado("Alertam para o risco.", ["economistas"], ["CartaCapital"]),
                           questao="A flexibilização é boa para o Brasil?"),
                "motivo": "Proposta contra alerta."}
    chamada = Chamada(resposta)
    with caplog.at_level(logging.INFO, logger="techdigest.ai.lados"):
        analise = analisar_lados(chamada, TEXTOS)
    # sobrou um lado só: a disputa era com quem não é ator, então a questão sai e o lado fica com todos os veículos
    assert analise.lados == [Lado("Flávio propõe.", ("Flávio Bolsonaro",), ("Agência Brasil", "CartaCapital"))]
    assert analise.questao == "" and analise.problemas == [] and len(chamada.recebido) == 1
    assert analise.removidos == ["lado 2, só com ator genérico (economistas)"]
    assert "saiu o que só tem ator genérico (lado 2, só com ator genérico (economistas))" in caplog.text

    tres = _disputa(_lado("A Meta nega.", ["Meta"]), _lado("Críticos veem risco.", ["críticos", "o governo"], VEICULOS),
                    _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"]))
    analise = analise_da_resposta(tres, VEICULOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert [lado.veiculos for lado in analise.lados] == [("Agência Brasil",), ("CartaCapital",)]   # com dois lados, cada um mantém os seus
    assert [lado.resposta for lado in analise.lados] == ["Resposta 1", "Resposta 3"] and analise.questao    # e a questão continua
    assert analise.problemas == [] and analise.removidos == ["lado 2, só com ator genérico (críticos, o governo)"]


def test_ator_generico_sai_do_lado_que_tem_outro_ator():
    resposta = _disputa(_lado("A Meta nega.", ["Meta", "especialistas"]), _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"]))
    analise = analise_da_resposta(resposta, VEICULOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert analise.problemas == [] and analise.removidos == ["ator genérico do lado 1 (especialistas)"]


def test_se_todos_os_lados_sao_de_ator_generico_a_resposta_nao_vale():
    resposta = _disputa(_lado("O governo defende.", ["o governo"], VEICULOS), _lado("Criticam.", ["especialistas"], VEICULOS))
    analise = analise_da_resposta(resposta, VEICULOS)
    assert analise.lados == EMERGENCIA and analise.problemas == ["nenhum lado com ator específico"]
    assert len(analise.removidos) == 2


def test_os_lados_que_ficam_ainda_passam_pela_validacao():
    # quatro lados com um genérico: ficam três, e a resposta vale
    quatro = _disputa(*(_lado(atores=[a], veiculos=VEICULOS) for a in ("Meta", "PT", "analistas", "TSE")))
    assert len(analise_da_resposta(quatro, VEICULOS).lados) == 3
    # o veículo que só o lado removido citava fica sem lado quando sobram dois
    orfao = _disputa(_lado(atores=["Meta"]), _lado(atores=["PT"]), _lado(atores=["analistas"], veiculos=["CartaCapital"]))
    analise = analise_da_resposta(orfao, VEICULOS)
    assert analise.lados == EMERGENCIA and analise.problemas == ["veículo da pauta em nenhum lado (CartaCapital)"]
    # o número do lado na mensagem é o da resposta do LLM
    repetido = _disputa(_lado(atores=["fontes"], veiculos=VEICULOS), _lado(atores=["Meta", "PT"], veiculos=VEICULOS),
                        _lado(atores=["PT"], veiculos=VEICULOS))
    assert analise_da_resposta(repetido, VEICULOS).problemas == ["lado 3 sem ator que não esteja em outro lado"]


# ── A chamada ─────────────────────────────────────────────────────────────────────────────

def test_a_chamada_leva_os_trechos_com_veiculo_e_titulo_e_temperatura_baixa():
    chamada = Chamada(DOIS_LADOS)
    analisar_lados(chamada, TEXTOS)
    [(system, user, opcoes)] = chamada.recebido
    assert system == PROMPT_LADOS
    assert user == entrada_dos_lados(TEXTOS) == (
        "TEXTO 1\nVeículo: Agência Brasil\nTítulo: Meta alega problemas técnicos\nTexto:\nA Meta respondeu.\n\n"
        "TEXTO 2\nVeículo: CartaCapital\nTítulo: Campanha de Lula acusa Meta\nTexto:\nA campanha acusou.\n\n"
        "VEÍCULOS DA PAUTA: Agência Brasil, CartaCapital"
    )
    assert opcoes == {"chaves": ("lados",), "temperatura": 0.1, "max_saida": modulo.MAX_SAIDA_LADOS}


def test_o_prompt_pede_a_questao_antes_dos_lados():
    assert PROMPT_LADOS.index('{"questao":') < PROMPT_LADOS.index('"lados": [{"resposta":') < PROMPT_LADOS.index('"motivo":')


# ── O bloco da entrada ────────────────────────────────────────────────────────────────────

def test_bloco_diz_a_questao_os_lados_o_elenco_exato_e_o_alvo_de_palavras():
    analise = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    assert bloco_dos_lados(analise.lados, analise.questao) == (
        "\nLADOS DA PAUTA: 2 lados.\n"
        "QUESTÃO: A Meta favoreceu um candidato?\n"
        "Lado 1 (resposta: Sim): A campanha acusa a Meta. Atores: campanha de Lula, PT. Veículos: Agência Brasil, CartaCapital.\n"
        "Lado 2 (resposta: Não): A Meta nega. Atores: Meta. Veículos: Agência Brasil.\n"
        'ELENCO: Helena e exatamente 2 analistas, um por lado; "houve_divergencia": true. Helena apresenta a questão, e '
        "cada analista responde por um lado, numa frase que nomeia um ator do lado, cita um veículo do lado e usa um "
        'verbo de posição, como em "segundo <veículo>, <ator> afirma que...". Alvo: 320 a 400 palavras por personagem.'
    )
    um = analise_da_resposta(UM_LADO, VEICULOS)
    assert bloco_dos_lados(um.lados, um.questao) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: Uma posição. Atores: Meta. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, que aprofunda o tema com ela; "houve_divergencia": false. '
        "Alvo: 360 a 420 palavras por personagem."
    )
    tres = [Lado("p", (f"Ator {i}",), ("G1",), f"Resposta {i}") for i in range(3)]
    assert "exatamente 3 analistas, um por lado" in bloco_dos_lados(tres, "Q?") and "Alvo: 260 a 310" in bloco_dos_lados(tres, "Q?")


def test_bloco_do_lado_de_emergencia_leva_a_posicao_e_os_veiculos():
    assert bloco_dos_lados(lado_unico(VEICULOS)) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        "Lado 1: relato dos fatos, sem lados definidos. Veículos: Agência Brasil, CartaCapital.\n"
        'ELENCO: Helena e exatamente 1 analista, que aprofunda o tema com ela; "houve_divergencia": false. '
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

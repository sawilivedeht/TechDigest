"""Testes de ai/lados.py sem LLM: a validação da resposta, a queda para um lado só e o bloco da entrada."""
import logging

import pytest

from techdigest.ai import lados as modulo
from techdigest.ai.lados import (
    Lado, analisar_lados, analise_da_resposta, ator_generico, bloco_dos_lados, entrada_dos_lados, lado_unico,
)
from techdigest.ai.prompt import PROMPT_LADOS

VEICULOS = ["Agência Brasil", "CartaCapital"]
TEXTOS = [
    {"fonte": "Agência Brasil", "titulo": "Meta alega problemas técnicos", "texto": "A Meta respondeu."},
    {"fonte": "CartaCapital", "titulo": "Campanha de Lula acusa Meta", "texto": "A campanha acusou."},
]


def _lado(posicao="Uma posição.", atores=("Meta",), veiculos=("Agência Brasil",)) -> dict:
    return {"posicao": posicao, "atores": list(atores), "veiculos": list(veiculos)}


DOIS_LADOS = {
    "lados": [_lado("A campanha acusa a Meta.", ["campanha de Lula", "PT"], ["cartacapital", "Agencia Brasil"]),
              _lado("A Meta nega.", ["Meta"], ["AGÊNCIA BRASIL"])],
    "motivo": " Acusação contra defesa. ",
}


class Chamada:
    """Faz o papel do chat_json: guarda o que recebeu e devolve (ou levanta) o que foi combinado."""

    def __init__(self, resposta):
        self.resposta = resposta
        self.recebido = []

    def __call__(self, system, user, **opcoes):
        self.recebido.append((system, user, opcoes))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


# ── Validação ─────────────────────────────────────────────────────────────────────────────

def test_resposta_valida_vira_lados_com_a_grafia_da_pauta():
    assert analise_da_resposta(DOIS_LADOS, VEICULOS).problemas == []
    analise = analisar_lados(Chamada(DOIS_LADOS), TEXTOS)
    assert analise.lados == [
        Lado("A campanha acusa a Meta.", ("campanha de Lula", "PT"), ("Agência Brasil", "CartaCapital")),   # um veículo pode relatar dois lados
        Lado("A Meta nega.", ("Meta",), ("Agência Brasil",)),
    ]
    assert analise.motivo == "Acusação contra defesa." and analise.problemas == []


def test_um_lado_so_e_valido_e_o_motivo_e_opcional():
    um = {"lados": [_lado(veiculos=VEICULOS)]}
    assert analise_da_resposta(um, VEICULOS).problemas == []
    assert analisar_lados(Chamada(um), TEXTOS).lados == [Lado("Uma posição.", ("Meta",), ("Agência Brasil", "CartaCapital"))]


@pytest.mark.parametrize("resposta, problema", [
    ({"lados": [_lado(atores=[f"Ator {i}"], veiculos=VEICULOS) for i in range(4)]}, "resposta com 4 lados (vale de 1 a 3)"),
    ({"lados": []}, "resposta com 0 lados (vale de 1 a 3)"),
    ({"lados": "dois"}, "resposta sem a lista de lados"),
    ({"lados": [_lado(atores=["Meta", "PT"], veiculos=VEICULOS), _lado(atores=["PT"], veiculos=VEICULOS)]},
     "lado 2 sem ator que não esteja em outro lado"),
    ({"lados": [_lado(atores=["Lula"], veiculos=VEICULOS), _lado(atores=["campanha de Lula"], veiculos=VEICULOS)]},
     "lado 1 sem ator que não esteja em outro lado"),                                      # um nome dentro do outro é o mesmo ator
    ({"lados": [_lado(veiculos=["Agência Brasil", "Folha de S.Paulo"]), _lado(atores=["PT"], veiculos=["CartaCapital"])]},
     "lado 1 com veículo fora da pauta (Folha de S.Paulo)"),
    ({"lados": [_lado(), _lado(atores=["PT"])]}, "veículo da pauta em nenhum lado (CartaCapital)"),
    ({"lados": [_lado(posicao=" ", veiculos=VEICULOS)]}, "lado 1 sem posição"),
    ({"lados": [_lado(atores=[], veiculos=VEICULOS)]}, "lado 1 sem ator"),
    ({"lados": [_lado(veiculos=[])]}, "lado 1 sem veículo"),
    ({"lados": ["Meta contra Lula"]}, "lado 1 não é um objeto"),
])
def test_resposta_invalida_cai_em_um_lado_so_com_aviso_no_log(resposta, problema, caplog):
    assert problema in analise_da_resposta(resposta, VEICULOS).problemas
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(resposta), TEXTOS)
    assert analise.lados == [Lado("", (), ("Agência Brasil", "CartaCapital"))] == lado_unico(VEICULOS)
    assert problema in analise.problemas and analise.resposta is resposta
    assert "Análise de lados inválida" in caplog.text and "a pauta segue com um lado só" in caplog.text


def test_chamada_que_falha_cai_em_um_lado_so_com_aviso_no_log(caplog):
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(ValueError("Modelo retornou resposta VAZIA.")), TEXTOS)
    assert analise.lados == lado_unico(VEICULOS)
    assert analise.problemas == ["a chamada falhou (ValueError: Modelo retornou resposta VAZIA.)"]
    assert "A pauta segue com um lado só." in caplog.text


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
    resposta = {"lados": [_lado("Flávio propõe.", ["Flávio Bolsonaro"]), _lado("Alertam para o risco.", ["economistas"], ["CartaCapital"])],
                "motivo": "Proposta contra alerta."}
    with caplog.at_level(logging.INFO, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(resposta), TEXTOS)
    # sobrou um lado só: ele fica com todos os veículos da pauta, inclusive o que só o lado removido citava
    assert analise.lados == [Lado("Flávio propõe.", ("Flávio Bolsonaro",), ("Agência Brasil", "CartaCapital"))]
    assert analise.problemas == [] and analise.removidos == ["lado 2, só com ator genérico (economistas)"]
    assert "saiu o que só tem ator genérico (lado 2, só com ator genérico (economistas))" in caplog.text

    tres = {"lados": [_lado("A Meta nega.", ["Meta"]), _lado("Críticos veem risco.", ["críticos", "o governo"], VEICULOS),
                      _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"])]}
    analise = analise_da_resposta(tres, VEICULOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert [lado.veiculos for lado in analise.lados] == [("Agência Brasil",), ("CartaCapital",)]   # com dois lados, cada um mantém os seus
    assert analise.problemas == [] and analise.removidos == ["lado 2, só com ator genérico (críticos, o governo)"]


def test_ator_generico_sai_do_lado_que_tem_outro_ator():
    resposta = {"lados": [_lado("A Meta nega.", ["Meta", "especialistas"]), _lado("A campanha acusa.", ["campanha de Lula"], ["CartaCapital"])]}
    analise = analise_da_resposta(resposta, VEICULOS)
    assert [lado.atores for lado in analise.lados] == [("Meta",), ("campanha de Lula",)]
    assert analise.problemas == [] and analise.removidos == ["ator genérico do lado 1 (especialistas)"]


def test_se_todos_os_lados_sao_de_ator_generico_vale_um_lado_so(caplog):
    resposta = {"lados": [_lado("O governo defende.", ["o governo"], VEICULOS), _lado("Criticam.", ["especialistas"], VEICULOS)]}
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.lados"):
        analise = analisar_lados(Chamada(resposta), TEXTOS)
    assert analise.lados == lado_unico(VEICULOS) and analise.problemas == ["nenhum lado com ator específico"]
    assert len(analise.removidos) == 2 and "a pauta segue com um lado só" in caplog.text


def test_os_lados_que_ficam_ainda_passam_pela_validacao():
    # quatro lados com um genérico: ficam três, e a resposta vale
    quatro = {"lados": [_lado(atores=[a], veiculos=VEICULOS) for a in ("Meta", "PT", "analistas", "TSE")]}
    assert len(analise_da_resposta(quatro, VEICULOS).lados) == 3
    # o veículo que só o lado removido citava fica sem lado quando sobram dois: um lado só, com aviso
    orfao = {"lados": [_lado(atores=["Meta"]), _lado(atores=["PT"]), _lado(atores=["analistas"], veiculos=["CartaCapital"])]}
    analise = analise_da_resposta(orfao, VEICULOS)
    assert analise.lados == lado_unico(VEICULOS) and analise.problemas == ["veículo da pauta em nenhum lado (CartaCapital)"]
    # o número do lado na mensagem é o da resposta do LLM
    repetido = {"lados": [_lado(atores=["fontes"], veiculos=VEICULOS), _lado(atores=["Meta", "PT"], veiculos=VEICULOS),
                          _lado(atores=["PT"], veiculos=VEICULOS)]}
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


# ── O bloco da entrada ────────────────────────────────────────────────────────────────────

def test_bloco_diz_os_lados_o_elenco_exato_e_o_alvo_de_palavras():
    dois = analisar_lados(Chamada(DOIS_LADOS), TEXTOS).lados
    assert bloco_dos_lados(dois) == (
        "\nLADOS DA PAUTA: 2 lados.\n"
        "Lado 1: A campanha acusa a Meta. Atores: campanha de Lula, PT. Veículos: Agência Brasil, CartaCapital.\n"
        "Lado 2: A Meta nega. Atores: Meta. Veículos: Agência Brasil.\n"
        'ELENCO: Helena e exatamente 2 analistas, um por lado; "houve_divergencia": true. Cada analista apresenta a '
        "posição do seu lado numa frase que nomeia um ator do lado, cita um veículo do lado e usa um verbo de posição, "
        'como em "segundo <veículo>, <ator> afirma que...". Alvo: 320 a 400 palavras por personagem.'
    )
    assert bloco_dos_lados(lado_unico(VEICULOS)) == (
        "\nLADOS DA PAUTA: 1 lado.\n"
        'ELENCO: Helena e exatamente 1 analista, que aprofunda o tema com ela; "houve_divergencia": false. '
        "Alvo: 360 a 420 palavras por personagem."
    )
    tres = [Lado("p", (f"Ator {i}",), ("G1",)) for i in range(3)]
    assert "exatamente 3 analistas, um por lado" in bloco_dos_lados(tres) and "Alvo: 260 a 310" in bloco_dos_lados(tres)


def test_bloco_nunca_passa_do_espaco_reservado():
    longos = [Lado("Posição muito comprida. " * 40, ("Ator Um", "Ator Dois", "Ator Três"), ("O GLOBO", "G1", "Agência Brasil"))
              for _ in range(3)]
    bloco = bloco_dos_lados(longos)
    assert len(bloco) <= modulo.MAX_BLOCO and bloco.count("…") == 3 and bloco.endswith("palavras por personagem.")
    assert all(f"Lado {i}: Posição muito comprida." in bloco for i in (1, 2, 3))

    exagerados = [Lado("Posição.", tuple(f"Ator de nome bem comprido número {i}" for i in range(30)), ("G1",)) for _ in range(3)]
    cortado = bloco_dos_lados(exagerados)
    assert len(cortado) <= modulo.MAX_BLOCO
    assert cortado.startswith("\nLADOS DA PAUTA: 3 lados.\nELENCO: Helena e exatamente 3 analistas")   # o elenco nunca é cortado

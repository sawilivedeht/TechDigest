"""Testes de ai/summarizer.py sem LLM: a entrada dentro do orçamento, o recorte por relevância, a análise de lados e o
fluxo de process."""
import datetime
import json
import math
from types import SimpleNamespace

import pytest

from techdigest.ai import qa, summarizer
from techdigest.ai.lados import (
    MAX_BLOCO, MAX_SAIDA_LADOS, Lado, Ressalva, bloco_dos_lados, entrada_dos_lados, lado_unico, textos_que_cabem,
)
from techdigest.ai.prompt import PROMPT_LADOS, PROMPT_RESUMO, PROMPT_REVISOR, PROMPT_ROTEIRO, PROMPT_SISTEMA, PROMPT_TITULO
from techdigest.ai.recorte import cortar_em_paragrafo
from techdigest.ai.summarizer import LEMBRETE, QAReprovado, Summarizer, _repartir, montar_entrada, textos_da_pauta

UTC = datetime.timezone.utc


def _texto(caracteres: int, marca: str = "texto") -> str:
    """Texto de parágrafos de umas 400 letras, com pelo menos `caracteres` no total."""
    paragrafos, n = [], 0
    while sum(map(len, paragrafos)) < caracteres:
        n += 1
        paragrafos.append(f"Parágrafo {n} de {marca}. " + "Uma frase qualquer sobre o assunto. " * 10)
    return "\n\n".join(p.strip() for p in paragrafos)


def _artigo(fonte: str, caracteres: int, **extras) -> dict:
    return {"source": fonte, "title": f"Título de {fonte}", "text": _texto(caracteres, fonte), **extras}


def _entrada_antiga(principal: dict) -> str:
    """A entrada de fonte única sem o bloco de lados: o texto até o teto, cortado em fim de parágrafo."""
    partes = [
        "ARTIGO PRINCIPAL\n"
        f"Fonte: {principal['source']}\n"
        f"Título: {summarizer._limpar(principal['title'])}\n"
        f"Texto:\n{cortar_em_paragrafo(summarizer._limpar(principal['text']), 5000)}"
    ]
    partes.append(
        "\nLEMBRETE: só o JSON das 8 chaves. Roteiro com 600-1300 palavras "
        "no total, 240-480 por personagem, 10-20 turnos."
    )
    return "\n".join(partes)


def _episodio(fontes: list[str]) -> dict:
    """Episódio que passa no QA de tamanho, com as fontes dadas."""
    por_personagem = max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 2))
    fala = " ".join(["palavra"] * por_personagem)
    return {
        "titulo_reescrito": "Título", "resumo_didatico": "Uma frase. " * qa.MIN_FRASES_RESUMO,
        "pontos_chave": ["a", "b"], "por_que_importa": "Importa.",
        "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Ramos", "papel": "analista"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Ramos", "fala": fala}],
        "houve_divergencia": False, "fontes_citadas": fontes,
    }


def _artigos_da_meta() -> tuple[dict, list[dict]]:
    """Os dois artigos da pauta da Meta, cada um citando o seu ator em mais de uma frase (nenhum lado é fino)."""
    principal, relacionado = _artigo("Agência Brasil", 2000), _artigo("CartaCapital", 2000)
    principal["text"] += "\n\nA Meta nega o favorecimento. A Meta fala em problemas técnicos."
    relacionado["text"] += "\n\nA campanha de Lula acusa a empresa. A campanha de Lula acionou o tribunal."
    return principal, [relacionado]


class ProviderFalso:
    """Devolve as respostas em fila e guarda o que recebeu; conta 1 token a cada 4 caracteres.

    A análise de lados fica fora da fila: recebe sempre `lados` e é guardada em `analises`. Sem
    `lados`, a resposta é inválida nas duas tentativas e a pauta segue com o lado de emergência.
    """

    def __init__(self, *respostas, lados=None):
        self.respostas = list(respostas)
        self.lados = {"lados": []} if lados is None else lados
        self.chamadas = []    # as do episódio: geração e revisão
        self.analises = []
        self.ultimo_uso = {}

    def chat_json(self, *args, **kwargs):
        self.ultimo_uso = {"prompt": sum(map(len, args)) // 4, "saida": 2000}
        if args[0] == PROMPT_LADOS:
            self.analises.append((args, kwargs))
            return self.lados
        self.chamadas.append((args, kwargs))
        return self.respostas.pop(0)


@pytest.fixture
def ollama_8192(monkeypatch):
    monkeypatch.setattr(summarizer, "settings", SimpleNamespace(
        llm_provider="ollama", ollama_num_ctx=8192, ollama_num_predict=10240, llm_reserva_saida=3000,
        llm_max_prompt_chars=4096,
    ))


# ── Fonte única ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("caracteres", [900, 5000, 12000])
def test_fonte_unica_leva_o_bloco_de_lados_antes_do_lembrete(caracteres, ollama_8192):
    principal = {"source": "G1", "title": "Um  título\tcom espaços", "text": "\x00Sujeira  no começo.\n\n\n\n" + _texto(caracteres)}
    sem_bloco = _entrada_antiga(principal)
    limite = Summarizer(provider=ProviderFalso())._limite_da_entrada(PROMPT_SISTEMA)    # o limite real de num_ctx=8192

    # sem os lados, a entrada é a de sempre: o limite não chega a cortar um texto de fonte única
    assert montar_entrada(principal).texto == montar_entrada(principal, [], limite).texto == sem_bloco
    assert montar_entrada(principal).fontes == ["G1"]

    um_lado = lado_unico(["G1"])
    entrada = montar_entrada(principal, None, limite, um_lado)
    assert entrada.texto == sem_bloco.removesuffix(LEMBRETE) + bloco_dos_lados(um_lado) + "\n" + LEMBRETE
    assert entrada.textos == montar_entrada(principal, None, limite).textos == [
        {"fonte": "G1", "titulo": "Um título com espaços", "texto": cortar_em_paragrafo(summarizer._limpar(principal["text"]), 5000)}
    ]
    assert len(entrada.textos[0]["texto"]) <= 5000                      # o teto do principal vale mesmo com espaço sobrando


def test_fonte_unica_que_nao_cabe_e_cortada_em_fim_de_paragrafo():
    principal = _artigo("G1", 9000)
    entrada = montar_entrada(principal, limite=2500, reserva=MAX_BLOCO)
    assert len(entrada.texto) <= 2500 - MAX_BLOCO and entrada.texto.endswith(LEMBRETE)
    trecho = entrada.texto.split("Texto:\n")[1].removesuffix("\n" + LEMBRETE)
    assert principal["text"].startswith(trecho + "\n\n")
    assert entrada.cortes == [{"fonte": "G1", "texto": len(principal["text"]), "incluido": len(trecho)}]
    # sem a reserva e sem o bloco, o texto fica com o espaço todo
    assert len(trecho) + 1000 < len(montar_entrada(principal, limite=2500).textos[0]["texto"]) <= 2500


# ── Orçamento com relacionados ────────────────────────────────────────────────────────────

def test_reparticao_da_metade_ao_principal_e_repassa_a_sobra():
    assert _repartir([5000, 3000, 3000], 20000) == [5000, 3000, 3000]          # tudo cabe: ninguém é cortado
    assert _repartir([5000, 3000, 3000], 6000) == [3000, 1500, 1500]
    assert _repartir([1000, 3000, 3000], 6000) == [1000, 2500, 2500]           # o principal devolve o que não usa
    assert _repartir([5000, 200, 3000], 6000) == [3866, 200, 1933]             # a sobra de um relacionado vai para os outros
    assert _repartir([5000, 3000], 4000) == [2000, 2000]
    assert _repartir([9000], 4000) == [4000]


@pytest.mark.parametrize("limite", [2300 + MAX_BLOCO, 5000, 8000, 11000, 30000])   # o menor ainda dá para os três textos
def test_partes_fixas_ficam_inteiras_e_o_total_cabe_no_limite(limite):
    principal = _artigo("Valor", 9000)
    relacionados = [_artigo("G1", 6000, relacao="mesmo_acontecimento"), _artigo("Folha", 6000, relacao="mesmo_acontecimento")]
    entrada = montar_entrada(principal, relacionados, limite, reserva=MAX_BLOCO)

    assert len(entrada.texto) <= limite - MAX_BLOCO
    assert entrada.texto.startswith("ARTIGO PRINCIPAL\nFonte: Valor\nTítulo: Título de Valor\nTexto:\nParágrafo 1 de Valor.")
    assert "\n\nARTIGO RELACIONADO [1]\nFonte: G1\nTítulo: Título de G1\nTrecho:\nParágrafo 1 de G1." in entrada.texto
    assert "\n\nARTIGO RELACIONADO [2]\nFonte: Folha\nTítulo: Título de Folha\nTrecho:\nParágrafo 1 de Folha." in entrada.texto
    assert ("\n\nAVISO DO EDITOR-CHEFE: há 3 textos de 3 veículos sobre este assunto (Folha, G1, Valor). "
            "Cite cada veículo pelo nome.\n") in entrada.texto
    assert entrada.texto.endswith("\n" + LEMBRETE)
    # cada texto termina num fim de parágrafo do original
    for artigo, corte in zip([principal, *relacionados], entrada.cortes):
        assert corte["incluido"] == len(artigo["text"][:corte["incluido"]].rstrip())
        assert artigo["text"][corte["incluido"]:corte["incluido"] + 2] in ("\n\n", "") or corte["incluido"] in (5000, 3000)
    if limite < 11000:
        principal_cabe, g1_cabe, folha_cabe = (c["incluido"] for c in entrada.cortes)
        assert principal_cabe > g1_cabe and abs(g1_cabe - folha_cabe) <= 450      # ~metade para o principal

    # com os lados e a mesma reserva, o bloco entra no espaço guardado: os trechos são os mesmos e o total cabe no limite
    tres_lados = [Lado("Uma posição bem comprida. " * 20, (f"Ator {i}", "Outro Ator"), ("Valor", "G1", "Folha")) for i in range(3)]
    com_lados = montar_entrada(principal, relacionados, limite, tres_lados, reserva=MAX_BLOCO)
    assert len(com_lados.texto) <= limite and com_lados.textos == entrada.textos and com_lados.cortes == entrada.cortes
    assert com_lados.texto.endswith(bloco_dos_lados(tres_lados) + "\n" + LEMBRETE)
    # sem `reserva`, o orçamento guarda o tamanho que o bloco tem: sobra mais espaço para os textos
    bloco = bloco_dos_lados(tres_lados)
    no_tamanho = montar_entrada(principal, relacionados, limite, tres_lados)
    assert len(no_tamanho.texto) <= limite and no_tamanho.texto.endswith(bloco + "\n" + LEMBRETE)
    assert no_tamanho.textos == montar_entrada(principal, relacionados, limite, reserva=len(bloco)).textos
    assert sum(c["incluido"] for c in no_tamanho.cortes) >= sum(c["incluido"] for c in entrada.cortes)
    assert [t["fonte"] for t in entrada.textos] == ["Valor", "G1", "Folha"]
    assert all(t["texto"] and t["texto"] in entrada.texto for t in entrada.textos)


def test_sem_aperto_os_textos_vao_ate_o_teto_de_cada_um_em_fim_de_paragrafo():
    principal, relacionado = _artigo("Valor", 9000), _artigo("G1", 6000)
    entrada = montar_entrada(principal, [relacionado], limite=None)
    assert [t["texto"] for t in entrada.textos] == [cortar_em_paragrafo(principal["text"], 5000), cortar_em_paragrafo(relacionado["text"], 3000)]
    assert [4500 < c["incluido"] <= teto for c, teto in zip(entrada.cortes, (5000, 3000))] == [True, False]
    assert 2600 < entrada.cortes[1]["incluido"] <= 3000


def test_aviso_conta_e_nomeia_so_os_relacionados_que_entraram():
    principal = _artigo("Valor", 3000)
    tres = [_artigo("G1", 2000), _artigo("Folha", 2000), _artigo("Estadão", 2000)]

    entrada = montar_entrada(principal, tres, limite=None)                       # só cabem dois relacionados na entrada
    assert entrada.fontes == ["Valor", "G1", "Folha"] and "Estadão" not in entrada.texto
    assert "há 3 textos de 3 veículos sobre este assunto (Folha, G1, Valor)" in entrada.texto
    assert [c["incluido"] > 0 for c in entrada.cortes] == [True, True, True, False]

    apertada = montar_entrada(principal, tres, limite=1900)                      # o orçamento só dá para um relacionado
    assert apertada.fontes == ["Valor", "G1"] and len(apertada.texto) <= 1900
    assert "há 2 textos de 2 veículos sobre este assunto (G1, Valor)" in apertada.texto
    assert "ARTIGO RELACIONADO [2]" not in apertada.texto and "Folha" not in apertada.texto

    so_o_principal = montar_entrada(principal, tres, limite=1000)                # nem um relacionado: some o aviso
    assert so_o_principal.fontes == ["Valor"] and "AVISO DO EDITOR-CHEFE" not in so_o_principal.texto


def test_aviso_de_mesmo_veiculo_e_de_desdobramento():
    principal = _artigo("Agência Brasil", 1000, data=datetime.datetime(2026, 10, 11, 15, 13, tzinfo=UTC))
    anterior = datetime.datetime(2026, 10, 10, 20, 28, tzinfo=UTC)

    do_mesmo = montar_entrada(principal, [_artigo("agência brasil", 1000, relacao="mesmo_acontecimento", data=anterior)]).texto
    assert "há 2 textos do mesmo veículo sobre este assunto (Agência Brasil). Cite-o como uma fonte só.\n" in do_mesmo
    assert "ordem cronológica" not in do_mesmo

    resposta = montar_entrada(principal, [_artigo("CartaCapital", 1000, relacao="desdobramento", data=anterior)]).texto
    assert "(Agência Brasil, CartaCapital). Cite cada veículo pelo nome. Os textos relatam" in resposta
    assert "divergência" not in resposta.lower() and "divergência" not in do_mesmo.lower()   # os lados vêm no bloco, não no aviso
    assert ("narre os fatos em ordem cronológica (CartaCapital, 10/10 17:28; Agência Brasil, 11/10 12:13).") in resposta

    sem_datas = montar_entrada(_artigo("G1", 1000), [_artigo("Folha", 1000, relacao="desdobramento")]).texto
    assert sem_datas.count("narre os fatos em ordem cronológica.") == 1


# ── Limite da entrada e proporção medida ──────────────────────────────────────────────────

def test_limite_no_ollama_desconta_reserva_margem_e_prompt_de_sistema(ollama_8192):
    s = Summarizer(provider=ProviderFalso())
    assert s._limite_da_entrada(PROMPT_SISTEMA) == int((8192 - 3000 - 256) * 3.0) - len(PROMPT_SISTEMA)
    assert s._limite_da_entrada(PROMPT_REVISOR, extra=7000) == int((8192 - 3000 - 256) * 3.0) - len(PROMPT_REVISOR) - 7000
    # a chamada que limita a própria saída reserva só isso: é o caso da análise de lados
    assert s._limite_da_entrada(PROMPT_LADOS, saida=MAX_SAIDA_LADOS) == int((8192 - 1200 - 256) * 3.0) - len(PROMPT_LADOS)

    summarizer.settings.ollama_num_predict = 2000        # num_predict menor que a reserva: vale ele
    assert s._limite_da_entrada("") == int((8192 - 2000 - 256) * 3.0)

    summarizer.settings.llm_provider = "openai"          # no caminho OpenAI o limite é LLM_MAX_PROMPT_CHARS
    assert s._limite_da_entrada(PROMPT_SISTEMA, extra=96) == 4000


def test_proporcao_de_caracteres_por_token_vem_do_que_o_provider_mediu(ollama_8192):
    provider = ProviderFalso({}, {}, {})
    s = Summarizer(provider=provider)
    assert s.chars_por_token == 3.0                      # antes de medir: conservador

    s._chamar("s" * 1000, "u" * 3000)                    # 4000 caracteres, 1000 tokens
    assert s.chars_por_token == pytest.approx(4.0 * 0.9)
    provider.chat_json = lambda system, user: provider.__dict__.update(ultimo_uso={"prompt": 2000}) or {}
    s._chamar("s" * 1000, "u" * 5000)                    # 3 caracteres por token: fica a menor medida
    assert s.chars_por_token == pytest.approx(3.0 * 0.9)
    provider.chat_json = lambda system, user: provider.__dict__.update(ultimo_uso={}) or {}
    s._chamar("s" * 1000, "u" * 9000)                    # provider sem contagem: nada muda
    assert s.chars_por_token == pytest.approx(3.0 * 0.9)


# ── process ───────────────────────────────────────────────────────────────────────────────

def test_process_de_fonte_unica_analisa_os_lados_e_gera_com_o_bloco(ollama_8192):
    principal = _artigo("G1", 3000)
    episodio = _episodio(["G1"])
    provider = ProviderFalso(episodio)          # a análise de lados responde algo inválido duas vezes: lado de emergência
    s = Summarizer(provider=provider)

    assert s.process(principal) is episodio
    um_lado = lado_unico(["G1"])
    com_bloco = _entrada_antiga(principal).removesuffix(LEMBRETE) + bloco_dos_lados(um_lado) + "\n" + LEMBRETE
    assert provider.chamadas == [((PROMPT_SISTEMA, com_bloco), {})]                       # a geração segue sem argumentos novos
    ((sistema, entrada), opcoes), ((_, nova_tentativa), _) = provider.analises
    assert sistema == PROMPT_LADOS and opcoes == {"chaves": ("lados",), "temperatura": 0.1, "max_saida": 1200}
    assert entrada == entrada_dos_lados([{"fonte": "G1", "titulo": "Título de G1", "texto": principal["text"]}])
    assert nova_tentativa.startswith(entrada + "\n\nCORREÇÃO: a sua resposta anterior não valeu: resposta com 0 lados")
    assert "\nLado 1: relato dos fatos, sem lados definidos. Veículos: G1.\n" in com_bloco
    assert s.ultimo_diagnostico["lados"].lados == um_lado and s.ultimo_diagnostico["lados"].problemas
    assert s.ultimo_diagnostico["problemas"] == [] and s.ultimo_diagnostico["revisao"] is None


def test_process_com_dois_veiculos_cobra_as_fontes_e_revisa_dentro_do_orcamento(ollama_8192):
    principal = _artigo("O Globo", 9000)
    relacionados = [_artigo("G1", 6000, relacao="desdobramento"), _artigo("Agência Brasil", 6000, relacao="desdobramento")]
    sem_uma_fonte, completo = _episodio(["O GLOBO", "g1"]), _episodio(["O Globo", "G1", "Agência Brasil"])
    provider = ProviderFalso(sem_uma_fonte, completo)
    s = Summarizer(provider=provider)

    assert s.process(principal, relacionados) is completo
    (sistema, entrada), (revisor, revisao) = (args for args, _ in provider.chamadas)
    assert (sistema, revisor) == (PROMPT_SISTEMA, PROMPT_REVISOR)
    # o limite da geração é calculado depois da análise, já com a proporção que ela mediu (4 caracteres por token × 0,9)
    assert len(entrada) <= int((8192 - 3000 - 256) * 3.6) - len(PROMPT_SISTEMA)
    trechos = s.ultimo_diagnostico["entrada"].textos
    assert [len(t["texto"]) for t in trechos] < [5000, 3000, 3000] and all(t["texto"] in entrada for t in trechos)
    # a análise de lados lê os textos inteiros; estes 21 mil caracteres não cabem na chamada dela e foram cortados, com o registro
    completos = textos_da_pauta(principal, relacionados)
    espaco = int((8192 - 1200 - 256) * 3.0) - len(PROMPT_LADOS)
    lidos, cortes = textos_que_cabem(completos, espaco)
    assert provider.analises[0][0][1] == entrada_dos_lados(lidos) and len(provider.analises[0][0][1]) <= espaco
    analise = s.ultimo_diagnostico["lados"]                           # inválida duas vezes: a nova tentativa leva o pedido e lê menos texto
    assert analise.primeira.cortes == cortes and [c["lido"] > 3000 for c in cortes] == [True, True, True]
    # o corte é em fim de parágrafo: com o pedido, a nova tentativa cabe no mesmo espaço e não lê mais que a primeira
    assert sum(c["lido"] for c in analise.cortes) <= sum(c["lido"] for c in cortes) and len(provider.analises[1][0][1]) <= espaco
    assert "\nLADOS DA PAUTA: 1 lado.\n" in entrada and "\nLADOS DA PAUTA: 1 lado.\n" in revisao
    assert s.ultimo_diagnostico["problemas"] == [
        "fontes_citadas sem Agência Brasil (o episódio tem 3 veículos como fonte: cite cada um pelo nome no "
        "roteiro e liste todos em fontes_citadas)"
    ]
    assert revisao.startswith("ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\nARTIGO PRINCIPAL\n")
    assert "\n\nPROBLEMAS DETECTADOS:\n- fontes_citadas sem Agência Brasil" in revisao
    assert revisao.endswith("\n\nEPISÓDIO ORIGINAL:\n" + json.dumps(sem_uma_fonte, ensure_ascii=False))
    # a revisão leva o episódio original e cabe na janela pela proporção já medida (4 caracteres por token × 0,9)
    assert len(revisor) + len(revisao) <= int((8192 - 3000 - 256) * 3.6)
    assert s.ultimo_diagnostico["problemas_da_revisao"] == []


def test_process_com_dois_lados_exige_um_analista_por_lado(ollama_8192):
    dois_lados = {"questao": "A Meta favoreceu um candidato?", "respostas_por_ator": [   # trechos de _artigos_da_meta
        {"ator": "campanha de Lula", "resposta": "Sim", "trecho": "A campanha de Lula acusa a empresa", "veiculo": "CartaCapital"},
        {"ator": "Meta", "resposta": "Não", "trecho": "A Meta nega o favorecimento", "veiculo": "Agência Brasil"},
    ], "lados": [
        {"resposta": "Sim", "posicao": "A campanha acusa a Meta.", "atores": ["campanha de Lula"], "veiculos": ["CartaCapital"]},
        {"resposta": "Não", "posicao": "A Meta nega.", "atores": ["Meta"], "veiculos": ["Agência Brasil"]},
    ], "motivo": "Acusação contra defesa."}
    um_analista = _episodio(["Agência Brasil", "CartaCapital"])
    terco = " ".join(["palavra"] * max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 3)))
    debate = {
        **um_analista, "houve_divergencia": True,
        "personagens": [{"nome": "Helena"}, {"nome": "Bia"}, {"nome": "Ramos"}],
        "roteiro_podcast": [
            {"personagem": "Helena", "fala": terco},
            {"personagem": "Bia", "fala": terco + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
            {"personagem": "Ramos", "fala": terco + ". Já a Agência Brasil registra que a Meta nega."},
        ],
    }
    provider = ProviderFalso(um_analista, debate, lados=dois_lados)
    s = Summarizer(provider=provider)

    assert s.process(*_artigos_da_meta()) is debate
    assert [lado.atores for lado in s.ultimo_diagnostico["lados"].lados] == [("campanha de Lula",), ("Meta",)]
    assert s.ultimo_diagnostico["problemas"] == [
        "1 analista(s) (Ramos) para 2 lado(s): o elenco é Helena e exatamente 2 analista(s), um por lado",
        "houve_divergencia tem de ser true: a pauta tem 2 lado(s), e o campo é true se e só se houver 2 lados ou mais",
    ]
    (_, entrada), (_, revisao) = (args for args, _ in provider.chamadas)
    for mensagem in (entrada, revisao):                                   # o bloco vai na geração e na revisão
        assert ("\nLADOS DA PAUTA: 2 lados.\nQUESTÃO: A Meta favoreceu um candidato?\n"
                "Lado 1 (resposta: Sim): A campanha acusa a Meta. Atores: campanha de Lula. Veículos: CartaCapital.\n") in mensagem
        assert 'ELENCO: Helena e exatamente 2 analistas, um por lado; "houve_divergencia": true.' in mensagem
    assert len(provider.analises) == 1                                    # os lados são analisados uma vez só, antes da geração


def test_process_com_ressalva_cobra_a_pergunta_atribuida_da_helena(ollama_8192):
    um_lado_e_uma_ressalva = {"questao": "A flexibilização é boa para o Brasil?", "respostas_por_ator": [
        {"ator": "Flávio Bolsonaro", "resposta": "Sim", "trecho": "Flávio Bolsonaro defende flexibilizar o Mercosul", "veiculo": "G1"},
    ], "lados": [
        {"resposta": "Sim", "posicao": "Flávio propõe flexibilizar o Mercosul.", "atores": ["Flávio Bolsonaro"], "grupos": [], "veiculos": ["G1"]},
        {"resposta": "Não", "posicao": "A mudança pode enfraquecer a tarifa comum.", "atores": [], "grupos": ["economistas"],
         "trecho": "economistas alertam para o risco", "veiculos": ["G1"]},
    ]}
    sem_pergunta = _episodio(["G1"])
    roteiro = json.loads(json.dumps(sem_pergunta["roteiro_podcast"]))
    roteiro[0]["fala"] += " Segundo o G1, economistas alertam que a tarifa comum pode enfraquecer. Como você vê isso?"
    provider = ProviderFalso(sem_pergunta, {"roteiro_podcast": roteiro}, lados=um_lado_e_uma_ressalva)
    s = Summarizer(provider=provider)
    principal = _artigo("G1", 2000)
    principal["text"] += "\n\nFlávio Bolsonaro defende flexibilizar o Mercosul. No entanto, economistas alertam para o risco."

    episodio = s.process(principal)                                          # um lado e uma ressalva: um analista, sem divergência
    assert episodio == {**sem_pergunta, "roteiro_podcast": roteiro}          # só o roteiro mudou
    analise = s.ultimo_diagnostico["lados"]
    assert len(analise.lados) == 1 and analise.questao == "" and [r.grupos for r in analise.ressalvas] == [("economistas",)]
    [problema] = s.ultimo_diagnostico["problemas"]
    assert problema.startswith("ressalva 1 (economistas; G1): não aparece numa frase da Helena")
    assert s.ultimo_diagnostico["correcao"] == "roteiro" and s.ultimo_diagnostico["problemas_da_revisao"] == []
    (_, entrada), (_, revisao) = (args for args, _ in provider.chamadas)
    for mensagem in (entrada, revisao):                                      # a ressalva vai no bloco, na geração e na revisão
        assert "\nRessalva 1: A mudança pode enfraquecer a tarifa comum. Grupos: economistas. Veículos: G1.\n" in mensagem
    assert len(provider.analises) == 1


# ── Recorte por relevância ────────────────────────────────────────────────────────────────

FIM_DA_AB = "No fim do texto, a Meta negou o favorecimento. A Meta falou em problema técnico."
FIM_DA_CARTA = "No fim do texto, a campanha de Lula acusou a empresa. A campanha de Lula acionou o tribunal."
DISPUTA_NO_FIM = {"questao": "A Meta favoreceu um candidato?", "respostas_por_ator": [
    {"ator": "campanha de Lula", "resposta": "Sim", "trecho": "a campanha de Lula acusou a empresa", "veiculo": "CartaCapital"},
    {"ator": "Meta", "resposta": "Não", "trecho": "a Meta negou o favorecimento", "veiculo": "Agência Brasil"},
], "lados": [
    {"resposta": "Sim", "posicao": "A campanha acusa a Meta.", "atores": ["campanha de Lula"], "veiculos": ["CartaCapital"]},
    {"resposta": "Não", "posicao": "A Meta nega.", "atores": ["Meta"], "veiculos": ["Agência Brasil"]},
]}


def _pauta_com_as_posicoes_no_fim() -> tuple[dict, list[dict]]:
    """Dois artigos em que a posição de cada lado só aparece no último parágrafo, depois do teto do texto."""
    principal, relacionado = _artigo("Agência Brasil", 6500), _artigo("CartaCapital", 4500)
    principal["text"] += "\n\n" + FIM_DA_AB
    relacionado["text"] += "\n\n" + FIM_DA_CARTA
    return principal, [relacionado]


def _debate(fontes: list[str]) -> dict:
    """Episódio de dois analistas que passa no QA da pauta da Meta."""
    terco = " ".join(["palavra"] * max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 3)))
    return {
        **_episodio(fontes), "houve_divergencia": True,
        "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Bia", "papel": "analista"}, {"nome": "Ramos", "papel": "analista"}],
        "roteiro_podcast": [
            {"personagem": "Helena", "fala": terco},
            {"personagem": "Bia", "fala": terco + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
            {"personagem": "Ramos", "fala": terco + ". Já a Agência Brasil registra que a Meta nega."},
        ],
    }


def test_a_analise_le_os_textos_inteiros_e_a_geracao_recebe_os_paragrafos_dos_trechos(ollama_8192):
    principal, relacionados = _pauta_com_as_posicoes_no_fim()
    provider = ProviderFalso(lados=DISPUTA_NO_FIM)
    s = Summarizer(provider=provider)
    entrada, analise = s.preparar(principal, relacionados)

    # a análise recebeu os dois textos inteiros, além do teto de cada um na geração (5000 e 3000)
    [((_, lido), _)] = provider.analises
    assert lido == entrada_dos_lados(textos_da_pauta(principal, relacionados)) and FIM_DA_AB in lido and FIM_DA_CARTA in lido
    assert len(principal["text"]) > 6500 and analise.cortes == [] and [e.comprovada for e in analise.respostas] == [True, True]

    # a geração recebe de cada texto o começo e, depois da marca, o parágrafo do trecho de evidência
    da_ab, da_carta = (t["texto"] for t in entrada.textos)
    assert da_ab.startswith("Parágrafo 1 de Agência Brasil.") and da_ab.endswith("\n[...]\n" + FIM_DA_AB) and len(da_ab) <= 5000
    assert da_carta.startswith("Parágrafo 1 de CartaCapital.") and da_carta.endswith("\n[...]\n" + FIM_DA_CARTA) and len(da_carta) <= 3000
    assert da_ab in entrada.texto and da_carta in entrada.texto and len(entrada.texto) <= s._limite_da_entrada(PROMPT_SISTEMA)
    ab, carta = entrada.recortes
    assert (ab["fonte"], carta["fonte"]) == ("Agência Brasil", "CartaCapital") and ab["fora"] == carta["fora"] == []
    assert [e["motivo"] for e in ab["entraram"][:3]] == ["lide", "lide", "ordem do texto"]
    assert ab["entraram"][-1] == {"paragrafo": ab["paragrafos"], "motivo": "trecho do lado 2", "caracteres": len(FIM_DA_AB)}
    assert carta["entraram"][-1] == {"paragrafo": carta["paragrafos"], "motivo": "trecho do lado 1", "caracteres": len(FIM_DA_CARTA)}
    assert entrada.cortes == [{"fonte": "Agência Brasil", "texto": len(principal["text"]), "incluido": len(da_ab)},
                              {"fonte": "CartaCapital", "texto": len(relacionados[0]["text"]), "incluido": len(da_carta)}]
    # os atores aparecem em duas frases do recorte: nenhum lado é fino, e o bloco ocupa o tamanho que tem
    assert [lado.mencoes for lado in analise.lados] == [2, 2] and "lado fino" not in entrada.texto
    assert entrada.texto.endswith(bloco_dos_lados(analise.lados, analise.questao) + "\n" + LEMBRETE)


def test_o_lado_fino_e_contado_no_recorte_que_a_geracao_recebe(ollama_8192):
    principal, relacionados = _pauta_com_as_posicoes_no_fim()
    # a Meta aparece em mais três frases do texto, em parágrafos que ficam depois do teto e não têm trecho de evidência
    principal["text"] = principal["text"].replace(FIM_DA_AB, "A Meta divulgou nota.\n\nA Meta citou números.\n\nNo fim do texto, a Meta negou o favorecimento.")
    s = Summarizer(provider=ProviderFalso(lados=DISPUTA_NO_FIM))
    entrada, analise = s.preparar(principal, relacionados)
    assert entrada.textos[0]["texto"].endswith("\n[...]\nNo fim do texto, a Meta negou o favorecimento.")
    assert "A Meta divulgou nota." not in entrada.texto
    assert [(lado.atores, lado.mencoes, lado.fino) for lado in analise.lados] == [(("campanha de Lula",), 2, False), (("Meta",), 1, True)]
    assert "Lado 2 (resposta: Não; lado fino): A Meta nega." in entrada.texto and len(entrada.texto) <= s._limite_da_entrada(PROMPT_SISTEMA)


def test_paragrafo_com_trecho_que_nao_cabe_fica_registrado_e_avisado(caplog):
    principal, relacionados = _pauta_com_as_posicoes_no_fim()
    comprido = "A campanha de Lula acusou a empresa de favorecer o adversário. " + "Mais uma frase do mesmo parágrafo. " * 30
    relacionados[0]["text"] = relacionados[0]["text"].replace(FIM_DA_CARTA, comprido.strip())
    lados = [Lado("A campanha acusa a Meta.", ("campanha de Lula",), ("CartaCapital",), "Sim", ("a campanha de Lula acusou a empresa",)),
             Lado("A Meta nega.", ("Meta",), ("Agência Brasil",), "Não", ("a Meta negou o favorecimento",))]
    ressalvas = [Ressalva(("economistas",), "Há risco.", ("Agência Brasil",), "A Meta falou em problema técnico")]
    with caplog.at_level("WARNING", logger="techdigest.ai.summarizer"):
        entrada = montar_entrada(principal, relacionados, 4200, lados, "A Meta favoreceu um candidato?", ressalvas)
    assert len(entrada.texto) <= 4200 and entrada.fontes == ["Agência Brasil", "CartaCapital"]
    ab, carta = entrada.recortes
    # o parágrafo do fim da Agência Brasil traz o trecho do lado 2 e o da ressalva; o da CartaCapital não coube
    assert ab["entraram"][-1]["motivo"] == "trecho do lado 2; trecho da ressalva 1" and ab["fora"] == []
    assert carta["fora"] == [{"paragrafo": carta["paragrafos"], "motivo": "trecho do lado 1", "caracteres": len(comprido.strip())}]
    assert all(e["motivo"] in ("lide", "ordem do texto") for e in carta["entraram"])
    assert (f"Parágrafo(s) com trecho de evidência fora da entrada (CartaCapital): §{carta['paragrafos']}, trecho do lado 1, "
            f"{len(comprido.strip())} caracteres.") in caplog.text

    # com menos espaço ainda, o relacionado sai da entrada: o registro diz que o parágrafo do trecho dele ficou de fora
    fixos = len(entrada.texto) - sum(c["incluido"] for c in entrada.cortes)      # cabeçalhos, aviso, bloco e lembrete
    so_o_principal = montar_entrada(principal, relacionados, fixos + 700, lados, "A Meta favoreceu um candidato?", ressalvas)
    assert so_o_principal.fontes == ["Agência Brasil"] and len(so_o_principal.texto) <= fixos + 700
    assert so_o_principal.recortes[1]["entraram"] == [] and [f["motivo"] for f in so_o_principal.recortes[1]["fora"]] == ["trecho do lado 1"]


@pytest.mark.parametrize("tipo, prompt", [("roteiro", PROMPT_ROTEIRO), ("completa", PROMPT_REVISOR)], ids=["roteiro", "completa"])
def test_as_revisoes_levam_o_recorte_por_relevancia_no_espaco_de_cada_uma(tipo, prompt, ollama_8192):
    principal, relacionados = _pauta_com_as_posicoes_no_fim()
    debate = _debate(["Agência Brasil", "CartaCapital"])
    reprovado = json.loads(json.dumps(debate))
    if tipo == "roteiro":
        reprovado["roteiro_podcast"][2]["fala"] = "A Agência Brasil registra que a Meta nega."            # Ramos fala pouco: problema só no roteiro
    else:
        reprovado["fontes_citadas"] = ["Agência Brasil"]                                                 # campo sem correção própria
    provider = ProviderFalso(reprovado, debate if tipo == "completa" else {"roteiro_podcast": debate["roteiro_podcast"]}, lados=DISPUTA_NO_FIM)
    s = Summarizer(provider=provider)

    assert s.process(principal, relacionados) == debate
    diagnostico = s.ultimo_diagnostico
    assert diagnostico["correcao"] == tipo and diagnostico["problemas_da_revisao"] == []
    (_, geracao), (sistema, revisao) = (args for args, _ in provider.chamadas)
    assert sistema == prompt and len(sistema) + len(revisao) <= int((8192 - 3000 - 256) * 3.6)
    fonte = diagnostico["revisao"]
    # a revisão completa tem menos espaço que a geração, e mesmo assim leva o parágrafo do trecho de cada lado, depois da marca
    incluido, na_geracao = (sum(c["incluido"] for c in e.cortes) for e in (fonte, diagnostico["entrada"]))
    # (a do roteiro leva só o roteiro, e com o PROMPT_SISTEMA mais comprido pode levar mais texto que a geração)
    assert incluido < na_geracao if tipo == "completa" else incluido > 0
    for texto, fim in zip(fonte.textos, (FIM_DA_AB, FIM_DA_CARTA)):
        assert texto["texto"].endswith("\n[...]\n" + fim) and texto["texto"] in revisao
    assert [r["entraram"][-1]["motivo"] for r in fonte.recortes] == ["trecho do lado 2", "trecho do lado 1"]
    assert [r["fora"] for r in fonte.recortes] == [[], []]
    # o bloco é o mesmo da geração (os lados finos não são recontados) e ocupa o tamanho que tem
    bloco = bloco_dos_lados(diagnostico["lados"].lados, diagnostico["lados"].questao)
    assert bloco in geracao and bloco in revisao


# ── Quem diz o quê (item 4 de 19/10) ──────────────────────────────────────────────────────

def test_o_prompt_do_episodio_pede_atribuicao_e_nada_alem_do_que_os_textos_trazem():
    from techdigest.ai import prompt
    secao = prompt.PROMPT_SISTEMA.split("## QUEM DIZ O QUÊ")[1].split("## ENTRADA")[0]
    assert prompt.PROMPT_SISTEMA.index("## IDENTIDADE") < prompt.PROMPT_SISTEMA.index("## QUEM DIZ O QUÊ") < prompt.PROMPT_SISTEMA.index("## ENTRADA")
    assert "Acusação, crítica, opinião, avaliação e previsão são de quem as faz" in secao
    assert "o episódio mantém a ressalva, atribuída ao veículo" in secao and "A análise que o veículo faz em nome próprio" in secao
    # a regra de não acrescentar vale também para o "por que importa"
    assert 'Helena, os analistas e o "por_que_importa" não acrescentam avaliação, motivo, consequência' in secao
    assert "sem consequência ou previsão que eles não fazem" in prompt.PROMPT_SISTEMA
    assert "Helena não monta escolhas, dilemas ou contrapontos que os textos não fazem" in secao
    # a versão curta vale para as duas revisões, e a completa cobra também o "por que importa"
    curta = "Acusação, crítica, opinião e previsão ficam sempre atribuídas a quem as faz"
    assert curta in prompt.PROMPT_REVISOR and curta in prompt.PROMPT_ROTEIRO
    assert "O por_que_importa também não traz consequência ou previsão" in prompt.PROMPT_REVISOR


def test_os_exemplos_dos_prompts_nao_usam_veiculos_que_existem():
    # num prompt sobre atribuição, um veículo real é o nome que o modelo pode pôr num episódio em que ele não é fonte
    from techdigest.ai import prompt
    textos = [getattr(prompt, nome) for nome in dir(prompt) if nome.startswith(("PROMPT_", "_REGRAS"))]
    for real in ("Jornal do Vale", "Diário do Litoral"):
        assert not any(real in texto for texto in textos), real
    assert "Diário de Lagoa Quieta" in prompt.PROMPT_SISTEMA and "Correio de Serra Quieta" in prompt.PROMPT_SISTEMA


# ── Correções direcionadas ────────────────────────────────────────────────────────────────

def test_tipo_de_correcao_vem_dos_campos_dos_problemas():
    resumo, roteiro, titulo = qa.Problema(qa.RESUMO, "r"), qa.Problema(qa.ROTEIRO, "f"), qa.Problema(qa.TITULO, "t")
    papel = qa.Problema(qa.PAPEL, "p")
    assert summarizer.tipo_de_correcao([titulo]) == summarizer.tipo_de_correcao([titulo, titulo]) == "titulo"
    assert summarizer.tipo_de_correcao([resumo]) == summarizer.tipo_de_correcao([resumo, resumo]) == "resumo"
    assert summarizer.tipo_de_correcao([roteiro, roteiro]) == "roteiro"
    assert summarizer.tipo_de_correcao([papel]) == summarizer.tipo_de_correcao([papel, roteiro]) == "roteiro"   # o papel vai com o roteiro
    assert summarizer.tipo_de_correcao([resumo, roteiro]) == summarizer.tipo_de_correcao([titulo, resumo]) == "completa"   # mais de um campo
    assert summarizer.tipo_de_correcao([qa.Problema(qa.ELENCO, "e")]) == "completa"      # um campo só, mas sem correção própria
    assert summarizer.tipo_de_correcao([qa.Problema(qa.ESTRUTURA, "e")]) == "completa"


def test_problema_so_no_resumo_reescreve_so_o_resumo_com_os_mesmos_trechos(ollama_8192):
    curto = {**_episodio(["O Globo", "G1", "Agência Brasil"]), "resumo_didatico": "Uma frase. " * (qa.MIN_FRASES_RESUMO - 1)}
    novo = "Outra frase. " * qa.MIN_FRASES_RESUMO
    provider = ProviderFalso(curto, {"resumo_didatico": novo})
    s = Summarizer(provider=provider)
    principal = _artigo("O Globo", 9000)
    relacionados = [_artigo("G1", 6000, relacao="desdobramento"), _artigo("Agência Brasil", 6000, relacao="desdobramento")]

    assert s.process(principal, relacionados) == {**curto, "resumo_didatico": novo}      # o resto do episódio fica como estava
    diagnostico = s.ultimo_diagnostico
    assert diagnostico["correcao"] == "resumo" and diagnostico["problemas_da_revisao"] == []
    assert diagnostico["problemas"] == [f"resumo com {qa.MIN_FRASES_RESUMO - 1} frases (alvo {qa.MIN_FRASES_RESUMO}-{qa.MAX_FRASES_RESUMO})"]
    assert diagnostico["revisao"] is diagnostico["entrada"]                               # os textos são os da geração, no orçamento normal

    ((_, _), _), ((sistema, mensagem), opcoes) = provider.chamadas
    assert sistema == PROMPT_RESUMO and opcoes == {"chaves": ("resumo_didatico",), "max_saida": summarizer.MAX_SAIDA_RESUMO}
    assert mensagem == (
        "ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\n" + diagnostico["entrada"].artigos
        + "\n\nhouve_divergencia: false"
        + f"\n\nPROBLEMAS DETECTADOS:\n- {diagnostico['problemas'][0]}"
        + "\n\nRESUMO ORIGINAL:\n" + curto["resumo_didatico"]
    )
    assert all(t["texto"] in mensagem for t in diagnostico["entrada"].textos)
    assert "roteiro_podcast" not in mensagem and "LADOS DA PAUTA" not in mensagem and "LEMBRETE" not in mensagem
    assert len(mensagem) < len(provider.chamadas[0][0][1])                                # é uma chamada mais curta que a da geração


def test_problema_so_no_roteiro_reescreve_so_o_roteiro_com_os_mesmos_personagens(ollama_8192):
    curto = _episodio(["G1"])
    curto["roteiro_podcast"][1]["fala"] = " ".join(["palavra"] * (qa.MIN_POR_PERSONAGEM - 1))
    roteiro = _episodio(["G1"])["roteiro_podcast"]
    provider = ProviderFalso(curto, {"roteiro_podcast": roteiro})
    s = Summarizer(provider=provider)

    assert s.process(_artigo("G1", 3000)) == {**curto, "roteiro_podcast": roteiro}
    diagnostico = s.ultimo_diagnostico
    assert diagnostico["correcao"] == "roteiro" and diagnostico["problemas_da_revisao"] == []
    ((_, _), _), ((sistema, mensagem), opcoes) = provider.chamadas
    assert sistema == PROMPT_ROTEIRO and opcoes == {"chaves": ("roteiro_podcast",)}
    assert mensagem.startswith("ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\nARTIGO PRINCIPAL\n")
    assert "\nLADOS DA PAUTA: 1 lado.\n" in mensagem and summarizer.LEMBRETE_DO_ROTEIRO in mensagem
    assert summarizer.LEMBRETE not in mensagem and "resumo_didatico" not in mensagem      # só o roteiro, sem o episódio inteiro
    assert ('\n\nPERSONAGENS (os mesmos, com estes nomes):\n[{"nome": "Helena", "papel": "apresentadora"}, '
            '{"nome": "Ramos", "papel": "analista"}]\n\nPROBLEMAS DETECTADOS:\n- Ramos com ') in mensagem
    assert mensagem.endswith("\n\nROTEIRO ORIGINAL:\n" + json.dumps(curto["roteiro_podcast"], ensure_ascii=False))
    assert diagnostico["revisao"].cortes == [{"fonte": "G1", "texto": len(summarizer._limpar(_artigo("G1", 3000)["text"])),
                                              "incluido": diagnostico["revisao"].cortes[0]["incluido"]}]


def test_problema_so_no_titulo_reescreve_so_o_titulo_a_partir_do_resumo(ollama_8192):
    com_proporcao = {**_episodio(["G1"]), "titulo_reescrito": "Maioria das candidatas sofre ataques"}
    provider = ProviderFalso(com_proporcao, {"titulo_reescrito": "Candidatas sofrem ataques no primeiro turno"},
                             lados={"lados": [{"posicao": "Fato central.", "atores": ["Terra de Direitos", "Justiça Global"], "veiculos": ["G1"]}]})
    s = Summarizer(provider=provider)

    assert s.process(_artigo("G1", 3000)) == {**com_proporcao, "titulo_reescrito": "Candidatas sofrem ataques no primeiro turno"}
    diagnostico = s.ultimo_diagnostico
    assert diagnostico["correcao"] == "titulo" and diagnostico["problemas_da_revisao"] == [] and diagnostico["revisao"] is None
    ((_, _), _), ((sistema, mensagem), opcoes) = provider.chamadas
    assert sistema == PROMPT_TITULO and opcoes == {"chaves": ("titulo_reescrito",), "max_saida": summarizer.MAX_SAIDA_TITULO}
    assert mensagem == (
        "RESUMO:\n" + com_proporcao["resumo_didatico"]
        + "\n\nATORES: Terra de Direitos, Justiça Global"
        + f'\n\nTÍTULOS JÁ REPROVADOS:\n- "Maioria das candidatas sofre ataques": {diagnostico["problemas"][0]}'
    )
    assert diagnostico["problemas"][0].startswith("título com percentual ou proporção (Maioria)")
    assert "ARTIGO" not in mensagem and "roteiro_podcast" not in mensagem             # sem os textos e sem o resto do episódio
    assert diagnostico["titulos_reprovados"] == [{"titulo": "Maioria das candidatas sofre ataques", "motivos": diagnostico["problemas"]}]


def test_titulo_corrigido_que_ainda_reprova_ganha_uma_segunda_tentativa_com_os_dois_recusados(ollama_8192):
    # como no episódio 2 de 12/10/2026: a correção trocou "maioria" por "60 dos 102", outra proporção
    primeiro, segundo = "Mulheres concentram maioria dos casos de violência", "Mulheres são alvo de 60 dos 102 episódios de violência"
    com_proporcao = {**_episodio(["G1"]), "titulo_reescrito": primeiro,
                     "resumo_didatico": "Foram 102 episódios, e 60 tiveram mulheres como vítimas. " + "Uma frase. " * 7}
    lados = {"lados": [{"posicao": "Fato central.", "atores": ["Terra de Direitos"], "veiculos": ["G1"]}]}
    artigo = _artigo("G1", 3000)
    artigo["text"] += "\n\nForam 102 episódios, e 60 tiveram mulheres como vítimas."
    provider = ProviderFalso(com_proporcao, {"titulo_reescrito": segundo}, {"titulo_reescrito": "Mulheres são o principal alvo da violência política"}, lados=lados)
    s = Summarizer(provider=provider)

    assert s.process(artigo)["titulo_reescrito"] == "Mulheres são o principal alvo da violência política"
    diagnostico = s.ultimo_diagnostico
    assert diagnostico["correcao"] == "titulo" and diagnostico["problemas_da_revisao"] == []
    assert [r["titulo"] for r in diagnostico["titulos_reprovados"]] == [primeiro, segundo]
    (_, (sistema1, tentativa1), (sistema2, tentativa2)) = (args for args, _ in provider.chamadas)
    assert sistema1 == sistema2 == PROMPT_TITULO and segundo not in tentativa1
    assert tentativa2.startswith(tentativa1 + f'\n- "{segundo}": título com percentual ou proporção (60 dos 102)')   # leva os dois, cada um com o motivo

    # a segunda tentativa é a última: se ela também reprova, o item é pulado
    teimoso = ProviderFalso(com_proporcao, {"titulo_reescrito": segundo}, {"titulo_reescrito": "Metade das vítimas é mulher"}, lados=lados)
    with pytest.raises(QAReprovado, match="correção do título ainda reprovada pelo QA: .*Metade"):
        Summarizer(provider=teimoso).process(artigo)
    assert len(teimoso.chamadas) == 3


def test_papel_com_nome_de_ator_vai_para_a_revisao_do_roteiro_que_so_troca_o_papel(ollama_8192):
    dois_lados = {"questao": "A Meta favoreceu um candidato?", "respostas_por_ator": [   # trechos de _artigos_da_meta
        {"ator": "campanha de Lula", "resposta": "Sim", "trecho": "A campanha de Lula acusa a empresa", "veiculo": "CartaCapital"},
        {"ator": "Meta", "resposta": "Não", "trecho": "A Meta nega o favorecimento", "veiculo": "Agência Brasil"},
    ], "lados": [
        {"resposta": "Sim", "posicao": "A campanha acusa a Meta.", "atores": ["campanha de Lula"], "veiculos": ["CartaCapital"]},
        {"resposta": "Não", "posicao": "A Meta nega.", "atores": ["Meta"], "veiculos": ["Agência Brasil"]},
    ]}
    terco = " ".join(["palavra"] * max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 3)))
    roteiro = [
        {"personagem": "Helena", "fala": terco},
        {"personagem": "Bia", "fala": terco + ". Segundo a CartaCapital, a campanha de Lula acusa a empresa."},
        {"personagem": "Ramos", "fala": terco + ". Já a Agência Brasil registra que a Meta nega."},
    ]
    porta_voz = {
        **_episodio(["Agência Brasil", "CartaCapital"]), "houve_divergencia": True, "roteiro_podcast": roteiro,
        "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Bia", "papel": "analista da campanha de Lula"},
                        {"nome": "Ramos", "papel": "analista da Meta"}],
    }
    devolvido = {"roteiro_podcast": roteiro, "personagens": [
        {"nome": "Bia", "papel": "analista de política"}, {"nome": "Ramos", "papel": "analista de tecnologia"},
        {"nome": "Intruso", "papel": "analista"}, {"nome": "Helena", "papel": ""},
    ]}
    provider = ProviderFalso(porta_voz, devolvido, lados=dois_lados)
    s = Summarizer(provider=provider)

    episodio = s.process(*_artigos_da_meta())
    assert episodio["personagens"] == [                                               # os mesmos nomes, na mesma ordem: só o papel muda
        {"nome": "Helena", "papel": "apresentadora"}, {"nome": "Bia", "papel": "analista de política"},
        {"nome": "Ramos", "papel": "analista de tecnologia"},
    ]
    assert s.ultimo_diagnostico["correcao"] == "roteiro" and s.ultimo_diagnostico["problemas_da_revisao"] == []
    assert [p[:26] for p in s.ultimo_diagnostico["problemas"]] == ["papel de Bia com o nome de", "papel de Ramos com o nome d"[:26]]
    ((_, _), _), ((sistema, mensagem), opcoes) = provider.chamadas
    assert sistema == PROMPT_ROTEIRO and opcoes == {"chaves": ("roteiro_podcast",)}
    assert '"papel": "analista da Meta"' in mensagem and "papel de Ramos com o nome de um ator dos lados" in mensagem


def test_correcao_direcionada_que_nao_resolve_levanta_qareprovado(ollama_8192):
    curto = {**_episodio(["G1"]), "resumo_didatico": "Uma frase. " * (qa.MIN_FRASES_RESUMO - 1)}
    s = Summarizer(provider=ProviderFalso(curto, {"resumo_didatico": curto["resumo_didatico"]}))
    with pytest.raises(QAReprovado, match="correção do resumo ainda reprovada pelo QA"):
        s.process(_artigo("G1", 2000))
    assert s.ultimo_diagnostico["episodio"] == curto and s.ultimo_diagnostico["primeira_versao"] is curto

    sem_chave = Summarizer(provider=ProviderFalso(curto, {"outra": 1}))
    with pytest.raises(QAReprovado, match="correção do resumo falhou \\(KeyError"):
        sem_chave.process(_artigo("G1", 2000))


def test_a_lista_de_veiculos_nunca_chega_como_none_ao_qa(ollama_8192, monkeypatch):
    recebidos = []
    monkeypatch.setattr(
        summarizer, "problemas_com_campo",
        lambda result, veiculos, lados, ressalvas, textos: recebidos.append((veiculos, lados, ressalvas, len(textos))) or [],
    )

    Summarizer(provider=ProviderFalso(_episodio([]))).process(_artigo("G1", 2000))                 # como o pipeline chama: só o principal
    Summarizer(provider=ProviderFalso(_episodio([]))).process(_artigo("G1", 2000), [_artigo("Folha", 2000), _artigo("G1", 2000)])
    assert recebidos == [
        (["G1"], lado_unico(["G1"]), [], 1),                               # e os textos da pauta, um por artigo
        (["G1", "Folha", "G1"], lado_unico(["G1", "Folha"]), [], 3),
    ]
    with pytest.raises(TypeError):                                        # e não há mais valor padrão para esquecer a lista
        summarizer._qa(_episodio([]))


def test_process_levanta_qareprovado_se_a_revisao_tambem_falha(ollama_8192):
    s = Summarizer(provider=ProviderFalso(_episodio(["G1"]), _episodio(["G1"])))
    with pytest.raises(QAReprovado, match="fontes_citadas sem Folha"):
        s.process(_artigo("G1", 2000), [_artigo("Folha", 2000)])

"""Testes de ai/summarizer.py sem LLM: a entrada dentro do orçamento e o fluxo de process."""
import datetime
import json
import math
from types import SimpleNamespace

import pytest

from techdigest.ai import qa, summarizer
from techdigest.ai.prompt import PROMPT_REVISOR, PROMPT_SISTEMA
from techdigest.ai.summarizer import LEMBRETE, QAReprovado, Summarizer, _repartir, montar_entrada

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
    """A entrada de fonte única como era montada antes do orçamento, para comparar."""
    partes = [
        "ARTIGO PRINCIPAL\n"
        f"Fonte: {principal['source']}\n"
        f"Título: {summarizer._limpar(principal['title'])}\n"
        f"Texto:\n{summarizer._limpar(principal['text'])[:5000]}"
    ]
    partes.append(
        "\nLEMBRETE: só o JSON das 8 chaves. Roteiro com 600-1300 palavras "
        "no total, 240-480 por personagem, 14-24 turnos."
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


class ProviderFalso:
    """Devolve as respostas em fila e guarda o que recebeu; conta 1 token a cada 4 caracteres."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []
        self.ultimo_uso = {}

    def chat_json(self, *args, **kwargs):
        self.chamadas.append((args, kwargs))
        self.ultimo_uso = {"prompt": sum(map(len, args)) // 4, "saida": 2000}
        return self.respostas.pop(0)


@pytest.fixture
def ollama_8192(monkeypatch):
    monkeypatch.setattr(summarizer, "settings", SimpleNamespace(
        llm_provider="ollama", ollama_num_ctx=8192, ollama_num_predict=10240, llm_reserva_saida=3000,
        llm_max_prompt_chars=4096,
    ))


# ── Fonte única: igual a antes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("caracteres", [900, 5000, 12000])
def test_fonte_unica_sai_identica_a_de_antes_quando_cabe(caracteres, ollama_8192):
    principal = {"source": "G1", "title": "Um  título\tcom espaços", "text": "\x00Sujeira  no começo.\n\n\n\n" + _texto(caracteres)}
    antiga = _entrada_antiga(principal)

    assert montar_entrada(principal).texto == antiga
    assert montar_entrada(principal, [], limite=20000).texto == antiga
    assert Summarizer(provider=ProviderFalso())._montar_entrada(principal) == antiga   # com o limite real de num_ctx=8192
    assert montar_entrada(principal).fontes == ["G1"]


def test_fonte_unica_que_nao_cabe_e_cortada_em_fim_de_paragrafo():
    principal = _artigo("G1", 9000)
    entrada = montar_entrada(principal, limite=2500)
    assert len(entrada.texto) <= 2500 and entrada.texto.endswith(LEMBRETE)
    trecho = entrada.texto.split("Texto:\n")[1].removesuffix("\n" + LEMBRETE)
    assert principal["text"].startswith(trecho + "\n\n")
    assert entrada.cortes == [{"fonte": "G1", "texto": len(principal["text"]), "incluido": len(trecho)}]


# ── Orçamento com relacionados ────────────────────────────────────────────────────────────

def test_reparticao_da_metade_ao_principal_e_repassa_a_sobra():
    assert _repartir([5000, 3000, 3000], 20000) == [5000, 3000, 3000]          # tudo cabe: ninguém é cortado
    assert _repartir([5000, 3000, 3000], 6000) == [3000, 1500, 1500]
    assert _repartir([1000, 3000, 3000], 6000) == [1000, 2500, 2500]           # o principal devolve o que não usa
    assert _repartir([5000, 200, 3000], 6000) == [3866, 200, 1933]             # a sobra de um relacionado vai para os outros
    assert _repartir([5000, 3000], 4000) == [2000, 2000]
    assert _repartir([9000], 4000) == [4000]


@pytest.mark.parametrize("limite", [3500, 5000, 8000, 11000, 30000])
def test_partes_fixas_ficam_inteiras_e_o_total_cabe_no_limite(limite):
    principal = _artigo("Valor", 9000)
    relacionados = [_artigo("G1", 6000, relacao="mesmo_acontecimento"), _artigo("Folha", 6000, relacao="mesmo_acontecimento")]
    entrada = montar_entrada(principal, relacionados, limite)

    assert len(entrada.texto) <= limite
    assert entrada.texto.startswith("ARTIGO PRINCIPAL\nFonte: Valor\nTítulo: Título de Valor\nTexto:\nParágrafo 1 de Valor.")
    assert "\n\nARTIGO RELACIONADO [1]\nFonte: G1\nTítulo: Título de G1\nTrecho:\nParágrafo 1 de G1." in entrada.texto
    assert "\n\nARTIGO RELACIONADO [2]\nFonte: Folha\nTítulo: Título de Folha\nTrecho:\nParágrafo 1 de Folha." in entrada.texto
    assert ("\n\nAVISO DO EDITOR-CHEFE: há 3 textos de 3 veículos sobre este assunto (Folha, G1, Valor). Verifique se há "
            "divergência real entre os relatos; se houver, aplique a REGRA DE DIVERGÊNCIA.\n") in entrada.texto
    assert entrada.texto.endswith("\n" + LEMBRETE)
    # cada texto termina num fim de parágrafo do original
    for artigo, corte in zip([principal, *relacionados], entrada.cortes):
        assert corte["incluido"] == len(artigo["text"][:corte["incluido"]].rstrip())
        assert artigo["text"][corte["incluido"]:corte["incluido"] + 2] in ("\n\n", "") or corte["incluido"] in (5000, 3000)
    if limite < 11000:
        principal_cabe, g1_cabe, folha_cabe = (c["incluido"] for c in entrada.cortes)
        assert principal_cabe > g1_cabe and abs(g1_cabe - folha_cabe) <= 450      # ~metade para o principal


def test_sem_aperto_os_textos_vao_com_o_teto_de_sempre():
    entrada = montar_entrada(_artigo("Valor", 9000), [_artigo("G1", 6000)], limite=None)
    assert [c["incluido"] for c in entrada.cortes] == [5000, 3000]


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
    assert "há 2 textos do mesmo veículo sobre este assunto (Agência Brasil). Trate-os como uma fonte só" in do_mesmo
    assert "REGRA DE DIVERGÊNCIA" not in do_mesmo and "ordem cronológica" not in do_mesmo

    resposta = montar_entrada(principal, [_artigo("CartaCapital", 1000, relacao="desdobramento", data=anterior)]).texto
    assert "se houver, aplique a REGRA DE DIVERGÊNCIA." in resposta and "obrigatoriamente" not in resposta
    assert ("narre os fatos em ordem cronológica (CartaCapital, 10/10 17:28; Agência Brasil, 11/10 12:13).") in resposta

    sem_datas = montar_entrada(_artigo("G1", 1000), [_artigo("Folha", 1000, relacao="desdobramento")]).texto
    assert sem_datas.count("narre os fatos em ordem cronológica.") == 1


# ── Limite da entrada e proporção medida ──────────────────────────────────────────────────

def test_limite_no_ollama_desconta_reserva_margem_e_prompt_de_sistema(ollama_8192):
    s = Summarizer(provider=ProviderFalso())
    assert s._limite_da_entrada(PROMPT_SISTEMA) == int((8192 - 3000 - 256) * 3.0) - len(PROMPT_SISTEMA)
    assert s._limite_da_entrada(PROMPT_REVISOR, extra=7000) == int((8192 - 3000 - 256) * 3.0) - len(PROMPT_REVISOR) - 7000

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

def test_process_de_fonte_unica_chama_o_provider_como_antes(ollama_8192):
    principal = _artigo("G1", 3000)
    episodio = _episodio(["G1"])
    provider = ProviderFalso(episodio)
    s = Summarizer(provider=provider)

    assert s.process(principal) is episodio
    assert provider.chamadas == [((PROMPT_SISTEMA, _entrada_antiga(principal)), {})]   # sem argumentos novos
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
    assert len(entrada) <= int((8192 - 3000 - 256) * 3.0) - len(PROMPT_SISTEMA)
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


def test_process_levanta_qareprovado_se_a_revisao_tambem_falha(ollama_8192):
    s = Summarizer(provider=ProviderFalso(_episodio(["G1"]), _episodio(["G1"])))
    with pytest.raises(QAReprovado, match="fontes_citadas sem Folha"):
        s.process(_artigo("G1", 2000), [_artigo("Folha", 2000)])

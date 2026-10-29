"""Testes de ai/llm.py sem LLM: o parse das respostas e as opções que cada chamada envia ao Ollama."""
import json
from types import SimpleNamespace

import pytest

from techdigest.ai import llm

EPISODIO = {chave: "..." for chave in llm.REQUIRED_KEYS}
CHAVES_AGRUPADOR = {"grupos", "isolados"}


def test_parse_json_exige_por_padrao_as_8_chaves_do_episodio():
    assert llm.parse_json(json.dumps(EPISODIO)) == EPISODIO
    sem_roteiro = {k: v for k, v in EPISODIO.items() if k != "roteiro_podcast"}
    with pytest.raises(ValueError, match="roteiro_podcast"):
        llm.parse_json(json.dumps(sem_roteiro))


def test_parse_json_aceita_chaves_obrigatorias_personalizadas():
    veredito = {"grupos": [], "isolados": [1, 2], "motivo": "temas diferentes"}
    assert llm.parse_json(json.dumps(veredito), CHAVES_AGRUPADOR) == veredito
    with pytest.raises(ValueError, match="roteiro_podcast"):          # sem o parâmetro, continua valendo o episódio
        llm.parse_json(json.dumps(veredito))
    with pytest.raises(ValueError, match=r"\['isolados'\]"):
        llm.parse_json('{"grupos": []}', CHAVES_AGRUPADOR)
    assert llm.parse_json(json.dumps(EPISODIO), ()) == EPISODIO      # nenhuma chave obrigatória


def test_parse_json_tira_cercas_e_recusa_resposta_vazia_ou_quebrada():
    assert llm.parse_json('```json\n{"grupos": [], "isolados": []}\n```', CHAVES_AGRUPADOR) == {"grupos": [], "isolados": []}
    with pytest.raises(ValueError, match="VAZIA"):
        llm.parse_json("   ", CHAVES_AGRUPADOR)
    with pytest.raises(ValueError, match="JSON inválido"):
        llm.parse_json('{"grupos": [', CHAVES_AGRUPADOR)


class ClienteFalso:
    """Faz o papel do ollama.Client: guarda o que recebeu e devolve uma resposta pronta."""

    def __init__(self, conteudo: str, done_reason: str = "stop", saida_tok: int = 40):
        self.chamadas = []
        self._resposta = SimpleNamespace(
            message=SimpleNamespace(content=conteudo, thinking=None), done_reason=done_reason,
            prompt_eval_count=1200, eval_count=saida_tok, eval_duration=2_000_000_000, total_duration=9_000_000_000,
        )

    def chat(self, **kwargs):
        self.chamadas.append(kwargs)
        return self._resposta


@pytest.fixture
def ollama(monkeypatch):
    monkeypatch.setattr(llm, "_amostra_sistema", lambda: "")   # sem nvidia-smi nem /proc nos testes

    def criar(conteudo: str, **resposta) -> llm.OllamaProvider:
        provider = llm.OllamaProvider.__new__(llm.OllamaProvider)   # sem o construtor: não cria o cliente de rede
        provider.client = ClienteFalso(conteudo, **resposta)
        provider.model = "modelo-de-teste"
        provider.think = False
        provider.s = SimpleNamespace(ollama_num_ctx=8192, ollama_num_predict=4096, ollama_temperature=0.5,
                                     ollama_keep_alive="30m")
        return provider

    return criar


def test_chamada_do_episodio_envia_ao_ollama_as_opcoes_do_env(ollama):
    provider = ollama(json.dumps(EPISODIO))
    assert provider.chat_json("sistema", "artigo") == EPISODIO

    [chamada] = provider.client.chamadas
    assert chamada["options"] == {"num_ctx": 8192, "num_predict": 4096, "temperature": 0.5}
    assert chamada["format"] == "json" and chamada["keep_alive"] == "30m" and chamada["think"] is False
    assert chamada["messages"] == [{"role": "system", "content": "sistema"}, {"role": "user", "content": "artigo"}]
    assert provider.ultimo_uso == {"prompt": 1200, "saida": 40}


def test_opcoes_por_chamada_mudam_temperatura_e_saida_mas_nunca_o_num_ctx(ollama):
    veredito = {"grupos": [], "isolados": [1, 2]}
    provider = ollama(json.dumps(veredito))
    assert provider.chat_json("sistema", "pauta", chaves=CHAVES_AGRUPADOR, temperatura=0.1, max_saida=512) == veredito
    assert provider.client.chamadas[0]["options"] == {"num_ctx": 8192, "num_predict": 512, "temperature": 0.1}

    provider.chat_json("sistema", "pauta", chaves=CHAVES_AGRUPADOR, temperatura=0.0)   # zero é um valor, não "sem valor"
    assert provider.client.chamadas[1]["options"] == {"num_ctx": 8192, "num_predict": 4096, "temperature": 0.0}

    with pytest.raises(ValueError, match="roteiro_podcast"):                           # a chamada seguinte volta ao padrão
        provider.chat_json("sistema", "artigo")
    assert provider.client.chamadas[2]["options"] == {"num_ctx": 8192, "num_predict": 4096, "temperature": 0.5}


def test_truncamento_cita_o_limite_que_valeu_na_chamada(ollama):
    cortado = ollama('{"grupos": [', done_reason="length", saida_tok=512)
    with pytest.raises(ValueError, match=r"limite de saída desta chamada \(512\)"):
        cortado.chat_json("sistema", "pauta", chaves=CHAVES_AGRUPADOR, max_saida=512)

    do_episodio = ollama('{"titulo_reescrito": "', done_reason="length", saida_tok=4096)
    with pytest.raises(ValueError, match=r"atingiu OLLAMA_NUM_PREDICT \(4096\)\. Aumente-o no \.env"):
        do_episodio.chat_json("sistema", "artigo")


def test_openai_registra_erro_quando_corta_a_entrada(caplog):
    resposta = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=50),
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content='{"grupos": [], "isolados": [1]}'))],
    )
    pedidos = []
    provider = llm.OpenAIProvider.__new__(llm.OpenAIProvider)        # sem o construtor: não cria o cliente de rede
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: pedidos.append(kwargs) or resposta)))
    provider.model, provider.max_tokens, provider.reasoning_effort, provider.max_prompt_chars = "modelo", 1000, None, 100

    with caplog.at_level("ERROR", logger="techdigest.ai.llm"):
        provider.chat_json("sistema", "x" * 80, chaves=CHAVES_AGRUPADOR)
    assert caplog.text == "" and pedidos[-1]["messages"][1]["content"] == "x" * 80        # cabe: nada a registrar

    with caplog.at_level("ERROR", logger="techdigest.ai.llm"):
        provider.chat_json("sistema", "x" * 500, chaves=CHAVES_AGRUPADOR)
    assert "Entrada de 500 caracteres cortada em LLM_MAX_PROMPT_CHARS (100)" in caplog.text
    assert pedidos[-1]["messages"][1]["content"].startswith("x" * 100 + "\n\n[TEXTO TRUNCADO")
    assert "temperature" not in pedidos[-1] and provider.ultimo_uso == {"prompt": 900, "saida": 50}


def test_todo_pedido_vai_com_truncate_e_shift_desligados(ollama):
    # decisão de 29/10/2026: a entrada grande demais volta com erro, e a resposta que chega ao fim da janela não desloca
    # o contexto; o "shift" vai igual em todos os pedidos, porque trocá-lo recarrega o modelo
    provider = ollama(json.dumps(EPISODIO))
    provider.chat_json("sistema", "artigo")
    assert provider.contar_tokens_fixos("sistema") == 1200
    pedido, contagem = provider.client.chamadas
    assert pedido["truncate"] is False and pedido["shift"] is False
    assert contagem["truncate"] is False and contagem["shift"] is False
    assert contagem["messages"] == [{"role": "system", "content": "sistema"}, {"role": "user", "content": ""}]
    assert contagem["options"]["num_predict"] == 1 and contagem["options"]["num_ctx"] == 8192


class RespostaHttp:
    def __init__(self, status: int, corpo):
        self.status_code, self.ok, self._corpo = status, status == 200, corpo
        self.text = corpo if isinstance(corpo, str) else json.dumps(corpo)

    def json(self):
        if isinstance(self._corpo, str):
            raise ValueError("não é JSON")
        return self._corpo


def test_o_pedido_que_passa_da_janela_vira_janela_excedida_com_a_contagem_do_servidor(monkeypatch):
    # a resposta do Ollama 0.40.2 na sessão de 29/10/2026: o erro do llama-server dentro do "error"
    erro = {"error": json.dumps({"error": {
        "code": 400, "message": "request (15329 tokens) exceeds the available context size (8192 tokens), try increasing it",
        "type": "exceed_context_size_error", "n_prompt_tokens": 15329, "n_ctx": 8192}})}
    pedidos = []
    monkeypatch.setattr(llm.requests, "post", lambda url, json, timeout: pedidos.append((url, json)) or RespostaHttp(400, erro))
    cliente = llm._ClienteOllama("http://127.0.0.1:11434/")
    with pytest.raises(llm.JanelaExcedida) as e:
        cliente.chat(model="m", messages=[], truncate=False, shift=False)
    assert (e.value.tokens, e.value.janela) == (15329, 8192)
    assert pedidos == [("http://127.0.0.1:11434/api/chat", {"model": "m", "messages": [], "truncate": False, "shift": False,
                                                            "stream": False})]
    # só a mensagem, sem o objeto: a contagem sai do texto
    monkeypatch.setattr(llm.requests, "post", lambda url, json, timeout: RespostaHttp(400, {
        "error": "request (9000 tokens) exceeds the available context size (8192 tokens), try increasing it"}))
    with pytest.raises(llm.JanelaExcedida) as e:
        cliente.chat(model="m", messages=[])
    assert (e.value.tokens, e.value.janela) == (9000, 8192)
    # outro erro do servidor não é de janela
    monkeypatch.setattr(llm.requests, "post", lambda url, json, timeout: RespostaHttp(500, {"error": "model not found"}))
    with pytest.raises(RuntimeError, match="HTTP 500: model not found") as e:
        cliente.chat(model="m", messages=[])
    assert not isinstance(e.value, llm.JanelaExcedida)


def test_a_resposta_do_servidor_vira_a_chat_response_do_cliente_python(monkeypatch):
    corpo = {"model": "m", "created_at": "2026-10-29T10:00:00Z", "done": True, "done_reason": "stop",
             "message": {"role": "assistant", "content": "{}"}, "prompt_eval_count": 1573, "eval_count": 1,
             "total_duration": 1, "eval_duration": 1}
    monkeypatch.setattr(llm.requests, "post", lambda url, json, timeout: RespostaHttp(200, corpo))
    resposta = llm._ClienteOllama("http://x").chat(model="m", messages=[])
    assert (resposta.prompt_eval_count, resposta.done_reason, resposta.message.content) == (1573, "stop", "{}")

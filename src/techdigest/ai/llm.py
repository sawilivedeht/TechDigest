"""Providers de LLM — Ollama (local) e qualquer endpoint compatível com OpenAI."""
import glob
import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger("techdigest.ai.llm")


class JanelaExcedida(RuntimeError):
    """O Ollama recusou o pedido: a entrada passa da janela (num_ctx). Nada foi processado nem cortado.

    `tokens` é quantos tokens a entrada tem, como o servidor contou (None se a resposta não disse), e `janela`, o
    num_ctx. Com "truncate": false o Ollama devolve esse erro em vez de cortar o meio do prompt em silêncio.
    """

    def __init__(self, tokens: int | None, janela: int | None, mensagem: str):
        super().__init__(mensagem)
        self.tokens, self.janela = tokens, janela


# ---------------------------------------------------------------- helpers

def _ascii(value: str, campo: str) -> str:
    if any(ord(c) > 127 for c in value):
        raise ValueError(
            f"{campo} contém caracteres não-ASCII (acento?). "
            f"Reescreva o valor no .env digitando à mão."
        )
    return value


def parse_json(text: str, chaves=None) -> dict:
    """Parse defensivo: mensagem clara para vazio, cercas e JSON quebrado.

    `chaves` são as chaves obrigatórias da resposta; sem ele valem as 8 do episódio (REQUIRED_KEYS).
    """
    if not text or not text.strip():
        raise ValueError(
            "Modelo retornou resposta VAZIA. Causas comuns: modelo truncado, "
            "format incompatível ou RAM insuficiente (veja os logs do provider)."
        )
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON inválido ({e}). Início da resposta: {text[:300]!r}") from e

    faltando = (REQUIRED_KEYS if chaves is None else set(chaves)) - data.keys()
    if faltando:
        raise ValueError(
            f"LLM retornou JSON sem as chaves {sorted(faltando)}. "
            f"Chaves recebidas: {sorted(data.keys())}. Bruto: {text[:300]!r}"
        )
    return data


def _temperatura_cpu() -> float | None:
    """Temperatura do pacote da CPU via hwmon (coretemp = Intel, k10temp/zenpower = AMD)."""
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(f"{hw}/name") as f:
                nome = f.read().strip()
            if nome in ("coretemp", "k10temp", "zenpower"):
                with open(f"{hw}/temp1_input") as f:
                    return int(f.read()) / 1000
        except (OSError, ValueError):
            continue
    return None


def _amostra_sistema() -> str:
    """RAM disponível, swap em uso e temperaturas no momento: diagnóstico da queda de velocidade.

    Tudo é opcional: o que não estiver disponível nesta máquina simplesmente não aparece.
    """
    partes = []
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for linha in f:
                chave, valor = linha.split(":", 1)
                mem[chave] = int(valor.split()[0])  # kB
        partes.append(f"RAM disp.={mem['MemAvailable'] / 1048576:.1f} GB")
        partes.append(f"swap usado={(mem['SwapTotal'] - mem['SwapFree']) / 1048576:.1f} GB")
    except (OSError, KeyError, ValueError):
        pass
    temp = _temperatura_cpu()
    if temp is not None:
        partes.append(f"CPU={temp:.0f}°C")
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu,clocks.sm", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            gpu_temp, gpu_clock = (x.strip() for x in r.stdout.splitlines()[0].split(","))
            partes.append(f"GPU={gpu_temp}°C/{gpu_clock} MHz")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return ", ".join(partes)


# ---------------------------------------------------------------- schema

SCHEMA = {
    "type": "object",
    "properties": {
        "titulo_reescrito": {"type": "string"},
        "resumo_didatico": {"type": "string"},
        "pontos_chave": {"type": "array", "items": {"type": "string"}},
        "por_que_importa": {"type": "string"},
        "personagens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"nome": {"type": "string"}, "papel": {"type": "string"}},
                "required": ["nome", "papel"],
            },
        },
        "roteiro_podcast": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"personagem": {"type": "string"}, "fala": {"type": "string"}},
                "required": ["personagem", "fala"],
            },
        },
        "houve_divergencia": {"type": "boolean"},
        "fontes_citadas": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "titulo_reescrito", "resumo_didatico", "pontos_chave", "por_que_importa",
        "personagens", "roteiro_podcast", "houve_divergencia", "fontes_citadas",
    ],
}

REQUIRED_KEYS = set(SCHEMA["required"])


# ---------------------------------------------------------------- providers

class LLMProvider(ABC):
    """Contrato comum: toda chamada devolve o dict validado.

    Sem argumentos extras, a chamada é a do episódio: as 8 chaves de REQUIRED_KEYS e os parâmetros
    do .env. `chaves`, `temperatura` e `max_saida` valem só para a chamada que os passa.
    """

    ultimo_uso: dict[str, int] = {}  # tokens da última chamada: {"prompt": n, "saida": n}

    @abstractmethod
    def chat_json(self, system: str, user: str, chaves=None,
                  temperatura: float | None = None, max_saida: int | None = None) -> dict: ...


_ERRO_DE_JANELA = re.compile(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)")


class _ClienteOllama:
    """O /api/chat do Ollama por HTTP. O cliente Python (0.6) não manda "truncate" nem "shift" (ver `OllamaProvider`).

    Devolve a mesma `ChatResponse` do cliente Python. O pedido que passa da janela vira `JanelaExcedida`; outro erro
    do servidor, um RuntimeError com a mensagem dele. O resto (`ps`, `generate`, que as conferências da GPU usam) é o
    do cliente Python.
    """

    def __init__(self, host: str):
        from ollama import Client
        base = host.strip().rstrip("/") or "http://127.0.0.1:11434"
        self.url = (base if "://" in base else f"http://{base}") + "/api/chat"   # como o cliente Python, que aceita "host:porta"
        self._ollama = Client(host=host)

    def __getattr__(self, nome):
        if nome == "_ollama":      # ainda não existe (objeto em construção)
            raise AttributeError(nome)
        return getattr(self._ollama, nome)

    def chat(self, **pedido):
        from ollama import ChatResponse
        resposta = requests.post(self.url, json={**pedido, "stream": False}, timeout=(10, None))
        if resposta.ok:
            return ChatResponse.model_validate(resposta.json())
        try:
            erro = resposta.json().get("error", resposta.text)
        except ValueError:
            erro = resposta.text
        if isinstance(erro, str):
            try:
                erro = json.loads(erro)
            except ValueError:
                pass
        if isinstance(erro, dict) and "error" in erro:
            erro = erro["error"]
        mensagem = erro.get("message", str(erro)) if isinstance(erro, dict) else str(erro)
        tipo = erro.get("type", "") if isinstance(erro, dict) else ""
        contagem = _ERRO_DE_JANELA.search(mensagem)
        if tipo == "exceed_context_size_error" or contagem:
            tokens = erro.get("n_prompt_tokens") if isinstance(erro, dict) else None
            janela = erro.get("n_ctx") if isinstance(erro, dict) else None
            if contagem:
                tokens, janela = tokens or int(contagem.group(1)), janela or int(contagem.group(2))
            raise JanelaExcedida(tokens, janela, f"a entrada passa da janela: {mensagem[:200]}")
        raise RuntimeError(f"Ollama respondeu HTTP {resposta.status_code}: {mensagem[:300]}")


class OllamaProvider(LLMProvider):
    """Local — todos os parâmetros vêm do .env via settings.

    Todo pedido vai com "truncate": false e "shift": false (decisão de 29/10/2026): a entrada que passa da janela
    volta com erro (`JanelaExcedida`), em vez de o Ollama cortar o meio do prompt, e a resposta que chega ao fim da
    janela para com done_reason "length", em vez de deslocar o contexto. O "shift" é uma opção do servidor do modelo:
    trocá-lo entre pedidos recarrega o modelo, por isso ele vai igual em todos.
    """

    def __init__(self, model: str, host: str, settings):
        self.client = _ClienteOllama(host)
        self.model = model
        self.s = settings
        self.think = self._parse_think(getattr(settings, "ollama_think", ""))
        logger.info(
            "Ollama configurado: modelo=%s, num_ctx=%d, num_predict=%d, think=%s",
            model, settings.ollama_num_ctx, settings.ollama_num_predict,
            "padrão do modelo" if self.think is None else self.think,
        )
        if settings.ollama_num_predict > settings.ollama_num_ctx:
            logger.warning(
                "OLLAMA_NUM_PREDICT (%d) é maior que OLLAMA_NUM_CTX (%d): o limite "
                "efetivo da geração é a janela de contexto (prompt + saída), não o "
                "num_predict.",
                settings.ollama_num_predict, settings.ollama_num_ctx,
            )

    def _pedido(self, system: str, user: str, num_predict: int, temperatura: float | None) -> dict:
        return dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            format="json",
            keep_alive=self.s.ollama_keep_alive,
            options={
                # num_ctx é sempre o do .env: mudar a janela numa chamada faz o Ollama recarregar o modelo.
                "num_ctx": self.s.ollama_num_ctx,
                "num_predict": num_predict,
                "temperature": self.s.ollama_temperature if temperatura is None else temperatura,
            },
            truncate=False,
            shift=False,
            **({} if self.think is None else {"think": self.think}),
        )

    def contar_tokens_fixos(self, system: str) -> int:
        """Quantos tokens custa a parte fixa de uma chamada: o prompt de sistema e o template do modelo, com a mensagem
        do usuário vazia. Uma chamada com num_predict 1 e as opções das outras; não entra nas métricas do log."""
        resp = self.client.chat(**self._pedido(system, "", 1, None))
        return getattr(resp, "prompt_eval_count", None) or 0

    def chat_json(self, system: str, user: str, chaves=None,
                  temperatura: float | None = None, max_saida: int | None = None) -> dict:
        num_predict = self.s.ollama_num_predict if max_saida is None else max_saida
        resp = self.client.chat(**self._pedido(system, user, num_predict, temperatura))
        prompt_tok = getattr(resp, "prompt_eval_count", None) or 0
        saida_tok = getattr(resp, "eval_count", None) or 0
        self.ultimo_uso = {"prompt": prompt_tok, "saida": saida_tok}
        done = getattr(resp, "done_reason", None)
        self._log_metricas(resp, prompt_tok, saida_tok, done)
        if done == "length":
            raise ValueError(self._explicar_truncamento(resp, prompt_tok, saida_tok, num_predict))
        return parse_json(resp.message.content, chaves)

    @staticmethod
    def _parse_think(valor) -> bool | None:
        """OLLAMA_THINK: vazio = padrão do modelo (não envia); true/false = liga/desliga o raciocínio."""
        v = str(valor or "").strip().lower()
        if v in ("", "auto", "default"):
            return None
        if v in ("true", "1", "on", "yes", "sim"):
            return True
        if v in ("false", "0", "off", "no", "nao", "não"):
            return False
        raise ValueError(f"OLLAMA_THINK inválido: {valor!r}. Use true, false ou deixe vazio.")

    def _log_metricas(self, resp, prompt_tok: int, saida_tok: int, done) -> None:
        """Uma linha por chamada: tokens, velocidade e tempo (base p/ estimar a duração do lote)."""
        eval_ns = getattr(resp, "eval_duration", None) or 0
        total_ns = getattr(resp, "total_duration", None) or 0
        tok_s = saida_tok / (eval_ns / 1e9) if eval_ns else 0.0
        sistema = _amostra_sistema()
        logger.info(
            "Ollama %s: prompt=%d tok, saída=%d tok (%.1f tok/s), total=%.1fs, done=%s%s",
            self.model, prompt_tok, saida_tok, tok_s, total_ns / 1e9, done,
            f" | {sistema}" if sistema else "",
        )

    def _explicar_truncamento(self, resp, prompt_tok: int, saida_tok: int, num_predict: int) -> str:
        """Diz QUAL limite estourou e registra início/fim da saída cortada (nível WARNING).

        `num_predict` é o limite de saída que valeu na chamada: o do .env ou o `max_saida` dela.
        """
        num_ctx = self.s.ollama_num_ctx
        do_env = num_predict == self.s.ollama_num_predict
        limite = f"OLLAMA_NUM_PREDICT ({num_predict})" if do_env else f"o limite de saída desta chamada ({num_predict})"
        if num_predict > 0 and saida_tok >= num_predict:
            causa = f"atingiu {limite}. " + (
                f"Aumente-o no .env (a janela total é OLLAMA_NUM_CTX={num_ctx}) ou reduza o roteiro."
                if do_env else "Aumente o max_saida passado na chamada."
            )
        else:
            causa = (
                f"parou antes de {limite}: o limite atingido foi "
                f"a janela de contexto (OLLAMA_NUM_CTX={num_ctx}; prompt+saída="
                f"{prompt_tok + saida_tok}). Aumentar {'OLLAMA_NUM_PREDICT' if do_env else 'o limite de saída'} NÃO ajuda: "
                f"suba OLLAMA_NUM_CTX ou investigue por que a saída passa do esperado "
                f"(raciocínio interno ou repetição — veja o trecho final no log)."
            )
        conteudo = resp.message.content or ""
        pensamento = getattr(resp.message, "thinking", None) or ""
        logger.warning(
            "Truncamento: content=%d chars, thinking=%d chars\n"
            "  início do content: %r\n  fim do content: %r\n  fim do thinking: %r",
            len(conteudo), len(pensamento), conteudo[:200], conteudo[-300:], pensamento[-300:],
        )
        dica = ""
        if pensamento and self.think is not False:
            dica = (
                f" O modelo gastou {len(pensamento)} chars em raciocínio (thinking): "
                f"defina OLLAMA_THINK=false no .env para desligá-lo."
            )
        return (
            f"Saída truncada (done_reason=length): prompt={prompt_tok} + "
            f"saída={saida_tok} tokens. A geração {causa}{dica}"
        )


class OpenAIProvider(LLMProvider):
    """Protocolo OpenAI — cobre OpenAI, Groq, OpenRouter (base_url decide)."""

    def __init__(self, model: str, api_key: str,
                 base_url: str | None = None, max_tokens: int = 8192,
                 reasoning_effort: str | None = None,
                 max_prompt_chars: int = 8000):
        from openai import OpenAI
        self.client = OpenAI(api_key=_ascii(api_key, "API key do provedor"),
                             base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort or None
        self.max_prompt_chars = max_prompt_chars

    def chat_json(self, system: str, user: str, chaves=None,
                  temperatura: float | None = None, max_saida: int | None = None) -> dict:
        max_tokens = self.max_tokens if max_saida is None else max_saida
        # blindagem de tamanho (defesa contra 413)
        if len(user) > self.max_prompt_chars:
            # O Summarizer monta a entrada dentro deste limite; chegar aqui é erro de orçamento,
            # e o que se perde é o fim do prompt (relacionados, aviso e lembrete).
            logger.error(
                "Entrada de %d caracteres cortada em LLM_MAX_PROMPT_CHARS (%d): o fim do prompt foi descartado.",
                len(user), self.max_prompt_chars,
            )
            user = user[: self.max_prompt_chars] + \
                "\n\n[TEXTO TRUNCADO POR LIMITE DE REQUISIÇÃO]"

        total_chars = len(system) + len(user)
        logger.debug("request: %d chars (~%d tokens) + max_tokens=%d",
                     total_chars, total_chars // 4, max_tokens)

        tentativas = [
            {"response_format": {"type": "json_object"}},  # modo estrito (validador do provedor)
            {},                                            # fallback: geração livre
        ]
        ultimo_erro = None

        for i, rf in enumerate(tentativas, 1):
            kwargs = dict(
                model=self.model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + (
                        "\n\nATENÇÃO: comece sua resposta IMEDIATAMENTE com o caractere { "
                        "e produza somente o JSON válido, sem texto antes ou depois."
                        if i > 1 else "")},
                ],
                **rf,
            )
            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort
            if temperatura is not None:  # sem pedido na chamada, vale o padrão do provedor, como sempre
                kwargs["temperature"] = temperatura
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                if "404" in str(e) or "model_not_found" in str(e):
                    raise ValueError(
                        f"Modelo '{self.model}' não existe neste provedor. "
                        f"Confira o nome no .env / catálogo do provedor."
                    ) from e
                ultimo_erro = e
                logger.warning("Tentativa %d falhou (%s) — %s",
                               i, type(e).__name__, str(e)[:120])
                continue

            uso = getattr(resp, "usage", None)
            self.ultimo_uso = {"prompt": getattr(uso, "prompt_tokens", None) or 0,
                               "saida": getattr(uso, "completion_tokens", None) or 0}
            choice = resp.choices[0]
            if choice.finish_reason == "length":
                raise ValueError(
                    "Saída truncada (finish_reason=length): "
                    + ("aumente LLM_MAX_TOKENS no .env." if max_saida is None
                       else f"aumente o max_saida passado na chamada ({max_saida}).")
                )
            try:
                return parse_json(choice.message.content, chaves)
            except ValueError as e:
                ultimo_erro = e
                logger.warning("Tentativa %d: JSON inservível — %s", i, str(e)[:120])

        raise ValueError(f"Todas as tentativas falharam. Último erro: {ultimo_erro}")


# ---------------------------------------------------------------- factory

def get_provider(settings) -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings.ollama_model, settings.ollama_host, settings)

    # "openai" cobre OpenAI E compatíveis (Groq, OpenRouter) via OPENAI_BASE_URL
    return OpenAIProvider(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url or None,
        max_tokens=settings.llm_max_tokens,
        reasoning_effort=settings.openai_reasoning_effort or None,
        max_prompt_chars=settings.llm_max_prompt_chars,
    )
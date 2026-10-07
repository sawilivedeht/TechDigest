"""Providers de LLM — Ollama (local) e qualquer endpoint compatível com OpenAI."""
import glob
import json
import logging
import re
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger("techdigest.ai.llm")


# ---------------------------------------------------------------- helpers

def _ascii(value: str, campo: str) -> str:
    if any(ord(c) > 127 for c in value):
        raise ValueError(
            f"{campo} contém caracteres não-ASCII (acento?). "
            f"Reescreva o valor no .env digitando à mão."
        )
    return value


def parse_json(text: str) -> dict:
    """Parse defensivo: mensagem clara para vazio, cercas e JSON quebrado."""
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

    faltando = REQUIRED_KEYS - data.keys()
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
    """Contrato comum: toda chamada devolve o dict editorial validado."""

    @abstractmethod
    def chat_json(self, system: str, user: str) -> dict: ...


class OllamaProvider(LLMProvider):
    """Local — todos os parâmetros vêm do .env via settings."""

    def __init__(self, model: str, host: str, settings):
        from ollama import Client
        self.client = Client(host=host)
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

    def chat_json(self, system: str, user: str) -> dict:
        resp = self.client.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            format="json",
            keep_alive=self.s.ollama_keep_alive,
            options={
                "num_ctx": self.s.ollama_num_ctx,
                "num_predict": self.s.ollama_num_predict,
                "temperature": self.s.ollama_temperature,
            },
            **({} if self.think is None else {"think": self.think}),
        )
        prompt_tok = getattr(resp, "prompt_eval_count", None) or 0
        saida_tok = getattr(resp, "eval_count", None) or 0
        done = getattr(resp, "done_reason", None)
        self._log_metricas(resp, prompt_tok, saida_tok, done)
        if done == "length":
            raise ValueError(self._explicar_truncamento(resp, prompt_tok, saida_tok))
        return parse_json(resp.message.content)

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

    def _explicar_truncamento(self, resp, prompt_tok: int, saida_tok: int) -> str:
        """Diz QUAL limite estourou e registra início/fim da saída cortada (nível WARNING)."""
        num_ctx = self.s.ollama_num_ctx
        num_predict = self.s.ollama_num_predict
        if num_predict > 0 and saida_tok >= num_predict:
            causa = (
                f"atingiu OLLAMA_NUM_PREDICT ({num_predict}). Aumente-o no .env "
                f"(a janela total é OLLAMA_NUM_CTX={num_ctx}) ou reduza o roteiro."
            )
        else:
            causa = (
                f"parou antes de OLLAMA_NUM_PREDICT ({num_predict}): o limite atingido foi "
                f"a janela de contexto (OLLAMA_NUM_CTX={num_ctx}; prompt+saída="
                f"{prompt_tok + saida_tok}). Aumentar OLLAMA_NUM_PREDICT NÃO ajuda: "
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

    def chat_json(self, system: str, user: str) -> dict:
        # blindagem de tamanho (defesa contra 413)
        if len(user) > self.max_prompt_chars:
            user = user[: self.max_prompt_chars] + \
                "\n\n[TEXTO TRUNCADO POR LIMITE DE REQUISIÇÃO]"

        total_chars = len(system) + len(user)
        logger.debug("request: %d chars (~%d tokens) + max_tokens=%d",
                     total_chars, total_chars // 4, self.max_tokens)

        tentativas = [
            {"response_format": {"type": "json_object"}},  # modo estrito (validador do provedor)
            {},                                            # fallback: geração livre
        ]
        ultimo_erro = None

        for i, rf in enumerate(tentativas, 1):
            kwargs = dict(
                model=self.model,
                max_tokens=self.max_tokens,
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

            choice = resp.choices[0]
            if choice.finish_reason == "length":
                raise ValueError(
                    "Saída truncada (finish_reason=length): aumente LLM_MAX_TOKENS no .env."
                )
            try:
                return parse_json(choice.message.content)
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
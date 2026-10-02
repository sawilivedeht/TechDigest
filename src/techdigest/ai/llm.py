"""Providers de LLM — Ollama (local) e qualquer endpoint compatível com OpenAI."""
import json
import logging
import re
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
        )
        if getattr(resp, "done_reason", None) == "length":
            raise ValueError(
                f"Saída truncada (done_reason=length): gerou {resp.eval_count} tokens. "
                f"Aumente OLLAMA_NUM_PREDICT ({self.s.ollama_num_predict}) no .env, "
                f"ou reduza o tamanho do roteiro."
            )
        return parse_json(resp.message.content)


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
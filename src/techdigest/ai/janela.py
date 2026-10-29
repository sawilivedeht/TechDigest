"""A parte fixa de cada chamada em tokens exatos (decisão do dono de 29/10/2026).

O limite da entrada desconta da janela o prompt de sistema pelo número exato de tokens, e não convertido pela proporção
do texto: na execução de 25/10 em que a proporção caiu para 2,34, o PROMPT_SISTEMA (9.661 caracteres, 2.591 tokens)
custava 4.129 tokens no limite. O número sai de uma chamada com o prompt de sistema e a mensagem do usuário vazia, com
num_predict 1 (`OllamaProvider.contar_tokens_fixos`, pelas travas da máquina), e fica guardado em TOKENS_FIXOS (um
JSON na pasta de estado, ao lado da trava do modelo, de modo que a pasta principal, a worktree e as simulações o
dividem), pela chave sha256 do modelo, do OLLAMA_THINK e do prompt: um prompt novo, outro modelo ou outro think pede outra
contagem. Um modelo
atualizado com o mesmo nome e outro template não é percebido; apague o arquivo nesse caso.
"""
import datetime
import hashlib
import json
import logging
import os
from pathlib import Path

from techdigest.config import Settings

settings = Settings()
logger = logging.getLogger("techdigest.ai.janela")

_memoria: dict[str, int] = {}


# Um prompt de sistema tem de 3 a 4 caracteres por token: uma contagem com mais de 8 vem de um prefixo reaproveitado pelo
# servidor ou de um erro, e não é guardada.
MAX_CARACTERES_POR_TOKEN = 8


def chave(modelo: str, system: str, think=None) -> str:
    return hashlib.sha256(f"{modelo}\n{think}\n{system}".encode("utf-8")).hexdigest()


def _ler(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.warning("Parte fixa: %s ilegível (%s: %s); as contagens são refeitas", caminho, type(e).__name__, str(e)[:120])
        return {}


def _gravar(caminho: Path, chave_: str, modelo: str, system: str, tokens: int) -> None:
    try:
        guardadas = _ler(caminho)
        guardadas[chave_] = {"modelo": modelo, "caracteres": len(system), "inicio": system[:60], "tokens": tokens,
                             "contada_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
        caminho.parent.mkdir(parents=True, exist_ok=True)
        provisorio = caminho.with_suffix(f".{os.getpid()}.tmp")
        provisorio.write_text(json.dumps(guardadas, ensure_ascii=False, indent=1), encoding="utf-8")
        provisorio.replace(caminho)
    except OSError as e:
        logger.warning("Parte fixa: não foi possível guardar a contagem em %s (%s: %s)", caminho, type(e).__name__, str(e)[:120])


def tokens_fixos(provider, system: str) -> int | None:
    """Os tokens da parte fixa de uma chamada com este prompt de sistema: guardados, ou contados agora e guardados.

    None quando o provider não conta tokens (o caminho OpenAI, os provedores falsos dos testes) ou a contagem falhou:
    o limite usa então a conversão de `Summarizer._fixos`. A trava da máquina (`ExecucaoInterrompida`) passa.
    """
    modelo = str(getattr(provider, "model", ""))
    chave_ = chave(modelo, system, getattr(provider, "think", None))
    if chave_ in _memoria:
        return _memoria[chave_]
    caminho = Path(settings.tokens_fixos)
    guardada = _ler(caminho).get(chave_)
    if isinstance(guardada, dict) and isinstance(guardada.get("tokens"), int) and guardada["tokens"] > 0:
        _memoria[chave_] = guardada["tokens"]
        return guardada["tokens"]
    if not hasattr(getattr(provider, "provider", provider), "contar_tokens_fixos"):   # o vigiado embrulha o provider
        return None
    try:
        tokens = provider.contar_tokens_fixos(system)
    except Exception as e:
        logger.warning("Parte fixa não contada (%s: %s): o limite usa a conversão do prompt", type(e).__name__, str(e)[:200])
        return None
    if not tokens or len(system) / tokens > MAX_CARACTERES_POR_TOKEN:
        logger.warning("Parte fixa recusada: %d caracteres contados como %s tokens; o limite usa a conversão do prompt",
                       len(system), tokens)
        return None
    _memoria[chave_] = tokens
    _gravar(caminho, chave_, modelo, system, tokens)
    logger.info("Parte fixa contada: prompt de sistema de %d caracteres = %d tokens com o template (%s), guardada em %s",
                len(system), tokens, modelo, caminho)
    return tokens

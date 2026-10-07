"""Summarizer — geração + revisão com QA determinístico."""
import json
import logging
import re

from techdigest.ai.llm import get_provider
from techdigest.ai.prompt import PROMPT_REVISOR, PROMPT_SISTEMA
from techdigest.ai.qa import problemas
from techdigest.config import Settings

logger = logging.getLogger("techdigest.ai.summarizer")

settings = Settings()


class QAReprovado(ValueError):
    """Episódio ainda viola as regras editoriais depois da passada de revisão."""


def _limpar(texto: str) -> str:
    """Remove caracteres de controle e whitespace degenerado de extrações sujas."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _qa(result: dict) -> list[str]:
    """Roda o QA sem deixar um JSON malformado derrubar o fluxo (vira problema, não exceção)."""
    try:
        return problemas(result)
    except (KeyError, TypeError, AttributeError) as e:
        return [f"estrutura inválida para o QA ({type(e).__name__}: {e})"]


class Summarizer:
    """Gera (e se preciso, revisa) o JSON editorial completo de uma notícia."""

    def __init__(self, provider=None):
        self.provider = provider or get_provider(settings)

    def _montar_entrada(self, principal: dict, relacionados: list[dict] | None = None) -> str:
        partes = [
            "ARTIGO PRINCIPAL\n"
            f"Fonte: {principal['source']}\n"
            f"Título: {_limpar(principal['title'])}\n"
            f"Texto:\n{_limpar(principal['text'])[:5000]}"
        ]
        for i, rel in enumerate((relacionados or [])[:2], 1):
            partes.append(
                f"\nARTIGO RELACIONADO [{i}]\n"
                f"Fonte: {rel['source']}\n"
                f"Título: {_limpar(rel['title'])}\n"
                f"Trecho:\n{_limpar(rel['text'])[:3000]}"
            )
        if relacionados:
            fontes = {principal["source"]} | {r["source"] for r in relacionados}
            partes.append(
                f"\nAVISO DO EDITOR-CHEFE: existem {len(relacionados) + 1} fontes distintas "
                f"sobre este assunto ({', '.join(sorted(fontes))}). Verifique conflitos "
                f"entre os relatos e aplique a REGRA DE DIVERGÊNCIA obrigatoriamente."
            )
        partes.append(
            "\nLEMBRETE: só o JSON das 8 chaves. Roteiro com 600-1300 palavras "
            "no total, 240-480 por personagem, 14-24 turnos."
        )
        return "\n".join(partes)

    def process(self, principal: dict, relacionados: list[dict] | None = None) -> dict:
        """Devolve um episódio que passou no QA; do contrário levanta QAReprovado (item é pulado)."""
        entrada_artigo = self._montar_entrada(principal, relacionados)
        logger.info(
            "Resumindo: %r (fonte: %s, %d caracteres de texto, %d relacionado(s))",
            str(principal["title"])[:80], principal["source"],
            len(principal["text"]), len(relacionados or []),
        )
        logger.debug("Início da entrada enviada ao LLM: %r", entrada_artigo[:600])

        result = self.provider.chat_json(PROMPT_SISTEMA, entrada_artigo)

        probs = _qa(result)
        if not probs:
            return result

        logger.warning("QA reprovou a 1ª versão: %s — acionando revisão", probs)
        # A revisão recebe o artigo-fonte: sem ele, "expandir" o roteiro vira invenção de fatos.
        entrada = (
            "ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\n"
            + entrada_artigo
            + "\n\nPROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs)
            + "\n\nEPISÓDIO ORIGINAL:\n" + json.dumps(result, ensure_ascii=False)
        )
        try:
            corrigido = self.provider.chat_json(PROMPT_REVISOR, entrada)
        except Exception as e:
            raise QAReprovado(
                f"revisão falhou ({type(e).__name__}: {str(e)[:200]}); "
                f"1ª versão reprovada: {probs}"
            ) from e

        probs2 = _qa(corrigido)
        if not probs2:
            logger.info("Revisão aprovada pelo QA.")
            return corrigido

        raise QAReprovado(f"revisão ainda reprovada pelo QA: {probs2}")
"""Summarizer — geração + revisão com QA determinístico."""
import json
import re

from techdigest.ai.llm import get_provider
from techdigest.ai.prompt import PROMPT_REVISOR, PROMPT_SISTEMA
from techdigest.ai.qa import problemas
from techdigest.config import Settings
import logging
logger = logging.getLogger("techdigest.ai.summarizer")

settings = Settings()


def _limpar(texto: str) -> str:
    """Remove caracteres de controle e whitespace degenerado de extrações sujas."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


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
        result = self.provider.chat_json(PROMPT_SISTEMA, self._montar_entrada(principal, relacionados))

        probs = problemas(result)
        if not probs:
            return result

        print(f"  QA reprovou 1ª versão: {probs}\n🔁 Acionando revisão/expansão...")
        entrada = (
            "PROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs) +
            "\n\nEPISÓDIO ORIGINAL:\n" + json.dumps(result, ensure_ascii=False)
        )
        try:
            corrigido = self.provider.chat_json(PROMPT_REVISOR, entrada)
            probs2 = problemas(corrigido)
            if not probs2:
                print(" Revisão aprovada pelo QA.")
                return corrigido
            print(f"Revisão ainda com pendências: {probs2} — usando a melhor versão.")
        except Exception as e:
            print(f"Revisão falhou ({e}) — usando versão original.")

        return result
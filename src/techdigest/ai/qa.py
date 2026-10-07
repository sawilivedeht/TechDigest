import logging

from techdigest.config import Settings

logger = logging.getLogger("techdigest.ai.qa")

settings = Settings()

# Faixas editoriais (regras 2, 3 e 6). Os valores vêm do .env (QA_*); os defaults do
# config.py são as regras originais do dono.
MIN_POR_PERSONAGEM, MAX_POR_PERSONAGEM = settings.qa_min_por_personagem, settings.qa_max_por_personagem
MIN_TOTAL, MAX_TOTAL = settings.qa_min_total, settings.qa_max_total
MIN_FRASES_RESUMO, MAX_FRASES_RESUMO = settings.qa_min_frases, settings.qa_max_frases


def contar_palavras(t: str) -> int:
    return len(t.split())


def palavras_por_personagem(roteiro: list[dict]) -> dict[str, int]:
    acc: dict[str, int] = {}
    for turno in roteiro:
        acc[turno["personagem"]] = acc.get(turno["personagem"], 0) + contar_palavras(turno["fala"])
    return acc


def problemas(result: dict) -> list[str]:
    """Retorna lista de violações; lista vazia = aprovado."""
    probs = []

    frases = sum(result["resumo_didatico"].count(p) for p in ".!?")
    if not (MIN_FRASES_RESUMO <= frases <= MAX_FRASES_RESUMO):
        probs.append(f"resumo com {frases} frases (alvo {MIN_FRASES_RESUMO}-{MAX_FRASES_RESUMO})")

    por_pers = palavras_por_personagem(result["roteiro_podcast"])
    for nome, n in por_pers.items():
        if not (MIN_POR_PERSONAGEM <= n <= MAX_POR_PERSONAGEM):
            probs.append(f"{nome} com {n} palavras (alvo {MIN_POR_PERSONAGEM}-{MAX_POR_PERSONAGEM})")

    total = sum(por_pers.values())
    if not (MIN_TOTAL <= total <= MAX_TOTAL):
        probs.append(f"total de {total} palavras (alvo {MIN_TOTAL}-{MAX_TOTAL})")

    declarados = {p["nome"] for p in result["personagens"]}
    falantes = set(por_pers)
    if falantes != declarados:
        probs.append(f"personagens inconsistentes: {falantes ^ declarados}")

    return probs
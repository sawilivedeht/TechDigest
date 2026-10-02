import logging
logger = logging.getLogger("techdigest.ai.qa")

MIN_POR_PERSONAGEM, MAX_POR_PERSONAGEM = 240, 480
MIN_TOTAL, MAX_TOTAL = 600, 1300
MIN_FRASES_RESUMO, MAX_FRASES_RESUMO = 7, 10


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
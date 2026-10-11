import logging
import re
import unicodedata

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


def _palavras_do_nome(nome) -> list[str]:
    sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", str(nome)) if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", sem_acentos.lower())


def mesmo_veiculo(a, b) -> bool:
    """Comparação tolerante de nomes de veículo: sem acento nem caixa, e um nome pode estar contido no outro.

    A comparação é por palavras inteiras: "Folha" casa com "Folha de S.Paulo", mas "ge" não casa
    com "Agência Brasil".
    """
    menor, maior = sorted((_palavras_do_nome(a), _palavras_do_nome(b)), key=len)
    return bool(menor) and any(maior[i:i + len(menor)] == menor for i in range(len(maior) - len(menor) + 1))


def veiculos_distintos(veiculos) -> list[str]:
    """Os veículos sem repetição (pela comparação tolerante), na ordem em que aparecem."""
    distintos: list[str] = []
    for veiculo in veiculos:
        if not any(mesmo_veiculo(veiculo, outro) for outro in distintos):
            distintos.append(veiculo)
    return distintos


def problemas(result: dict, veiculos=None) -> list[str]:
    """Retorna lista de violações; lista vazia = aprovado.

    `veiculos` são os veículos das fontes do episódio. Com dois ou mais veículos distintos, todos
    têm de aparecer em fontes_citadas; com um só (ou sem a lista), essa regra não se aplica.
    """
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

    distintos = veiculos_distintos(veiculos or [])
    if len(distintos) >= 2:
        citadas = result["fontes_citadas"] if isinstance(result["fontes_citadas"], list) else []
        faltando = [v for v in distintos if not any(mesmo_veiculo(v, citada) for citada in citadas)]
        if faltando:
            probs.append(
                f"fontes_citadas sem {', '.join(faltando)} (o episódio tem {len(distintos)} veículos como "
                f"fonte: cite cada um pelo nome no roteiro e liste todos em fontes_citadas)"
            )

    return probs
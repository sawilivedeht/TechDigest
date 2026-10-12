"""Análise de lados: quantas posições em disputa a pauta tem, quem as sustenta e que veículo as relata.

Roda em toda pauta, inclusive nas de um veículo só, antes da geração e sobre os mesmos trechos que
vão para o episódio. O número de lados define o elenco (um analista por lado) e o valor de
houve_divergencia; quem confere isso no episódio é `qa.problemas_dos_analistas`.
"""
import logging
from dataclasses import dataclass, field

from techdigest.ai.prompt import PROMPT_LADOS
from techdigest.ai.qa import atores_exclusivos, mesmo_veiculo, veiculos_distintos

logger = logging.getLogger("techdigest.ai.lados")

CHAVES_LADOS = ("lados",)
MAX_LADOS = 3
TEMPERATURA_LADOS = 0.1     # baixa, para a contagem dos lados variar pouco entre execuções
MAX_SAIDA_LADOS = 800       # tokens: a resposta é um JSON curto
MAX_BLOCO = 1200            # caracteres do bloco de lados na entrada do episódio; o orçamento reserva sempre isto
MAX_POSICAO = 220           # caracteres da frase de cada lado no bloco
MIN_POSICAO = 60
# Alvo de palavras por personagem conforme o número de analistas: com Helena, o total cabe em 600-1300.
ALVO_POR_PERSONAGEM = {1: "360 a 420", 2: "320 a 400", 3: "260 a 310"}


@dataclass(frozen=True)
class Lado:
    """Uma posição em disputa na pauta. No lado único de emergência, `posicao` e `atores` vêm vazios."""
    posicao: str
    atores: tuple[str, ...]
    veiculos: tuple[str, ...]   # com a grafia da pauta


@dataclass
class Analise:
    """Os lados que valem para a pauta e o que o LLM respondeu."""
    lados: list[Lado]
    motivo: str = ""
    problemas: list[str] = field(default_factory=list)   # por que a resposta não valeu (e a pauta ficou com um lado só)
    resposta: dict | None = None


def entrada_dos_lados(textos) -> str:
    """O que o LLM recebe: cada trecho com veículo e título. `textos` são os de `Entrada.textos`."""
    partes = [
        f"TEXTO {i}\nVeículo: {t['fonte']}\nTítulo: {t['titulo']}\nTexto:\n{t['texto']}" for i, t in enumerate(textos, 1)
    ]
    partes.append(f"VEÍCULOS DA PAUTA: {', '.join(veiculos_distintos(t['fonte'] for t in textos))}")
    return "\n\n".join(partes)


def _sem_repetir(itens) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in itens if item.strip()))


def _ler(lados: list[dict], da_pauta: list[str]) -> list[Lado]:
    """Os lados de uma resposta já conferida, com os veículos na grafia e na ordem da pauta."""
    return [
        Lado(
            posicao=" ".join(lado["posicao"].split()),
            atores=_sem_repetir(lado["atores"]),
            veiculos=tuple(v for v in da_pauta if any(mesmo_veiculo(v, citado) for citado in lado["veiculos"])),
        )
        for lado in lados
    ]


def problemas_da_analise(resposta, veiculos) -> list[str]:
    """Por que a resposta do LLM não serve para a pauta destes veículos; lista vazia = válida.

    Vale de 1 a 3 lados, cada um com posição, pelo menos um ator e pelo menos um veículo, todos da
    pauta (pela comparação tolerante de `qa.mesmo_veiculo`); cada lado com um ator que nenhum
    outro lado tem; e todo veículo da pauta em pelo menos um lado.
    """
    lados = resposta.get("lados") if isinstance(resposta, dict) else None
    if not isinstance(lados, list):
        return ["resposta sem a lista de lados"]
    if not 1 <= len(lados) <= MAX_LADOS:
        return [f"resposta com {len(lados)} lados (vale de 1 a {MAX_LADOS})"]
    da_pauta = veiculos_distintos(veiculos)
    probs = []
    for i, lado in enumerate(lados, 1):
        if not isinstance(lado, dict):
            probs.append(f"lado {i} não é um objeto")
            continue
        posicao, atores, citados = lado.get("posicao"), lado.get("atores"), lado.get("veiculos")
        if not (isinstance(posicao, str) and posicao.strip()):
            probs.append(f"lado {i} sem posição")
        if not (isinstance(atores, list) and atores and all(isinstance(a, str) and a.strip() for a in atores)):
            probs.append(f"lado {i} sem ator")
        if not (isinstance(citados, list) and citados and all(isinstance(v, str) for v in citados)):
            probs.append(f"lado {i} sem veículo")
        elif fora := [v for v in citados if not any(mesmo_veiculo(v, p) for p in da_pauta)]:
            probs.append(f"lado {i} com veículo fora da pauta ({', '.join(fora)})")
    if probs:
        return probs
    lidos = _ler(lados, da_pauta)
    probs += [f"lado {i} sem ator que não esteja em outro lado" for i, proprios in enumerate(atores_exclusivos(lidos), 1) if not proprios]
    sem_lado = [v for v in da_pauta if not any(v in lado.veiculos for lado in lidos)]
    if sem_lado:
        probs.append(f"veículo da pauta em nenhum lado ({', '.join(sem_lado)})")
    return probs


def lado_unico(veiculos) -> list[Lado]:
    """A saída de emergência: um lado só, com todos os veículos da pauta."""
    return [Lado(posicao="", atores=(), veiculos=tuple(veiculos_distintos(veiculos)))]


def analisar_lados(chamar, textos) -> Analise:
    """Pergunta ao LLM os lados da pauta. Chamada que falha ou resposta inválida viram um lado só, com aviso no log.

    `chamar(system, user, **opções)` é o chat_json do provider (ou o `_chamar` do Summarizer).
    """
    veiculos = [t["fonte"] for t in textos]
    try:
        resposta = chamar(
            PROMPT_LADOS, entrada_dos_lados(textos),
            chaves=CHAVES_LADOS, temperatura=TEMPERATURA_LADOS, max_saida=MAX_SAIDA_LADOS,
        )
    except Exception as e:  # resposta vazia, cortada, sem a chave, servidor fora do ar...
        problema = f"a chamada falhou ({type(e).__name__}: {str(e)[:200]})"
        logger.warning("Análise de lados: %s. A pauta segue com um lado só.", problema)
        return Analise(lado_unico(veiculos), problemas=[problema])
    probs = problemas_da_analise(resposta, veiculos)
    if probs:
        logger.warning("Análise de lados inválida (%s): a pauta segue com um lado só.", "; ".join(probs))
        return Analise(lado_unico(veiculos), problemas=probs, resposta=resposta)
    lados = _ler(resposta["lados"], veiculos_distintos(veiculos))
    logger.info("Lados da pauta: %d (%s)", len(lados), " × ".join(", ".join(lado.atores) for lado in lados))
    motivo = resposta.get("motivo")
    return Analise(lados, motivo.strip() if isinstance(motivo, str) else "", resposta=resposta)


def _encurtar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1].rsplit(None, 1)[0].rstrip(",;:") + "…"


def bloco_dos_lados(lados) -> str:
    """O bloco LADOS DA PAUTA da entrada do episódio: os lados, o elenco exato e o alvo de palavras.

    Nunca passa de MAX_BLOCO caracteres, que é o que o orçamento da entrada reserva para ele: se
    for preciso, as frases de posição encolhem.
    """
    n = len(lados)
    if n == 1:
        elenco = 'ELENCO: Helena e exatamente 1 analista, que aprofunda o tema com ela; "houve_divergencia": false.'
    else:
        elenco = (
            f'ELENCO: Helena e exatamente {n} analistas, um por lado; "houve_divergencia": true. Cada analista '
            f"apresenta a posição do seu lado numa frase que nomeia um ator do lado, cita um veículo do lado e usa "
            f'um verbo de posição, como em "segundo <veículo>, <ator> afirma que...".'
        )
    elenco += f" Alvo: {ALVO_POR_PERSONAGEM[n]} palavras por personagem."
    cabecalho = f"\nLADOS DA PAUTA: {n} lado{'s' if n > 1 else ''}."
    descritos = [(i, lado) for i, lado in enumerate(lados, 1) if lado.posicao]

    def montar(teto: int) -> str:
        linhas = [
            f"Lado {i}: {_encurtar(lado.posicao, teto)} Atores: {', '.join(lado.atores)}. Veículos: {', '.join(lado.veiculos)}."
            for i, lado in descritos
        ]
        return "\n".join([cabecalho, *linhas, elenco])

    teto = MAX_POSICAO
    bloco = montar(teto)
    while len(bloco) > MAX_BLOCO and teto > MIN_POSICAO:
        teto -= 20
        bloco = montar(teto)
    if len(bloco) > MAX_BLOCO:   # listas de atores longas demais: o que fica de fora é o fim do último lado
        logger.warning("Bloco de lados com %d caracteres: cortado em %d.", len(bloco), MAX_BLOCO)
        bloco = "\n".join([cabecalho, elenco, *bloco.split("\n")[2:-1]])[:MAX_BLOCO - 1] + "…"
    return bloco

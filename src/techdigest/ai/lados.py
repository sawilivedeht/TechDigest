"""Análise de lados: a questão em disputa na pauta, quem responde a ela de cada lado e que veículo relata cada um.

Roda em toda pauta, inclusive nas de um veículo só, antes da geração e sobre os mesmos trechos que
vão para o episódio. O número de lados define o elenco (um analista por lado) e o valor de
houve_divergencia; quem confere isso no episódio é `qa.problemas_dos_analistas`.
"""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace

from techdigest.ai.prompt import PROMPT_LADOS
from techdigest.ai.qa import atores_exclusivos, mesmo_veiculo, palavras_do_ator, veiculos_distintos

logger = logging.getLogger("techdigest.ai.lados")

CHAVES_LADOS = ("lados",)
MAX_LADOS = 3
TEMPERATURA_LADOS = 0.1     # baixa, para a contagem dos lados variar pouco entre execuções
MAX_SAIDA_LADOS = 800       # tokens: a resposta é um JSON curto
MAX_BLOCO = 1200            # caracteres do bloco de lados na entrada do episódio; o orçamento reserva sempre isto
MAX_POSICAO = 220           # caracteres da frase de cada lado no bloco
MIN_POSICAO = 60
MAX_QUESTAO = 160           # caracteres da questão no bloco
MAX_RESPOSTA = 60           # caracteres da resposta de cada lado no bloco
MAX_ANTERIOR = 2000         # caracteres da resposta recusada que voltam ao LLM na nova tentativa
# A posição do lado único de emergência, quando as duas tentativas da análise não valem.
POSICAO_DE_EMERGENCIA = "relato dos fatos, sem lados definidos"
# Alvo de palavras por personagem conforme o número de analistas: com Helena, o total cabe em 600-1300.
ALVO_POR_PERSONAGEM = {1: "360 a 420", 2: "320 a 400", 3: "260 a 310"}
# Termos que não fazem um ator, sem acento: coletivo sem nome ("economistas"), designação vaga sem
# qualificador ("o governo", "a empresa") e os quantificadores que os acompanham ("alguns analistas").
# É genérico o ator que só tem palavras daqui: "governo federal" e "governo do Amazonas" valem.
TERMOS_GENERICOS = frozenset({
    "economista", "economistas", "especialista", "especialistas", "analista", "analistas", "critico", "criticos",
    "observador", "observadores", "pesquisador", "pesquisadores", "estudioso", "estudiosos", "cientista", "cientistas",
    "jurista", "juristas", "tecnico", "tecnicos", "comentarista", "comentaristas", "autoridade", "autoridades",
    "fonte", "fontes", "opositor", "opositores", "adversario", "adversarios", "aliado", "aliados",
    "apoiador", "apoiadores", "parlamentar", "parlamentares", "politico", "politicos",
    "governo", "governos", "empresa", "empresas", "companhia", "companhias", "entidade", "entidades",
    "organizacao", "organizacoes", "instituicao", "instituicoes", "orgao", "orgaos",
    "um", "uma", "uns", "umas", "algum", "alguma", "alguns", "algumas", "varios", "varias", "outro", "outra",
    "outros", "outras", "muitos", "muitas", "diversos", "diversas",
})
# O que a nova tentativa lembra ao LLM, depois do erro da primeira.
LEMBRETE_DA_CORRECAO = (
    "Responda de novo, com o JSON completo. Uma questão só; cada lado é uma resposta diferente a ela; agrupe os "
    "atores pela resposta que dão à questão, nunca um lado por ator; sem disputa, a questão fica vazia e há um lado só."
)


@dataclass(frozen=True)
class Lado:
    """Uma resposta à questão da pauta ou, sem disputa, o fato central da história.

    No lado único de emergência, `posicao` é POSICAO_DE_EMERGENCIA e `atores` vem vazio.
    """
    posicao: str
    atores: tuple[str, ...]
    veiculos: tuple[str, ...]   # com a grafia da pauta
    resposta: str = ""          # a resposta do lado à questão; vazia quando a pauta tem um lado só


@dataclass
class Analise:
    """Os lados que valem para a pauta e o que o LLM respondeu."""
    lados: list[Lado]
    questao: str = ""                                    # a pergunta em disputa; vazia quando a pauta tem um lado só
    motivo: str = ""
    problemas: list[str] = field(default_factory=list)   # por que a resposta não valeu (e a pauta ficou com o lado de emergência)
    removidos: list[str] = field(default_factory=list)   # os atores genéricos e os lados que saíram com eles
    resposta: dict | None = None
    primeira: "Analise | None" = None                    # a primeira tentativa, quando ela não valeu e houve outra


def entrada_dos_lados(textos) -> str:
    """O que o LLM recebe: cada trecho com veículo e título. `textos` são os de `Entrada.textos`."""
    partes = [
        f"TEXTO {i}\nVeículo: {t['fonte']}\nTítulo: {t['titulo']}\nTexto:\n{t['texto']}" for i, t in enumerate(textos, 1)
    ]
    partes.append(f"VEÍCULOS DA PAUTA: {', '.join(veiculos_distintos(t['fonte'] for t in textos))}")
    return "\n\n".join(partes)


def _sem_repetir(itens) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in itens if item.strip()))


def _linha(texto) -> str:
    """O texto numa linha só, sem espaços repetidos; o que não é texto vira vazio."""
    return " ".join(texto.split()) if isinstance(texto, str) else ""


def _mesma_resposta(a: str, b: str) -> bool:
    """Se duas respostas à questão são a mesma, sem contar caixa, acento nem pontuação."""
    def palavras(texto):
        sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        return re.findall(r"\w+", sem_acentos.lower())
    return palavras(a) == palavras(b)


def _ler(lados: list[dict], da_pauta: list[str]) -> list[Lado]:
    """Os lados de uma resposta já conferida, com os veículos na grafia e na ordem da pauta."""
    return [
        Lado(
            posicao=_linha(lado["posicao"]),
            atores=_sem_repetir(lado["atores"]),
            veiculos=tuple(v for v in da_pauta if any(mesmo_veiculo(v, citado) for citado in lado["veiculos"])),
            resposta=_linha(lado.get("resposta")),
        )
        for lado in lados
    ]


def ator_generico(nome) -> bool:
    """Se o nome não chega a ser um ator: só tem termos de TERMOS_GENERICOS (sem contar artigo nem partícula)."""
    return palavras_do_ator(nome) <= TERMOS_GENERICOS


def _problemas_dos_campos(lados: list, da_pauta: list[str]) -> list[str]:
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
    return probs


def _sem_genericos(lidos: list[Lado]) -> tuple[dict[int, Lado], list[str]]:
    """Tira os atores genéricos; o lado que fica sem ator sai. Devolve os lados que ficam, pelo número, e o que saiu."""
    ficam, removidos = {}, []
    for i, lado in enumerate(lidos, 1):
        genericos = [a for a in lado.atores if ator_generico(a)]
        especificos = tuple(a for a in lado.atores if a not in genericos)
        if not especificos:
            removidos.append(f"lado {i}, só com ator genérico ({', '.join(genericos)})")
            continue
        if genericos:
            removidos.append(f"ator genérico do lado {i} ({', '.join(genericos)})")
        ficam[i] = replace(lado, atores=especificos)
    return ficam, removidos


def _problemas_das_respostas(ficam: dict[int, Lado]) -> list[str]:
    """Com questão, cada lado tem a sua resposta, diferente das dos outros."""
    probs = [f"lado {i} sem resposta à questão" for i, lado in ficam.items() if not lado.resposta]
    respondidos = [(i, lado.resposta) for i, lado in ficam.items() if lado.resposta]
    probs += [
        f"lados {i} e {j} com a mesma resposta à questão ({a})"
        for n, (i, a) in enumerate(respondidos) for j, b in respondidos[n + 1:] if _mesma_resposta(a, b)
    ]
    return probs


def lado_unico(veiculos) -> list[Lado]:
    """A saída de emergência: um lado só, sem atores, com todos os veículos da pauta e a posição de emergência."""
    return [Lado(posicao=POSICAO_DE_EMERGENCIA, atores=(), veiculos=tuple(veiculos_distintos(veiculos)))]


def analise_da_resposta(resposta, veiculos) -> Analise:
    """A análise que vale para a pauta destes veículos, a partir da resposta do LLM (função pura).

    Cada lado tem posição, pelo menos um ator e pelo menos um veículo, todos da pauta (pela
    comparação tolerante de `qa.mesmo_veiculo`). Ator genérico (`ator_generico`) não conta: sai da
    lista, e o lado que fica sem ator é removido. Dos lados que ficam, vale de 1 a 3, cada um com
    um ator que nenhum outro tem, e todo veículo da pauta em pelo menos um deles.

    A questão e os lados andam juntos: questão vazia exige exatamente 1 lado, e questão preenchida
    exige 2 ou 3, cada um com a sua resposta, diferente das outras. Se a remoção dos genéricos
    deixar um lado só, a disputa era com quem não é ator: a questão sai, e o lado fica com todos
    os veículos da pauta.

    Resposta que não cumpre isso vira o lado único de emergência, com o motivo em `problemas`.
    """
    da_pauta = veiculos_distintos(veiculos)

    def invalida(*probs: str, removidos=()) -> Analise:
        return Analise(lado_unico(da_pauta), problemas=list(probs), removidos=list(removidos), resposta=resposta)

    lados = resposta.get("lados") if isinstance(resposta, dict) else None
    if not isinstance(lados, list):
        return invalida("resposta sem a lista de lados")
    if probs := _problemas_dos_campos(lados, da_pauta):
        return invalida(*probs)
    questao = _linha(resposta.get("questao"))
    ficam, removidos = _sem_genericos(_ler(lados, da_pauta))
    if lados and not ficam:
        return invalida("nenhum lado com ator específico", removidos=removidos)
    if not 1 <= len(ficam) <= MAX_LADOS:
        return invalida(f"resposta com {len(ficam)} lados (vale de 1 a {MAX_LADOS})", removidos=removidos)
    if len(ficam) > 1:
        if not questao:
            return invalida(f"questão vazia com {len(ficam)} lados (questão vazia exige exatamente 1 lado)", removidos=removidos)
        probs = _problemas_das_respostas(ficam)
    elif len(lados) > 1:   # sobrou um lado só: o que os lados removidos traziam é ressalva dele
        questao, probs = "", []
        ficam = {i: replace(lado, resposta="", veiculos=tuple(da_pauta)) for i, lado in ficam.items()}
    elif questao:
        return invalida("questão preenchida com 1 lado (questão preenchida exige de 2 a 3 lados; sem disputa, a questão fica vazia)")
    else:
        probs = []
        ficam = {i: replace(lado, resposta="") for i, lado in ficam.items()}
    validos = list(ficam.values())
    probs += [
        f"lado {i} sem ator que não esteja em outro lado"
        for i, proprios in zip(ficam, atores_exclusivos(validos)) if not proprios
    ]
    sem_lado = [v for v in da_pauta if not any(v in lado.veiculos for lado in validos)]
    if sem_lado:
        probs.append(f"veículo da pauta em nenhum lado ({', '.join(sem_lado)})")
    if probs:
        return invalida(*probs, removidos=removidos)
    return Analise(validos, questao, _linha(resposta.get("motivo")), removidos=removidos, resposta=resposta)


def pedido_de_correcao(recusada: Analise) -> str:
    """O que a nova tentativa acrescenta à entrada: o erro da resposta recusada, a própria resposta e o lembrete."""
    partes = [f"CORREÇÃO: a sua resposta anterior não valeu: {'; '.join(recusada.problemas)}."]
    if recusada.removidos:
        partes.append(f"Não contam como atores: {'; '.join(recusada.removidos)}.")
    if recusada.resposta is not None:
        partes.append(f"Resposta anterior: {json.dumps(recusada.resposta, ensure_ascii=False)[:MAX_ANTERIOR]}")
    partes.append(LEMBRETE_DA_CORRECAO)
    return "\n".join(partes)


def _tentar(chamar, entrada: str, veiculos) -> Analise:
    try:
        resposta = chamar(
            PROMPT_LADOS, entrada, chaves=CHAVES_LADOS, temperatura=TEMPERATURA_LADOS, max_saida=MAX_SAIDA_LADOS,
        )
    except Exception as e:  # resposta vazia, cortada, sem a chave, servidor fora do ar...
        return Analise(lado_unico(veiculos), problemas=[f"a chamada falhou ({type(e).__name__}: {str(e)[:200]})"])
    return analise_da_resposta(resposta, veiculos)


def analisar_lados(chamar, textos) -> Analise:
    """Pergunta ao LLM a questão e os lados da pauta.

    Chamada que falha ou resposta inválida ganham uma nova tentativa, com o erro anexado à entrada.
    Se ela também não valer, a pauta segue com o lado único de emergência, com aviso no log.
    `chamar(system, user, **opções)` é o chat_json do provider (ou o `_chamar` do Summarizer).
    """
    veiculos = [t["fonte"] for t in textos]
    entrada = entrada_dos_lados(textos)
    analise = _tentar(chamar, entrada, veiculos)
    if analise.problemas:
        logger.warning("Análise de lados: a resposta não valeu (%s). Nova tentativa, com o erro anexado.", "; ".join(analise.problemas))
        analise = replace(_tentar(chamar, f"{entrada}\n\n{pedido_de_correcao(analise)}", veiculos), primeira=analise)
    if analise.removidos:
        logger.info("Análise de lados: saiu o que só tem ator genérico (%s).", "; ".join(analise.removidos))
    if analise.problemas:
        logger.warning(
            "Análise de lados inválida nas duas tentativas (%s): a pauta segue com um lado só, sem lados definidos.",
            "; ".join(analise.problemas),
        )
    else:
        logger.info(
            "Lados da pauta: %d (%s)%s", len(analise.lados), " × ".join(", ".join(lado.atores) for lado in analise.lados),
            f" · questão: {analise.questao}" if analise.questao else "",
        )
    return analise


def _encurtar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1].rsplit(None, 1)[0].rstrip(",;:") + "…"


def _frase(texto: str) -> str:
    return texto if texto.endswith((".", "!", "?", "…")) else texto + "."


def bloco_dos_lados(lados, questao: str = "") -> str:
    """O bloco LADOS DA PAUTA da entrada do episódio: a questão, os lados, o elenco exato e o alvo de palavras.

    Nunca passa de MAX_BLOCO caracteres, que é o que o orçamento da entrada reserva para ele: se
    for preciso, as frases de posição encolhem.
    """
    n = len(lados)
    if n == 1:
        elenco = 'ELENCO: Helena e exatamente 1 analista, que aprofunda o tema com ela; "houve_divergencia": false.'
    else:
        elenco = (
            f'ELENCO: Helena e exatamente {n} analistas, um por lado; "houve_divergencia": true. Helena apresenta a '
            f"questão, e cada analista responde por um lado, numa frase que nomeia um ator do lado, cita um veículo do "
            f'lado e usa um verbo de posição, como em "segundo <veículo>, <ator> afirma que...".'
        )
    elenco += f" Alvo: {ALVO_POR_PERSONAGEM[n]} palavras por personagem."
    cabecalho = f"\nLADOS DA PAUTA: {n} lado{'s' if n > 1 else ''}."
    if questao:
        cabecalho += f"\nQUESTÃO: {_encurtar(questao, MAX_QUESTAO)}"

    def descrever(i: int, lado: Lado, teto: int) -> str:
        resposta = f" (resposta: {_encurtar(lado.resposta, MAX_RESPOSTA).rstrip('.')})" if lado.resposta else ""
        atores = f" Atores: {', '.join(lado.atores)}." if lado.atores else ""
        return f"Lado {i}{resposta}: {_frase(_encurtar(lado.posicao, teto))}{atores} Veículos: {', '.join(lado.veiculos)}."

    def montar(teto: int) -> str:
        return "\n".join([cabecalho, *(descrever(i, lado, teto) for i, lado in enumerate(lados, 1)), elenco])

    teto = MAX_POSICAO
    bloco = montar(teto)
    while len(bloco) > MAX_BLOCO and teto > MIN_POSICAO:
        teto -= 20
        bloco = montar(teto)
    if len(bloco) > MAX_BLOCO:   # listas de atores longas demais: o que fica de fora é o fim do último lado
        logger.warning("Bloco de lados com %d caracteres: cortado em %d.", len(bloco), MAX_BLOCO)
        linhas = bloco[len(cabecalho) + 1:].split("\n")[:-1]
        bloco = "\n".join([cabecalho, elenco, *linhas])[:MAX_BLOCO - 1] + "…"
    return bloco

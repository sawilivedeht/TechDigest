import itertools
import logging
import re
import unicodedata
from dataclasses import dataclass

from techdigest.ai.atribuicoes import atribuicoes_a_grupos, grupo_na_pauta, plano
from techdigest.ai.elenco import nomes_dos_analistas
from techdigest.ai.numeros import dobrar as _dobrar
from techdigest.ai.numeros import formatar, mais_proximo, numeros, pede_fonte, qualificador, tem_fonte, valores_dos_textos
from techdigest.ai.orcamento import Orcamento, cinco, minimo_do_qa
from techdigest.ai.verbos import FORMAS_DE_POSICAO, INFINITIVOS, agentes_da_decisao, verbos_de_posicao
from techdigest.config import Settings

logger = logging.getLogger("techdigest.ai.qa")

settings = Settings()

# Faixas editoriais (regras 2, 3 e 6). Os valores vêm do .env (QA_*); os defaults do
# config.py são as regras originais do dono.
MIN_POR_PERSONAGEM, MAX_POR_PERSONAGEM = settings.qa_min_por_personagem, settings.qa_max_por_personagem
# O analista de um lado fino (ver `ai/lados.py`) não amplia além do que as fontes trazem: o QA cobra
# o mínimo dele, e o teto que o prompt pede (MAX_LADO_FINO) é só diagnóstico.
MIN_LADO_FINO, MAX_LADO_FINO = settings.qa_min_lado_fino, settings.qa_max_lado_fino
MIN_HELENA_COM_DEBATE = settings.qa_min_helena_com_debate   # com dois analistas ou mais, Helena pode falar menos
MIN_TOTAL, MAX_TOTAL = settings.qa_min_total, settings.qa_max_total
MIN_FRASES_RESUMO, MAX_FRASES_RESUMO = settings.qa_min_frases, settings.qa_max_frases

HELENA = "helena"
# Os campos do episódio em que um problema pode estar: é o campo que decide o tipo de correção.
TITULO, RESUMO, PONTOS, ROTEIRO = "titulo_reescrito", "resumo_didatico", "pontos_chave", "roteiro_podcast"
ELENCO, FONTES, DIVERGENCIA, ESTRUTURA = "personagens", "fontes_citadas", "houve_divergencia", "estrutura"
PAPEL = "papel"   # o papel de um personagem: quem corrige é a revisão do roteiro, que devolve também os personagens


@dataclass(frozen=True)
class Problema:
    """Uma violação das regras editoriais e o campo do episódio em que ela está."""
    campo: str
    texto: str
_ARTIGOS = {"o", "a", "os", "as"}
_PREPOSICOES = {"de", "do", "da", "dos", "das"}
# Não contam como palavras na comparação de atores: partículas (da, de, do, das, dos, e), artigos e "em".
_SEM_PESO = _ARTIGOS | _PREPOSICOES | {"e", "em", "no", "na", "nos", "nas"}
# Quantificadores que acompanham um grupo sem nome ("alguns economistas"): não são o termo do grupo.
QUANTIFICADORES = frozenset({
    "um", "uma", "uns", "umas", "algum", "alguma", "alguns", "algumas", "varios", "varias", "outro", "outra",
    "outros", "outras", "muitos", "muitas", "diversos", "diversas",
})
_ABREVIATURA = re.compile(r"(?:^|[\s(\"'“‘])(?:dr|dra|sr|sra|prof|profa|sen|dep|min|gov|pres|gen|cel|[^\W\d_])\.$", re.IGNORECASE)

# Título sem percentuais nem proporções. Os padrões valem sobre o título sem acento e em minúsculas.
_ALGARISMOS = r"\d+(?:[.,]\d+)*"
_PALAVRA_DE_NUMERO = (
    r"(?:dois|duas|tres|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|catorze|quatorze|quinze|dezesseis|"
    r"dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|"
    r"(?:duz|trez|quatroc|quinh|seisc|setec|oitoc|novec)ent[oa]s|mil|(?:m|b|tr)ilh(?:ao|oes))"
)
_POR_EXTENSO = rf"\b{_PALAVRA_DE_NUMERO}\b(?:\s+(?:e\s+)?(?:um|uma|{_PALAVRA_DE_NUMERO})\b)*"
_NUMERO = rf"(?:{_ALGARISMOS}|{_POR_EXTENSO})"
_UM_OU_NUMERO = rf"(?:{_NUMERO}|\bum\b|\buma\b)"   # "um" só conta como número dentro de uma proporção
_APROXIMADOR = r"\b(?:quase|mais de|menos de|cerca de|perto de|pelo menos|ao menos|acima de|abaixo de|aproximadamente)\s+"
_PROPORCOES_NO_TITULO = [re.compile(padrao) for padrao in (
    rf"(?:(?:{_APROXIMADOR})?{_NUMERO}\s*)?(?:%|\bpor cento\b|\bpontos? percentua(?:l|is)\b)",   # percentuais
    rf"(?:{_APROXIMADOR})?{_NUMERO}\s+vezes\b",                                                    # "3 vezes", "três vezes"
    r"\b(?:dobro|triplo|quadruplo)\b",                                                            # valem por "x vezes"
    rf"{_UM_OU_NUMERO}\s+(?:em|a|de|entre)\s+cada\b(?:\s+{_NUMERO})?",                            # "três em cada quatro"
    rf"\b(?:a|em|de)\s+cada\s+{_NUMERO}",                                                         # "a cada 9 horas"
    r"\bmetade\b",
    r"\b(?:maioria|minoria|maior parte|grande parte)\b",                                           # proporção sem número
    rf"{_UM_OU_NUMERO}\s+tercos?\b",                                                              # "um terço", "dois terços"
    rf"{_UM_OU_NUMERO}\s+(?:quartos?|quintos?|sextos?|decimos?)\s+d[oa]s?\b",                      # "um quarto dos eleitores"
)]
_N_DE_M = re.compile(r"\b(\d+)\s+d[eoa]s?\s+(\d+)\b")   # "6 de 11 ministros", "60 dos 102 casos"; à parte por causa de "Pixel 9 de 128 GB"


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


def proporcoes_no_titulo(titulo) -> list[str]:
    """Os trechos do título que a regra do título bloqueia; lista vazia = aprovado.

    Bloqueia percentuais, "x vezes" (e "dobro", "triplo", "quádruplo") e proporções ("metade", "um
    terço", "três em cada quatro", "6 de 11", "a cada 9 horas", "maioria", "minoria", "maior parte",
    "grande parte"). Quantidade absoluta passa, em
    algarismos ou por extenso, mesmo com "quase", "mais de" e parecidos ("12 mortos", "doze
    mortos", "mais de 100 mortos"), assim como ano, ordinal e nome com algarismo ("Eleições 2026",
    "1º turno", "escala 6x1").
    """
    titulo = unicodedata.normalize("NFC", str(titulo))
    dobrado = _dobrar(titulo)
    achados = [m.span() for padrao in _PROPORCOES_NO_TITULO for m in padrao.finditer(dobrado)]
    for m in _N_DE_M.finditer(dobrado):
        anterior = re.search(r"[^\W\d_]+$", titulo[:m.start()].rstrip(" "))
        de_um_nome = anterior is not None and anterior.group() != anterior.group().lower()   # "Pixel 9 de 128 GB"
        if int(m.group(1)) < int(m.group(2)) and not de_um_nome:
            achados.append(m.span())
    trechos: list[list[int]] = []
    for inicio, fim in sorted(achados):
        if trechos and dobrado[trechos[-1][1]:inicio].strip() == "":   # sobrepostos, ou só espaço entre eles
            trechos[-1][1] = max(trechos[-1][1], fim)
        else:
            trechos.append([inicio, fim])
    return [titulo[inicio:fim].strip() for inicio, fim in trechos]


def _formas_faladas(veiculo) -> list[list[str]]:
    """Como um veículo pode ser dito numa fala: o nome sem artigo nem slogan, ou só o que vem antes do "de" ("Folha")."""
    palavras = _palavras_do_nome(re.split(r"\s[-–—|]\s", str(veiculo))[0])
    if len(palavras) > 1 and palavras[0] in _ARTIGOS:
        palavras = palavras[1:]
    corte = next((i for i, p in enumerate(palavras) if i and p in _PREPOSICOES), None)
    return [forma for forma in (palavras, palavras[:corte] if corte else []) if forma]


def veiculo_citado(veiculo, texto) -> bool:
    """Se o texto cita o veículo pelo nome (sem acento nem caixa, por palavras inteiras)."""
    palavras = _palavras_do_nome(texto)
    return any(palavras[i:i + len(forma)] == forma
               for forma in _formas_faladas(veiculo) for i in range(len(palavras) - len(forma) + 1))


def frases(texto) -> list[str]:
    """O texto dividido em frases. Ponto de abreviatura ("Dr.", "S. Paulo") não encerra a frase."""
    partes: list[str] = []
    for pedaco in re.split(r"(?<=[.!?…])[\"'”’)]*\s+", str(texto).strip()):
        if partes and _ABREVIATURA.search(partes[-1]):
            partes[-1] += " " + pedaco
        else:
            partes.append(pedaco)
    return [p for p in partes if p]


def palavras_do_ator(nome) -> set[str]:
    """As palavras que contam no nome de um ator: sem acento nem caixa, e sem artigo nem partícula."""
    return {p for p in _palavras_do_nome(nome) if p not in _SEM_PESO}


def mesmo_ator(a, b) -> bool:
    """Comparação tolerante de atores: sem acento, caixa, artigo nem preposição, e um nome pode conter o outro.

    "Lula" e "campanha de Lula" contam como o mesmo ator: um nome dentro do outro não separa dois lados.
    """
    menor, maior = sorted((palavras_do_ator(a), palavras_do_ator(b)), key=len)
    return bool(menor) and menor <= maior


def ator_citado(ator, texto, alheios=()) -> bool:
    """Se o texto nomeia o ator, aceitando a forma curta de um nome comprido.

    Contam as palavras do nome que nenhum ator de outro lado (`alheios`) usa, em qualquer ordem, e
    é preciso achar mais da metade delas. Assim "Nunes Marques" vale por "Kassio Nunes Marques", e
    "Lula" vale por "campanha de Lula" quando o outro lado tem a "campanha de Flávio Bolsonaro".
    Nome de uma ou duas palavras tem de aparecer inteiro.
    """
    proprias = palavras_do_ator(ator) - {p for outro in alheios for p in palavras_do_ator(outro)}
    return bool(proprias) and len(proprias & set(_palavras_do_nome(texto))) > len(proprias) / 2


def atores_exclusivos(lados) -> list[list[str]]:
    """Para cada lado, os atores que não aparecem em nenhum outro lado (pela comparação tolerante)."""
    return [
        [a for a in lado.atores if not any(mesmo_ator(a, b) for j, outro in enumerate(lados) if j != i for b in outro.atores)]
        for i, lado in enumerate(lados)
    ]


def frases_que_apresentam(result: dict, lados) -> list[list[tuple[str, str]]]:
    """Para cada lado (pela posição na lista), as frases dos analistas que o apresentam: (personagem, frase).

    Apresentar um lado é ter uma frase que cita um veículo do lado e usa um verbo de posição e
    nomeia um ator que só aquele lado tem; ou que cita um veículo do lado e traz um verbo de decisão
    na passiva com esse ator como agente ("foi determinada por decisão de <ator>"; ver
    `verbos.agentes_da_decisao`), como a análise de lados aceita a decisão de quem decidiu.
    """
    exclusivos = atores_exclusivos(lados)
    alheios = [[a for j, outro in enumerate(lados) if j != i for a in outro.atores] for i in range(len(lados))]
    achadas: list[list[tuple[str, str]]] = [[] for _ in lados]
    for turno in result["roteiro_podcast"]:
        if _palavras_do_nome(turno["personagem"]) == [HELENA]:
            continue
        for frase in frases(turno["fala"]):
            posicao, agentes = verbos_de_posicao(frase), agentes_da_decisao(frase)
            if not posicao and not agentes:
                continue
            for i, lado in enumerate(lados):
                if not any(veiculo_citado(v, frase) for v in lado.veiculos):
                    continue
                if (posicao and any(ator_citado(a, frase, alheios[i]) for a in exclusivos[i])
                        or any(ator_citado(a, agente, alheios[i]) for a in exclusivos[i] for agente in agentes)):
                    achadas[i].append((turno["personagem"], frase))
    return achadas


def lados_de_cada_analista(result: dict, lados) -> dict[str, list[int]]:
    """Para cada personagem que não é Helena, os lados (pela posição na lista) que ele apresenta (ver `frases_que_apresentam`)."""
    apresenta: dict[str, list[int]] = {
        turno["personagem"]: [] for turno in result["roteiro_podcast"] if _palavras_do_nome(turno["personagem"]) != [HELENA]
    }
    for i, achadas in enumerate(frases_que_apresentam(result, lados)):
        for personagem, _ in achadas:
            if i not in apresenta[personagem]:
                apresenta[personagem].append(i)
    return apresenta


def lado_de_cada_analista(result: dict, lados) -> dict[str, int]:
    """A correspondência um a um entre analistas e lados, quando ela existe: analista -> lado. Sem ela, vazio."""
    apresenta = lados_de_cada_analista(result, lados)
    analistas = list(apresenta)
    if len(analistas) != len(lados):
        return {}
    for ordem in itertools.permutations(range(len(lados))):
        if all(lado in apresenta[nome] for nome, lado in zip(analistas, ordem)):
            return dict(zip(analistas, ordem))
    return {}


def analistas_de_lado_fino(result: dict, lados) -> set[str]:
    """Os analistas que apresentam um lado fino (ver `ai/lados.py`; só em pauta de 2 lados ou mais).

    Vem da correspondência um a um entre analistas e lados: sem ela, nenhum.
    """
    finos = {i for i, lado in enumerate(lados) if len(lados) >= 2 and lado.fino}
    return {nome for nome, lado in (lado_de_cada_analista(result, lados) if finos else {}).items() if lado in finos}


def _lado_no_orcamento(result: dict, lados) -> dict[str, int]:
    """O lado de cada analista que se liga a um: com um lado só e um analista, o lado; senão, a correspondência um a um."""
    analistas = [nome for nome in palavras_por_personagem(result["roteiro_podcast"]) if _palavras_do_nome(nome) != [HELENA]]
    return {analistas[0]: 0} if len(lados) <= 1 and len(analistas) == 1 else lado_de_cada_analista(result, lados)


def alvo_de_cada_personagem(result: dict, lados, orc: Orcamento) -> dict[str, int]:
    """O alvo de palavras de cada personagem que fala, pelo orçamento da pauta (ver `ai/orcamento.py`).

    O da Helena é o dela. O analista leva o alvo do lado que apresenta: com um lado só e um
    analista, o do lado; com dois lados ou mais, pela correspondência um a um entre analistas e
    lados (ver `lado_de_cada_analista`). O analista que não se liga a um lado leva o menor alvo de
    analista da pauta.
    """
    por_pers = palavras_por_personagem(result["roteiro_podcast"])
    do_lado = _lado_no_orcamento(result, lados)

    def alvo(nome: str) -> int:
        if _palavras_do_nome(nome) == [HELENA]:
            return orc.helena
        lado = do_lado.get(nome)
        return orc.analistas[lado] if lado is not None and lado < len(orc.analistas) else min(orc.analistas)

    return {nome: alvo(nome) for nome in por_pers}


def limites_de_cada_personagem(result: dict, lados, orc: Orcamento | None = None) -> dict[str, tuple[int, int]]:
    """O mínimo e o máximo de palavras de cada personagem que fala.

    O máximo é sempre MAX_POR_PERSONAGEM. O mínimo de antes é MIN_POR_PERSONAGEM, a não ser para o
    analista de um lado fino (ver `analistas_de_lado_fino`), que é MIN_LADO_FINO, e para Helena em
    episódio com dois analistas ou mais, que é MIN_HELENA_COM_DEBATE. Com o orçamento da pauta
    (`orc`), o mínimo é uma fração do alvo de cada personagem, nunca acima do mínimo de antes (ver
    `orcamento.minimo_do_qa`): fica sempre abaixo do alvo que o bloco pede. O teto que o prompt
    pedia ao analista de lado fino (MAX_LADO_FINO) não entra aqui: é só diagnóstico.
    """
    por_pers = palavras_por_personagem(result["roteiro_podcast"])
    analistas = [nome for nome in por_pers if _palavras_do_nome(nome) != [HELENA]]
    finos = analistas_de_lado_fino(result, lados)
    alvos = alvo_de_cada_personagem(result, lados, orc) if orc else {}

    def minimo(nome: str) -> int:
        if nome in finos:
            de_antes = MIN_LADO_FINO
        elif _palavras_do_nome(nome) == [HELENA] and len(analistas) >= 2:
            de_antes = MIN_HELENA_COM_DEBATE
        else:
            de_antes = MIN_POR_PERSONAGEM
        return minimo_do_qa(alvos[nome], de_antes) if orc else de_antes

    return {nome: (minimo(nome), MAX_POR_PERSONAGEM) for nome in por_pers}


def o_que_falta(result: dict, lados, orc: Orcamento, nome: str) -> str:
    """O que falta nas falas de um personagem abaixo do mínimo, pelo plano das falas do bloco (ver `orcamento.Orcamento.plano`).

    Com o número de falas do plano, diz quantas palavras acrescentar a cada fala; com outro número, quantas palavras
    faltam para o alvo. O analista que não se liga a um lado não tem plano: só as palavras que faltam.
    """
    falas = [contar_palavras(t["fala"]) for t in result["roteiro_podcast"] if t["personagem"] == nome]
    palavras, media = sum(falas), round(sum(falas) / len(falas))
    alvo = alvo_de_cada_personagem(result, lados, orc)[nome]
    do_lado = _lado_no_orcamento(result, lados)
    i = 0 if _palavras_do_nome(nome) == [HELENA] else (do_lado[nome] + 1 if nome in do_lado else None)
    faltam = f"faltam uns {cinco(alvo - palavras)} palavras para o alvo"
    if i is None or i >= len(orc.plano.falas):
        return f"{faltam}, com o que os textos trazem"
    n, tamanho = orc.plano.falas[i], orc.plano.tamanhos[i]
    feito = f"{len(falas)} fala{'s' if len(falas) > 1 else ''} de uns {media} palavras; o plano pede {n} falas de uns {tamanho}"
    if len(falas) == n and cinco(tamanho - media) > 0:
        return f"{feito}: acrescente uns {cinco(tamanho - media)} palavras a cada fala, com o que os textos trazem"
    return f"{feito}: {faltam}; siga o plano e complete as falas com o que os textos trazem"


def limites_do_total(orc: Orcamento | None = None) -> tuple[int, int]:
    """O mínimo e o máximo de palavras do roteiro inteiro: com o orçamento, o mínimo é uma fração do alvo total."""
    return (minimo_do_qa(orc.total, MIN_TOTAL) if orc else MIN_TOTAL), MAX_TOTAL


def problemas_dos_papeis(result: dict, lados) -> list[str]:
    """O papel de um analista não traz o nome de um ator dos lados ("analista da Meta"); lista vazia = aprovado."""
    atores = [ator for lado in lados for ator in lado.atores]
    probs = []
    for personagem in result["personagens"]:
        papel = str(personagem.get("papel") or "")
        citados = [ator for ator in atores if ator_citado(ator, papel)]
        if citados and _palavras_do_nome(personagem["nome"]) != [HELENA]:
            probs.append(
                f"papel de {personagem['nome']} com o nome de um ator dos lados (\"{papel}\"): o papel diz a especialidade "
                f"do analista (\"analista de regulação\"), sem ligá-lo a {', '.join(citados)}"
            )
    return probs


def problemas_dos_nomes(result: dict, lados, textos=()) -> list[str]:
    """Os analistas que falam no roteiro têm os nomes que o bloco LADOS DA PAUTA dá (ver `elenco.nomes_dos_analistas`);
    lista vazia = aprovado.

    Confere o nome, não o lado: o analista do lado 2 com o nome do lado 1 passa. O número de analistas é da regra dos
    analistas por lado (ver `problemas_dos_analistas`). `textos` são os textos da pauta, os mesmos que o bloco recebe:
    a escolha do nome evita também as pessoas citadas neles.
    """
    nomes = nomes_dos_analistas(lados, textos)
    return [
        f"o analista {nome} não tem um dos nomes que o bloco LADOS DA PAUTA dá aos analistas ({', '.join(nomes)}): use os "
        f"nomes do bloco, em \"personagens\" e no roteiro"
        for nome in palavras_por_personagem(result["roteiro_podcast"])
        if _palavras_do_nome(nome) != [HELENA] and _palavras_do_nome(nome) not in [_palavras_do_nome(n) for n in nomes]
    ]


def _dos_analistas(result: dict, lados) -> list[Problema]:
    n = len(lados)
    apresenta = lados_de_cada_analista(result, lados)
    analistas = list(apresenta)
    probs = []
    if len(analistas) != n:
        probs.append(Problema(ELENCO, (
            f"{len(analistas)} analista(s) ({', '.join(analistas) or 'nenhum'}) para {n} lado(s): o elenco é Helena e "
            f"exatamente {n} analista(s), um por lado"
        )))
    if result["houve_divergencia"] is not (n >= 2):
        probs.append(Problema(DIVERGENCIA, (
            f"houve_divergencia tem de ser {'true' if n >= 2 else 'false'}: a pauta tem {n} lado(s), e o campo é true "
            f"se e só se houver 2 lados ou mais"
        )))
    um_a_um = any(all(lado in apresenta[nome] for nome, lado in zip(analistas, ordem)) for ordem in itertools.permutations(range(n)))
    if n >= 2 and len(analistas) == n and not um_a_um:
        feito = "; ".join(
            f"{nome}: {' e '.join(f'lado {i + 1}' for i in sorted(apresenta[nome])) or 'nenhum lado'}" for nome in analistas
        )
        exclusivos = atores_exclusivos(lados)
        descricao = " ".join(
            f"Lado {i + 1}: atores {', '.join(exclusivos[i]) or 'nenhum'}; veículos {', '.join(lado.veiculos)}."
            for i, lado in enumerate(lados)
        )
        probs.append(Problema(ROTEIRO, (
            f"os analistas não apresentam os lados um a um ({feito}): cada analista precisa de uma frase que nomeie um "
            f"ator do seu lado, cite um veículo do lado e use um verbo de posição ({INFINITIVOS}), como em "
            f"\"segundo <veículo>, <ator> afirma que...\". {descricao}"
        )))
    return probs


def problemas_dos_analistas(result: dict, lados) -> list[str]:
    """As regras que ligam o elenco aos lados da pauta (ver `ai/lados.py`); lista vazia = aprovado.

    O episódio tem exatamente um analista por lado (Helena não conta), e houve_divergencia é true
    se e só se há dois lados ou mais. Com dois lados ou mais, é preciso haver uma correspondência
    um a um entre analistas e lados em que cada analista apresenta o seu lado (ver
    `lados_de_cada_analista`). A regra confere a forma da atribuição, não se ela é fiel ao texto.
    """
    return [p.texto for p in _dos_analistas(result, lados)]


def _raiz(palavra: str) -> str:
    """A palavra (sem acento, em minúsculas) sem as marcas de número e de gênero.

    "pesquisador", "pesquisadora", "pesquisadores" e "pesquisadoras" têm a mesma raiz, assim como
    "crítico" e "críticas" ou "organização" e "organizações". Não cobre plural irregular nem
    palavra em "-ês" ("portugueses").
    """
    if palavra.endswith(("oes", "aes")):
        palavra = palavra[:-3] + "ao"
    elif palavra.endswith(("ais", "eis", "ois", "uis")):
        palavra = palavra[:-2] + "l"
    elif palavra.endswith("ns"):
        palavra = palavra[:-2] + "m"
    elif palavra.endswith(("res", "zes")):
        palavra = palavra[:-2]
    elif palavra.endswith("s"):
        palavra = palavra[:-1]
    return palavra[:-1] if palavra.endswith(("o", "a", "e")) else palavra


def termo_do_grupo(grupo) -> str:
    """A palavra principal de um grupo sem nome: a primeira que não é artigo, partícula nem quantificador.

    Para "especialistas em segurança" e para "alguns especialistas", é "especialistas".
    """
    return next((p for p in _palavras_do_nome(grupo) if p not in _SEM_PESO and p not in QUANTIFICADORES), "")


def grupo_citado(grupo, texto) -> bool:
    """Se o texto traz o termo do grupo, em qualquer número ou gênero ("pesquisadores", "pesquisadora").

    Forma de verbo de posição não conta como termo: em "o candidato critica", "critica" não é "críticos".
    """
    raiz = _raiz(termo_do_grupo(grupo))
    palavras = re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", str(texto)).lower())
    return bool(raiz) and any(_raiz(_dobrar(p)) == raiz for p in palavras if p not in FORMAS_DE_POSICAO)


def _de_helena(result: dict) -> list[str]:
    return [turno["fala"] for turno in result["roteiro_podcast"] if _palavras_do_nome(turno["personagem"]) == [HELENA]]


def perguntas_das_ressalvas(result: dict, ressalvas) -> list[list[tuple[str, bool]]]:
    """Para cada ressalva, as frases da Helena que a trazem e se a fala de cada uma tem ponto de interrogação.

    Trazer a ressalva é citar um veículo dela, nomear um dos grupos (ver `grupo_citado`) e usar um
    verbo de posição, tudo na mesma frase. Ressalva sem grupo só pede o veículo e o verbo.
    """
    achadas: list[list[tuple[str, bool]]] = []
    for ressalva in ressalvas:
        achadas.append([
            (frase, "?" in fala)
            for fala in _de_helena(result) for frase in frases(fala)
            if verbos_de_posicao(frase) and any(veiculo_citado(v, frase) for v in ressalva.veiculos)
            and (not ressalva.grupos or any(grupo_citado(g, frase) for g in ressalva.grupos))
        ])
    return achadas


def problemas_das_ressalvas(result: dict, ressalvas) -> list[str]:
    """Cada ressalva da pauta (ver `ai/lados.py`) é uma pergunta atribuída da Helena; lista vazia = aprovado.

    A regra confere a forma: a frase com veículo, grupo e verbo de posição, numa fala da Helena
    que tenha ponto de interrogação. Não confere se a Helena avalia a ressalva.
    """
    probs = []
    for i, (ressalva, achadas) in enumerate(zip(ressalvas, perguntas_das_ressalvas(result, ressalvas)), 1):
        if any(tem_pergunta for _, tem_pergunta in achadas):
            continue
        descricao = f"ressalva {i} ({', '.join(ressalva.grupos) or 'sem grupo'}; {', '.join(ressalva.veiculos)})"
        falta = (
            "a fala da Helena que a traz não tem pergunta" if achadas
            else "não aparece numa frase da Helena com o veículo, o grupo e um verbo de posição"
        )
        probs.append(
            f"{descricao}: {falta}. Helena apresenta cada ressalva como pergunta atribuída, numa fala com ponto de "
            f"interrogação em que uma frase cita o veículo, nomeia o grupo e usa um verbo de posição ({INFINITIVOS}), "
            f"como em \"Segundo <veículo>, <grupo> alertam que... Como você vê isso?\""
        )
    return probs


def _textos_do_episodio(result: dict) -> list[tuple[str, str, str]]:
    """Os textos do episódio em que uma atribuição pode estar: (campo, onde, texto)."""
    pontos = result["pontos_chave"] if isinstance(result.get("pontos_chave"), list) else []
    return [
        (TITULO, "no título", str(result["titulo_reescrito"])),
        (RESUMO, "no resumo", str(result["resumo_didatico"])),
        *((PONTOS, "nos pontos-chave", str(ponto)) for ponto in pontos),
        *((ROTEIRO, f"na fala de {turno['personagem']}", str(turno["fala"])) for turno in result["roteiro_podcast"]),
    ]


def problemas_das_atribuicoes(result: dict, textos) -> list[Problema]:
    """As atribuições a um grupo sem nome que nenhum texto da pauta cita; lista vazia = aprovado.

    `textos` são os textos da pauta (título e texto de cada artigo). Vale a lista fechada de
    `ai/atribuicoes.py`: "para os analistas, ...", "especialistas afirmam", "segundo as análises".
    O grupo conta como citado quando os textos trazem uma palavra da mesma família.
    """
    da_pauta = plano(textos)
    probs = []
    for campo, onde, texto in _textos_do_episodio(result):
        for grupo, expressao, _ in atribuicoes_a_grupos(texto):
            if not grupo_na_pauta(grupo, da_pauta):
                probs.append(Problema(campo, (
                    f"atribuição a um grupo que os textos da pauta não citam, {onde} (\"{expressao}\"): atribua a "
                    f"informação a quem as fontes nomeiam ou retire a frase"
                )))
    return probs


def problemas_dos_numeros(result: dict, textos) -> list[Problema]:
    """Os percentuais e os números a partir de 10 que nenhum texto da pauta traz; lista vazia = aprovado.

    `textos` são os textos da pauta (título e texto completo de cada artigo). O número vale em
    algarismos ou por extenso, e o arredondamento segue `numeros.tem_fonte`: com "cerca de" ou
    "aproximadamente", até 5% do número da fonte; com "quase", a fonte abaixo do dito; com "mais
    de", acima; sem qualificador, só o inteiro que arredonda ou trunca um decimal da fonte, também
    na escala em que o número é dito ("245 milhões" para R$ 245,5 milhões, com 10 ou mais na escala).
    Número menor que 10 que não é percentual fica só no diagnóstico (`scripts/checar_fidelidade.py`).
    """
    da_pauta = valores_dos_textos(textos)
    probs = []
    for campo, onde, texto in _textos_do_episodio(result):
        texto = unicodedata.normalize("NFC", texto)
        for n in numeros(texto):
            if not pede_fonte(n) or tem_fonte(n, qualificador(texto, n), da_pauta):
                continue
            perto = mais_proximo(n, da_pauta)
            dica = f"; a pauta traz {formatar(perto, n.percentual)}" if perto is not None else ""
            dito = " ".join(f"{qualificador(texto, n)} {n.trecho}".split())
            probs.append(Problema(campo, (
                f"número que os textos da pauta não trazem, {onde} (\"{dito}\"{dica}): use o número da fonte "
                f"ou retire-o"
            )))
    return probs


def problemas_com_campo(result: dict, veiculos, lados, ressalvas, textos, orc: Orcamento | None = None) -> list[Problema]:
    """As violações do episódio, cada uma com o campo em que está; lista vazia = aprovado.

    `veiculos` são os veículos dos textos que entraram no episódio: com dois ou mais distintos,
    todos têm de aparecer em fontes_citadas. `lados` e `ressalvas` são o resultado da análise de
    lados da pauta (`ai/lados.py`): os lados definem o elenco (ver `problemas_dos_analistas`) e
    cada ressalva pede uma pergunta atribuída da Helena (ver `problemas_das_ressalvas`). `textos`
    são os textos da pauta, para as regras das atribuições e dos números (ver
    `problemas_das_atribuicoes` e `problemas_dos_numeros`). Todos são obrigatórios: quem monta as
    listas é o Summarizer, para toda pauta. `orc` é o orçamento de palavras da pauta (ver
    `ai/orcamento.py`): com ele, os mínimos de palavras vêm do alvo de cada personagem e do total, e
    a mensagem diz o alvo e, para quem está abaixo do mínimo, o que falta em cada fala pelo plano (ver
    `o_que_falta`); sem ele, valem os mínimos de antes. Os analistas têm os nomes que o bloco dá (ver
    `problemas_dos_nomes`).
    """
    probs = []

    proporcoes = proporcoes_no_titulo(result["titulo_reescrito"])
    if proporcoes:
        probs.append(Problema(TITULO, (
            f"título com percentual ou proporção ({'; '.join(proporcoes)}): o título não leva percentuais, \"x vezes\" "
            f"(nem \"dobro\" ou \"triplo\") nem proporções, como \"metade\" ou \"maioria\" (quantidades absolutas "
            f"podem ficar); reescreva-o a partir do resumo_didatico"
        )))

    frases_do_resumo = sum(result["resumo_didatico"].count(p) for p in ".!?")
    if not (MIN_FRASES_RESUMO <= frases_do_resumo <= MAX_FRASES_RESUMO):
        probs.append(Problema(RESUMO, f"resumo com {frases_do_resumo} frases (alvo {MIN_FRASES_RESUMO}-{MAX_FRASES_RESUMO})"))

    por_pers = palavras_por_personagem(result["roteiro_podcast"])
    finos = analistas_de_lado_fino(result, lados)
    alvos = alvo_de_cada_personagem(result, lados, orc) if orc else {}
    for nome, (minimo, maximo) in limites_de_cada_personagem(result, lados, orc).items():
        if not (minimo <= por_pers[nome] <= maximo):
            fino = ": é o analista de um lado fino, que não amplia além do que as fontes trazem" if nome in finos else ""
            limites = f"aceito de {minimo} a {maximo}; o alvo do bloco é {alvos[nome]}" if orc else f"alvo {minimo}-{maximo}"
            falta = f": {o_que_falta(result, lados, orc, nome)}" if orc and por_pers[nome] < minimo else ""
            probs.append(Problema(ROTEIRO, f"{nome} com {por_pers[nome]} palavras ({limites}{fino}){falta}"))

    total = sum(por_pers.values())
    minimo_total, maximo_total = limites_do_total(orc)
    if not (minimo_total <= total <= maximo_total):
        limites = f"aceito de {minimo_total} a {maximo_total}; o alvo do bloco é {orc.total}" if orc else f"alvo {MIN_TOTAL}-{MAX_TOTAL}"
        probs.append(Problema(ROTEIRO, f"total de {total} palavras ({limites})"))

    declarados = {p["nome"] for p in result["personagens"]}
    falantes = set(por_pers)
    if falantes != declarados:
        probs.append(Problema(ELENCO, f"personagens inconsistentes: {falantes ^ declarados}"))

    distintos = veiculos_distintos(veiculos)
    if len(distintos) >= 2:
        citadas = result["fontes_citadas"] if isinstance(result["fontes_citadas"], list) else []
        faltando = [v for v in distintos if not any(mesmo_veiculo(v, citada) for citada in citadas)]
        if faltando:
            probs.append(Problema(FONTES, (
                f"fontes_citadas sem {', '.join(faltando)} (o episódio tem {len(distintos)} veículos como "
                f"fonte: cite cada um pelo nome no roteiro e liste todos em fontes_citadas)"
            )))

    probs += _dos_analistas(result, lados)
    probs += [Problema(ELENCO, texto) for texto in problemas_dos_nomes(result, lados, textos)]
    probs += [Problema(PAPEL, texto) for texto in problemas_dos_papeis(result, lados)]
    probs += [Problema(ROTEIRO, texto) for texto in problemas_das_ressalvas(result, ressalvas)]
    probs += problemas_das_atribuicoes(result, textos)
    probs += problemas_dos_numeros(result, textos)
    return probs


def problemas(result: dict, veiculos, lados, ressalvas, textos, orc: Orcamento | None = None) -> list[str]:
    """Retorna lista de violações; lista vazia = aprovado (ver `problemas_com_campo`)."""
    return [p.texto for p in problemas_com_campo(result, veiculos, lados, ressalvas, textos, orc)]

"""Verbos de posição: com eles o analista atribui uma posição a quem a sustenta ("a Meta alega...").

A lista é uma só para o prompt, que mostra os infinitivos, e para o QA, que aceita as formas
abaixo: terceira pessoa do presente, do pretérito perfeito e do imperfeito, no singular e no
plural, o gerúndio e o infinitivo. As formas vão escritas uma a uma, sem radicais: "nega" não é
"negócio", "cobra" não é "cobertura". O pretérito composto ("havia afirmado", "tinha dito") vale
como um par, o auxiliar seguido do particípio: o particípio sozinho não conta, porque "dito" e
"pedido" também são substantivos ("o pedido da campanha").

Verbo que apresenta a afirmação como verdadeira não entra ("constatar", "revelar", "reconhecer",
"admitir"): numa pauta com disputa, ele toma partido.

Os verbos de decisão são outra lista: quem decide responde a favor da decisão, mas "suspender" e
"mandar" não atribuem uma posição. A análise de lados aceita a frase que nomeia o ator e tem um deles
(ver `lados.traz_a_resposta`), e o QA aceita o particípio deles na passiva com o ator como agente
("a suspensão foi determinada por decisão do presidente do TSE, <ator>"; ver `agentes_da_decisao`).
"""
import re
import unicodedata

VERBOS_DE_POSICAO = {
    "afirmar": ("afirma", "afirmam", "afirmou", "afirmaram", "afirmava", "afirmavam", "afirmando"),
    "defender": ("defende", "defendem", "defendeu", "defenderam", "defendia", "defendiam", "defendendo"),
    "apontar": ("aponta", "apontam", "apontou", "apontaram", "apontava", "apontavam", "apontando"),
    "criticar": ("critica", "criticam", "criticou", "criticaram", "criticava", "criticavam", "criticando"),
    "questionar": ("questiona", "questionam", "questionou", "questionaram", "questionava", "questionavam", "questionando"),
    "negar": ("nega", "negam", "negou", "negaram", "negava", "negavam", "negando"),
    "alertar": ("alerta", "alertam", "alertou", "alertaram", "alertava", "alertavam", "alertando"),
    "sustentar": ("sustenta", "sustentam", "sustentou", "sustentaram", "sustentava", "sustentavam", "sustentando"),
    "contestar": ("contesta", "contestam", "contestou", "contestaram", "contestava", "contestavam", "contestando"),
    "cobrar": ("cobra", "cobram", "cobrou", "cobraram", "cobrava", "cobravam", "cobrando"),
    "responder": ("responde", "respondem", "respondeu", "responderam", "respondia", "respondiam", "respondendo"),
    "acusar": ("acusa", "acusam", "acusou", "acusaram", "acusava", "acusavam", "acusando"),
    "alegar": ("alega", "alegam", "alegou", "alegaram", "alegava", "alegavam", "alegando"),
    "rebater": ("rebate", "rebatem", "rebateu", "rebateram", "rebatia", "rebatiam", "rebatendo"),
    "avaliar": ("avalia", "avaliam", "avaliou", "avaliaram", "avaliava", "avaliavam", "avaliando"),
    "ponderar": ("pondera", "ponderam", "ponderou", "ponderaram", "ponderava", "ponderavam", "ponderando"),
    # os de quem decide ou fundamenta uma decisão
    "entender": ("entende", "entendem", "entendeu", "entenderam", "entendia", "entendiam", "entendendo"),
    "argumentar": ("argumenta", "argumentam", "argumentou", "argumentaram", "argumentava", "argumentavam", "argumentando"),
    "destacar": ("destaca", "destacam", "destacou", "destacaram", "destacava", "destacavam", "destacando"),
    "determinar": ("determina", "determinam", "determinou", "determinaram", "determinava", "determinavam", "determinando"),
    "decidir": ("decide", "decidem", "decidiu", "decidiram", "decidia", "decidiam", "decidindo"),
    # os de quem informa ou declara, como um órgão técnico ou um porta-voz
    "informar": ("informa", "informam", "informou", "informaram", "informava", "informavam", "informando"),
    "concluir": ("conclui", "concluem", "concluiu", "concluíram", "concluía", "concluíam", "concluindo"),
    "dizer": ("diz", "dizem", "disse", "disseram", "dizia", "diziam", "dizendo"),
    "declarar": ("declara", "declaram", "declarou", "declararam", "declarava", "declaravam", "declarando"),
    # os de quem qualifica um fato ou põe ênfase numa parte dele ("classificou o vídeo como...")
    "classificar": ("classifica", "classificam", "classificou", "classificaram", "classificava", "classificavam", "classificando"),
    "ressaltar": ("ressalta", "ressaltam", "ressaltou", "ressaltaram", "ressaltava", "ressaltavam", "ressaltando"),
}
# O particípio de cada verbo, que só conta depois de um auxiliar (ver `verbos_de_posicao`).
PARTICIPIOS = {
    "afirmar": "afirmado", "defender": "defendido", "apontar": "apontado", "criticar": "criticado",
    "questionar": "questionado", "negar": "negado", "alertar": "alertado", "sustentar": "sustentado",
    "contestar": "contestado", "cobrar": "cobrado", "responder": "respondido", "acusar": "acusado", "alegar": "alegado",
    "rebater": "rebatido", "avaliar": "avaliado", "ponderar": "ponderado", "entender": "entendido",
    "argumentar": "argumentado", "destacar": "destacado", "determinar": "determinado", "decidir": "decidido",
    "informar": "informado", "concluir": "concluído", "dizer": "dito", "declarar": "declarado",
    "classificar": "classificado", "ressaltar": "ressaltado",
}
AUXILIARES = frozenset({"tem", "têm", "tinha", "tinham", "teria", "teriam", "havia", "haviam"})
FORMAS_DE_POSICAO = frozenset(forma for formas in VERBOS_DE_POSICAO.values() for forma in formas) | frozenset(VERBOS_DE_POSICAO)
INFINITIVOS = ", ".join(VERBOS_DE_POSICAO)   # como a lista aparece nos prompts e nas mensagens do QA
_PARTICIPIOS = frozenset(PARTICIPIOS.values())

# Os verbos de decisão, com o particípio ("a suspensão determinada pelo ministro"). Não são verbos de posição.
FORMAS_DE_DECISAO = frozenset({
    "determina", "determinam", "determinou", "determinaram", "determinava", "determinavam", "determinando",
    "determinado", "determinada", "determinados", "determinadas",
    "decide", "decidem", "decidiu", "decidiram", "decidia", "decidiam", "decidindo",
    "decidido", "decidida", "decididos", "decididas",
    "suspende", "suspendem", "suspendeu", "suspenderam", "suspendia", "suspendiam", "suspendendo",
    "suspenso", "suspensa", "suspensos", "suspensas",
    "manda", "mandam", "mandou", "mandaram", "mandava", "mandavam", "mandando",
    "mandado", "mandada", "mandados", "mandadas",
})

# O particípio dos verbos de decisão, que faz a passiva ("foi determinada por..."), e o que pode vir no lugar do agente.
PARTICIPIOS_DE_DECISAO = frozenset(f for f in FORMAS_DE_DECISAO if re.search(r"(?:ad|id|s)[oa]s?$", f) and not f.endswith("ia"))
_DO_AGENTE = frozenset({"por", "pelo", "pela", "pelos", "pelas"})
_ATE_O_AGENTE = 3             # palavras, no máximo, entre o particípio e o "por" ("determinada na sexta-feira pelo...")
# Onde o agente acaba: no próximo verbo (de posição, de decisão ou de ligação), na conjunção que abre outra oração ou
# no ponto e vírgula. Com dois agentes ("pelo ministro e pelo governador"), fica o primeiro.
_FIM_DO_AGENTE = FORMAS_DE_POSICAO | FORMAS_DE_DECISAO | frozenset({
    "foi", "foram", "é", "são", "era", "eram", "será", "serão", "seria", "seriam", "está", "estão", "estava", "estavam",
    "e", "mas", "porém", "enquanto", "que", ";",
})


def _palavras(texto) -> list[str]:
    return re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", str(texto)).lower())


def verbos_de_posicao(texto) -> list[str]:
    """As formas de verbo de posição que aparecem no texto, como palavras inteiras, na ordem do texto.

    O pretérito composto vem como o par ("havia afirmado"). A caixa não conta, mas o acento conta:
    "crítica" (substantivo) não é "critica".
    """
    palavras = _palavras(texto)
    achadas = []
    for i, palavra in enumerate(palavras):
        if palavra in FORMAS_DE_POSICAO:
            achadas.append(palavra)
        elif palavra in _PARTICIPIOS and i and palavras[i - 1] in AUXILIARES:
            achadas.append(f"{palavras[i - 1]} {palavra}")
    return achadas


def verbos_de_decisao(texto) -> list[str]:
    """As formas de verbo de decisão que aparecem no texto, como palavras inteiras (o acento conta, como acima)."""
    return [palavra for palavra in _palavras(texto) if palavra in FORMAS_DE_DECISAO]


def agentes_da_decisao(texto) -> list[str]:
    """Os agentes da passiva dos verbos de decisão no texto, como estão escritos: o que vem depois do "por" (ou "pelo",
    "pela"...) que segue o particípio, em até _ATE_O_AGENTE palavras, até o próximo verbo, conjunção ou ponto e vírgula.

    Em "a suspensão foi determinada por decisão do presidente do TSE, Kassio Nunes Marques", o agente é "decisão do
    presidente do TSE, Kassio Nunes Marques"; em "a medida, determinada pelo TSE, foi criticada por Lula", é "TSE".
    """
    texto = unicodedata.normalize("NFC", str(texto))
    achadas = [(m.group().lower(), m.start(), m.end()) for m in re.finditer(r"[^\W\d_]+|;", texto)]
    agentes = []
    for i, (palavra, _, _) in enumerate(achadas):
        if palavra not in PARTICIPIOS_DE_DECISAO:
            continue
        por = next((k for k in range(i + 1, min(i + 2 + _ATE_O_AGENTE, len(achadas))) if achadas[k][0] in _DO_AGENTE), None)
        if por is None:
            continue
        fim = next((k for k in range(por + 1, len(achadas)) if achadas[k][0] in _FIM_DO_AGENTE), len(achadas))
        if fim > por + 1:
            agentes.append(texto[achadas[por + 1][1]:achadas[fim - 1][2]])
    return agentes

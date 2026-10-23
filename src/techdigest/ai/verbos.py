"""Verbos de posição: com eles o analista atribui uma posição a quem a sustenta ("a Meta alega...").

A lista é uma só para o prompt, que mostra os infinitivos, e para o QA, que aceita as formas
abaixo: terceira pessoa do presente, do pretérito perfeito e do imperfeito, no singular e no
plural, o gerúndio e o infinitivo. As formas vão escritas uma a uma, sem radicais: "nega" não é
"negócio", "cobra" não é "cobertura". O pretérito composto ("havia afirmado", "tinha dito") vale
como um par, o auxiliar seguido do particípio: o particípio sozinho não conta, porque "dito" e
"pedido" também são substantivos ("o pedido da campanha").

Verbo que apresenta a afirmação como verdadeira não entra ("constatar", "revelar", "reconhecer",
"admitir"): numa pauta com disputa, ele toma partido.

Os verbos de decisão são outra lista, que só a análise de lados usa (ver `lados.traz_a_resposta`):
quem decide responde a favor da decisão, mas "suspender" e "mandar" não atribuem uma posição.
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

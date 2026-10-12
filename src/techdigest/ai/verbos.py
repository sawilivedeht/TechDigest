"""Verbos de posição: com eles o analista atribui uma posição a quem a sustenta ("a Meta alega...").

A lista é uma só para o prompt, que mostra os infinitivos, e para o QA, que aceita as formas
abaixo: terceira pessoa do presente, do pretérito perfeito e do imperfeito, no singular e no
plural, mais o gerúndio. As formas vão escritas uma a uma, sem radicais: "nega" não é "negócio",
"cobra" não é "cobertura".
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
}
FORMAS_DE_POSICAO = frozenset(forma for formas in VERBOS_DE_POSICAO.values() for forma in formas)
INFINITIVOS = ", ".join(VERBOS_DE_POSICAO)   # como a lista aparece nos prompts e nas mensagens do QA


def verbos_de_posicao(texto) -> list[str]:
    """As formas de verbo de posição que aparecem no texto, como palavras inteiras.

    A caixa não conta, mas o acento conta: "crítica" (substantivo) não é "critica" (verbo).
    """
    palavras = re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", str(texto)).lower())
    return [p for p in palavras if p in FORMAS_DE_POSICAO]

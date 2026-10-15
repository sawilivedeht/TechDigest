"""Atribuições a grupos sem nome ("especialistas afirmam", "para os analistas, ...").

Acha essas atribuições num texto e diz se os textos da pauta citam o grupo. Serve ao QA, que
reprova a atribuição a um grupo que nenhum texto da pauta traz, e ao diagnóstico de
scripts/checar_fidelidade.py. Compara texto, não sentido: é uma lista fechada de grupos, de
marcas de atribuição e de verbos. Pergunta aberta ("O que os especialistas dizem sobre isso?")
não é atribuição: ver `pergunta_aberta`.
"""
import re
import unicodedata

from techdigest.ai.verbos import VERBOS_DE_POSICAO

# Grupo sem nome a quem o episódio atribui algo (no plural) -> radical que o confirma na pauta.
GRUPOS = {
    "analistas": "analis", "análises": "analis",              # a análise é de quem analisa: a mesma família
    "estudiosos": "estud", "estudos": "estud",
    "pesquisadores": "pesquisa", "pesquisadoras": "pesquisa", "pesquisas": "pesquisa",
    "especialistas": "especialista", "economistas": "economista", "juristas": "jurista", "cientistas": "cientista",
    "observadores": "observador", "críticos": "critic", "autoridades": "autoridade", "entidades": "entidade",
    "organizações": "organizac", "levantamentos": "levantamento", "relatórios": "relatorio",
    "projeções": "projec", "estimativas": "estimativa",
}
# Os verbos de posição cujos plurais esta regra usa. A lista não acompanha os verbos de posição
# acrescentados depois (informar, concluir, dizer, declarar): verbo novo aqui faz a regra reprovar
# mais, e regra nova que reprova passa antes pelo diagnóstico.
_POSICAO_DA_REGRA = (
    "afirmar", "defender", "apontar", "criticar", "questionar", "negar", "alertar", "sustentar", "contestar", "cobrar",
    "responder", "acusar", "alegar", "rebater", "avaliar", "ponderar", "entender", "argumentar", "destacar", "determinar",
    "decidir",
)
# Verbos que, depois do grupo, fazem dele a fonte de uma afirmação: os de posição acima, no plural, e mais alguns.
VERBOS_DE_ATRIBUICAO = frozenset(forma for verbo in _POSICAO_DA_REGRA for forma in VERBOS_DE_POSICAO[verbo] if forma.endswith("m")) | {
    "dizem", "disseram", "diziam", "veem", "viam", "consideram", "acreditam", "entendem", "estimam", "preveem",
    "indicam", "mostram", "sugerem", "revelam", "destacam", "ressaltam", "observam", "explicam", "argumentam",
    "temem", "calculam", "projetam", "concordam", "discordam", "divergem", "reconhecem", "admitem", "concluem",
}
_ALTERNATIVAS = "|".join(sorted(GRUPOS, key=len, reverse=True))
_QUANTOS = r"(?:os|as|alguns|algumas|muitos|muitas|diversos|diversas|vários|várias)"
_MARCA_ANTES = re.compile(     # "segundo as análises", "na avaliação de especialistas"
    rf"\b(?:segundo|conforme|de acordo com|na (?:visão|avaliação|opinião|leitura) d[eoa]s?)\s+(?:{_QUANTOS}\s+)?"
    rf"({_ALTERNATIVAS})\b", re.IGNORECASE)
_PARA_ANTES = re.compile(      # "Para os analistas, ...": só no começo da oração e seguido de vírgula
    rf"(?:^|[.!?;:,—–\n])\s*(para\s+{_QUANTOS}\s+({_ALTERNATIVAS}))\b(?=\s*,)", re.IGNORECASE)
_VERBO_DEPOIS = re.compile(    # "especialistas afirmam", "os economistas também alertam"
    rf"\b({_ALTERNATIVAS})\b(?:[ \t]+[^\W\d_]+){{0,3}}?[ \t]+(?:{'|'.join(sorted(VERBOS_DE_ATRIBUICAO))})\b", re.IGNORECASE)
# Antes do grupo, estas palavras dizem que ele é o elenco do episódio ("nossos analistas explicam"), não uma fonte.
_DO_ELENCO = re.compile(r"\b(?:nossos|nossas|dois|duas|três|esses|essas|estes|estas|meus|minhas)\s+$", re.IGNORECASE)
# Palavra interrogativa antes do grupo, numa frase que termina em "?": é pergunta aberta, não atribuição.
_INTERROGATIVA = re.compile(r"\b(?:o que|como|qual|quais|por que|quem|onde|quando)\b", re.IGNORECASE)
_FIM_DE_FRASE = re.compile(r"[.!?…\n]")


def pergunta_aberta(texto: str, posicao: int) -> bool:
    """Se o grupo que está em `posicao` faz parte de uma pergunta aberta, e não de uma atribuição.

    É a frase que termina em "?" e tem uma palavra interrogativa (o que, como, qual, quais, por
    que, quem, onde, quando) antes do grupo: "O que os especialistas dizem sobre isso?". A pergunta
    que carrega uma afirmação ("Os especialistas dizem que..., não é?") continua contando.
    """
    inicio = max((texto.rfind(sinal, 0, posicao) for sinal in ".!?…\n"), default=-1) + 1
    fim = _FIM_DE_FRASE.search(texto, posicao)
    return fim is not None and fim.group() == "?" and _INTERROGATIVA.search(texto, inicio, posicao) is not None


def _achados(texto: str) -> list[tuple[str, str, int, bool]]:
    """As expressões que atribuem algo a um grupo sem nome, com a última posição dizendo se são pergunta aberta."""
    achados: dict[int, tuple[str, str, int, bool]] = {}
    # de cada padrão: o parêntese em que está o grupo e se a expressão é o casamento inteiro
    for padrao, grupo, inteira in ((_MARCA_ANTES, 1, True), (_PARA_ANTES, 2, False), (_VERBO_DEPOIS, 1, True)):
        for m in padrao.finditer(texto):
            if _DO_ELENCO.search(texto[:m.start(grupo)]):
                continue
            expressao, inicio = (m.group(), m.start()) if inteira else (m.group(1), m.start(1))
            achados.setdefault(m.start(grupo), (m.group(grupo).lower(), expressao, inicio, pergunta_aberta(texto, m.start(grupo))))
    return [achados[posicao] for posicao in sorted(achados)]


def atribuicoes_a_grupos(texto: str) -> list[tuple[str, str, int]]:
    """As atribuições a um grupo sem nome: (grupo, expressão como está escrita, posição da expressão).

    A pergunta aberta não conta (ver `pergunta_aberta`); `perguntas_abertas_a_grupos` lista as que ficaram de fora.
    """
    return [(grupo, expressao, inicio) for grupo, expressao, inicio, aberta in _achados(texto) if not aberta]


def perguntas_abertas_a_grupos(texto: str) -> list[tuple[str, str, int]]:
    """As perguntas abertas que citam um grupo sem nome e por isso não contam como atribuição: (grupo, expressão, posição)."""
    return [(grupo, expressao, inicio) for grupo, expressao, inicio, aberta in _achados(texto) if aberta]


def plano(textos) -> str:
    """Os textos numa linha só, sem acento e em minúsculas: é onde se procura o radical de cada grupo."""
    junto = "\n".join(str(texto) for texto in textos)
    return "".join(c for c in unicodedata.normalize("NFKD", junto) if not unicodedata.combining(c)).lower()


def grupo_na_pauta(grupo: str, plano_da_pauta: str) -> bool:
    """Se os textos (já passados por `plano`) citam o grupo, por ele mesmo ou por uma palavra da mesma família."""
    return re.search(rf"\b{GRUPOS[grupo]}", plano_da_pauta) is not None

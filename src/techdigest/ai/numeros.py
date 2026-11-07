"""Números de um texto, em algarismos ou por extenso, e se eles têm fonte nos textos da pauta.

Serve ao QA, que reprova percentual e número a partir de 10 que nenhum texto da pauta traz, e ao
diagnóstico de scripts/checar_fidelidade.py. Compara valor com valor, não sentido: um número
certo usado para dizer outra coisa passa.
"""
import math
import re
import unicodedata
from dataclasses import dataclass

_TOKEN = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?|[^\W\d_]+")

_UNIDADES = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
    "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14, "quinze": 15,
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
}
_DEZENAS = {"vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
            "oitenta": 80, "noventa": 90}
_CENTENAS = {"cem": 100, "cento": 100} | {
    radical + final: valor
    for radical, valor in (("duzent", 200), ("trezent", 300), ("quatrocent", 400), ("quinhent", 500),
                           ("seiscent", 600), ("setecent", 700), ("oitocent", 800), ("novecent", 900))
    for final in ("os", "as")
}
_PARCELAS = _UNIDADES | _DEZENAS | _CENTENAS
_ESCALAS = {"mil": 10**3, "milhao": 10**6, "milhoes": 10**6, "bilhao": 10**9, "bilhoes": 10**9,
            "trilhao": 10**12, "trilhoes": 10**12}
_TERCOS = {"terco", "tercos"}
_DEPOIS_DE_UM = {"milhao", "bilhao", "trilhao"} | _TERCOS   # "um" só é número antes destas palavras
_SEPARADORES = ("virgula", "ponto")   # o separador decimal falado: "um vírgula oito", "um ponto setenta e dois"

MENOR_NUMERO_COM_FONTE = 10   # abaixo disto, só o percentual precisa de fonte ("dois lados" é contagem de quem fala)
TOLERANCIA = 0.05             # o quanto o número dito pode se afastar do da fonte quando vem com um qualificador
# Dito em mil, milhões ou bilhões, o número da fonte nessa escala pode ser arredondado a partir daqui:
# 245,5 milhões vira "245 milhões", mas 3,6 bilhões não vira "três bilhões" (ver `tem_fonte`).
MENOR_NUMERO_NA_ESCALA = 10
# O qualificador que vem logo antes do número e o que ele admite (ver `tem_fonte`).
_QUALIFICADOR = re.compile(r"\b(cerca de|aproximadamente|quase|mais de)\s+$")


def dobrar(texto: str) -> str:
    """`texto` sem acentos e em minúsculas, com o mesmo comprimento: as posições valem nos dois."""
    saida = []
    for c in texto:
        base = "".join(d for d in unicodedata.normalize("NFKD", c) if not unicodedata.combining(d)).lower()
        saida.append(base if len(base) == 1 else c)
    return "".join(saida)


@dataclass(frozen=True)
class Token:
    texto: str
    norm: str      # sem acento e em minúsculas
    inicio: int
    fim: int

    @property
    def numerico(self) -> bool:
        return self.texto[0].isdigit()

    @property
    def maiuscula(self) -> bool:
        return not self.numerico and self.texto[0].isupper()


def tokens(texto: str) -> list[Token]:
    return [Token(m.group(), dobrar(m.group()), m.start(), m.end()) for m in _TOKEN.finditer(texto)]


def junto(texto: str, a: Token, b: Token) -> bool:
    """Só espaço entre os dois tokens: nenhuma pontuação."""
    meio = texto[a.fim:b.inicio]
    return meio != "" and meio.strip(" \t") == ""


@dataclass(frozen=True)
class Numero:
    valor: float
    percentual: bool
    trecho: str     # como está escrito
    inicio: int
    fim: int
    escala: int = 1   # a escala em que é dito: 10**6 em "245 milhões" e "duzentos milhões"; 1 em "mil e quinhentos"


def _continua(texto: str, a: Token, b: Token) -> bool:
    """Se `b` continua o número por extenso que vai até `a`: só espaço entre os dois, ou uma vírgula depois da escala,
    antes de uma parcela menor que ela ("nove mil, quinhentas e quarenta e quatro" vale 9.544; decisão de 29/10/2026)."""
    if junto(texto, a, b):
        return True
    return (a.norm in _ESCALAS and texto[a.fim:b.inicio].strip(" \t") == "," and b.norm in _PARCELAS
            and b.norm not in ("um", "uma") and _PARCELAS[b.norm] < _ESCALAS[a.norm])


def _pode_somar(atual: float, parcela: int) -> bool:
    """Se `parcela` continua o grupo já lido ("duzentos" + "noventa", "vinte" + "um"); "dois e três" são dois números."""
    if atual == 0:
        return True
    if atual % 100 == 0:
        return parcela < 100
    return atual % 10 == 0 and atual % 100 >= 20 and parcela < 10


def _antes_de_decimal(lidos: list[Token], j: int, texto: str) -> bool:
    """Se o token `j` é "vírgula" ou "ponto" seguido de um número ("um vírgula oito"), e não "um ponto de vista"."""
    if not (j + 1 < len(lidos) and lidos[j].norm in _SEPARADORES and junto(texto, lidos[j], lidos[j + 1])):
        return False
    proximo = lidos[j + 1]
    return proximo.texto.isdigit() or proximo.norm in _PARCELAS


def _ler_por_extenso(lidos: list[Token], i: int, texto: str) -> tuple[int, float | None, int]:
    """Lê um número por extenso a partir do token `i`: o índice depois dele, o valor (None se ali não há número) e a
    escala em que ele termina ("um milhão e duzentos mil" termina em mil; "mil e quinhentos", em unidades)."""
    total = atual = 0
    escala = 1
    j = i
    virgula = None   # onde a leitura atravessou a vírgula depois de uma escala: (índice, total, atual, escala, a escala)
    while j < len(lidos):
        t = lidos[j]
        if j > i and not junto(texto, lidos[j - 1], t):
            if not _continua(texto, lidos[j - 1], t):
                break
            virgula = (j, total, atual, escala, _ESCALAS[lidos[j - 1].norm])
        if virgula and t.norm in _ESCALAS and _ESCALAS[t.norm] >= virgula[4]:
            j, total, atual, escala = virgula[:4]   # "dez mil, vinte mil": a vírgula separava dois números
            break
        if t.norm == "e" and j > i:
            proxima = lidos[j + 1] if j + 1 < len(lidos) and junto(texto, t, lidos[j + 1]) else None
            parcela = _PARCELAS.get(proxima.norm) if proxima else None
            if parcela is None or not _pode_somar(atual, parcela) or (parcela == 1 and atual == 0):
                break                                                      # "três milhões e uma promessa"
            atual += parcela
            j += 2
        elif t.norm in _ESCALAS and (j > i or t.norm == "mil"):
            total += (atual or 1) * _ESCALAS[t.norm]
            atual, escala = 0, _ESCALAS[t.norm]
            j += 1
        elif t.norm in _PARCELAS and (j == i or (atual == 0 and total)):   # sem "e", só depois de mil ou milhão
            if j == i and t.norm in ("um", "uma") and not (
                    j + 1 < len(lidos) and junto(texto, t, lidos[j + 1])
                    and (lidos[j + 1].norm in _DEPOIS_DE_UM or _antes_de_decimal(lidos, j + 1, texto))):
                break                                                      # artigo, não número
            if j == i and t.norm == "cento" and i > 0 and lidos[i - 1].norm == "por":
                break                                                      # "por cento" sem número antes
            atual = _PARCELAS[t.norm]
            j += 1
        else:
            break
    return (j, total + atual, 1 if atual else escala) if j > i else (i, None, 1)


def _decimal_falado(lidos: list[Token], j: int, texto: str) -> tuple[int, float | None]:
    """A parte decimal dita depois de "vírgula" ou "ponto" ("cinquenta e oito vírgula oito", "um ponto setenta e
    dois"): o índice depois dela e o valor. "Ponto percentual" não é decimal: depois dele não vem número."""
    if not (j + 1 < len(lidos) and lidos[j].norm in _SEPARADORES and junto(texto, lidos[j - 1], lidos[j])
            and junto(texto, lidos[j], lidos[j + 1])):
        return j, None
    proximo = lidos[j + 1]
    if proximo.numerico:
        if not proximo.texto.isdigit():
            return j, None
        fim, casas = j + 2, proximo.texto
    else:
        if proximo.norm in ("um", "uma"):                # depois de "vírgula", "um" é algarismo, não artigo
            fim, parte = j + 2, 1
        else:
            fim, parte, _ = _ler_por_extenso(lidos, j + 1, texto)
        if parte is None or parte != int(parte) or parte >= 1000:
            return j, None
        casas = str(int(parte))
    return fim, int(casas) / 10 ** len(casas)


def _e_meio(lidos: list[Token], j: int, texto: str) -> int:
    """O índice depois de "e meio", se ele vem a partir de `j` ("dois milhões e meio"); 0 se não vem."""
    if (j + 1 < len(lidos) and lidos[j].norm == "e" and lidos[j + 1].norm == "meio"
            and junto(texto, lidos[j - 1], lidos[j]) and junto(texto, lidos[j], lidos[j + 1])):
        return j + 2
    return 0


def numeros(texto: str) -> list[Numero]:
    """Os números de `texto`, em algarismos ou por extenso, com o valor e se é percentual.

    "1.200" vale 1200, "67,50" vale 67,5, "3,2 milhões" vale 3.200.000, "dois milhões e meio" vale
    2.500.000, "duzentos e setenta e um por cento" vale 271 (percentual), "cinquenta e oito vírgula
    oito por cento" vale 58,8 (percentual), "zero vírgula vinte e cinco" vale 0,25, "um ponto setenta e dois"
    vale 1,72 e "um terço" vale 1/3. Ordinais por extenso e "um"/"uma"
    sozinhos não contam. O "e meio" só conta depois de milhão, bilhão ou trilhão: "dez e meia" é hora.
    """
    lidos = tokens(texto)
    achados, i = [], 0
    while i < len(lidos):
        t = lidos[i]
        if t.numerico:
            j, valor, escala = i + 1, float(t.texto.replace(".", "").replace(",", ".")), 1
            if j < len(lidos) and lidos[j].norm in _ESCALAS and junto(texto, t, lidos[j]):
                escala = _ESCALAS[lidos[j].norm]
                valor *= escala
                j += 1
        elif t.norm == "zero" and i + 1 < len(lidos) and junto(texto, t, lidos[i + 1]) \
                and _antes_de_decimal(lidos, i + 1, texto):
            j, valor, escala = i + 1, 0, 1            # "zero vírgula vinte e cinco"; "zero" sozinho não conta
        else:
            j, valor, escala = _ler_por_extenso(lidos, i, texto)
            if valor is None:
                i += 1
                continue
        if escala >= 10**6 and (depois := _e_meio(lidos, j, texto)):
            valor, j = valor + escala / 2, depois
        if valor == int(valor):
            j, decimal = _decimal_falado(lidos, j, texto)
            if decimal:
                valor, escala = valor + decimal, 1
        if j < len(lidos) and lidos[j].norm in _TERCOS and 1 <= valor <= 2 and junto(texto, lidos[j - 1], lidos[j]):
            valor /= 3
            j += 1
        fim, percentual = lidos[j - 1].fim, False
        sinal = re.match(r"\s*%", texto[fim:])
        if sinal:
            fim, percentual = fim + sinal.end(), True
        elif (j + 1 < len(lidos) and lidos[j].norm == "por" and lidos[j + 1].norm == "cento"
              and junto(texto, lidos[j - 1], lidos[j]) and junto(texto, lidos[j], lidos[j + 1])):
            fim, percentual, j = lidos[j + 1].fim, True, j + 2
        achados.append(Numero(round(valor, 6), percentual, texto[t.inicio:fim], t.inicio, fim, escala))
        i = j
    return _intervalos(texto, achados)


_ABRE_INTERVALO = re.compile(r"\b(entre|de)\s+$")
_MEIO_DO_INTERVALO = re.compile(r"\s+(e|a)\s+")


def _intervalos(texto: str, achados: list[Numero]) -> list[Numero]:
    """No intervalo "entre quinze e dezesseis bilhões", "de 3 a 5 milhões" ou "entre quinze e vinte por cento", a escala
    (ou o "por cento") dita no último número vale para os dois (decisão de 07/11/2026): o texto da pauta traz "US$ 15 bilhões
    e US$ 16 bilhões", e o "quinze" lido sozinho não tem fonte. Só vale para um número de 10 ou mais, o que o QA cobra: abaixo
    disso ele continua fora da conta, em vez de passar a ser cobrado na escala."""
    for i in range(len(achados) - 1):
        a, b = achados[i], achados[i + 1]
        if a.percentual or a.escala != 1 or a.valor < MENOR_NUMERO_COM_FONTE or a.valor >= 1000:
            continue
        if not (b.percentual or b.escala >= 1000):
            continue
        if not (_ABRE_INTERVALO.search(dobrar(texto[:a.inicio])) and _MEIO_DO_INTERVALO.fullmatch(texto[a.fim:b.inicio])):
            continue
        if b.percentual:
            achados[i] = Numero(a.valor, True, a.trecho, a.inicio, a.fim, 1)
        elif a.valor * b.escala <= b.valor:
            achados[i] = Numero(a.valor * b.escala, False, a.trecho, a.inicio, a.fim, b.escala)
    return achados


def _nos_nomes(texto: str, nomes) -> list[tuple[int, int]]:
    """Onde os nomes que têm algarismo aparecem em `texto`: (início, fim) de cada ocorrência.

    Compara parte a parte (letras e algarismos são partes separadas), sem acento nem caixa, com só
    espaço ou nada entre as partes: "Poder360" e "Poder 360" são o mesmo nome. Do nome vale o que vem
    antes de um slogan (" - ", " | ").
    """
    lidos = tokens(texto)
    trechos = []
    for nome in nomes:
        partes = tokens(re.split(r"\s[-–—|]\s", str(nome))[0])
        if not any(p.numerico for p in partes):
            continue
        normas = [p.norm for p in partes]
        for i in range(len(lidos) - len(partes) + 1):
            janela = lidos[i:i + len(partes)]
            if [t.norm for t in janela] == normas and all(texto[a.fim:b.inicio].strip(" \t") == ""
                                                          for a, b in zip(janela, janela[1:])):
                trechos.append((janela[0].inicio, janela[-1].fim))
    return trechos


def numeros_fora_dos_nomes(texto: str, nomes) -> list[Numero]:
    """Os números de `texto` que não fazem parte de um dos `nomes`: o "360" de "Poder360" e o "247" de "Brasil 247",
    quando o veículo é da pauta, não são dados (decisão de 25/10/2026)."""
    nos_nomes = _nos_nomes(texto, nomes)
    return [n for n in numeros(texto) if not any(inicio <= n.inicio and n.fim <= fim for inicio, fim in nos_nomes)]


def formatar(valor: float, percentual: bool = False) -> str:
    inteiro = valor == int(valor)
    texto = f"{int(valor):,}".replace(",", ".") if inteiro else f"{valor:.6g}".replace(".", ",")
    return texto + ("%" if percentual else "")


# ── A fonte de um número ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Valores:
    """Os números que um conjunto de textos traz. Percentual só casa com percentual."""
    numeros: frozenset[float]
    percentuais: frozenset[float]

    def de(self, n: Numero) -> frozenset[float]:
        return self.percentuais if n.percentual else self.numeros


def valores_dos_textos(textos) -> Valores:
    achados = [n for texto in textos for n in numeros(unicodedata.normalize("NFC", str(texto)))]
    return Valores(frozenset(n.valor for n in achados), frozenset(n.valor for n in achados if n.percentual))


def pede_fonte(n: Numero) -> bool:
    """Se o QA cobra fonte para o número: todo percentual, e os demais a partir de MENOR_NUMERO_COM_FONTE."""
    return n.percentual or n.valor >= MENOR_NUMERO_COM_FONTE


def qualificador(texto: str, n: Numero) -> str:
    """O qualificador logo antes do número ("cerca de", "aproximadamente", "quase", "mais de"), ou vazio."""
    achado = _QUALIFICADOR.search(dobrar(texto[:n.inicio]))
    return achado.group(1) if achado else ""


def _perto(dito: float, da_fonte: float) -> bool:
    return da_fonte != 0 and abs(da_fonte - dito) / abs(da_fonte) <= TOLERANCIA


def _arredonda(dito: float, da_fonte: float) -> bool:
    """Se `dito` é o inteiro que trunca ou arredonda o decimal `da_fonte`."""
    return dito == int(dito) and da_fonte != int(da_fonte) and dito in (math.floor(da_fonte), math.floor(da_fonte + 0.5))


def _arredonda_na_escala(n: Numero, da_fonte: float) -> bool:
    """Se `n`, dito em mil, milhões ou bilhões, arredonda ou trunca o número da fonte nessa escala.

    Compara o valor, escrito na fonte de qualquer forma: R$ 245,5 milhões e R$ 245.500.000 são 245,5 na
    escala de "245 milhões". Só vale com o número da fonte na escala a partir de MENOR_NUMERO_NA_ESCALA.
    """
    if n.escala == 1 or n.percentual:
        return False
    na_escala = round(da_fonte / n.escala, 6)
    return na_escala >= MENOR_NUMERO_NA_ESCALA and _arredonda(round(n.valor / n.escala, 6), na_escala)


def tem_fonte(n: Numero, qualificado_por: str, valores: Valores) -> bool:
    """Se os textos sustentam o número dito.

    Vale o número igual ao de um texto. Com "cerca de" ou "aproximadamente", vale o que fica a
    até 5% de um número da fonte; com "quase", o da fonte tem de estar abaixo do dito e, com "mais
    de", acima, sempre a até 5%. Sem qualificador, vale o inteiro que arredonda ou trunca um
    decimal da fonte (30,7 pode ser dito 30 ou 31), e o mesmo vale na escala em que o número é dito
    (R$ 245,5 milhões ou R$ 245.500.000 podem ser ditos "245 milhões" ou "246 milhões"), desde que
    o número da fonte nessa escala seja 10 ou mais: 3,6 bilhões não vira "três bilhões".
    """
    da_fonte = valores.de(n)
    if n.valor in da_fonte:
        return True
    if qualificado_por in ("cerca de", "aproximadamente"):
        return any(_perto(n.valor, v) for v in da_fonte)
    if qualificado_por == "quase":
        return any(v < n.valor and _perto(n.valor, v) for v in da_fonte)
    if qualificado_por == "mais de":
        return any(v > n.valor and _perto(n.valor, v) for v in da_fonte)
    return any(_arredonda(n.valor, v) or _arredonda_na_escala(n, v) for v in da_fonte)


def mais_proximo(n: Numero, valores: Valores, ate: float = 0.10) -> float | None:
    """O número da fonte mais perto do dito, se algum fica a até `ate` dele (para dizer na mensagem do QA)."""
    candidatos = [v for v in valores.de(n) if v and abs(v - n.valor) / abs(v) <= ate]
    return min(candidatos, key=lambda v: abs(v - n.valor), default=None)

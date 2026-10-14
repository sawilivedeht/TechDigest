"""O recorte de um texto-fonte por relevância: o lide, os parágrafos com os trechos de evidência e o resto, em ordem.

Serve às chamadas que levam texto-fonte (a geração e as revisões, em `summarizer.montar_entrada`),
que dão a cada fonte um teto de caracteres, e à análise de lados, que confere os trechos de
evidência nos textos inteiros com a mesma comparação literal.
"""
import re
import unicodedata
from dataclasses import dataclass, field

LIDE = 400                # caracteres: o lide junta os primeiros parágrafos até somar isto
MIN_LINHA_DO_LIDE = 60    # linha mais curta que isto não entra no lide (chamada, intertítulo, data)
MARCA = "[...]"           # o que o recorte põe onde pula parágrafos
MOTIVO_DO_LIDE = "lide"
MOTIVO_DA_ORDEM = "ordem do texto"
# Linha que parece legenda de foto ou chamada do site, e não texto da notícia: não entra no lide.
_LEGENDA_OU_CHAMADA = re.compile(
    r"\b(?:fotos?|imagem|imagens|arte|ilustração|vídeo|crédito|créditos|reprodução)\s*:"
    r"|^\W*(?:ouça|compartilh|leia (?:mais|também)|veja (?:mais|também)|saiba mais|assista|siga |clique|publicidade"
    r"|continua após|receba |inscreva-se|assine )",
    re.IGNORECASE,
)


def literal(texto) -> str:
    """O texto para a comparação de trechos: espaços e aspas normalizados, sem contar maiúsculas."""
    texto = unicodedata.normalize("NFC", str(texto))
    texto = re.sub("[“”„‟«»]", '"', re.sub("[‘’‚‛]", "'", texto))
    return " ".join(texto.split()).casefold()


def procurado(trecho) -> str:
    """O trecho como é procurado num texto: pela comparação de `literal`, sem as aspas e as reticências em volta."""
    return literal(trecho).strip("\"'. …")


# ── O trecho quase literal ────────────────────────────────────────────────────────────────

PALAVRAS_POR_DIFERENCA = 10   # o trecho pode diferir do texto em uma palavra a cada tantas (arredondado para baixo)
NEGACOES = frozenset({"não", "nem", "nunca", "jamais"})   # palavra que nenhuma diferença pode envolver
_PROIBIDA = float("inf")
_ABRE_ASPAS, _FECHA_ASPAS = "\"'“‘«", "\"'”’»"


def _palavras(texto) -> list[re.Match]:
    """As palavras do texto, sem pontuação: a comparação palavra por palavra ignora vírgulas, aspas e o resto."""
    return list(re.finditer(r"\w+", unicodedata.normalize("NFC", str(texto))))


def _alinhar(pedidas: list[str], do_texto: list[str], maximo: int) -> tuple[int, int] | None:
    """O pedaço contínuo do texto mais parecido com o trecho, em índices de palavra (início, fim); None se não há.

    Diferença é uma palavra trocada, a mais ou a menos. Vale o pedaço com até `maximo` diferenças,
    nenhuma delas com uma palavra de NEGACOES. No empate fica o pedaço mais curto e que termina primeiro.
    """
    n = len(pedidas)

    def custo(palavra: str) -> float:
        return _PROIBIDA if palavra in NEGACOES else 1

    coluna = [(0.0, 0)]                     # por quantas palavras do trecho já foram alinhadas: (diferenças, início)
    for i in range(1, n + 1):
        coluna.append((coluna[-1][0] + custo(pedidas[i - 1]), 0))
    melhor = None
    for j, palavra in enumerate(do_texto, 1):
        nova = [(0.0, j)]                   # o pedaço pode começar em qualquer palavra do texto
        for i in range(1, n + 1):
            pedida = pedidas[i - 1]
            trocada = 0 if pedida == palavra else max(custo(pedida), custo(palavra))
            candidatos = (
                (coluna[i - 1][0] + trocada, coluna[i - 1][1]),   # a mesma palavra, ou uma trocada
                (nova[i - 1][0] + custo(pedida), nova[i - 1][1]),  # palavra do trecho que o texto não tem
                (coluna[i][0] + custo(palavra), coluna[i][1]),     # palavra do texto que o trecho não tem
            )
            nova.append(min(candidatos, key=lambda c: (c[0], -c[1])))
        coluna = nova
        diferencas, inicio = coluna[n]
        if diferencas <= maximo and (melhor is None or diferencas < melhor[0]):
            melhor = (diferencas, inicio, j)
    return None if melhor is None else (melhor[1], melhor[2])


def localizar_trecho(trecho, texto) -> tuple[str, int] | None:
    """Onde o trecho está no texto: o trecho como vale e quantas palavras ele difere do texto; None se não está.

    Primeiro a comparação literal de `procurado` e `literal`: achado assim, o trecho vale como veio
    (o mesmo objeto), com 0 diferenças. Senão, palavra por palavra, sem pontuação nem maiúsculas (o
    tipo de aspas não conta): vale o pedaço contínuo do texto que difere do trecho em até uma
    palavra a cada PALAVRAS_POR_DIFERENCA (trocada, a mais ou a menos; arredondado para baixo, então
    trecho de menos de dez palavras tem de ter as mesmas palavras), sem nenhuma diferença que
    envolva negação. Achado assim, vale o trecho como está no texto, que é o que localiza o
    parágrafo dele no recorte; as diferenças podem ser 0, quando só a pontuação mudou.
    """
    alvo = procurado(trecho)
    if not alvo:
        return None
    if alvo in literal(texto):
        return str(trecho), 0
    pedidas = [m.group().casefold() for m in _palavras(trecho)]
    achadas = _palavras(texto)
    if not pedidas:
        return None
    pedaco = _alinhar(pedidas, [m.group().casefold() for m in achadas], len(pedidas) // PALAVRAS_POR_DIFERENCA)
    if pedaco is None:
        return None
    inicio, fim = pedaco
    de, ate = achadas[inicio].start(), achadas[fim - 1].end()
    texto = str(texto)
    while de > 0 and texto[de - 1] in _ABRE_ASPAS:       # as aspas em volta das primeiras e das últimas palavras vão junto
        de -= 1
    while ate < len(texto) and texto[ate] in _FECHA_ASPAS:
        ate += 1
    versao = texto[de:ate]
    vistas = [m.group().casefold() for m in achadas[inicio:fim]]
    return versao, _diferencas(pedidas, vistas)


def _diferencas(a: list[str], b: list[str]) -> int:
    """Quantas palavras trocadas, a mais ou a menos separam duas listas de palavras (a distância de edição)."""
    anterior = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        atual = [i]
        for j, y in enumerate(b, 1):
            atual.append(min(anterior[j - 1] + (x != y), anterior[j] + 1, atual[j - 1] + 1))
        anterior = atual
    return anterior[-1]


@dataclass(frozen=True)
class Paragrafo:
    numero: int     # a partir de 1, na ordem do texto
    inicio: int     # posições no texto
    fim: int


def paragrafos(texto: str) -> list[Paragrafo]:
    """Os parágrafos do texto: cada linha que não está vazia."""
    return [Paragrafo(n, m.start(), m.end()) for n, m in enumerate(re.finditer(r"[^\n]*\S[^\n]*", texto), 1)]


def lide(texto: str, titulo: str = "") -> list[int]:
    """Os números dos parágrafos do lide: os primeiros do texto, até somarem LIDE caracteres.

    Ficam de fora as linhas com menos de MIN_LINHA_DO_LIDE caracteres, as que parecem legenda ou
    chamada ("Ouça este conteúdo", "Compartilhar matéria", "... — Foto: ...") e a que repete o título.
    """
    do_lide, soma = [], 0
    for p in paragrafos(texto):
        linha = texto[p.inicio:p.fim].strip()
        if len(linha) < MIN_LINHA_DO_LIDE or _LEGENDA_OU_CHAMADA.search(linha) or (titulo and literal(linha) == literal(titulo)):
            continue
        do_lide.append(p.numero)
        soma += len(linha)
        if soma >= LIDE:
            break
    return do_lide


def paragrafos_com(trecho, texto: str) -> list[int]:
    """Os números dos parágrafos de `texto` em que o trecho está, ao pé da letra (pela comparação de `literal`).

    O trecho que atravessa dois parágrafos traz os dois, e o que se repete traz todos os lugares.
    """
    alvo = procurado(trecho)
    if not alvo:
        return []
    pars = paragrafos(texto)
    normas = [literal(texto[p.inicio:p.fim]) for p in pars]
    inicios, posicao = [], 0
    for norma in normas:
        inicios.append(posicao)
        posicao += len(norma) + 1
    junto = " ".join(normas)
    achados, de = [], junto.find(alvo)
    while de >= 0:
        ate = de + len(alvo)
        achados += [p.numero for p, inicio, norma in zip(pars, inicios, normas) if inicio < ate and de < inicio + len(norma)]
        de = junto.find(alvo, de + 1)
    return list(dict.fromkeys(achados))


def cortar_em_paragrafo(texto: str, limite: int) -> str:
    """Os primeiros `limite` caracteres, terminando em fim de parágrafo.

    Se o corte no parágrafo jogar fora mais da metade do espaço (um parágrafo enorme), vale o fim
    de frase; em último caso, o fim de palavra.
    """
    if len(texto) <= limite:
        return texto
    trecho = texto[:max(limite, 0)]
    fim = trecho.rfind("\n")
    if fim >= limite // 2:
        return trecho[:fim].rstrip()
    fim = max(trecho.rfind(sinal) for sinal in (". ", "! ", "? "))
    if fim >= limite // 2:
        return trecho[:fim + 1]
    return trecho.rsplit(None, 1)[0] if " " in trecho else trecho


@dataclass
class Recorte:
    """O que entrou de um texto-fonte numa mensagem, e por quê."""
    texto: str = ""
    total: int = 0                                      # quantos parágrafos o texto inteiro tem
    entraram: list[dict] = field(default_factory=list)  # por parágrafo, na ordem do texto: paragrafo, motivo, caracteres
    fora: list[dict] = field(default_factory=list)      # os que têm trecho de evidência e não couberam (mesmas chaves)


def _montar(texto: str, pars: list[Paragrafo], fins: dict[int, int]) -> str:
    """Os parágrafos escolhidos, na ordem do texto, com MARCA onde algo foi pulado.

    `fins` diz, para cada número escolhido, onde o parágrafo termina no recorte (ele pode entrar em parte).
    """
    corridas: list[list[int]] = []
    anterior = None                 # o número do último escolhido, se ele entrou inteiro
    for p in pars:
        fim = fins.get(p.numero)
        if fim is None:
            continue
        if anterior == p.numero - 1:
            corridas[-1][1] = fim   # emenda no anterior, com as quebras de linha do original
        else:
            corridas.append([p.inicio, fim])
        anterior = p.numero if fim == p.fim else None
    if not corridas:
        return ""
    saida = f"\n{MARCA}\n".join(texto[inicio:fim] for inicio, fim in corridas)
    return f"{MARCA}\n{saida}" if corridas[0][0] > pars[0].inicio else saida


def recortar(texto: str, cabe: int, trechos=(), titulo: str = "") -> Recorte:
    """O recorte de `texto` em até `cabe` caracteres.

    Entram, nesta ordem de prioridade: o lide (ver `lide`); os parágrafos que contêm os trechos de
    evidência (`trechos`: pares de motivo e trecho, já na ordem de prioridade); e o resto do texto,
    em ordem, até o primeiro parágrafo que não couber. O que entra aparece na ordem do texto, com
    MARCA onde algo foi pulado. O parágrafo com trecho que não cabe vai para `fora`.

    Sem trechos e sem linhas que o lide pula, o recorte é o começo do texto, cortado em fim de
    parágrafo; se assim sobrar mais da metade do espaço (um parágrafo enorme), o parágrafo
    seguinte entra em parte, até um fim de frase ou, em último caso, de palavra.
    """
    pars = paragrafos(texto)
    por_numero = {p.numero: p for p in pars}
    fins: dict[int, int] = {}
    motivos: dict[int, list[str]] = {}

    def tamanho(extra: dict[int, int] | None = None) -> int:
        return len(_montar(texto, pars, {**fins, **(extra or {})}))

    def entra(numero: int, motivo: str) -> bool:
        """Põe o parágrafo no recorte, se ele couber inteiro."""
        if motivo not in motivos.setdefault(numero, []):
            motivos[numero].append(motivo)
        if numero in fins:
            return True
        if tamanho({numero: por_numero[numero].fim}) > cabe:
            return False
        fins[numero] = por_numero[numero].fim
        return True

    def entra_em_parte(numero: int, minimo: int) -> None:
        """Põe o começo do parágrafo no que sobra do espaço: até um fim de frase que leve o recorte a `minimo`
        caracteres ou, sem isso, até um fim de palavra."""
        p = por_numero[numero]
        sobra = cabe - tamanho({numero: p.inicio})      # o que cabe do parágrafo, já contada a marca que ele traz
        pedaco = texto[p.inicio:p.fim][:max(sobra, 0)]
        if not pedaco.strip():
            return
        fim = max(pedaco.rfind(sinal) for sinal in (". ", "! ", "? "))
        if fim >= 0 and tamanho({numero: p.inicio + fim + 1}) >= minimo:
            pedaco = pedaco[:fim + 1]
        elif " " in pedaco:
            pedaco = pedaco.rsplit(None, 1)[0]
        fins[numero] = p.inicio + len(pedaco)

    fora: list[dict] = []
    for numero in lide(texto, titulo):
        if not entra(numero, MOTIVO_DO_LIDE):
            break
    for motivo, trecho in trechos:
        for numero in paragrafos_com(trecho, texto):
            if not entra(numero, motivo) and not any(f["paragrafo"] == numero for f in fora):
                fora.append({"paragrafo": numero, "motivo": motivo, "caracteres": por_numero[numero].fim - por_numero[numero].inicio})
    for p in pars:
        if p.numero in fins:
            continue
        if not entra(p.numero, MOTIVO_DA_ORDEM):
            if tamanho() < cabe // 2:
                entra_em_parte(p.numero, minimo=cabe // 2)
            break
    for item in fora:   # o motivo completo de quem ficou de fora (um parágrafo pode trazer trechos de dois lados)
        item["motivo"] = "; ".join(m for m in motivos[item["paragrafo"]] if m != MOTIVO_DA_ORDEM)
    entraram = [
        {"paragrafo": p.numero, "motivo": "; ".join(motivos[p.numero]), "caracteres": fins[p.numero] - p.inicio,
         **({"cortado": True} if fins[p.numero] < p.fim else {})}
        for p in pars if p.numero in fins
    ]
    return Recorte(_montar(texto, pars, fins), len(pars), entraram, fora)

"""Agrupamento de notícias em pautas — Fase 1: similaridade de título e de texto.

Uma pauta junta os artigos que relatam o MESMO FATO (o mesmo acontecimento, não só o mesmo
tema) e vira um único episódio. Este módulo só tem funções puras: sem rede, banco ou LLM.
Limiares e pesos chegam por parâmetro; quem lê Settings é o chamador.

    Etapa 1 (título): trigramas de caracteres + entidades (nomes próprios, siglas, números).
    Etapa 2 (texto):  TF-IDF de palavras e bigramas sobre o início do texto extraído.
    Score:            peso_titulo × título + (1 − peso_titulo) × texto.

A confirmação de cada pauta pelo LLM (etapa 3) e a integração no pipeline são fases seguintes.
"""
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

# Stopwords em português, na grafia correta: a checagem é feita ANTES de tirar os acentos, para
# "Pará" não cair junto com "para". Ficam de fora de propósito as que colidem com siglas e nomes
# frequentes nas notícias: "ia" (IA), "ir" (IR), "aí" (AI), "pro" (iPhone Pro), "sim" (cartão SIM).
STOPWORDS = frozenset("""
    a à o as às os um uma uns umas ao aos
    de da do das dos dum duma em na no nas nos num numa nuns numas
    por pela pelo pelas pelos para pra com sem sob sobre entre até após ante desde contra perante durante
    este esta estes estas esse essa esses essas aquele aquela aqueles aquelas isto isso aquilo
    deste desta destes destas desse dessa desses dessas daquele daquela daqueles daquelas disto disso daquilo
    neste nesta nestes nestas nesse nessa nesses nessas naquele naquela naqueles naquelas nisto nisso naquilo
    eu tu ele ela eles elas nós vós vos você vocês me te se lhe lhes
    meu minha meus minhas teu tua teus tuas seu sua seus suas nosso nossa nossos nossas dele dela deles delas
    que quem qual quais cujo cuja cujos cujas onde quando como quanto quanta quantos quantas
    e ou nem mas porém contudo entretanto todavia porque pois embora enquanto conforme segundo portanto logo
    não já ainda só também mais menos muito muita muitos muitas pouco pouca poucos poucas
    todo toda todos todas tudo nada algum alguma alguns algumas nenhum nenhuma outro outra outros outras
    mesmo mesma mesmos mesmas cada qualquer quaisquer tal tais tão tanto tanta tantos tantas apenas além
    aqui lá agora hoje ontem amanhã então assim depois antes sempre nunca bem mal quase
    ser é são era eram foi foram fosse fossem será serão seria seriam sendo sido sou somos seja sejam
    estar está estão estava estavam esteve estiveram estou estamos esteja estejam estando
    ter tem têm tinha tinham teve tiveram tenho temos terá terão teria teriam tenha tenham tendo tido
    haver há havia haviam houve haja
    vai vão vou vamos iria iriam
    poder pode podem podia podiam pôde poderá poderão poderia poderiam possa possam
    dever deve devem devia deviam deverá deverão deveria deveriam
    fazer faz fazem fez fizeram fazia faziam feito feita
    dizer diz dizem disse disseram
""".split())

# Um token é uma sequência de letras e dígitos; o separador entre dígitos fica dentro do número.
_RE_TOKEN = re.compile(r"[^\W_]+(?:[.,]\d+)*")
# Separadores entre a manchete e o nome do veículo.
_RE_SEPARADOR = re.compile(r"\s+[-–—|]\s+")
# Depois destes sinais começa outra frase: a maiúscula seguinte não indica nome próprio.
_RE_NOVA_FRASE = re.compile(r"[.!?:;|\"“‘«(\[]|\s[-–—]\s")
# A partir desta fração de palavras com inicial maiúscula, a caixa da manchete não diz nada.
_CAIXA_SEM_INFORMACAO = 0.8


# ── Normalização ──────────────────────────────────────────────────────────────────────────

def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _palavras(texto: str) -> list[re.Match]:
    """As palavras do texto como estão escritas, com a posição de cada uma."""
    return list(_RE_TOKEN.finditer(texto.replace("×", "x")))  # "6×1" e "6x1": a mesma escala


def _token(palavra: str) -> str:
    """Forma normalizada de uma palavra, ou "" se ela não entra na comparação (stopword, letra solta)."""
    minuscula = palavra.lower()
    if minuscula in STOPWORDS:
        return ""
    token = _sem_acentos(minuscula)
    return token if len(token) > 1 or token.isdigit() else ""


def _chave(nome: str) -> str:
    """Forma de comparar nomes de veículo: minúsculas, sem acentos e só letras e dígitos."""
    return "".join(c for c in _sem_acentos(nome).lower() if c.isalnum())


def tokenizar(texto: str) -> list[str]:
    """Palavras em minúsculas, sem acentos, pontuação nem stopwords.

    Letras soltas saem. O separador entre dígitos fica, para "5,2" e "1.200" continuarem um
    número só.
    """
    return [t for t in (_token(m.group()) for m in _palavras(texto)) if t]


def normalizar(texto: str) -> str:
    """Texto pronto para comparar: os tokens de `tokenizar` separados por um espaço."""
    return " ".join(tokenizar(texto))


def url_canonica(url: str) -> str:
    """Identidade da matéria entre feeds: sem parâmetros utm_*, sem fragmento e sem barra final."""
    partes = urlsplit(url.strip())
    consulta = "&".join(
        p for p in partes.query.split("&") if p and not p.split("=", 1)[0].lower().startswith("utm_")
    )
    return urlunsplit((partes.scheme.lower(), partes.netloc.lower(), partes.path.rstrip("/"), consulta, ""))


def _cortar_sufixo(titulo: str, alvo: str) -> str | None:
    for m in _RE_SEPARADOR.finditer(titulo):
        if m.start() > 0 and _chave(titulo[m.end():]) == alvo:
            return titulo[:m.start()].rstrip()
    return None


def separar_veiculo(titulo: str, veiculo: str = "") -> tuple[str, str]:
    """Devolve (título sem o sufixo do veículo, nome do veículo).

    O Google Notícias entrega "Manchete - Veículo". O collect_rss já corta o sufixo quando o
    feed informa o veículo; aqui ficam os casos que sobram:
    - veículo conhecido: o sufixo só sai se for o próprio veículo, depois de " - " ou " | " (há
      sites que repetem o nome no título). Um " - " que faz parte da manchete não é cortado;
    - veículo desconhecido (vazio, ou o título do feed de busca do Google): o trecho depois do
      último " - " é o veículo.
    """
    titulo, veiculo = titulo.strip(), veiculo.strip()
    alvo = _chave(veiculo)
    if alvo and not alvo.endswith(("googlenoticias", "googlenews")):
        while (menor := _cortar_sufixo(titulo, alvo)) is not None:
            titulo = menor
        return titulo, veiculo
    cortes = list(re.finditer(r"\s+[-–—]\s+", titulo))
    if cortes and cortes[-1].start() > 0 and titulo[cortes[-1].end():]:
        return titulo[:cortes[-1].start()].rstrip(), titulo[cortes[-1].end():]
    return titulo, veiculo


# ── Etapa 1: título ───────────────────────────────────────────────────────────────────────

def trigramas(texto: str) -> frozenset[str]:
    """Trigramas de caracteres de cada palavra do texto normalizado, com margens (como no pg_trgm)."""
    gramas: set[str] = set()
    for palavra in tokenizar(texto):
        marcada = f"  {palavra} "
        gramas.update(marcada[i:i + 3] for i in range(len(marcada) - 2))
    return frozenset(gramas)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def sim_trigramas(titulo_a: str, titulo_b: str) -> float:
    """Jaccard entre os conjuntos de trigramas dos dois títulos."""
    return _jaccard(trigramas(titulo_a), trigramas(titulo_b))


def vocabulario_minusculo(textos: Iterable[str]) -> frozenset[str]:
    """Palavras que os textos escrevem em minúsculas: evidência de que não são nome próprio."""
    return frozenset(
        token for texto in textos for m in _palavras(texto)
        if m.group().islower() and (token := _token(m.group()))
    )


def entidades(titulo: str, minusculas: Collection[str] = frozenset()) -> frozenset[str]:
    """Entidades do título: nomes próprios, siglas e números, já normalizados.

    Tudo o que tem dígito é entidade ("6x1", "2026", "s26"), e sigla em maiúsculas também.
    Palavra com maiúscula no meio da frase é nome próprio. No início da frase a maiúscula não
    diz nada ("Governo anuncia..."): ali a palavra só conta se não estiver em `minusculas`, o
    vocabulário que a execução escreve em minúsculas. A mesma checagem vale para a manchete
    inteira quando quase todas as palavras têm inicial maiúscula (Título Assim ou TUDO ASSIM).
    """
    achados = _palavras(titulo)
    palavras = [m.group() for m in achados if m.group().isalpha() and _token(m.group())]
    com_maiuscula = sum(1 for p in palavras if p[0].isupper())
    caixa_informativa = not palavras or com_maiuscula / len(palavras) < _CAIXA_SEM_INFORMACAO

    encontradas: set[str] = set()
    fim_anterior = None
    for m in achados:
        palavra, token = m.group(), _token(m.group())
        inicio_de_frase = fim_anterior is None or bool(_RE_NOVA_FRASE.search(titulo[fim_anterior:m.start()]))
        fim_anterior = m.end()
        if not token:
            continue
        if any(c.isdigit() for c in palavra):
            encontradas.add(token)
        elif any(c.isupper() for c in palavra):
            sigla = len(palavra) > 1 and palavra.isupper()
            caixa_diz_algo = caixa_informativa and (sigla or not inicio_de_frase)
            if caixa_diz_algo or token not in minusculas:
                encontradas.add(token)
    return frozenset(encontradas)


def _raridade(n: int, df: int) -> float:
    # IDF ao quadrado, o mesmo peso que um termo tem no cosseno do TF-IDF. Com 100 notícias: quem
    # aparece em 2 pesa ~15; em 30 ("Lula" num dia de política), ~2.
    return math.log(1 + n / df) ** 2


def pesos_de_raridade(documentos: Sequence[Collection[str]]) -> tuple[dict[str, float], float]:
    """Peso de cada termo pela raridade na execução, e o peso de um termo visto numa notícia só.

    `documentos` traz os termos de cada notícia. Quanto mais notícias usam um termo, menos ele
    pesa: é o que faz "Lula" ou "STF" contarem pouco como sinal de mesmo fato.
    """
    n = len(documentos)
    df = Counter(termo for doc in documentos for termo in set(doc))
    return {termo: _raridade(n, vezes) for termo, vezes in df.items()}, _raridade(max(n, 1), 1)


def sim_entidades(a: Collection[str], b: Collection[str], pesos: Mapping[str, float], fantasma: float) -> float:
    """Jaccard das entidades ponderado pela raridade, com uma entidade rara "fantasma" na união.

    Sem a fantasma os pesos se cancelam: dois títulos cuja única entidade é "Lula" dariam 1,0.
    Com ela, a sobreposição só chega perto de 1 quando as entidades em comum são raras e várias.
    """
    a, b = set(a), set(b)
    em_comum = sum(pesos.get(e, fantasma) for e in a & b)
    if not em_comum:
        return 0.0
    return em_comum / (sum(pesos.get(e, fantasma) for e in a | b) + fantasma)


# ── Etapa 2: texto ────────────────────────────────────────────────────────────────────────

def _inicio(texto: str, chars: int) -> str:
    """Os primeiros `chars` caracteres, sem deixar uma palavra cortada no fim."""
    if len(texto) <= chars or texto[chars].isspace():
        return texto[:chars]
    return re.sub(r"\S+$", "", texto[:chars])


def _termos(tokens: list[str]) -> list[str]:
    """Palavras e bigramas (palavras vizinhas depois de tirar as stopwords)."""
    return tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def vetores_tfidf(textos: Sequence[str]) -> list[dict[str, float]]:
    """Um vetor TF-IDF de norma 1 por texto, com palavras e bigramas; o IDF sai dos próprios textos."""
    contagens = [Counter(_termos(tokenizar(texto))) for texto in textos]
    n = len(contagens)
    df = Counter(termo for contagem in contagens for termo in contagem)
    vetores = []
    for contagem in contagens:
        vetor = {
            termo: (1 + math.log(vezes)) * (math.log((1 + n) / (1 + df[termo])) + 1)
            for termo, vezes in contagem.items()
        }
        norma = math.sqrt(sum(x * x for x in vetor.values()))
        vetores.append({termo: x / norma for termo, x in vetor.items()} if norma else {})
    return vetores


def _principais_termos(parcelas: Mapping[str, float], quantos: int) -> tuple[str, ...]:
    """Os termos que mais pesaram no cosseno, sem repetir a palavra que já está num bigrama."""
    escolhidos: list[str] = []
    for termo in sorted(parcelas, key=lambda t: (-parcelas[t], t)):
        palavras = termo.split()
        if len(palavras) == 1 and any(termo in e.split() for e in escolhidos if " " in e):
            continue
        if len(palavras) == 2:
            escolhidos = [e for e in escolhidos if e not in palavras]
        escolhidos.append(termo)
    return tuple(escolhidos[:quantos])


# ── Candidatos, pares e pautas ────────────────────────────────────────────────────────────

@dataclass(frozen=True, eq=False)
class Candidato:
    """Um artigo da execução, já extraído. A identidade é a do objeto: dois artigos nunca são "iguais"."""
    titulo: str        # sem o sufixo " - Veículo"
    veiculo: str
    url: str           # link do feed: é a chave que o SeenStore conhece
    url_veiculo: str   # URL da matéria no site do veículo (igual a `url` nos feeds diretos)
    texto: str         # texto extraído completo


@dataclass(frozen=True)
class ParPontuado:
    """Dois candidatos comparados: as similaridades de cada etapa e o score final."""
    a: Candidato
    b: Candidato
    sim_trigramas: float
    sim_entidades: float
    sim_titulo: float
    sim_texto: float
    score: float
    entidades_comuns: tuple[str, ...] = ()   # da mais rara para a mais comum
    termos_comuns: tuple[str, ...] = ()      # os que mais pesaram na similaridade de texto
    duplicata: bool = False                  # mesmo texto republicado: não é outra fonte


@dataclass(frozen=True)
class Pauta:
    """Artigos que relatam o mesmo fato e viram um único episódio (pode ter um artigo só)."""
    principal: Candidato
    relacionados: tuple[Candidato, ...] = ()   # do mais parecido com o principal para o menos
    duplicatas: tuple[Candidato, ...] = ()     # republicações de artigos da pauta: não contam como fonte
    pares: tuple[ParPontuado, ...] = ()        # pares entre os artigos da pauta, do maior score para o menor

    @property
    def artigos(self) -> tuple[Candidato, ...]:
        return (self.principal, *self.relacionados)

    @property
    def veiculos(self) -> tuple[str, ...]:
        """Veículos distintos entre os artigos da pauta (as duplicatas não contam)."""
        distintos: dict[str, str] = {}
        for c in self.artigos:
            distintos.setdefault(_chave(c.veiculo), c.veiculo)
        return tuple(distintos.values())

    @property
    def links(self) -> tuple[str, ...]:
        """Links do feed de tudo o que a pauta cobre, duplicatas inclusive (o que marcar como visto)."""
        return tuple(c.url for c in (*self.artigos, *self.duplicatas))


class SimTitulo(NamedTuple):
    trigramas: float
    entidades: float
    titulo: float
    entidades_comuns: tuple[str, ...]


class SimTexto(NamedTuple):
    texto: float
    termos_comuns: tuple[str, ...]


def comparar_titulos(candidatos: Sequence[Candidato], chars_texto: int) -> dict[tuple[int, int], SimTitulo]:
    """Etapa 1: trigramas e entidades dos títulos de cada par (i, j) de posições, i < j.

    A similaridade de título é a média das duas; se um dos títulos não tem entidade, não há o
    que comparar e valem só os trigramas. O texto entra apenas como estatística da execução:
    em quantas notícias cada entidade aparece e quais palavras são escritas em minúsculas.
    """
    trechos = [_inicio(c.texto, chars_texto) for c in candidatos]
    minusculas = vocabulario_minusculo([c.titulo for c in candidatos] + trechos)
    pesos, fantasma = pesos_de_raridade(
        [set(tokenizar(c.titulo)) | set(tokenizar(trecho)) for c, trecho in zip(candidatos, trechos)]
    )
    gramas = [trigramas(c.titulo) for c in candidatos]
    ents = [entidades(c.titulo, minusculas) for c in candidatos]

    resultado = {}
    for i, j in combinations(range(len(candidatos)), 2):
        tri = _jaccard(gramas[i], gramas[j])
        if ents[i] and ents[j]:
            ent = sim_entidades(ents[i], ents[j], pesos, fantasma)
            titulo = (tri + ent) / 2
        else:
            ent, titulo = 0.0, tri
        comuns = sorted(ents[i] & ents[j], key=lambda e: (-pesos.get(e, fantasma), e))
        resultado[i, j] = SimTitulo(tri, ent, titulo, tuple(comuns))
    return resultado


def comparar_textos(
    candidatos: Sequence[Candidato], chars_texto: int, max_termos: int = 6,
) -> dict[tuple[int, int], SimTexto]:
    """Etapa 2: cosseno entre os vetores TF-IDF do início do texto de cada par (i, j), i < j."""
    vetores = vetores_tfidf([_inicio(c.texto, chars_texto) for c in candidatos])
    resultado = {}
    for i, j in combinations(range(len(vetores)), 2):
        menor, maior = sorted((vetores[i], vetores[j]), key=len)
        parcelas = {termo: x * maior[termo] for termo, x in menor.items() if termo in maior}
        cosseno = min(1.0, sum(parcelas.values()))
        resultado[i, j] = SimTexto(cosseno, _principais_termos(parcelas, max_termos))
    return resultado


def pontuar_pares(
    candidatos: Sequence[Candidato],
    titulos: Mapping[tuple[int, int], SimTitulo],
    textos: Mapping[tuple[int, int], SimTexto],
    peso_titulo: float,
    limiar_duplicata: float,
) -> list[ParPontuado]:
    """Junta as duas etapas no score de cada par e devolve os pares do maior score para o menor."""
    pares = []
    for (i, j), t in titulos.items():
        x = textos[i, j]
        pares.append(ParPontuado(
            a=candidatos[i], b=candidatos[j],
            sim_trigramas=t.trigramas, sim_entidades=t.entidades, sim_titulo=t.titulo, sim_texto=x.texto,
            score=peso_titulo * t.titulo + (1 - peso_titulo) * x.texto,
            entidades_comuns=t.entidades_comuns, termos_comuns=x.termos_comuns,
            duplicata=x.texto >= limiar_duplicata,
        ))
    pares.sort(key=lambda p: -p.score)  # ordenação estável: no empate vale a ordem da coleta
    return pares


class _Conjuntos:
    """Union-find em que a raiz de cada conjunto é o seu menor elemento."""

    def __init__(self, n: int):
        self.pai = list(range(n))
        self.tamanho = [1] * n

    def raiz(self, i: int) -> int:
        while self.pai[i] != i:
            self.pai[i] = self.pai[self.pai[i]]  # compressão de caminho
            i = self.pai[i]
        return i

    def unir(self, i: int, j: int) -> None:
        ri, rj = self.raiz(i), self.raiz(j)
        if ri == rj:
            return
        menor, maior = min(ri, rj), max(ri, rj)
        self.pai[maior] = menor
        self.tamanho[menor] += self.tamanho[maior]


def formar_pautas(
    candidatos: Sequence[Candidato], pares: Iterable[ParPontuado], limiar: float, max_artigos: int,
) -> tuple[list[Pauta], list[ParPontuado]]:
    """Agrupa os candidatos em pautas e devolve (pautas, pares barrados pelo teto).

    1. As republicações (pares marcados como duplicata) são fundidas primeiro: fica o artigo
       que veio antes na coleta, e os outros vão para `duplicatas` sem ocupar vaga na pauta.
    2. Union-find do maior score para o menor: une quando o score chega ao limiar e a pauta
       resultante cabe em `max_artigos`. O par que passa do limiar mas não cabe volta na
       segunda lista, para a fonte que ficou de fora não se perder de vista.

    Todo candidato sai em alguma pauta, inclusive nas de um artigo só, na ordem da coleta. O
    principal é o artigo de texto mais longo (critério provisório, a rever na Fase 3).
    """
    pares = sorted(pares, key=lambda p: -p.score)
    posicao = {c: i for i, c in enumerate(candidatos)}
    por_posicoes = {frozenset((posicao[p.a], posicao[p.b])): p for p in pares}

    copias = _Conjuntos(len(candidatos))
    for p in pares:
        if p.duplicata:
            copias.unir(posicao[p.a], posicao[p.b])

    grupos = _Conjuntos(len(candidatos))
    barrados = []
    for p in pares:
        if p.score < limiar:
            break
        i, j = posicao[p.a], posicao[p.b]
        if copias.raiz(i) != i or copias.raiz(j) != j:
            continue  # republicação não disputa vaga: quem representa o texto é o original
        ri, rj = grupos.raiz(i), grupos.raiz(j)
        if ri == rj:
            continue
        if grupos.tamanho[ri] + grupos.tamanho[rj] > max_artigos:
            barrados.append(p)
            continue
        grupos.unir(ri, rj)

    membros: dict[int, list[int]] = {}
    copias_de: dict[int, list[int]] = {}
    for i in range(len(candidatos)):
        if copias.raiz(i) == i:
            membros.setdefault(grupos.raiz(i), []).append(i)
        else:
            copias_de.setdefault(copias.raiz(i), []).append(i)

    def score_entre(i: int, j: int) -> float:
        par = por_posicoes.get(frozenset((i, j)))
        return par.score if par else 0.0

    pautas = []
    for grupo in sorted(membros.values(), key=min):
        principal = max(grupo, key=lambda i: (len(candidatos[i].texto), -i))
        relacionados = sorted((i for i in grupo if i != principal), key=lambda i: (-score_entre(principal, i), i))
        internos = [por_posicoes[k] for k in map(frozenset, combinations(grupo, 2)) if k in por_posicoes]
        pautas.append(Pauta(
            principal=candidatos[principal],
            relacionados=tuple(candidatos[i] for i in relacionados),
            duplicatas=tuple(candidatos[d] for i in grupo for d in copias_de.get(i, ())),
            pares=tuple(sorted(internos, key=lambda p: -p.score)),
        ))
    return pautas, barrados

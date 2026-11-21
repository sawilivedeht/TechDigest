"""Teste dos feeds candidatos ao config/feeds.txt pelo caminho que o pipeline usa (frente 10 das melhorias, 20/11/2026).

Etapa 1, sem o modelo e só com a rede: lê `config/feeds_candidatos.txt` (colunas separadas por " | ": categoria,
subcategoria, nome, idioma e URL; linha vazia e linha que começa com "#" ficam de fora) e testa cada feed com as funções
do pacote, sem reimplementar nenhuma: `rss._baixar_feed` (o User-Agent e o timeout da coleta), `rss._artigos_do_feed`
(a data, MAX_IDADE_DIAS e MAX_POR_FEED), `filtro.motivo_do_filtro` e `filtro.pela_url`, `extractor.extrair`,
`qa._formas_faladas` e `numeros.numeros`. Uma requisição por vez, com pausa entre elas. Nada vai para o banco e nada é
marcado como visto: o script não abre o `SeenStore` nem configura o log do pacote.

Os critérios, e o que cada um dá:
1. Acesso: o feed responde e tem entradas. Um erro que esperar pode consertar (`rss._vale_repetir`) ganha uma segunda
   tentativa, depois de FEED_ESPERA_S. Erro, tempo esgotado duas vezes ou nenhuma entrada: REPROVADO.
2. Itens aproveitáveis (`rss._artigos_do_feed`): zero, REPROVADO (o item sem data também dá zero, porque a coleta o
   descarta); menos de `MIN_ITENS`, aviso.
3. Repetido: a URL, ou o host sem "www.", já está no `config/feeds.txt`: REPROVADO. O mesmo host em dois candidatos é
   só aviso (seções diferentes; a coleta já tira o link repetido).
4. Site de partido (`config/sites_de_partido.txt`), no feed, nos links ou nas URLs resolvidas: REPROVADO. Mais da metade
   dos itens filtrada (esporte, ofertas), pelo link e pela categoria, ou depois da extração: aviso.
5. Extração (`extractor.extrair`) dos `N_EXTRAIDOS` itens mais recentes que passam pelo filtro, contando o texto como o
   pipeline conta (com o resumo do feed quando a extração falha): menos de 60% com MIN_TEXTO_CHARS ou mais (3 de 5):
   REPROVADO. A página de consentimento de cookies não conta como texto, qualquer que seja o tamanho: são duas ou mais
   de `MARCAS_DE_CONSENTIMENTO` nos primeiros `INICIO_DO_CONSENTIMENTO` caracteres (decisão do dono de 20/11/2026,
   depois que a do Golem.de, com 1949 caracteres em inglês, passou na primeira rodada).
6. Nome do veículo: o que o episódio citaria (o título do feed, pela `rss._titulo_e_veiculo`) e a forma falada dele
   (`qa._formas_faladas`), contra a coluna "nome". Bate quando a forma do feed contém a da coluna, ou quando a da coluna
   contém a do feed e esta tem duas palavras ou mais. Não bate: AJUSTE.
7. Idioma e números: o idioma dos textos extraídos (palavras frequentes e proporção de ideogramas; no português, as
   marcas de Portugal e do Brasil) e as expressões com escala que `ai/numeros.py` não conhece, com o que `numeros()`
   lê em cada uma. A coluna ou o texto fora do pt-BR, ou alguma dessas expressões: ETAPA 2.
8. robots.txt (`urllib.robotparser`): o feed com o User-Agent da coleta, as matérias com o do trafilatura (o que a
   extração manda). Se proíbe: aviso.
9. Sobreposição com o Google Notícias: nos registros da produção (`<EXECUCOES_DIR>/*/amostra.json`, só leitura), as
   matérias que vieram por um feed do Google Notícias com a URL resolvida num host do candidato. Com o agrupamento
   desligado, a mesma matéria pelo Google Notícias e pelo feed direto vira dois episódios. Aviso.

Veredito: REPROVADO, se algum critério reprova; senão ETAPA 2 (só entra depois da simulação); senão AJUSTE (só o nome);
senão APROVADO. Saída em `data/agrupamento/feeds_<AAAAMMDD>/` (ou `--pasta`): `etapa1.csv`, uma linha por feed com os
números de cada critério, `etapa1.md`, a tabela por categoria e subcategoria, e `etapa1_textos.json`, o começo de cada
texto extraído, com a origem (o trafilatura ou o resumo do feed) e o que o teste fez dele, para conferir à mão.

Etapa 2, com o modelo e só com o ok do dono: `--lotes` monta os lotes dos APROVADO, AJUSTE e ETAPA 2 do `etapa1.csv` e
mostra o comando do `scripts/rodada.py` de cada um (a simulação sem áudio, que o dono roda); `--simulacao <pastas>` lê
as simulações, só para leitura, e escreve o `etapa2.md`, com o veredito pela regra (b) do dono (`DoFeed.veredito`).

Uso:
    .venv/bin/python scripts/testar_feeds.py [--candidatos <arquivo>] [--pasta <pasta>] [--registros <EXECUCOES_DIR>]
                                             [--pausa <segundos>]
    .venv/bin/python scripts/testar_feeds.py --lotes [--etapa1 <etapa1.csv>] [--por-lote <n>]
    .venv/bin/python scripts/testar_feeds.py --simulacao <pasta>... [--etapa1 <etapa1.csv>] [--producao <EXECUCOES_DIR>]
"""
import argparse
import collections
import csv
import datetime
import json
import logging
import math
import re
import statistics
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from trafilatura.downloads import USER_AGENT as UA_DA_EXTRACAO

from techdigest import config
from techdigest.ai import qa
from techdigest.ai.numeros import dobrar, formatar, numeros, pede_fonte
from techdigest.collectors import rss
from techdigest.models import Article
from techdigest.processing import extractor, filtro
from techdigest.registro import FORMATO_DA_PASTA

CAMINHO_DOS_CANDIDATOS = config.BASE_DIR / "config" / "feeds_candidatos.txt"
UA_DA_COLETA = rss._HEADERS["User-Agent"]
COLUNAS = ("categoria", "subcategoria", "nome", "idioma", "url")

MIN_ITENS = 3               # abaixo disto, aviso: o feed quase não entra na intercalação
N_EXTRAIDOS = 5             # os itens mais recentes que o teste extrai
FRACAO_COM_TEXTO = 0.6      # a fração mínima dos extraídos com MIN_TEXTO_CHARS (3 de 5)
PAUSA_S = 2.0               # entre duas requisições
# A página de consentimento de cookies (a do Golem.de, em 20/11/2026): duas ou mais destas marcas, sem acento nem caixa
# ("consent" pega consentimento, consenting, consentement), no começo do texto.
MARCAS_DE_CONSENTIMENTO = ("cookie", "consent", "privacy", "privacidade", "javascript")
INICIO_DO_CONSENTIMENTO = 500
MIN_MARCAS_DE_CONSENTIMENTO = 2
INICIO_NO_JSON = 300       # os caracteres de cada texto que vão para o etapa1_textos.json

APROVADO, AJUSTE, ETAPA_2, REPROVADO = "APROVADO", "AJUSTE", "ETAPA 2", "REPROVADO"


# ── Os candidatos ─────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidato:
    categoria: str
    subcategoria: str
    nome: str
    idioma: str
    url: str


def ler_candidatos(caminho: str | Path = CAMINHO_DOS_CANDIDATOS) -> list[Candidato]:
    """Os candidatos do arquivo, na ordem dele. Uma linha com outro número de colunas, uma URL que não é http(s) ou uma
    URL repetida levantam ValueError com o número da linha."""
    candidatos: list[Candidato] = []
    linha_de: dict[str, int] = {}
    for numero, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        partes = [p.strip() for p in linha.split(" | ")]
        if len(partes) != len(COLUNAS) or not all(partes):
            raise ValueError(f"{caminho}, linha {numero}: são {len(COLUNAS)} colunas separadas por \" | \" "
                             f"({', '.join(COLUNAS)})")
        url = partes[-1]
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).netloc:
            raise ValueError(f"{caminho}, linha {numero}: {url!r} não é uma URL http(s)")
        if url in linha_de:
            raise ValueError(f"{caminho}, linha {numero}: {url!r} repete a linha {linha_de[url]}")
        linha_de[url] = numero
        candidatos.append(Candidato(*partes))
    return candidatos


def _host(url: str) -> str:
    return (urlsplit(url.strip()).hostname or "").removeprefix("www.")


# ── A rede ────────────────────────────────────────────────────────────────────────────────

def _baixar_robots(url: str) -> tuple[int, str] | None:
    """O robots.txt (status e texto), pedido com o User-Agent da coleta; None se a requisição falhar."""
    try:
        resposta = requests.get(url, headers=rss._HEADERS, timeout=rss.settings.feed_timeout_s)
    except requests.RequestException:
        return None
    return resposta.status_code, resposta.text


def _leitor_de_robots(resposta: tuple[int, str] | None) -> RobotFileParser | None:
    """O robots.txt lido como o `RobotFileParser.read` o leria: 401 e 403 proíbem tudo, outro 4xx permite tudo; sem
    resposta, ou com 5xx, não há o que ler (None, que não conta)."""
    if resposta is None:
        return None
    status, texto = resposta
    leitor = RobotFileParser()
    if status in (401, 403):
        leitor.parse(["User-agent: *", "Disallow: /"])   # o mesmo que o disallow_all do read()
    elif 400 <= status < 500:
        leitor.parse([])                                 # o mesmo que o allow_all
    elif status == 200:
        leitor.parse(texto.splitlines())
    else:
        return None
    return leitor


@dataclass
class Rede:
    """As chamadas de rede do teste, uma por vez e com pausa entre elas. Os testes trocam cada função por uma falsa."""
    pausa_s: float = PAUSA_S
    baixar_feed: Callable[[str], Any] = rss._baixar_feed
    extrair: Callable[[str, str], extractor.Extracao] = extractor.extrair
    baixar_robots: Callable[[str], tuple[int, str] | None] = _baixar_robots
    dormir: Callable[[float], None] = time.sleep
    robots: dict[str, RobotFileParser | None] = field(default_factory=dict)   # por origem (esquema e host)
    _requisicoes: int = 0

    def esperar(self) -> None:
        """A pausa antes de cada requisição, menos da primeira."""
        if self._requisicoes:
            self.dormir(self.pausa_s)
        self._requisicoes += 1

    def robots_permite(self, url: str, user_agent: str) -> bool | None:
        """Se o robots.txt do site deixa o `user_agent` buscar a URL; None se não houver robots.txt para ler."""
        partes = urlsplit(url)
        origem = f"{partes.scheme}://{partes.netloc}"
        if origem not in self.robots:
            self.esperar()
            self.robots[origem] = _leitor_de_robots(self.baixar_robots(origem + "/robots.txt"))
        leitor = self.robots[origem]
        return None if leitor is None else leitor.can_fetch(user_agent, url)


# ── Idioma ────────────────────────────────────────────────────────────────────────────────

# Palavras frequentes de cada idioma: vence o idioma com mais ocorrências no texto. As listas se cruzam ("de", "que"),
# mas as palavras próprias de cada um decidem.
_PALAVRAS_FREQUENTES = {
    "pt": frozenset("não também são está uma um pelo pela pelos pelas ao aos às do da dos das no na nos nas em foi já "
                    "seu sua seus suas isso este esta quando ainda após até mais como para com que de o os as e".split()),
    "es": frozenset("el los las del y que de en con una un por más pero también fue está sus al ya este esta "
                    "es se lo le para como".split()),
    "en": frozenset("the and of to in is that for with on as by was are from this it be has have at an its which "
                    "will not or".split()),
    "de": frozenset("der die und das ist nicht mit den von zu auf für sich des ein eine dem auch im wird werden bei "
                    "nach wie oder aus".split()),
    "fr": frozenset("le la les des et est une un du que pour dans qui pas sur au avec ce par plus il en de sont aux "
                    "été".split()),
    "it": frozenset("il di che la per una un non gli della sono del con alla anche più nel delle dei è le si".split()),
}
# As marcas do português de Portugal e do Brasil: grafias e palavras que só um dos dois usa.
_MARCAS_PT_PT = frozenset((
    "económico económica económicos económicas prémio prémios género géneros fenómeno fenómenos académico académica "
    "académicos académicas anónimo anónima eletrónico eletrónica eletrónicos eletrónicas electrónico electrónica facto "
    "factos equipa equipas utilizador utilizadores utilizadora utilizadoras ecrã ecrãs telemóvel telemóveis registo "
    "registos autocarro autocarros comboio comboios bilião biliões contacto contactos aceder partilhar"
).split())
_MARCAS_PT_BR = frozenset((
    "econômico econômica econômicos econômicas prêmio prêmios gênero gêneros fenômeno fenômenos acadêmico acadêmica "
    "acadêmicos acadêmicas anônimo anônima eletrônico eletrônica eletrônicos eletrônicas fato fatos equipe equipes "
    "usuário usuários usuária usuárias tela telas celular celulares registro registros ônibus trem trens bilhão "
    "bilhões contato contatos acessar compartilhar"
).split())
_FORMAS_DE_ESTAR = r"(?:estou|está|estamos|estão|estava|estavam|esteve|estiveram|estar|estará|estarão)"
_ESTAR_A = re.compile(rf"\b{_FORMAS_DE_ESTAR}\s+a\s+[^\W\d_]+(?:ar|er|ir)\b", re.IGNORECASE)   # "está a fazer"
_ESTAR_GERUNDIO = re.compile(rf"\b{_FORMAS_DE_ESTAR}\s+[^\W\d_]+ndo\b", re.IGNORECASE)          # "está fazendo"
_IDEOGRAMA = re.compile(r"[㐀-䶿一-鿿]")


@dataclass(frozen=True)
class Idioma:
    idioma: str                # "pt-BR", "pt-PT", "pt" (sem marca que decida), "en", "es", "de", "fr", "it", "zh" ou "?"
    marcas_pt_pt: int = 0
    marcas_pt_br: int = 0


def detectar_idioma(textos: Iterable[str]) -> Idioma:
    """O idioma dos textos, só com a biblioteca padrão: ideogramas acima de 20% das letras são chinês; senão, o idioma
    com mais palavras frequentes; no português, as marcas de Portugal contra as do Brasil."""
    texto = unicodedata.normalize("NFC", "\n".join(textos))
    letras = sum(1 for c in texto if c.isalpha())
    if not letras:
        return Idioma("?")
    if len(_IDEOGRAMA.findall(texto)) / letras > 0.2:
        return Idioma("zh")
    palavras = re.findall(r"[^\W\d_]+", texto.lower())
    contagem = {idioma: sum(1 for p in palavras if p in lista) for idioma, lista in _PALAVRAS_FREQUENTES.items()}
    idioma = max(contagem, key=lambda i: contagem[i])
    if not palavras or contagem[idioma] < 0.05 * len(palavras):
        return Idioma("?")
    if idioma != "pt":
        return Idioma(idioma)
    pt_pt = sum(1 for p in palavras if p in _MARCAS_PT_PT) + len(_ESTAR_A.findall(texto))
    pt_br = sum(1 for p in palavras if p in _MARCAS_PT_BR) + len(_ESTAR_GERUNDIO.findall(texto))
    variante = "pt-PT" if pt_pt > pt_br else "pt-BR" if pt_br > pt_pt else "pt"
    return Idioma(variante, pt_pt, pt_br)


# ── Números ───────────────────────────────────────────────────────────────────────────────

# As escalas que ai/numeros.py não conhece (ele conhece mil, milhão, bilhão e trilhão, no singular e no plural).
_ESCALAS_DESCONHECIDAS = "|".join((
    r"thousands?", r"millions?", r"billions?", r"trillions?", r"bn",   # inglês ("millions" também é francês;
                                                                       # "Million" e "Billion", alemão)
    r"bili(?:ão|ões)",                                                  # português de Portugal (10¹²; o "mil milhões",
                                                                        # 10⁹, ai/numeros.py lê desde 21/11/2026)
    r"Millionen", r"Milliarden?", r"Billionen", r"Mio\.", r"Mrd\.",     # alemão
    r"milliards?",                                                      # francês
    r"mil\s+mill(?:ón|ones)", r"mill(?:ón|ones)", r"bill(?:ón|ones)",   # espanhol
    r"milioni", r"miliardi",                                            # italiano
))
_CASOS_DE_ESCALA = (
    # O número antes da escala, em algarismos ou uma palavra ("um", "two", "a"), e a escala, fora de outra palavra.
    re.compile(rf"(?:(?<![\w.,])\d+(?:[.,]\d+)*\s*|(?<!\w)[^\W\d_]+\s+)?(?<![^\W\d_])(?:{_ESCALAS_DESCONHECIDAS})"
               rf"(?![^\W\d_])", re.IGNORECASE),
    re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)*\s*(?:万亿|亿|万)"),   # chinês: o número vem colado aos ideogramas
    re.compile(r"[$€£¥]\s?\d+(?:[.,]\d+)*\s?[kmb](?![^\W\d_])", re.IGNORECASE),   # "$5M", "£40m" ("bn" vem acima)
)
# Formatos de algarismo de outros idiomas: só para o relatório (o texto que os tem já vai para a etapa 2 pelo idioma).
FORMATOS_DE_ALGARISMO = {
    "decimal com ponto": re.compile(r"(?<![\d.,])\d+\.\d{1,2}(?!\d)"),                     # "3.5": lê 3 e 5
    "milhar com vírgula": re.compile(r"(?<![\d.,])\d{1,3}(?:,\d{3})+(?!\d)"),               # "1,200": lê 1,2
    "milhar com espaço": re.compile(r"(?<![\d.,])\d{1,3}(?:[   ]\d{3})+(?!\d)"),  # "12 000": lê 12 e 0
}


def leitura(trecho: str) -> str:
    """O que `numeros()` devolve para o trecho: os valores, separados por "; ", ou "nada"."""
    lidos = numeros(unicodedata.normalize("NFC", trecho))
    return "; ".join(formatar(n.valor, n.percentual) for n in lidos) or "nada"


def casos_de_escala(texto: str) -> list[tuple[str, str]]:
    """As expressões com uma escala que ai/numeros.py não conhece, sem repetir, cada uma com o que `numeros()` lê nela."""
    texto = unicodedata.normalize("NFC", texto)
    achados: dict[str, str] = {}
    for padrao in _CASOS_DE_ESCALA:
        for m in padrao.finditer(texto):
            trecho = " ".join(m.group().split())
            achados.setdefault(trecho, leitura(trecho))
    return list(achados.items())


def formatos_de_algarismo(texto: str) -> dict[str, int]:
    return {nome: len(padrao.findall(texto)) for nome, padrao in FORMATOS_DE_ALGARISMO.items()}


def marcas_de_consentimento(texto: str) -> list[str]:
    """As marcas de página de consentimento no começo do texto, sem acento nem caixa."""
    inicio = dobrar(texto[:INICIO_DO_CONSENTIMENTO])
    return [marca for marca in MARCAS_DE_CONSENTIMENTO if marca in inicio]


# ── O nome do veículo ─────────────────────────────────────────────────────────────────────

def _contem(maior: list[str], menor: list[str]) -> bool:
    return bool(menor) and any(maior[i:i + len(menor)] == menor for i in range(len(maior) - len(menor) + 1))


def forma_falada(nome: str) -> list[str]:
    """A forma falada principal do nome (`qa._formas_faladas`): sem acento, caixa, artigo nem slogan."""
    formas = qa._formas_faladas(nome)
    return formas[0] if formas else []


def comparar_nome(nome_da_coluna: str, veiculo: str) -> tuple[bool, str]:
    """Se o veículo que o episódio citaria (o título do feed) é o da coluna "nome", e por quê não.

    Bate quando a forma falada do feed contém a da coluna ("Olhar Digital - O futuro..." e "Olhar Digital"), ou quando
    a da coluna contém a do feed e esta tem duas palavras ou mais ("Pesquisa FAPESP" e "Revista Pesquisa FAPESP"). Uma
    palavra só contida no nome da coluna é genérica demais ("Notícias" e "RTP Notícias"), e uma forma vazia (título em
    ideogramas) o QA nem reconhece.
    """
    do_feed, da_coluna = forma_falada(veiculo), forma_falada(nome_da_coluna)
    if not do_feed:
        return False, f"o título do feed ({veiculo!r}) não tem letras latinas nem algarismos: o QA não reconhece a citação"
    if not da_coluna:
        return False, f"a coluna \"nome\" ({nome_da_coluna!r}) não tem letras latinas nem algarismos"
    if _contem(do_feed, da_coluna) or (len(do_feed) >= 2 and _contem(da_coluna, do_feed)):
        return True, ""
    return False, f"o episódio citaria {veiculo!r} (dito \"{' '.join(do_feed)}\"), não \"{nome_da_coluna}\""


# ── O teste de um feed ────────────────────────────────────────────────────────────────────

@dataclass
class Resultado:
    candidato: Candidato
    reprovacoes: list[str] = field(default_factory=list)
    para_etapa2: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    acesso: str = ""                # "ok", "ok na tentativa 2" ou o erro
    titulo_do_feed: str = ""
    entradas: int = 0
    sem_data: int = 0
    antigas: int = 0
    sem_link: int = 0
    aproveitaveis: int = 0
    filtrados_no_feed: int = 0      # pelo link e pela categoria, entre os aproveitáveis
    extraidos: int = 0
    filtrados_depois: int = 0       # pela URL resolvida, entre os extraídos
    com_texto: int = 0
    pelo_resumo: int = 0            # dos com texto, os que vieram do resumo do feed (a extração falhou)
    consentimento: int = 0          # dos extraídos, os que são a página de consentimento de cookies
    amostras: list[dict] = field(default_factory=list)   # o começo de cada texto extraído, para o etapa1_textos.json
    caracteres: list[int] = field(default_factory=list)
    falhas_de_extracao: list[str] = field(default_factory=list)
    veiculo: str = ""
    nome_bate: bool | None = None
    nome_motivo: str = ""
    idioma: Idioma = Idioma("?")
    casos: list[tuple[str, str]] = field(default_factory=list)
    formatos: dict[str, int] = field(default_factory=dict)
    robots_feed: str = ""
    robots_materias: str = ""
    hosts: set[str] = field(default_factory=set)       # do feed, dos links e das URLs resolvidas
    google_noticias: int = 0

    def reprovar(self, motivo: str) -> None:
        """Junta um motivo de reprovação, uma vez só (o site de partido em cinco links é um motivo)."""
        if motivo not in self.reprovacoes:
            self.reprovacoes.append(motivo)

    @property
    def veredito(self) -> str:
        if self.reprovacoes:
            return REPROVADO
        if self.para_etapa2:
            return ETAPA_2
        if self.nome_bate is False:
            return AJUSTE
        return APROVADO

    @property
    def motivo(self) -> str:
        motivos = {REPROVADO: self.reprovacoes, ETAPA_2: self.para_etapa2, AJUSTE: [self.nome_motivo]}
        return "; ".join(motivos.get(self.veredito, []))

    @property
    def considerados(self) -> int:
        """Os extraídos que o filtro deixa seguir: a base da fração com texto."""
        return self.extraidos - self.filtrados_depois


def _acessar(r: Resultado, rede: Rede, url: str):
    """O feed baixado e lido (`rss._baixar_feed`), com uma segunda tentativa só para o erro que esperar pode consertar."""
    for tentativa in (1, 2):
        rede.esperar()
        try:
            parsed = rede.baixar_feed(url)
        except Exception as e:
            erro = f"{type(e).__name__}: {str(e)[:100]}"
            if tentativa == 1 and rss._vale_repetir(e):
                rede.dormir(rss.settings.feed_espera_s)
                continue
            r.acesso = erro
            vezes = " nas 2 tentativas" if tentativa == 2 else ""
            r.reprovar(f"acesso: {erro}{vezes}")
            return None
        r.acesso = "ok" if tentativa == 1 else f"ok na tentativa {tentativa}"
        return parsed
    return None


def _veiculo(parsed, artigos: list[Article], url: str) -> str:
    """O veículo que o episódio citaria: o `source` dos artigos (o mais comum), ou o da primeira entrada."""
    if artigos:
        return collections.Counter(a.source for a in artigos).most_common(1)[0][0]
    entrada = parsed.entries[0]
    return rss._titulo_e_veiculo(entrada, entrada.get("title", ""), parsed.feed.get("title", url))[1]


def _data(artigo: Article) -> float:
    return artigo.published.timestamp() if artigo.published else float("-inf")


def _robots(rede: Rede, url: str, user_agent: str) -> bool | None:
    try:
        return rede.robots_permite(url, user_agent)
    except Exception:   # uma URL que o robotparser não entende não derruba o teste do feed
        return None


def _prazo(dias: int) -> str:
    return f"nos últimos {dias} dias" if dias else "no feed"


def testar_feed(candidato: Candidato, rede: Rede, atuais: Iterable[str]) -> Resultado:
    """Os critérios 1 a 8 (ver o começo do módulo) para um feed. O 9 e o host repetido entre candidatos são de `testar`."""
    cfg = rss.settings
    r = Resultado(candidato)
    atuais = tuple(atuais)
    host = _host(candidato.url)
    r.hosts.add(host)

    # 3. Repetido
    if candidato.url in atuais:
        r.reprovar("repetido: a URL já está no config/feeds.txt")
    elif host in {_host(u) for u in atuais}:
        r.reprovar(f"repetido: o host {host} já está no config/feeds.txt")
    # 4. Site de partido, pelo endereço do feed
    if (motivo := filtro.pela_url(candidato.url)).startswith("site de partido"):
        r.reprovar(f"{motivo}, no endereço do feed")
    # 8. robots.txt do feed
    permite = _robots(rede, candidato.url, UA_DA_COLETA)
    r.robots_feed = {True: "permite", False: "proíbe", None: "sem robots.txt"}[permite]
    if permite is False:
        r.avisos.append("o robots.txt proíbe o feed para o User-Agent da coleta")

    # 1. Acesso
    parsed = _acessar(r, rede, candidato.url)
    if parsed is None:
        return r
    r.titulo_do_feed = str(parsed.feed.get("title", ""))
    r.entradas = len(parsed.entries)
    if not parsed.entries:
        r.reprovar("acesso: o feed não tem entradas" + (" (XML malformado)" if parsed.bozo else ""))
        return r

    # 2. Itens aproveitáveis, pela função da coleta
    for entrada in parsed.entries:
        idade = rss._idade_dias(entrada)
        if idade is None:
            r.sem_data += 1
        elif cfg.max_idade_dias and idade > cfg.max_idade_dias:
            r.antigas += 1
    artigos = rss._artigos_do_feed(parsed, candidato.url)
    r.sem_link = sum(1 for a in artigos if not a.url)   # a intercalação da coleta descarta o item sem link
    artigos = [a for a in artigos if a.url]
    r.aproveitaveis = len(artigos)

    # 6. Nome do veículo
    r.veiculo = _veiculo(parsed, artigos, candidato.url)
    r.nome_bate, r.nome_motivo = comparar_nome(candidato.nome, r.veiculo)

    if not artigos:
        partes = [f"{r.entradas} entrada(s)"]
        if r.sem_data and cfg.max_idade_dias:
            partes.append(f"{r.sem_data} sem data (a coleta descarta)")
        if r.antigas:
            partes.append(f"{r.antigas} com mais de {cfg.max_idade_dias} dias")
        if r.sem_link:
            partes.append(f"{r.sem_link} sem link")
        r.reprovar(f"nenhum item aproveitável ({', '.join(partes)})")
        return r
    if len(artigos) < MIN_ITENS:
        r.avisos.append(f"só {len(artigos)} item(ns) {_prazo(cfg.max_idade_dias)}")
    if r.sem_data and cfg.max_idade_dias:
        r.avisos.append(f"{r.sem_data} entrada(s) sem data, que a coleta descarta")

    # 4. O filtro pelo link e pela categoria
    seguem = []
    for artigo in artigos:
        r.hosts.add(_host(artigo.url))
        if motivo := filtro.motivo_do_filtro(artigo.url, artigo.categorias):
            r.filtrados_no_feed += 1
            if motivo.startswith("site de partido"):
                r.reprovar(f"{motivo}, num link do feed")
        else:
            seguem.append(artigo)
    if r.filtrados_no_feed * 2 > len(artigos):
        r.avisos.append(f"{r.filtrados_no_feed} de {len(artigos)} itens filtrados pelo link ou pela categoria")
    if not seguem:
        r.reprovar("todos os itens aproveitáveis são filtrados pelo link ou pela categoria")
        return r

    # 5. Extração dos mais recentes, com o filtro de novo pela URL resolvida
    textos = []
    proibidas = conferidas = 0
    for artigo in sorted(seguem, key=_data, reverse=True)[:N_EXTRAIDOS]:
        permite = _robots(rede, artigo.url, UA_DA_EXTRACAO)
        if permite is not None:
            conferidas += 1
            proibidas += not permite
        rede.esperar()
        r.extraidos += 1
        amostra = {"link": artigo.url, "url_resolvida": "", "origem": "", "caracteres": 0, "situacao": "",
                   "marcas_de_consentimento": [], "inicio": ""}
        r.amostras.append(amostra)
        try:
            extracao = rede.extrair(artigo.url, artigo.summary)
        except Exception as e:
            r.falhas_de_extracao.append(f"{type(e).__name__}: {str(e)[:80]}")
            amostra["situacao"] = f"falhou ({type(e).__name__})"
            continue
        marcas = marcas_de_consentimento(extracao.texto)
        amostra.update(url_resolvida=extracao.url_resolvida,
                       origem="trafilatura" if extracao.extraido else "resumo do feed",
                       caracteres=len(extracao.texto), marcas_de_consentimento=marcas,
                       inicio=" ".join(extracao.texto[:INICIO_NO_JSON].split()))
        if extracao.url_resolvida:
            r.hosts.add(_host(extracao.url_resolvida))
        if (extracao.url_resolvida and extracao.url_resolvida != artigo.url
                and (motivo := filtro.pela_url(extracao.url_resolvida))):
            r.filtrados_depois += 1
            amostra["situacao"] = f"filtrado ({motivo})"
            if motivo.startswith("site de partido"):
                r.reprovar(f"{motivo}, numa URL resolvida")
            continue
        r.caracteres.append(len(extracao.texto))
        if len(marcas) >= MIN_MARCAS_DE_CONSENTIMENTO:
            r.consentimento += 1      # o tamanho não importa: não é a matéria
            amostra["situacao"] = "página de consentimento"
        elif len(extracao.texto) >= cfg.min_texto_chars:
            r.com_texto += 1
            r.pelo_resumo += not extracao.extraido
            textos.append(extracao.texto)
            amostra["situacao"] = "texto"
        else:
            amostra["situacao"] = "curto"
    r.robots_materias = f"{proibidas} de {conferidas} proibidas" if conferidas else "sem robots.txt"
    if proibidas:
        r.avisos.append(f"o robots.txt proíbe {proibidas} de {conferidas} matérias para o User-Agent do trafilatura")
    if r.filtrados_depois * 2 > r.extraidos:
        r.avisos.append(f"{r.filtrados_depois} de {r.extraidos} extraídos filtrados pela URL resolvida")
    if r.pelo_resumo:
        r.avisos.append(f"{r.pelo_resumo} texto(s) do resumo do feed (a extração falhou)")
    if r.consentimento:
        r.avisos.append(f"{r.consentimento} texto(s) são a página de consentimento de cookies (não contam como texto)")
    precisa = math.ceil(FRACAO_COM_TEXTO * r.considerados)
    if r.considerados and r.com_texto < precisa:
        r.reprovar(f"extração: {r.com_texto} de {r.considerados} com {cfg.min_texto_chars} caracteres ou mais "
                             f"(mínimo {precisa}; paywall, bloqueio ou página em JavaScript)")
    elif not r.considerados:
        r.reprovar("extração: nenhum item extraído passou pelo filtro da URL resolvida")

    # 7. Idioma e números
    if textos:
        r.idioma = detectar_idioma(textos)
        vistos: set[str] = set()
        formatos: collections.Counter[str] = collections.Counter()
        for texto in textos:
            for trecho, lido in casos_de_escala(texto):
                if trecho not in vistos:
                    vistos.add(trecho)
                    r.casos.append((trecho, lido))
            formatos.update(formatos_de_algarismo(texto))
        r.formatos = dict(formatos)
    if candidato.idioma != "pt-BR":
        r.para_etapa2.append(f"idioma da coluna: {candidato.idioma}")
    if textos and r.idioma.idioma not in ("pt-BR", "pt"):
        r.para_etapa2.append(f"texto em {r.idioma.idioma}")
    if r.casos:
        r.para_etapa2.append(f"{len(r.casos)} expressão(ões) com escala que ai/numeros.py não lê")
    return r


# ── Sobreposição com o Google Notícias (critério 9) ───────────────────────────────────────

@dataclass
class Registros:
    """As matérias que chegaram à geração nas execuções registradas, vindas de um feed do Google Notícias."""
    pasta: str
    execucoes: int = 0
    datas: list[datetime.date] = field(default_factory=list)   # das execuções com algum item
    por_host: dict[str, set[str]] = field(default_factory=dict)    # host → as URLs resolvidas distintas


def ler_registros(pasta: str | Path) -> Registros:
    """Lê `<pasta>/*/amostra.json` (só leitura). A amostra guarda só as matérias que chegaram à geração, não tudo o que a
    coleta trouxe; a mesma matéria em duas execuções conta uma vez."""
    registros = Registros(str(pasta))
    for amostra in sorted(Path(pasta).glob("*/amostra.json")):
        try:
            candidatos = json.loads(amostra.read_text(encoding="utf-8")).get("candidatos") or []
        except (OSError, ValueError, AttributeError):
            continue
        registros.execucoes += 1
        if candidatos:
            try:
                registros.datas.append(datetime.datetime.strptime(amostra.parent.name[:15], FORMATO_DA_PASTA).date())
            except ValueError:
                pass
        for c in candidatos:
            url = str(c.get("url_resolvida") or "")
            if extractor._eh_google(str(c.get("feed") or "")) and url and not extractor._eh_google(url):
                registros.por_host.setdefault(_host(url), set()).add(url)
    return registros


def sobreposicao(hosts: Iterable[str], registros: Registros) -> int:
    """Quantas matérias distintas vieram pelo Google Notícias com a URL resolvida num destes hosts."""
    urls: set[str] = set()
    for host in hosts:
        urls |= registros.por_host.get(host, set())
    return len(urls)


def periodo(registros: Registros) -> str:
    if not registros.datas:
        return f"{registros.execucoes} execução(ões) registrada(s), nenhuma com itens"
    inicio, fim = min(registros.datas), max(registros.datas)
    return (f"{registros.execucoes} execução(ões) registrada(s), {len(registros.datas)} com itens, de "
            f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y} ({(fim - inicio).days + 1} dias)")


# ── Etapa 1 inteira ───────────────────────────────────────────────────────────────────────

def _mostrar(texto: str) -> None:
    print(texto, flush=True)   # com a saída num arquivo, sem o flush o andamento só aparecia no fim


def testar(candidatos: list[Candidato], rede: Rede, atuais: Iterable[str], registros: Registros | None,
           mostrar: Callable[[str], None] = _mostrar) -> list[Resultado]:
    """Testa os candidatos um por um e junta o que depende de todos: o host repetido entre eles e o critério 9."""
    atuais = tuple(atuais)
    resultados = []
    for i, candidato in enumerate(candidatos, 1):
        r = testar_feed(candidato, rede, atuais)
        resultados.append(r)
        mostrar(f"[{i}/{len(candidatos)}] {candidato.nome} ({candidato.url}): {r.veredito}"
                + (f" ({r.motivo})" if r.motivo else ""))
    for r in resultados:
        iguais = [o.candidato for o in resultados
                  if o is not r and _host(o.candidato.url) == _host(r.candidato.url)]
        if iguais:
            r.avisos.append("o mesmo host de " + ", ".join(f"{c.nome} ({c.url})" for c in iguais))
        if registros is not None:
            r.google_noticias = sobreposicao(r.hosts - {"news.google.com"}, registros)
            if r.google_noticias:
                r.avisos.append(f"sobreposição com o Google Notícias: {r.google_noticias} matéria(s) destes hosts já "
                                "vieram por ele nos registros da produção (a mesma matéria pode virar dois episódios)")
    return resultados


# ── A saída ───────────────────────────────────────────────────────────────────────────────

CAMPOS_DO_CSV = (
    "categoria", "subcategoria", "nome", "idioma_coluna", "url", "veredito", "motivo", "avisos", "acesso",
    "titulo_do_feed", "entradas", "sem_data", "antigas", "sem_link", "aproveitaveis", "filtrados_no_feed", "extraidos",
    "filtrados_depois", "com_texto", "pelo_resumo", "consentimento", "mediana_caracteres", "falhas_de_extracao", "veiculo",
    "forma_falada", "nome_bate", "idioma_texto", "marcas_pt_pt", "marcas_pt_br", "casos_de_escala",
    "exemplos_de_escala", "decimal_com_ponto", "milhar_com_virgula", "milhar_com_espaco", "robots_feed",
    "robots_materias", "google_noticias", "hosts",
)


def linha_do_csv(r: Resultado) -> dict:
    c = r.candidato
    return {
        "categoria": c.categoria, "subcategoria": c.subcategoria, "nome": c.nome, "idioma_coluna": c.idioma,
        "url": c.url, "veredito": r.veredito, "motivo": r.motivo, "avisos": "; ".join(r.avisos), "acesso": r.acesso,
        "titulo_do_feed": r.titulo_do_feed, "entradas": r.entradas, "sem_data": r.sem_data, "antigas": r.antigas,
        "sem_link": r.sem_link, "aproveitaveis": r.aproveitaveis, "filtrados_no_feed": r.filtrados_no_feed,
        "extraidos": r.extraidos, "filtrados_depois": r.filtrados_depois, "com_texto": r.com_texto,
        "pelo_resumo": r.pelo_resumo, "consentimento": r.consentimento,
        "mediana_caracteres": int(statistics.median(r.caracteres)) if r.caracteres else "",
        "falhas_de_extracao": "; ".join(r.falhas_de_extracao), "veiculo": r.veiculo,
        "forma_falada": " ".join(forma_falada(r.veiculo)) if r.veiculo else "",
        "nome_bate": "" if r.nome_bate is None else ("sim" if r.nome_bate else "não"),
        "idioma_texto": r.idioma.idioma, "marcas_pt_pt": r.idioma.marcas_pt_pt, "marcas_pt_br": r.idioma.marcas_pt_br,
        "casos_de_escala": len(r.casos), "exemplos_de_escala": "; ".join(f"{t} → {lido}" for t, lido in r.casos),
        "decimal_com_ponto": r.formatos.get("decimal com ponto", 0),
        "milhar_com_virgula": r.formatos.get("milhar com vírgula", 0),
        "milhar_com_espaco": r.formatos.get("milhar com espaço", 0),
        "robots_feed": r.robots_feed, "robots_materias": r.robots_materias, "google_noticias": r.google_noticias,
        "hosts": " ".join(sorted(h for h in r.hosts if h)),
    }


def escrever_csv(resultados: list[Resultado], caminho: Path) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=CAMPOS_DO_CSV)
        escritor.writeheader()
        escritor.writerows(linha_do_csv(r) for r in resultados)


def _celula(texto) -> str:
    return " ".join(str(texto).split()).replace("|", "\\|") or "—"


def _itens(r: Resultado) -> str:
    if not r.entradas:
        return "—"
    partes = [f"{r.aproveitaveis} de {r.entradas}"]
    partes += [f"{n} {nome}" for n, nome in ((r.sem_data, "sem data"), (r.antigas, "antigas"), (r.sem_link, "sem link"))
               if n]
    return ", ".join(partes)


def _extracao(r: Resultado) -> str:
    if not r.extraidos:
        return "—"
    texto = f"{r.com_texto} de {r.considerados}"
    if r.caracteres:
        texto += f", mediana {int(statistics.median(r.caracteres))} car."
    if r.pelo_resumo:
        texto += f", {r.pelo_resumo} pelo resumo"
    if r.consentimento:
        texto += f", {r.consentimento} consentimento"
    return texto


def _nome(r: Resultado) -> str:
    if not r.veiculo:
        return "—"
    falado = " ".join(forma_falada(r.veiculo)) or "(vazia)"
    return f"{r.veiculo} → \"{falado}\"" + ("" if r.nome_bate else " (não bate)")


def _idioma(r: Resultado) -> str:
    texto = f"{r.candidato.idioma} / {r.idioma.idioma}"
    if r.idioma.idioma.startswith("pt"):
        texto += f" (marcas PT {r.idioma.marcas_pt_pt}, BR {r.idioma.marcas_pt_br})"
    return texto


def escrever_md(resultados: list[Resultado], caminho: Path, cabecalho: list[str]) -> None:
    contagem = collections.Counter(r.veredito for r in resultados)
    linhas = [*cabecalho, "",
              "Vereditos: " + ", ".join(f"{v} {contagem[v]}" for v in (APROVADO, AJUSTE, ETAPA_2, REPROVADO))
              + f" (de {len(resultados)}).", ""]
    grupos: dict[tuple[str, str], list[Resultado]] = {}
    for r in resultados:
        grupos.setdefault((r.candidato.categoria, r.candidato.subcategoria), []).append(r)
    for (categoria, subcategoria), do_grupo in grupos.items():
        linhas += [f"## {categoria}: {subcategoria}", "",
                   "| Nome | Veredito | Motivo | Itens | Extração | Veículo (título do feed → forma falada) | "
                   "Idioma (coluna / texto) | Escala | Avisos |",
                   "|---|---|---|---|---|---|---|---|---|"]
        for r in do_grupo:
            linhas.append("| " + " | ".join(_celula(x) for x in (
                r.candidato.nome, r.veredito, r.motivo, _itens(r), _extracao(r), _nome(r), _idioma(r),
                len(r.casos) or "", "; ".join(r.avisos))) + " |")
        linhas.append("")
    com_casos = [r for r in resultados if r.casos]
    if com_casos:
        linhas += ["## Expressões com escala que ai/numeros.py não lê", "",
                   "Cada expressão como está no texto extraído, e o que `numeros()` devolve para ela.", ""]
        for r in com_casos:
            linhas.append(f"### {r.candidato.nome} ({r.candidato.url})")
            linhas += [f"- \"{trecho}\" → {lido}" for trecho, lido in r.casos[:10]]
            if len(r.casos) > 10:
                linhas.append(f"- e mais {len(r.casos) - 10}")
            linhas.append("")
    caminho.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")


def escrever_textos(resultados: list[Resultado], caminho: Path) -> None:
    """O começo de cada texto extraído, por feed, para conferir à mão o que o critério 5 contou."""
    caminho.write_text(json.dumps(
        [{"nome": r.candidato.nome, "url": r.candidato.url, "veredito": r.veredito, "textos": r.amostras}
         for r in resultados], ensure_ascii=False, indent=1), encoding="utf-8")


def cabecalho(agora: datetime.datetime, candidatos: str, atuais: tuple[str, ...], registros: Registros | None,
              pausa_s: float) -> list[str]:
    cfg = rss.settings
    return [
        f"# Feeds candidatos: etapa 1 ({agora:%d/%m/%Y %H:%M})", "",
        f"Sem o modelo: cada feed de `{candidatos}` pelas funções da coleta e da extração do pipeline "
        "(`scripts/testar_feeds.py`). Nada foi para o banco nem foi marcado como visto.", "",
        f"- Valores usados: MAX_IDADE_DIAS={cfg.max_idade_dias}, MAX_POR_FEED={cfg.max_por_feed}, "
        f"MIN_TEXTO_CHARS={cfg.min_texto_chars}, FEED_TIMEOUT_S={cfg.feed_timeout_s}, FEED_ESPERA_S={cfg.feed_espera_s}; "
        f"MAX_NEWS={cfg.max_news} e MAX_RUNTIME_MIN={cfg.max_runtime_min} só valem na etapa 2.",
        f"- Critérios do script: menos de {MIN_ITENS} itens é aviso; extração dos {N_EXTRAIDOS} mais recentes que passam "
        f"pelo filtro, com {FRACAO_COM_TEXTO:.0%} deles com texto (a página de consentimento não conta); pausa de "
        f"{pausa_s:g} s entre requisições.",
        f"- User-Agent do feed (coleta): `{UA_DA_COLETA}`; das matérias (trafilatura): `{UA_DA_EXTRACAO}`.",
        f"- Feeds de hoje (`config/feeds.txt`): {len(atuais)}, nos hosts "
        f"{', '.join(sorted({_host(u) for u in atuais}))}.",
        (f"- Registros da produção (critério 9): `{registros.pasta}`, {periodo(registros)}; a amostra guarda só as "
         "matérias que chegaram à geração." if registros is not None else "- Registros da produção: não lidos."),
    ]


# ── Etapa 2: os lotes da simulação ────────────────────────────────────────────────────────

POR_LOTE = 10
BANCO_DA_PRODUCAO = "/home/sytw/Projetos/techdigest/data/digest.db"
VEREDITOS_DA_ETAPA2 = (APROVADO, AJUSTE, ETAPA_2)   # os AJUSTE também (decisão do dono de 20/11/2026)
MIN_GERADOS = 2                      # o veredito da etapa 2: 2 ou mais itens gerados, 80% ou mais deles sem
FRACAO_SEM_PROBLEMA_DA_FONTE = 0.8   # nada contra o feed (DoFeed.contra_o_feed) e nenhuma reprovação por número do
                                     # formato da fonte


def ler_etapa1(caminho: str | Path) -> list[dict]:
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def etapa1_mais_recente(base: Path) -> Path | None:
    achados = sorted(base.glob("feeds_*/etapa1.csv"))
    return achados[-1] if achados else None


def montar_lotes(linhas: list[dict], por_lote: int = POR_LOTE) -> list[list[dict]]:
    """Os feeds que vão para a simulação (APROVADO, AJUSTE e ETAPA 2 da etapa 1), em lotes de até `por_lote`, na ordem
    do arquivo: cada categoria em lotes do mesmo tamanho, ou quase (18 feeds viram 9 e 9, não 10 e 8), para cada feed ter
    a mesma chance de chegar à geração antes de MAX_NEWS."""
    por_categoria: dict[str, list[dict]] = {}
    for linha in linhas:
        if linha["veredito"] in VEREDITOS_DA_ETAPA2:
            if "," in linha["url"] or "'" in linha["url"]:
                raise ValueError(f"{linha['url']!r}: o RSS_FEEDS separa por vírgula e vai entre aspas simples")
            por_categoria.setdefault(linha["categoria"], []).append(linha)
    lotes = []
    for feeds in por_categoria.values():
        partes = math.ceil(len(feeds) / por_lote)
        tamanho, sobra = divmod(len(feeds), partes)
        inicio = 0
        for k in range(partes):
            fim = inicio + tamanho + (k < sobra)
            lotes.append(feeds[inicio:fim])
            inicio = fim
    return lotes


def comando_do_lote(numero: int, lote: list[dict], agora: datetime.datetime) -> str:
    """O comando do `scripts/rodada.py` do lote, da raiz da worktree: a simulação sem áudio, com o RSS_FEEDS do lote no
    ambiente (vale mais que o .env e que o config/feeds.txt), entre aspas simples por causa do & e do ? das URLs."""
    data = f"{agora:%Y%m%d}"
    urls = ",".join(linha["url"] for linha in lote)
    return (f".venv/bin/python scripts/rodada.py --pasta data/agrupamento/feeds_lote{numero}_{data} "
            f"--pedido \"frente 10, etapa 2: simulação do lote {numero} de feeds candidatos, {agora:%d/%m/%Y}\" -- "
            f"env 'RSS_FEEDS={urls}' .venv/bin/techdigest --simular data/simulacoes/feeds_lote{numero}_{data} "
            f"--banco-origem {BANCO_DA_PRODUCAO} --sem-audio")


def escrever_lotes(lotes: list[list[dict]], pasta: Path, agora: datetime.datetime) -> Path:
    """`loteN.txt` (as URLs, no formato do config/feeds.txt, com o nome de cada feed em comentário) e `lotes.md` (os
    feeds e o comando de cada lote)."""
    linhas = [f"# Etapa 2: os lotes ({agora:%d/%m/%Y %H:%M})", "",
              f"Os APROVADO, AJUSTE e ETAPA 2 da etapa 1, em {len(lotes)} lotes de até {POR_LOTE} feeds, na ordem do "
              "arquivo, cada categoria em lotes de tamanho igual ou quase. Os comandos rodam da raiz da worktree.", ""]
    for numero, lote in enumerate(lotes, 1):
        (pasta / f"lote{numero}.txt").write_text(
            "".join(f"# {l['nome']} ({l['categoria']}: {l['subcategoria']}; {l['veredito']})\n{l['url']}\n" for l in lote),
            encoding="utf-8")
        linhas += [f"## Lote {numero}: {len(lote)} feeds", ""]
        linhas += [f"- {l['nome']} ({l['categoria']}: {l['subcategoria']}; {l['veredito']}): {l['url']}" for l in lote]
        linhas += ["", "```bash", "cd /home/sytw/Projetos/techdigest-teste-feeds", comando_do_lote(numero, lote, agora),
                   "```", ""]
    caminho = pasta / "lotes.md"
    caminho.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")
    return caminho


# ── Etapa 2: a leitura das simulações ─────────────────────────────────────────────────────

# As mensagens do log que a leitura usa (collectors/rss.py e pipeline.py), depois do "│ " do formato do logging_setup.
_FEED_OK = re.compile(r"│ Feed OK: (?P<n>\d+) entrada\(s\) — (?P<titulo>.*?)"
                      r"(?: \(fora do prazo de \d+ dia\(s\): \d+ antiga\(s\), \d+ sem data\))?$")
_DESCARTADO = re.compile(r"│ Item descartado \(texto insuficiente: \d+ caracteres, mínimo \d+\): ")
PROBLEMA_DE_NUMERO = "número que os textos da pauta não trazem"     # o começo do texto em qa.problemas_dos_numeros
_PROBLEMA_DE_NUMERO = re.compile(r'^número que os textos da pauta não trazem, (?P<onde>.*?) \("(?P<dito>.*?)"'
                                 r'(?:; a pauta traz (?P<traz>[^)]*))?\): use o número da fonte')
_FALHA = re.compile(r"^falhou \((?P<tipo>\w+)")


@dataclass
class DoFeed:
    """O que as execuções dizem de um feed."""
    url: str
    nome: str = ""
    categoria: str = ""
    subcategoria: str = ""
    coletados: int = 0
    fora: list[str] = field(default_factory=list)
    filtrados: int = 0
    gerados: int = 0
    aprovados: int = 0
    reprovados: int = 0
    falhas: int = 0
    entregues: int = 0
    numero_na_primeira: int = 0        # episódios cuja primeira versão teve problema de número
    reprovados_por_numero: int = 0
    reprovados_por_veiculo: int = 0
    reprovados_por_outro: int = 0
    reprovacoes: list[tuple[bool, bool]] = field(default_factory=list)   # por reprovado: (número do formato da fonte,
                                                                         # problema de veículo)
    nome_bate: bool = True             # o nome do feed bateu na etapa 1 (coluna nome_bate)
    falhas_por_tipo: collections.Counter[str] = field(default_factory=collections.Counter)   # pelo tipo do erro
    do_formato: list[str] = field(default_factory=list)       # as reprovações por número do formato da fonte
    numeros: list[str] = field(default_factory=list)          # todo problema de número, para o relatório
    fontes_citadas: collections.Counter[str] = field(default_factory=collections.Counter)

    @property
    def contra_o_feed(self) -> int:
        """Os gerados que contam contra o feed (regra (b) do dono, 20/11/2026): as falhas (o texto, como o
        JanelaExcedida) e as reprovações por um problema da fonte, o número do formato da fonte ou o veículo. O problema
        de veículo não conta quando o nome do feed não bateu na etapa 1 (título genérico ou em ideogramas: vai para a
        pendência do nome fixo, decisão de 20/11). As reprovações pelas regras gerais do QA (palavras, analistas,
        ressalvas) não contam: com 2 ou 3 itens por feed, uma delas derrubava o feed (o Olhar Digital do lote 1)."""
        return self.falhas + sum(1 for formato, veiculo in self.reprovacoes if formato or (veiculo and self.nome_bate))

    def veredito(self) -> tuple[str, str]:
        """2 ou mais gerados, 80% ou mais deles sem nada contra o feed (`contra_o_feed`) e nenhuma reprovação por número
        do formato da fonte."""
        if self.gerados < MIN_GERADOS:
            return REPROVADO, f"{self.gerados} item(ns) gerado(s), menos de {MIN_GERADOS}"
        motivos = []
        limpos = self.gerados - self.contra_o_feed
        if limpos < FRACAO_SEM_PROBLEMA_DA_FONTE * self.gerados:
            motivos.append(f"{limpos} de {self.gerados} sem falha nem reprovação pela fonte ({limpos / self.gerados:.0%}), "
                           f"menos de {FRACAO_SEM_PROBLEMA_DA_FONTE:.0%}")
        if self.do_formato:
            motivos.append("reprovação por número do formato da fonte: " + "; ".join(self.do_formato))
        return (REPROVADO, "; ".join(motivos)) if motivos else (APROVADO, "")


def _algarismos(texto: str) -> str:
    """Os algarismos significativos ("1.5 billion" e 1500000000 dão "15")."""
    return re.sub(r"\D", "", texto).strip("0")


def trechos_estrangeiros(texto: str) -> list[str]:
    """As expressões com escala que ai/numeros.py não lê e os formatos de algarismo de outros idiomas."""
    trechos = [trecho for trecho, _ in casos_de_escala(texto)]
    for padrao in FORMATOS_DE_ALGARISMO.values():
        trechos += [m.group() for m in padrao.finditer(texto)]
    return trechos


def formato_da_fonte(dito: str, textos: Iterable[str]) -> str:
    """O trecho da fonte, num formato que ai/numeros.py não lê, com os algarismos significativos de um número que o
    episódio disse ("1,5 bilhão" e "1.5 billion"); vazio se nenhum. É uma pista, para conferir à mão."""
    ditos = {_algarismos(f"{n.valor:f}") for n in numeros(unicodedata.normalize("NFC", dito)) if pede_fonte(n)} - {""}
    for texto in textos:
        for trecho in trechos_estrangeiros(texto):
            if _algarismos(trecho) in ditos:
                return trecho
    return ""


def ler_execucoes(pasta: Path) -> list[tuple[Path, dict, dict]]:
    """A pasta, a amostra e o relatório de cada execução registrada: `pasta` é a de uma simulação (com `execucoes/`) ou
    a EXECUCOES_DIR da produção. Só leitura."""
    base = pasta / "execucoes" if (pasta / "execucoes").is_dir() else pasta
    execucoes = []
    for relatorio in sorted(base.glob("*/relatorio_*.json")):
        try:
            dados = json.loads(relatorio.read_text(encoding="utf-8"))
            amostra = json.loads((relatorio.parent / "amostra.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        execucoes.append((relatorio.parent, amostra, dados))
    return execucoes


def linhas_do_log(pasta_de_logs: Path) -> list[str]:
    """As linhas do log rotativo, do arquivo mais antigo (techdigest.log.7) ao atual."""
    antigos = [a for a in pasta_de_logs.glob("techdigest.log.*") if a.suffix[1:].isdigit()]
    linhas: list[str] = []
    for arquivo in [*sorted(antigos, key=lambda a: -int(a.suffix[1:])), pasta_de_logs / "techdigest.log"]:
        if arquivo.is_file():
            linhas += arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
    return linhas


def _do_feed(feeds: dict[str, DoFeed], url: str) -> DoFeed:
    return feeds.setdefault(url, DoFeed(url))


def _dito(problema: str) -> tuple[str, str, str]:
    """O número dito, o que a pauta traz e onde ("no resumo", "na fala de Helena"), do texto de um problema de número do
    QA."""
    achado = _PROBLEMA_DE_NUMERO.match(problema)
    return (achado["dito"], achado["traz"] or "", achado["onde"]) if achado else (problema, "", "")


def contar_episodios(feeds: dict[str, DoFeed], execucoes: list[tuple[Path, dict, dict]]) -> None:
    """Gerados, aprovados, reprovados (os de número e de veículo à parte), falhas e entregues de cada feed, pelo `feed` de
    cada artigo na amostra; e cada problema de número, com a pista do formato da fonte."""
    for _, amostra, relatorio in execucoes:
        por_id = {c.get("id"): c for c in amostra.get("candidatos") or []}
        for episodio in relatorio.get("episodios") or []:
            artigos = [por_id[a["id"]] for a in episodio.get("artigos") or [] if a.get("id") in por_id]
            if not artigos:
                continue
            f = _do_feed(feeds, str(artigos[0].get("feed") or ""))
            situacao = str(episodio.get("situacao") or "")
            f.gerados += 1
            f.entregues += bool(episodio.get("entregue"))
            if situacao == "aprovado":
                f.aprovados += 1
            elif situacao.startswith("reprovado"):
                f.reprovados += 1
            else:
                f.falhas += 1
                f.falhas_por_tipo[achado["tipo"] if (achado := _FALHA.match(situacao)) else situacao[:40]] += 1
            textos = [f"{a.get('titulo', '')}\n{a.get('texto', '')}" for a in artigos]
            titulo = episodio.get("titulo") or artigos[0].get("titulo", "")
            primeira = [str(p) for p in episodio.get("problemas_antes_da_revisao") or []]
            depois = episodio.get("problemas_depois_da_revisao")
            final = primeira if depois is None else [str(p) for p in depois]
            if any(p.startswith(PROBLEMA_DE_NUMERO) for p in primeira):
                f.numero_na_primeira += 1
            versoes = [("primeira versão", primeira)] + ([("versão final", final)] if depois is not None else [])
            for versao, problemas in versoes:
                for problema in problemas:
                    if problema.startswith(PROBLEMA_DE_NUMERO):
                        dito, traz, onde = _dito(problema)
                        pista = formato_da_fonte(dito, textos)
                        f.numeros.append(f"{titulo} ({situacao.split(' (')[0]}, {versao}, {onde}): \"{dito}\""
                                         + (f"; a pauta traz {traz}" if traz else "")
                                         + (f"; na fonte: {pista!r}" if pista else ""))
            if situacao.startswith("reprovado"):
                de_numero = [p for p in final if p.startswith(PROBLEMA_DE_NUMERO)]
                de_veiculo = [p for p in final if "fontes_citadas" in p or "veículo" in p]
                f.reprovados_por_numero += bool(de_numero)
                f.reprovados_por_veiculo += bool(de_veiculo)
                f.reprovados_por_outro += len(final) > len(de_numero) + len(de_veiculo)
                do_formato = False
                for problema in de_numero:
                    dito, _, _ = _dito(problema)
                    if pista := formato_da_fonte(dito, textos):
                        f.do_formato.append(f"\"{dito}\" ({pista!r} na fonte)")
                        do_formato = True
                f.reprovacoes.append((do_formato, bool(de_veiculo)))
            try:
                gravado = json.loads(Path(str(episodio.get("arquivo"))).read_text(encoding="utf-8"))
                citadas = gravado.get("fontes_citadas") or []
                f.fontes_citadas.update(str(c) for c in (citadas if isinstance(citadas, list) else [citadas]))
            except (OSError, ValueError, AttributeError):
                pass


@dataclass
class DaSimulacao:
    pasta: str
    execucoes: int = 0
    coletados: int = 0
    filtrados: int = 0
    texto_curto: int = 0
    gerados: int = 0
    aprovados: int = 0
    entregues: int = 0
    feeds: list[str] = field(default_factory=list)     # os do lote, casados pela etapa 1
    sem_casar: list[str] = field(default_factory=list)


def ler_simulacao(pasta: Path, etapa1: list[dict], feeds: dict[str, DoFeed]) -> DaSimulacao:
    """Soma em `feeds` o que uma simulação diz de cada feed do lote: os coletados pelas linhas "Feed OK" do log, casadas
    pelo título que a etapa 1 anotou (um feed que cai muda a ordem do log, decisão do dono de 20/11/2026); os que ficaram
    fora, pelo relatório; os filtrados, pelos hosts dos links que a etapa 1 viu em cada feed (o feed da Sixth Tone está
    em api.sixthtone.com, as matérias não); e os episódios (`contar_episodios`). Só leitura."""
    sim = DaSimulacao(str(pasta))
    execucoes = ler_execucoes(pasta)
    sim.execucoes = len(execucoes)
    da_amostra = {str(c.get("feed")) for _, amostra, _ in execucoes for c in amostra.get("candidatos") or []}
    linhas_por_url = {linha["url"]: linha for linha in etapa1}
    por_titulo: dict[str, list[dict]] = {}
    for linha in etapa1:
        por_titulo.setdefault(linha["titulo_do_feed"] or linha["url"], []).append(linha)
    do_lote: dict[str, dict] = {}
    for texto in linhas_do_log(pasta / "logs"):
        if achado := _FEED_OK.search(texto):
            candidatos = por_titulo.get(achado["titulo"], [])
            if len(candidatos) > 1:
                candidatos = [c for c in candidatos if c["url"] in da_amostra] or candidatos
            if len(candidatos) != 1:
                sim.sem_casar.append(f"\"Feed OK\" de {achado['titulo']!r}: " + (
                    "o título de mais de um feed da etapa 1" if candidatos else "um título que a etapa 1 não anotou"))
                continue
            do_lote[candidatos[0]["url"]] = candidatos[0]
            _do_feed(feeds, candidatos[0]["url"]).coletados += int(achado["n"])
            sim.coletados += int(achado["n"])
        elif _DESCARTADO.search(texto):
            sim.texto_curto += 1
    for _, _, relatorio in execucoes:
        for fora in (relatorio.get("feeds") or {}).get("fora") or []:
            url = str(fora.get("url"))
            _do_feed(feeds, url).fora.append(str(fora.get("erro")))
            if url in linhas_por_url:
                do_lote[url] = linhas_por_url[url]
    for url in da_amostra:
        if url in linhas_por_url:
            do_lote[url] = linhas_por_url[url]
    for _, _, relatorio in execucoes:
        for filtrado in relatorio.get("filtrados") or []:
            host = _host(str(filtrado.get("url") or ""))
            donos = [url for url, linha in do_lote.items() if host in linha["hosts"].split()]
            sim.filtrados += 1
            if len(donos) == 1:
                _do_feed(feeds, donos[0]).filtrados += 1
            else:
                sim.sem_casar.append(f"filtrado {filtrado.get('url')}: o host {host} é de "
                                     + (f"{len(donos)} feeds do lote" if donos else "nenhum feed do lote"))
    antes = {url: (f.gerados, f.aprovados, f.entregues) for url, f in feeds.items()}
    contar_episodios(feeds, execucoes)
    for url, f in feeds.items():
        gerados, aprovados, entregues = antes.get(url, (0, 0, 0))
        sim.gerados += f.gerados - gerados
        sim.aprovados += f.aprovados - aprovados
        sim.entregues += f.entregues - entregues
    sim.feeds = list(do_lote)
    return sim


def _rotulo(url: str) -> str:
    """O feed numa linha curta: o host e, numa busca do Google Notícias, o que ela busca."""
    partes = urlsplit(url)
    busca = re.search(r"(?:^|&)q=([^&]*)", partes.query)
    return f"{partes.netloc} ({busca.group(1)})" if busca else (partes.netloc or url)


def _linha_de_feed(f: DoFeed, com_veredito: bool) -> list:
    reprovados = f"{f.reprovados}" + (f" ({f.reprovados_por_numero} / {f.reprovados_por_veiculo} / "
                                      f"{f.reprovados_por_outro})" if f.reprovados else "")
    partes = [f"{f.aprovados / f.gerados:.0%}"] if f.gerados else []
    if f.falhas and f.aprovados + f.reprovados:   # a falha não é do QA (na produção de 05/11, o 403 do Edge-TTS)
        partes.append(f"{f.aprovados / (f.aprovados + f.reprovados):.0%} dos julgados pelo QA")
    taxa = f" ({'; '.join(partes)})" if partes else ""
    falhas = f"{f.falhas}" + (f" ({', '.join(f'{tipo} {n}' for tipo, n in f.falhas_por_tipo.most_common())})"
                              if f.falhas else "")
    citadas = "; ".join(f"{nome} ({n})" for nome, n in f.fontes_citadas.most_common(3))
    linha: list = [f.nome or _rotulo(f.url)]
    if com_veredito:
        veredito, motivo = f.veredito()
        linha += [veredito, motivo, f.coletados, f.filtrados]
    linha += [f.gerados, f"{f.aprovados}{taxa}", reprovados, falhas, f.numero_na_primeira, citadas]
    if com_veredito:
        linha.append("; ".join(f.fora))
    return linha


def escrever_etapa2(simulacoes: list[DaSimulacao], feeds: dict[str, DoFeed], etapa1: list[dict], caminho: Path,
                    agora: datetime.datetime, csv_da_etapa1: Path,
                    producao: tuple[str, dict[str, DoFeed], str] | None) -> None:
    do_lote = [url for sim in simulacoes for url in sim.feeds]
    linhas_por_url = {linha["url"]: linha for linha in etapa1}
    for url in do_lote:
        linha, f = linhas_por_url[url], feeds[url]
        f.nome, f.categoria, f.subcategoria = linha["nome"], linha["categoria"], linha["subcategoria"]
        f.nome_bate = linha.get("nome_bate") != "não"
    contagem = collections.Counter(feeds[url].veredito()[0] for url in do_lote)
    linhas = [
        f"# Feeds candidatos: etapa 2 ({agora:%d/%m/%Y %H:%M})", "",
        f"A leitura das simulações (`scripts/testar_feeds.py --simulacao`), com a etapa 1 de `{csv_da_etapa1}`. "
        f"Veredito: APROVADO com {MIN_GERADOS} ou mais itens gerados, {FRACAO_SEM_PROBLEMA_DA_FONTE:.0%} ou mais deles sem "
        "falha nem reprovação pela fonte e nenhuma reprovação por número do formato da fonte (regra (b) do dono, "
        "20/11/2026). Contam contra o feed as falhas (o texto) e as reprovações por número do formato da fonte ou por "
        "veículo; o veículo não conta quando o nome do feed não bateu na etapa 1 (vai para a pendência do nome fixo), e "
        "as reprovações pelas regras gerais do QA (palavras, analistas, ressalvas) ficam na tabela sem contar. A pista do "
        "formato da fonte é um trecho da fonte, num formato que ai/numeros.py não lê, com os mesmos algarismos "
        "significativos do número dito: confira à mão.", "",
        "## Simulações", "",
        "| Pasta | Execuções | Feeds do lote | Coletados | Filtrados | Texto curto | Gerados | Aprovados | Entregues |",
        "|---|---|---|---|---|---|---|---|---|",
        *("| " + " | ".join(_celula(x) for x in (sim.pasta, sim.execucoes, len(sim.feeds), sim.coletados, sim.filtrados,
                                                  sim.texto_curto, sim.gerados, sim.aprovados, sim.entregues)) + " |"
          for sim in simulacoes), "",
    ]
    for sim in simulacoes:
        if sim.sem_casar:
            linhas += [f"Sem casar em `{sim.pasta}`:", *(f"- {s}" for s in sim.sem_casar), ""]
    linhas += ["Vereditos: " + ", ".join(f"{v} {contagem[v]}" for v in (APROVADO, REPROVADO)) + f" (de {len(do_lote)}).",
               ""]
    grupos: dict[tuple[str, str], list[DoFeed]] = {}
    for url in do_lote:
        grupos.setdefault((feeds[url].categoria, feeds[url].subcategoria), []).append(feeds[url])
    for (categoria, subcategoria), do_grupo in grupos.items():
        linhas += [f"## {categoria}: {subcategoria}", "",
                   "| Nome | Veredito | Motivo | Coletados | Filtrados | Gerados | Aprovados | Reprovados (número / "
                   "veículo / outro) | Falhas | Número na 1ª versão | Fontes citadas | Fora da coleta |",
                   "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        linhas += ["| " + " | ".join(_celula(x) for x in _linha_de_feed(f, True)) + " |" for f in do_grupo]
        linhas.append("")
    com_numeros = [feeds[url] for url in do_lote if feeds[url].numeros]
    if com_numeros:
        linhas += ["## Problemas de número", ""]
        for f in com_numeros:
            linhas += [f"### {f.nome}", *(f"- {n}" for n in f.numeros), ""]
    if producao is not None:
        pasta, da_producao, periodo_da_producao = producao
        linhas += ["## Feeds de hoje nas execuções reais", "",
                   f"Os mesmos números, das execuções em `{pasta}` ({periodo_da_producao}), pelo feed de cada artigo.", "",
                   "| Feed | Gerados | Aprovados | Reprovados (número / veículo / outro) | Falhas | Número na 1ª versão | "
                   "Fontes citadas |", "|---|---|---|---|---|---|---|"]
        linhas += ["| " + " | ".join(_celula(x) for x in _linha_de_feed(f, False)) + " |"
                   for f in sorted(da_producao.values(), key=lambda f: -f.gerados)]
        linhas.append("")
    caminho.write_text("\n".join(linhas).rstrip() + "\n", encoding="utf-8")


def periodo_das_execucoes(execucoes: list[tuple[Path, dict, dict]]) -> str:
    datas = []
    for pasta, _, _ in execucoes:
        try:
            datas.append(datetime.datetime.strptime(pasta.name[:15], FORMATO_DA_PASTA))
        except ValueError:
            pass
    if not datas:
        return f"{len(execucoes)} execução(ões)"
    return f"{len(execucoes)} execução(ões), de {min(datas):%d/%m/%Y} a {max(datas):%d/%m/%Y}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Testa os feeds candidatos ao config/feeds.txt: a etapa 1, sem o modelo; com "
                                            "--lotes, os lotes da etapa 2; com --simulacao, a leitura da etapa 2.")
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--lotes", action="store_true",
                      help="etapa 2: monta os lotes dos APROVADO, AJUSTE e ETAPA 2 da etapa 1 e mostra o comando de cada um")
    modo.add_argument("--simulacao", nargs="+", metavar="PASTA",
                      help="etapa 2: lê as pastas de simulação dos lotes (só leitura) e escreve o etapa2.md")
    p.add_argument("--candidatos", default=str(CAMINHO_DOS_CANDIDATOS), help="etapa 1: o arquivo dos candidatos")
    p.add_argument("--pasta", help="a pasta da saída (padrão: data/agrupamento/feeds_<AAAAMMDD>; na etapa 2, a do "
                                   "etapa1.csv)")
    p.add_argument("--registros", help="etapa 1: a pasta das execuções da produção, para o critério 9 "
                                       "(padrão: EXECUCOES_DIR)")
    p.add_argument("--pausa", type=float, default=PAUSA_S, help=f"etapa 1: segundos entre requisições (padrão: {PAUSA_S:g})")
    p.add_argument("--etapa1", metavar="CSV", help="etapa 2: o etapa1.csv (padrão: o mais recente de "
                                                   "data/agrupamento/feeds_*)")
    p.add_argument("--producao", metavar="EXECUCOES_DIR",
                   help="com --simulacao: as execuções reais, para comparar com os feeds de hoje (só leitura)")
    p.add_argument("--por-lote", type=int, default=POR_LOTE, help=f"com --lotes: feeds por lote (padrão: {POR_LOTE})")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    agora = datetime.datetime.now()
    if args.lotes or args.simulacao:
        csv_da_etapa1 = Path(args.etapa1) if args.etapa1 else etapa1_mais_recente(config.BASE_DIR / "data" / "agrupamento")
        if csv_da_etapa1 is None or not csv_da_etapa1.is_file():
            p.error("não achei o etapa1.csv: passe --etapa1 <arquivo>")
        etapa1 = ler_etapa1(csv_da_etapa1)
        pasta = Path(args.pasta or csv_da_etapa1.parent)
        if args.lotes:
            lotes = montar_lotes(etapa1, args.por_lote)
            caminho = escrever_lotes(lotes, pasta, agora)
            for numero, lote in enumerate(lotes, 1):
                print(f"Lote {numero} ({len(lote)} feeds): {', '.join(l['nome'] for l in lote)}\n"
                      f"{comando_do_lote(numero, lote, agora)}\n")
            print(caminho)
            return 0
        feeds: dict[str, DoFeed] = {}
        simulacoes = [ler_simulacao(Path(s), etapa1, feeds) for s in args.simulacao]
        producao = None
        if args.producao:
            da_producao: dict[str, DoFeed] = {}
            execucoes = ler_execucoes(Path(args.producao))
            contar_episodios(da_producao, execucoes)
            producao = (args.producao, da_producao, periodo_das_execucoes(execucoes))
        escrever_etapa2(simulacoes, feeds, etapa1, pasta / "etapa2.md", agora, csv_da_etapa1, producao)
        print(pasta / "etapa2.md")
        return 0

    candidatos = ler_candidatos(args.candidatos)
    atuais = config.ler_feeds()
    pasta_dos_registros = Path(args.registros or rss.settings.execucoes_dir)
    registros = ler_registros(pasta_dos_registros) if pasta_dos_registros.is_dir() else None
    pasta = Path(args.pasta or config.BASE_DIR / "data" / "agrupamento" / f"feeds_{agora:%Y%m%d}")
    pasta.mkdir(parents=True, exist_ok=True)

    resultados = testar(candidatos, Rede(pausa_s=args.pausa), atuais, registros)
    escrever_csv(resultados, pasta / "etapa1.csv")
    escrever_md(resultados, pasta / "etapa1.md", cabecalho(agora, args.candidatos, atuais, registros, args.pausa))
    escrever_textos(resultados, pasta / "etapa1_textos.json")
    print(f"\n{pasta / 'etapa1.md'}\n{pasta / 'etapa1.csv'}\n{pasta / 'etapa1_textos.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""O filtro de esporte, ofertas e sites de partido, com o agrupamento ligado ou desligado (fase 4).

Decisões do dono de 16, 17 e 25/10/2026:
- esporte e ofertas pela seção da URL e pela categoria do feed, nunca pelo título ("agenda" aparece em manchete de fato
  único, e notícia de preço não se separa de oferta por palavras);
- sites de partido por uma lista de domínios, `config/sites_de_partido.txt`, aplicada à URL final, depois de resolver o
  link do Google Notícias; cada domínio vale também para os subdomínios. O pt.org.br entrou como veículo "Partido dos
  Trabalhadores" numa pauta da amostra de 12/10, e o episódio atribuiu ao PT, como veículo, um relatório que o site não
  menciona.

A seção é o primeiro segmento do caminho da URL, como na medida de 16/10 (`data/agrupamento/filtros_20261016.txt`:
esporte 12 de 12 e ofertas 16 de 21 nas duas amostras, nenhum falso positivo; ficaram de fora notícias de preço do
Canaltech, em seções de assunto, que a categoria também não pega, porque o Canaltech não manda categoria). A categoria
do feed (<category>) entra por uma lista fechada, comparada sem acento, sem caixa e sem espaço repetido.

O link do Google Notícias só mostra o site depois de resolvido. Por isso o pipeline usa o filtro duas vezes: antes da
extração, com o link do feed e a categoria, o que não custa uma extração; e depois dela, com a URL resolvida.
"""
import functools
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from techdigest.config import BASE_DIR

CAMINHO_DOS_SITES_DE_PARTIDO = BASE_DIR / "config" / "sites_de_partido.txt"

SECOES_DE_ESPORTE = frozenset({"esporte", "esportes"})
SECOES_DE_OFERTAS = frozenset({"achados", "hardware-indica", "ofertas"})
SITES_DE_ESPORTE = ("ge.globo.com", "lance.com.br", "goal.com", "cbf.com.br")   # o site inteiro é de esporte
# A categoria do feed, sem acento nem caixa, e o que ela marca. O Hardware.com.br manda "Hardware Indica", a mesma seção
# que a URL já mostra; o Tecnoblog manda só etiquetas de assunto; o Canaltech e o Google Notícias não mandam nenhuma.
CATEGORIAS = {"esporte": "esporte", "esportes": "esporte", "ofertas": "ofertas", "achados": "ofertas",
              "hardware indica": "ofertas"}
_DOMINIO = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def _dobrar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def ler_sites_de_partido(caminho: str | Path = CAMINHO_DOS_SITES_DE_PARTIDO) -> tuple[str, ...]:
    """Os domínios do arquivo, em minúsculas e sem "www.": um por linha, com o que vem depois de "#" como comentário.

    Uma linha que não é um domínio ("https://...", um caminho, um espaço no meio) levanta ValueError com o número dela:
    um erro de digitação na lista não pode deixar um site de partido passar calado.
    """
    dominios = []
    for numero, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        dominio = linha.split("#", 1)[0].strip().lower().removeprefix("www.")
        if not dominio:
            continue
        if not _DOMINIO.match(dominio):
            raise ValueError(f"{caminho}, linha {numero}: {dominio!r} não é um domínio (um por linha, sem https:// nem caminho)")
        dominios.append(dominio)
    return tuple(dominios)


@functools.cache
def sites_de_partido() -> tuple[str, ...]:
    """A lista de `config/sites_de_partido.txt`, lida uma vez por processo."""
    return ler_sites_de_partido()


def _no_site(dominio: str, sites: Iterable[str]) -> str:
    """O site da lista que contém o domínio (ele mesmo ou um subdomínio dele); vazio se nenhum."""
    return next((s for s in sites if dominio == s or dominio.endswith("." + s)), "")


def pela_url(url: str, partidos: Iterable[str] | None = None) -> str:
    """Por que a URL fica fora ("site de partido (pt.org.br)", "esporte: seção /esportes/"...); vazio se ela segue.

    `partidos` troca a lista do arquivo (nos testes).
    """
    partes = urlsplit(url.strip())
    dominio = (partes.hostname or "").removeprefix("www.")
    if not dominio:
        return ""
    if site := _no_site(dominio, sites_de_partido() if partidos is None else partidos):
        return f"site de partido ({site})"
    if site := _no_site(dominio, SITES_DE_ESPORTE):
        return f"esporte: site {site}"
    secao = partes.path.strip("/").split("/")[0].lower()
    if secao in SECOES_DE_ESPORTE:
        return f"esporte: seção /{secao}/"
    if secao in SECOES_DE_OFERTAS:
        return f"ofertas: seção /{secao}/"
    return ""


def pela_categoria(categorias: Iterable[str]) -> str:
    """Por que a categoria do feed tira o item ("ofertas: categoria Hardware Indica"); vazio se nenhuma tira."""
    for categoria in categorias:
        if tipo := CATEGORIAS.get(_dobrar(categoria)):
            return f"{tipo}: categoria {categoria}"
    return ""


def motivo_do_filtro(url: str, categorias: Iterable[str] = (), partidos: Iterable[str] | None = None) -> str:
    """Por que o item fica fora da execução, pela URL e pela categoria do feed; vazio se ele segue. Nunca pelo título."""
    return pela_url(url, partidos) or pela_categoria(categorias)

import contextlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse

import trafilatura

from techdigest.config import Settings

logger = logging.getLogger("techdigest.processing.extractor")

settings = Settings()

_avisou_sem_decoder = False


def _eh_google(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host == "news.google.com" or host.endswith(".google.com") or host == "google.com"


def _resolver_google_news(url: str) -> str | None:
    """Link do Google Notícias -> URL do veículo (None se não for possível resolver)."""
    global _avisou_sem_decoder
    try:
        from googlenewsdecoder import gnewsdecoder
    except Exception as e:  # não instalado OU instalado mas quebrado (ex.: dependência incompatível)
        if not _avisou_sem_decoder:
            logger.warning(
                "googlenewsdecoder indisponível (%s: %s): itens do Google Notícias ficam sem texto.",
                type(e).__name__, str(e)[:150],
            )
            _avisou_sem_decoder = True
        return None
    try:
        r = gnewsdecoder(url, interval=1)
    except Exception as e:
        logger.warning("Falha ao resolver link do Google Notícias (%s: %s)", type(e).__name__, str(e)[:120])
        return None
    # A API mudou entre versões: a 0.1.x devolve {'status': True, 'decoded_url': ...}; a 0.2.x
    # não traz 'status'. O critério estável é existir uma URL http(s) em 'decoded_url'.
    decodificada = r.get("decoded_url") if isinstance(r, dict) else None
    if isinstance(decodificada, str) and decodificada.startswith(("http://", "https://")):
        return decodificada
    logger.info("Link do Google Notícias não resolvido: %s", str(r)[:150])
    return None


@dataclass(frozen=True)
class Extracao:
    """Resultado da extração de um item."""
    texto: str            # texto da matéria, ou o fallback quando não foi possível extrair
    url_resolvida: str    # URL da matéria no veículo; "" se o link do Google Notícias não resolveu
    extraido: bool        # False = `texto` é o fallback


def _extrair(url: str, fallback: str = "", limite_gnews=None) -> Extracao:
    """Extrai uma matéria. `limite_gnews` é o semáforo do lote para as resoluções no Google Notícias."""
    alvo = url
    if _eh_google(url):
        # Nunca roda o trafilatura em link do Google: ele cai na página de consentimento
        # e devolveria texto de cookies no lugar da matéria.
        if not settings.gnews_resolver:
            return Extracao(fallback, "", False)
        with limite_gnews or contextlib.nullcontext():
            alvo = _resolver_google_news(url)
        if not alvo or _eh_google(alvo):
            return Extracao(fallback, "", False)
        logger.info("Google Notícias → %s", urlparse(alvo).netloc)

    html = trafilatura.fetch_url(alvo)
    if html:
        text = trafilatura.extract(html, include_comments=False)
        if text:
            return Extracao(text, alvo, True)
    return Extracao(fallback, alvo, False)


def extract_full_text(url: str, fallback: str = "") -> str:
    return _extrair(url, fallback).texto


def extrair_em_lote(
    itens: list[tuple[str, str]], workers: int | None = None, workers_gnews: int | None = None,
) -> list[Extracao]:
    """Extrai vários itens em paralelo e devolve, na mesma ordem, o texto e a URL resolvida de cada um.

    `itens` são pares (url, fallback). São até `workers` extrações simultâneas (EXTRACAO_WORKERS),
    mas no máximo `workers_gnews` (EXTRACAO_WORKERS_GNEWS) resolvendo links do Google Notícias ao
    mesmo tempo, para não provocar bloqueio. O limite cobre só a resolução: o download da página
    do veículo acontece fora dele. Um item que falha devolve o fallback e não derruba o lote.
    """
    limite_gnews = threading.BoundedSemaphore(max(1, workers_gnews or settings.extracao_workers_gnews))

    def _um(item: tuple[str, str]) -> Extracao:
        url, fallback = item
        try:
            return _extrair(url, fallback, limite_gnews)
        except Exception as e:
            logger.warning("Extração falhou (%s: %s): %s", type(e).__name__, str(e)[:120], url)
            return Extracao(fallback, "", False)

    with ThreadPoolExecutor(max_workers=max(1, workers or settings.extracao_workers)) as pool:
        return list(pool.map(_um, itens))
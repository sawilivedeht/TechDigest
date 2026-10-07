import logging
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


def extract_full_text(url: str, fallback: str = "") -> str:
    alvo = url
    if _eh_google(url):
        # Nunca roda o trafilatura em link do Google: ele cai na página de consentimento
        # e devolveria texto de cookies no lugar da matéria.
        if not settings.gnews_resolver:
            return fallback
        alvo = _resolver_google_news(url)
        if not alvo or _eh_google(alvo):
            return fallback
        logger.info("Google Notícias → %s", urlparse(alvo).netloc)

    html = trafilatura.fetch_url(alvo)
    if html:
        text = trafilatura.extract(html, include_comments=False)
        if text:
            return text
    return fallback
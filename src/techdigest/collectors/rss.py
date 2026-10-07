import calendar
import html
import logging
import re
import time

import feedparser
import requests

from techdigest.config import Settings
from techdigest.models import Article

logger = logging.getLogger("techdigest.collectors.rss")

settings = Settings()

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TechDigest/0.1"}


def _texto_puro(valor: str) -> str:
    """Tira tags e entidades do summary do RSS: o fallback do extractor não pode ser markup."""
    sem_tags = re.sub(r"<[^>]+>", " ", valor or "")
    return re.sub(r"\s+", " ", html.unescape(sem_tags)).strip()


def _titulo_e_veiculo(entry, titulo: str, nome_do_feed: str) -> tuple[str, str]:
    """Google Notícias: o veículo real vem em <source> (e como sufixo ' - Veículo' no título)."""
    veiculo = (entry.get("source") or {}).get("title")
    if not veiculo:
        return titulo, nome_do_feed
    sufixo = f" - {veiculo}"
    return (titulo[: -len(sufixo)] if titulo.endswith(sufixo) else titulo), veiculo


def _idade_dias(entry) -> float | None:
    """Idade da notícia em dias pela data do feed (published, senão updated); None se não houver data.

    O feedparser já entrega essas datas normalizadas em UTC.
    """
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return max(0.0, (time.time() - calendar.timegm(t)) / 86400)


def _baixar_feed(feed_url: str):
    # feedparser.parse(url) não tem timeout: um servidor mudo travaria a execução inteira.
    resp = requests.get(feed_url, headers=_HEADERS, timeout=settings.feed_timeout_s)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def collect_rss(feeds: list[str] | None = None) -> list[Article]:
    limite_dias = settings.max_idade_dias
    por_feed: list[list[Article]] = []
    for feed_url in feeds or settings.feeds:      # ⬅️ .env = fonte de verdade
        try:
            parsed = _baixar_feed(feed_url)
        except Exception as e:
            logger.warning("Feed inacessível (%s: %s): %s", type(e).__name__, str(e)[:100], feed_url)
            continue
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed sem entradas (verifique a URL): %s", feed_url)
            continue

        nome_do_feed = parsed.feed.get("title", feed_url)
        artigos, antigas, sem_data = [], 0, 0
        # Filtra a idade ANTES de aplicar o MAX_POR_FEED: o limite vale para notícias dentro do prazo
        # (o Google Notícias ordena por relevância, não por data).
        for entry in parsed.entries:
            if limite_dias:
                idade = _idade_dias(entry)
                if idade is None:
                    sem_data += 1
                    continue
                if idade > limite_dias:
                    antigas += 1
                    continue
            if len(artigos) >= settings.max_por_feed:
                continue  # segue só contando as descartadas, para o log
            titulo, veiculo = _titulo_e_veiculo(entry, entry.get("title", ""), nome_do_feed)
            artigos.append(Article(
                title=titulo,
                url=entry.get("link", ""),
                summary=_texto_puro(entry.get("summary", "")),
                source=veiculo,
            ))
        fora = ""
        if antigas or sem_data:
            fora = f" (fora do prazo de {limite_dias} dia(s): {antigas} antiga(s), {sem_data} sem data)"
        logger.info("Feed OK: %d entrada(s) — %s%s", len(artigos), nome_do_feed, fora)
        por_feed.append(artigos)

    # Intercala os feeds (1º de cada um, depois o 2º de cada um...) para que o limite
    # MAX_NEWS não seja consumido só pelos primeiros feeds (regra 1: boletim duplo).
    # Também descarta URLs repetidas entre feeds.
    vistos: set[str] = set()
    articles: list[Article] = []
    for i in range(max((len(f) for f in por_feed), default=0)):
        for artigos in por_feed:
            if i < len(artigos) and artigos[i].url and artigos[i].url not in vistos:
                vistos.add(artigos[i].url)
                articles.append(artigos[i])
    return articles
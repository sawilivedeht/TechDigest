import feedparser

from techdigest.config import Settings
from techdigest.models import Article

import logging
logger = logging.getLogger("techdigest.collectors.rss")

settings = Settings()


def collect_rss(feeds: list[str] | None = None) -> list[Article]:
    articles = []
    for feed_url in feeds or settings.feeds:      # ⬅️ .env = fonte de verdade
        parsed = feedparser.parse(feed_url)
        if not parsed.bozo or parsed.entries:
            for entry in parsed.entries[:15]:
                articles.append(Article(
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    summary=entry.get("summary", ""),
                    source=parsed.feed.get("title", feed_url),
                ))
        else:
            print(f"  feed sem entradas (verifique a URL): {feed_url}")
    return articles
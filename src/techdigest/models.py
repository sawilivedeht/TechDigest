from dataclasses import dataclass
from datetime import datetime
import logging
logger = logging.getLogger("techdigest.models")

@dataclass
class Article:
    title: str
    url: str
    summary: str = ""
    source: str = ""
    published: datetime | None = None
    feed: str = ""                       # a URL do feed de onde o artigo veio (o da primeira aparição no intercalado)
    categorias: tuple[str, ...] = ()     # as categorias da entrada no feed (<category>), como o feed as escreve

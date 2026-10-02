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
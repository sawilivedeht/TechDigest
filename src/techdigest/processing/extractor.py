import trafilatura

import logging
logger = logging.getLogger("techdigest.<submódulo>")

def extract_full_text(url: str, fallback: str = "") -> str:
    html = trafilatura.fetch_url(url)
    if html:
        text = trafilatura.extract(html, include_comments=False)
        if text:
            return text
    return fallback
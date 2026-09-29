# delivery/__init__.py
from techdigest.config import Settings

settings = Settings()

import logging
logger = logging.getLogger("techdigest.<submódulo>")


def deliver(items: list[dict], audios: list[str]) -> str:
    """Despacha o digest para o canal configurado."""
    if settings.delivery_channel == "telegram":
        from techdigest.delivery.telegram import send_digest_telegram
        send_digest_telegram(items, audios)
        return "telegram"
    from techdigest.delivery.email_smtp import send_digest_email
    send_digest_email(items, audios)
    return "email"
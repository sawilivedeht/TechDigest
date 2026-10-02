import requests
from html import escape
from techdigest.config import Settings

settings = Settings()

import logging
logger = logging.getLogger("techdigest.delivery.telegram")

def _post(endpoint: str, data: dict, files: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{settings.telegram_token}/{endpoint}"
    resp = requests.post(url, data=data, files=files, timeout=120)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram/{endpoint} falhou: {body}")
    return body


def _render_item(it: dict) -> str:
    bullets = "\n".join(f"  • {escape(p)}" for p in it["pontos_chave"])
    return (
        f"<b>📰 {escape(it['titulo_reescrito'])}</b>\n\n"
        f"{escape(it['resumo_didatico'])}\n\n"
        f"<b>🔑 Pontos-chave:</b>\n{bullets}\n\n"
        f"<b>💡 Por que importa:</b> {escape(it['por_que_importa'])}\n\n"
        f'<a href="{escape(it["url"])}">🔗 {escape(it["source"])}</a>'
    )


def send_digest_telegram(items: list[dict], audios: list[str]) -> None:
    _post("sendMessage", {
        "chat_id": settings.telegram_chat_id,
        "text": f"📰 <b>TechDigest</b> — {len(items)} notícias hoje",
        "parse_mode": "HTML",
    })
    for it, audio in zip(items, audios):
        _post("sendMessage", {
            "chat_id": settings.telegram_chat_id,
            "text": _render_item(it),
            "parse_mode": "HTML",
        })
        if audio:
            with open(audio, "rb") as f:
                _post("sendAudio",
                      {"chat_id": settings.telegram_chat_id,
                       "title": it["titulo_reescrito"][:60]},
                      files={"audio": (audio.split("/")[-1], f, "audio/mpeg")})
import smtplib
from email.message import EmailMessage
from pathlib import Path
from techdigest.config import Settings
import re, datetime

settings = Settings()

import logging
logger = logging.getLogger("techdigest.<submódulo>")

def send_digest(subject: str, html: str, attachments: list[str] | None = None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_user
    msg["To"] = ", ".join(settings.recipients)
    msg.set_content("Ative a visualização HTML para ver o digest.")
    msg.add_alternative(html, subtype="html")

    for path in attachments or []:
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="audio",
                               subtype="mpeg", filename=Path(path).name)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.email_user, settings.email_password)
        smtp.send_message(msg)

def send_digest_email(items: list[dict], audios: list[str]) -> None:
    html = render_html(items)          

def render_html(items: list[dict]) -> str:
    cards = ""
    for it in items:
        bullets = "".join(f"<li>{p}</li>" for p in it["pontos_chave"])
        cards += f"""
        <div style="border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0;font-family:sans-serif">
          <h2 style="margin-top:0">{it['titulo_reescrito']}</h2>
          <p>{it['resumo_didatico']}</p>
          <ul>{bullets}</ul>
          <p><b>💡 Por que importa:</b> {it['por_que_importa']}</p>
          <p><a href="{it['url']}">🔗 Ler fonte original</a> — {it['source']}</p>
        </div>"""
    hoje = datetime.date.today().strftime("%d/%m/%Y")
    return f"<html><body><h1>📰 TechDigest — {hoje}</h1>{cards}</body></html>"
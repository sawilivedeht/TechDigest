import contextlib
import datetime
import os
import socket
import time

import requests
import urllib3.util.connection as _u3conn
from html import escape
from techdigest.config import Settings

settings = Settings()

import logging
logger = logging.getLogger("techdigest.delivery.telegram")

_cabecalho_enviado = False  # o cabeçalho com a data sai uma vez por execução, junto da 1ª notícia


class FalhaDeRede(RuntimeError):
    """Falha de transporte (conexão/timeout): vale uma nova tentativa."""


class AudioNaoEnviado(RuntimeError):
    """O texto da notícia foi entregue, mas o áudio não (esgotadas as tentativas)."""


@contextlib.contextmanager
def _somente_ipv4():
    """Força IPv4 nas chamadas ao Telegram (TELEGRAM_FORCAR_IPV4).

    Medido neste host: 3 MB sobem em ~2 s via IPv4; pela rota padrão (IPv6 primeiro) cada
    conexão trava até o timeout de conexão antes de cair para IPv4. O requests/urllib3 não
    faz "happy eyeballs", então a troca é feita só durante a chamada e desfeita em seguida.
    """
    if not settings.telegram_forcar_ipv4:
        yield
        return
    original = _u3conn.allowed_gai_family
    _u3conn.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        _u3conn.allowed_gai_family = original


def _post(endpoint: str, data: dict, files: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{settings.telegram_token}/{endpoint}"
    # Erros do requests citam a URL, e a URL contém o token: re-levanta SEM ela
    # para o token não vazar para o arquivo de log nem para o journal.
    # Timeout (conexão, leitura): conectar a api.telegram.org leva < 1 s; 15 s já é folga.
    try:
        with _somente_ipv4():
            resp = requests.post(url, data=data, files=files, timeout=(15, 120))
    except requests.RequestException as e:
        raise FalhaDeRede(f"Telegram/{endpoint}: falha de rede ({type(e).__name__})") from None
    try:
        body = resp.json()
    except ValueError:
        raise RuntimeError(
            f"Telegram/{endpoint}: resposta não-JSON (HTTP {resp.status_code})"
        ) from None
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


def send_item_telegram(it: dict, audio: str | None) -> None:
    """Envia UMA notícia (texto + áudio). Levanta exceção em qualquer falha."""
    global _cabecalho_enviado
    if not _cabecalho_enviado:
        _post("sendMessage", {
            "chat_id": settings.telegram_chat_id,
            "text": f"📰 <b>TechDigest</b> — {datetime.datetime.now():%d/%m/%Y %H:%M}",
            "parse_mode": "HTML",
        })
        _cabecalho_enviado = True
    _post("sendMessage", {
        "chat_id": settings.telegram_chat_id,
        "text": _render_item(it),
        "parse_mode": "HTML",
    })
    if audio:
        _enviar_audio(it, audio)
    logger.info("Entregue: %s", it["titulo_reescrito"])


def _enviar_audio(it: dict, audio: str) -> None:
    """Upload do áudio com novas tentativas SÓ em falha de rede (erro da API não se repete)."""
    tamanho_mb = os.path.getsize(audio) / 1e6
    tentativas = max(1, settings.telegram_tentativas_audio)
    for n in range(1, tentativas + 1):
        t0 = time.perf_counter()
        try:
            with open(audio, "rb") as f:  # reabre a cada tentativa
                _post("sendAudio",
                      {"chat_id": settings.telegram_chat_id,
                       "title": it["titulo_reescrito"][:60]},
                      files={"audio": (audio.split("/")[-1], f, "audio/mpeg")})
        except FalhaDeRede as e:
            dt = time.perf_counter() - t0
            if n == tentativas:
                raise AudioNaoEnviado(
                    f"texto entregue, áudio não ({tentativas} tentativa(s); última: {e})"
                ) from None
            logger.warning("Upload do áudio falhou após %.0fs (tentativa %d de %d): %s",
                           dt, n, tentativas, e)
            time.sleep(settings.telegram_pausa_s)
            continue
        dt = time.perf_counter() - t0
        logger.info("Áudio enviado: %.1f MB em %.0fs (%.0f KB/s)%s",
                    tamanho_mb, dt, tamanho_mb * 1000 / dt if dt else 0,
                    f" na tentativa {n}" if n > 1 else "")
        return


def send_footer_telegram(n: int) -> None:
    """Fechamento do lote: quantas notícias esta execução entregou (pode haver vários lotes por dia)."""
    _post("sendMessage", {
        "chat_id": settings.telegram_chat_id,
        "text": f"✅ Fim do lote: {n} {'notícia' if n == 1 else 'notícias'}",
        "parse_mode": "HTML",
    })
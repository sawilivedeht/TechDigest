# delivery/__init__.py
from techdigest.config import Settings

settings = Settings()

import logging
logger = logging.getLogger("techdigest.delivery.__init__")


def _canal_nao_implementado() -> NotImplementedError:
    return NotImplementedError(
        f"DELIVERY_CHANNEL={settings.delivery_channel!r}: só 'telegram' está implementado "
        f"(o envio por e-mail nunca foi concluído)."
    )


def deliver_item(item: dict, audio: str | None) -> str:
    """Entrega UMA notícia (texto + áudio) no canal configurado e devolve o nome do canal.

    Levanta exceção se a entrega falhar: quem chama decide o que fazer e só marca o item
    como visto depois que esta função retornar sem erro.
    """
    if settings.delivery_channel == "telegram":
        from techdigest.delivery.telegram import send_item_telegram
        send_item_telegram(item, audio)
        return "telegram"
    raise _canal_nao_implementado()


def deliver_footer(n: int) -> None:
    """Mensagem de fechamento do digest (quantas notícias foram entregues)."""
    if settings.delivery_channel == "telegram":
        from techdigest.delivery.telegram import send_footer_telegram
        send_footer_telegram(n)
        return
    raise _canal_nao_implementado()
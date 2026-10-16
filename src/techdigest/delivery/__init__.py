# delivery/__init__.py
from techdigest.config import Settings
from techdigest.simulacao import em_simulacao

settings = Settings()

import logging
logger = logging.getLogger("techdigest.delivery.__init__")


def _canal_nao_implementado() -> NotImplementedError:
    return NotImplementedError(
        f"DELIVERY_CHANNEL={settings.delivery_channel!r}: só 'telegram' está implementado, mais o 'arquivo' "
        f"da simulação (o envio por e-mail nunca foi concluído)."
    )


def _so_na_simulacao() -> None:
    """O canal `arquivo` só vale na simulação, que trabalha numa cópia do banco.

    Fora dela, o item iria para um arquivo e seria marcado como visto no banco de produção: sairia do
    Telegram sem ter chegado lá.
    """
    if not em_simulacao():
        raise RuntimeError("DELIVERY_CHANNEL='arquivo' só vale na simulação (techdigest --simular), "
                           "que trabalha numa cópia do banco")


def deliver_item(item: dict, audio: str | None) -> str:
    """Entrega UMA notícia (texto + áudio) no canal configurado e devolve o nome do canal.

    Levanta exceção se a entrega falhar: quem chama decide o que fazer e só marca o item
    como visto depois que esta função retornar sem erro.
    """
    if settings.delivery_channel == "telegram":
        from techdigest.delivery.telegram import send_item_telegram
        send_item_telegram(item, audio)
        return "telegram"
    if settings.delivery_channel == "arquivo":
        _so_na_simulacao()
        from techdigest.delivery.arquivo import entregar_item
        entregar_item(item, audio)
        return "arquivo"
    raise _canal_nao_implementado()


def deliver_footer(n: int) -> None:
    """Mensagem de fechamento do digest (quantas notícias foram entregues)."""
    if settings.delivery_channel == "telegram":
        from techdigest.delivery.telegram import send_footer_telegram
        send_footer_telegram(n)
        return
    if settings.delivery_channel == "arquivo":
        _so_na_simulacao()
        from techdigest.delivery.arquivo import entregar_fechamento
        entregar_fechamento(n)
        return
    raise _canal_nao_implementado()

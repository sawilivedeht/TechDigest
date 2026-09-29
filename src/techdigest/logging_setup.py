"""Configuração central de logging — fonte única para todo o projeto."""
import logging
import logging.handlers
from pathlib import Path

from techdigest.config import settings

NIVEL_FORMATO = "%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s"
FORMATO = logging.Formatter(NIVEL_FORMATO, datefmt="%d/%m %H:%M:%S")


def setup_logging() -> logging.Logger:
    """Configura handlers (console + arquivo rotativo) e retorna o logger raiz do projeto."""
    nivel = getattr(logging, settings.log_level.upper(), logging.INFO)

    logger = logging.getLogger("techdigest")
    logger.setLevel(logging.DEBUG)          # o filtro por nível é feito nos handlers
    logger.propagate = False

    if logger.handlers:                     # idempotente: chamadas repetidas não duplicam
        return logger

    # ── Console: nível configurável (INFO por padrão) ──
    console = logging.StreamHandler()
    console.setLevel(nivel)
    console.setFormatter(FORMATO)
    logger.addHandler(console)

    # ── Arquivo: sempre DEBUG (histórico completo, rotação de 7 dias) ──
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    arquivo = logging.handlers.RotatingFileHandler(
        log_dir / "techdigest.log",
        maxBytes=2 * 1024 * 1024,           # 2 MB por arquivo
        backupCount=7,                      # mantém até 7 arquivos antigos
        encoding="utf-8",
    )
    arquivo.setLevel(logging.DEBUG)
    arquivo.setFormatter(FORMATO)
    logger.addHandler(arquivo)

    # Bibliotecas barulhentas em modo DEBUG
    if nivel == logging.DEBUG:
        for ruidoso in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(ruidoso).setLevel(logging.WARNING)

    return logger
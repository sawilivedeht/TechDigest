"""Ponto de entrada único do TechDigest: configura o logging e roda o pipeline."""
import logging
import sys

from techdigest.logging_setup import setup_logging
from techdigest.pipeline import run as run_pipeline

logger = logging.getLogger("techdigest.main")


def main() -> None:
    setup_logging()  # fonte única: console (nível do .env) + arquivo rotativo (DEBUG)
    try:
        run_pipeline()
    except Exception:
        # Falha fora do try/except por item (coleta, entrega...): grava o
        # traceback completo no arquivo e sinaliza erro (exit 1) ao systemd.
        logger.exception("Falha fatal no pipeline")
        sys.exit(1)


# O console script do pyproject aponta para "techdigest.main:run".
# Este alias faz esse comando passar pelo main() e, portanto, pelo logging.
run = main


if __name__ == "__main__":
    main()
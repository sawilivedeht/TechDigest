from techdigest.pipeline import run
from techdigest.logging_setup import setup_logging
import logging
logger = logging.getLogger("techdigest.<submódulo>")

if __name__ == "__main__":
    log = setup_logging()
    log.info("=== TechDigest %s ===", "iniciando")
    run()
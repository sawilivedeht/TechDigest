"""Ponto de entrada único do TechDigest: configura o logging e roda o pipeline.

Os argumentos são lidos antes de qualquer import do pacote que leia a configuração: cada módulo
lê a configuração ao ser importado, e a simulação (`--simular`, ver `simulacao.py`) tem de pôr os
caminhos e o canal dela no ambiente antes disso. Por isso os imports do pacote ficam dentro de
`main()`.
"""
import argparse
import logging
import sys

logger = logging.getLogger("techdigest.main")


def _argumentos(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="techdigest", description="Coleta as notícias, gera os episódios e os entrega.")
    p.add_argument("--simular", metavar="PASTA",
                   help="simulação: coleta, extração, LLM e áudio de verdade, com a entrega em arquivos nesta pasta e "
                        "uma cópia do banco; nada vai ao Telegram. Uma pasta nova (ou vazia) pede --banco-origem; a de "
                        "uma simulação anterior continua com o banco dela")
    p.add_argument("--banco-origem", metavar="ARQUIVO",
                   help="com --simular, numa pasta nova: o banco de que a simulação parte (o de produção, por exemplo), "
                        "aberto só para leitura e copiado para a pasta")
    p.add_argument("--sem-audio", action="store_true",
                   help="com --simular: não gera o áudio (para as simulações de trabalho; a que libera o merge tem áudio)")
    args = p.parse_args(argv)
    if (args.banco_origem or args.sem_audio) and not args.simular:
        p.error("--banco-origem e --sem-audio só valem com --simular")
    return args


def main(argv: list[str] | None = None) -> None:
    args = _argumentos(sys.argv[1:] if argv is None else argv)
    if args.simular:
        from techdigest import simulacao    # só a biblioteca padrão: nada do pacote leu a configuração ainda
        try:
            ambiente = simulacao.preparar(args.simular, args.banco_origem)
        except simulacao.PastaRecusada as e:
            sys.exit(f"techdigest --simular: {e}")

    from techdigest.ai.maquina import ExecucaoInterrompida
    from techdigest.logging_setup import setup_logging
    from techdigest.pipeline import run as run_pipeline
    from techdigest.trava import TravaOcupada

    setup_logging()  # fonte única: console (nível do .env) + arquivo rotativo (DEBUG)
    if args.simular:
        logger.info("Simulação em %s: entrega em %s, banco %s, nada vai ao Telegram%s.",
                    ambiente["TECHDIGEST_SIMULACAO"], ambiente["ARQUIVO_DIR"], ambiente["DB_PATH"],
                    " (sem áudio)" if args.sem_audio else "")
    try:
        run_pipeline(sem_audio=args.sem_audio)
    except (TravaOcupada, ExecucaoInterrompida):
        sys.exit(1)     # o pipeline já registrou o motivo no log
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

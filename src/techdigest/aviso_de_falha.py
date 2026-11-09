"""O aviso de falha da execução pelo timer: o serviço do `OnFailure=` da `techdigest.service` (`deploy/systemd/`).

O pipeline já avisa quando para sozinho (`pipeline.run` e `_avisar`: trava ocupada, freio da máquina, erro inesperado,
falhas seguidas de entrega, todos os feeds fora) e sai com status 1. Este módulo cobre o que ele não consegue avisar: o
tempo máximo da unit (`RuntimeMaxSec=`), o OOM, um sinal, um core dump, um erro antes de o pipeline começar (uma `.venv`
fora do lock sai com status 1 sem aviso) e o systemd que não conseguiu iniciá-lo.

O systemd passa ao serviço do `OnFailure=` as variáveis MONITOR_SERVICE_RESULT, MONITOR_EXIT_CODE, MONITOR_EXIT_STATUS,
MONITOR_INVOCATION_ID e MONITOR_UNIT (systemd.exec(5), desde a versão 251), mas só quando um único serviço aponta para
ele. A regra (decisões do dono de 09/11/2026, frente 5 das melhorias), em que um aviso duplicado vale mais que um silêncio:

- saída com status 1: procura a linha do aviso de parada no journal daquela execução (pelo `_SYSTEMD_INVOCATION_ID`).
  Achou, só registra. Não achou, achou também a linha do aviso não enviado, ou não conseguiu ler o journal: avisa;
- qualquer outro resultado ou status (tempo esgotado, OOM, sinal, core dump...): avisa;
- sem as variáveis: avisa com um texto genérico.

O aviso sai pelo `delivery.deliver_aviso`, o mesmo do pipeline (no Telegram, pelo `_post` que esconde o token), e a linha
do log é a mesma do pipeline ("Aviso de parada: ..."), que o `scripts/resumo_lotes.py` já mostra. Roda pelo
`python -m techdigest.aviso_de_falha` da `techdigest-aviso.service`, nunca numa simulação.
"""
import datetime
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from techdigest.delivery import deliver_aviso
from techdigest.logging_setup import setup_logging
from techdigest.simulacao import em_simulacao

logger = logging.getLogger("techdigest.aviso_de_falha")

UNIT_DO_PIPELINE = "techdigest.service"
TEMPO_MAXIMO = "4 horas"                                  # o RuntimeMaxSec= da techdigest.service (tests/test_units.py)
LINHA_DO_AVISO = "Aviso de parada:"                       # o que `pipeline._avisar` escreve no log antes de enviar
LINHA_DO_AVISO_NAO_ENVIADO = "Aviso de parada não enviado"   # e o que ele escreve quando o envio falha
TEMPO_DO_JOURNALCTL = 30                                  # segundos para o journalctl responder
_ID_DA_EXECUCAO = re.compile(r"[0-9a-f]{32}")             # o formato de um invocation id do systemd


@dataclass(frozen=True)
class Decisao:
    """Se avisa e por quê: `motivo` completa o texto do aviso ou, sem aviso, a linha do log."""
    avisar: bool
    motivo: str


def ler_journal(execucao: str | None) -> str | None:
    """As linhas que a execução `execucao` (um invocation id) deixou no journal do usuário; None se não deu para ler."""
    if not execucao or not _ID_DA_EXECUCAO.fullmatch(execucao):
        return None
    try:
        saida = subprocess.run(
            ["journalctl", "--user", f"_SYSTEMD_INVOCATION_ID={execucao}", "--output=cat", "--no-pager", "--quiet"],
            capture_output=True, text=True, timeout=TEMPO_DO_JOURNALCTL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if saida.returncode != 0:
        return None
    return saida.stdout


def _motivo(resultado: str, codigo: str, status: str) -> str:
    """O motivo em palavras de uma falha que o pipeline não avisou, pelo resultado da unit (tabela do systemd.exec(5))."""
    if resultado == "timeout":
        return f"passou do tempo máximo da unit ({TEMPO_MAXIMO}) e foi encerrado pelo systemd"
    if resultado == "oom-kill":
        return "foi encerrado pelo sistema por falta de memória"
    if resultado == "signal":
        return f"foi encerrado pelo sinal {status or 'desconhecido'}"
    if resultado == "core-dump":
        return f"caiu com o sinal {status or 'desconhecido'} (core dump)"
    if resultado == "exit-code":
        if codigo == "exited" and status.isdigit():
            if int(status) >= 200:      # os status de 200 em diante são do próprio systemd (systemd.exec(5), "Process Exit Codes")
                return f"o systemd não conseguiu iniciar o pipeline (status {status})"
            return f"saiu com status {status} sem o aviso do pipeline"
        return f"saiu com erro ({codigo or 'sem código'}, status {status or 'desconhecido'}) sem o aviso do pipeline"
    return f"falhou no systemd (resultado {resultado})"


def decidir(ambiente: Mapping[str, str], ler: Callable[[str | None], str | None] = ler_journal) -> Decisao:
    """Se a falha descrita pelas variáveis MONITOR_* de `ambiente` pede um aviso (a regra está no docstring do módulo)."""
    resultado = ambiente.get("MONITOR_SERVICE_RESULT", "")
    if not resultado:
        return Decisao(True, "falhou, e o systemd não passou o motivo (sem as variáveis MONITOR_*)")
    codigo = ambiente.get("MONITOR_EXIT_CODE", "")
    status = ambiente.get("MONITOR_EXIT_STATUS", "")
    if (resultado, codigo, status) != ("exit-code", "exited", "1"):
        return Decisao(True, _motivo(resultado, codigo, status))
    journal = ler(ambiente.get("MONITOR_INVOCATION_ID"))
    if journal is None:
        return Decisao(True, "saiu com status 1, e o journal não pôde ser lido para saber se o pipeline avisou")
    if LINHA_DO_AVISO_NAO_ENVIADO in journal:
        return Decisao(True, "saiu com status 1, e o aviso do pipeline não foi enviado (o motivo está no journal)")
    if LINHA_DO_AVISO in journal:
        return Decisao(False, "saiu com status 1 depois do aviso do pipeline")
    return Decisao(True, "saiu com status 1 sem o aviso do pipeline (provavelmente antes de começar)")


def texto_do_aviso(unit: str, motivo: str) -> str:
    return (f"TechDigest ({unit}) parou às {datetime.datetime.now():%H:%M}: {motivo}. O que não foi entregue volta na "
            f"próxima execução. Detalhe: journalctl --user -u {unit}")


def executar(ambiente: Mapping[str, str], ler: Callable[[str | None], str | None] = ler_journal) -> int:
    """Decide e avisa. Devolve o status de saída: 0 avisou ou só registrou, 1 o envio falhou, 2 recusou (simulação)."""
    if em_simulacao():
        logger.error("Aviso de falha recusado numa simulação: ele só roda pelo OnFailure= da %s", UNIT_DO_PIPELINE)
        return 2
    unit = ambiente.get("MONITOR_UNIT") or UNIT_DO_PIPELINE
    decisao = decidir(ambiente, ler)
    if not decisao.avisar:
        logger.info("Falha da %s já avisada pelo pipeline (%s): só registrada.", unit, decisao.motivo)
        return 0
    texto = texto_do_aviso(unit, decisao.motivo)
    logger.warning("%s %s", LINHA_DO_AVISO, texto)
    try:
        deliver_aviso(texto)
    except Exception as e:
        logger.error("%s (%s: %s)", LINHA_DO_AVISO_NAO_ENVIADO, type(e).__name__, str(e)[:200])
        return 1
    return 0


def main() -> int:
    setup_logging()
    return executar(os.environ)


if __name__ == "__main__":
    sys.exit(main())

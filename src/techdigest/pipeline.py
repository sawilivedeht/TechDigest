import datetime
import fcntl
import re
import time
from pathlib import Path

from techdigest.ai.summarizer import QAReprovado, Summarizer
from techdigest.audio.tts import gerar_podcast
from techdigest.collectors.rss import collect_rss
from techdigest.config import Settings
from techdigest.delivery import deliver_footer, deliver_item
from techdigest.processing.extractor import extract_full_text
from techdigest.storage.dedup import SeenStore
import logging

logger = logging.getLogger("techdigest.pipeline")
settings = Settings()


def _travar_execucao():
    """Garante UMA execução por vez (timer do systemd, terminal, VSCode...).

    Duas execuções simultâneas podem processar e entregar a mesma notícia (o mark_seen só
    vem após a entrega), disputar o Ollama e sobrescrever os mesmos mp3. O flock é liberado
    pelo sistema quando o processo termina, inclusive se ele for morto: não sobra trava velha.
    """
    caminho = Path(settings.db_path).parent / "techdigest.lock"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arquivo = open(caminho, "w")
    try:
        fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        arquivo.close()
        return None
    return arquivo


def run():
    trava = _travar_execucao()
    if trava is None:
        logger.warning("Outra execução do TechDigest já está em andamento: esta foi cancelada.")
        return
    try:
        _executar()
    finally:
        trava.close()


def _executar():
    inicio = time.monotonic()
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    seen = SeenStore(settings.db_path)
    logger.info("=== TechDigest iniciando ===")
    summarizer = Summarizer()
    entregues = 0
    falhas_seguidas = 0
    abortada = False
    tentadas: set[str] = set()  # URLs já tentadas nesta execução (não repete o mesmo item)

    for art in collect_rss():
        if entregues >= settings.max_news:
            break
        if settings.max_runtime_min and time.monotonic() - inicio >= settings.max_runtime_min * 60:
            logger.warning(
                "Orçamento de tempo (%d min) esgotado: encerrando. "
                "O que sobrou fica para a próxima execução.", settings.max_runtime_min,
            )
            break
        if art.url in tentadas or not seen.is_new(art.url):
            continue
        tentadas.add(art.url)

        # 1) Gera o episódio. Guarda de resiliência nº 1: um item ruim é pulado com log
        #    e o digest sobrevive.
        try:
            text = extract_full_text(art.url, fallback=art.summary)
            if len(text) < settings.min_texto_chars:
                logger.info(
                    "Item descartado (texto insuficiente: %d caracteres, mínimo %d): %r",
                    len(text), settings.min_texto_chars, art.title,
                )
                continue

            principal = {"source": art.source, "title": art.title, "text": text}
            result = summarizer.process(principal)
            result["url"], result["source"] = art.url, art.source

            slug = re.sub(r"\W+", "-", result["titulo_reescrito"].lower())[:50]
            path, dur_s = gerar_podcast(
                result["roteiro_podcast"], result["personagens"],
                f"{settings.audio_dir}/{slug}.mp3",
            )
            logger.info(
                "✅ %s — episódio: %.1f min", result["titulo_reescrito"], dur_s / 60
            )
        except QAReprovado as e:
            # Rejeição editorial esperada (regras 2, 3 e 6): WARNING sem traceback.
            # O item não é marcado como visto e volta a ser tentado no próximo lote.
            logger.warning("Item pulado pelo QA: %r — %s ↳ %s", art.title, e, art.url)
            continue
        except Exception:
            logger.exception(  # .exception = nível ERROR + traceback COMPLETO (erro inesperado)
                "Item pulado: %r ↳ %s", art.title, art.url
            )
            continue

        # 2) Entrega NA HORA e só então marca como visto. Se o processo for interrompido
        #    (timeout, reboot), o que já foi entregue não se perde nem se repete, e o
        #    que não foi entregue volta na próxima execução.
        try:
            deliver_item(result, path)
        except Exception:
            falhas_seguidas += 1
            logger.exception(
                "Falha ao entregar %r — fica para a próxima execução", result["titulo_reescrito"]
            )
            if falhas_seguidas >= settings.max_falhas_entrega:
                logger.error(
                    "%d falhas de entrega seguidas: encerrando a execução.", falhas_seguidas
                )
                abortada = True
                break
            continue
        falhas_seguidas = 0
        entregues += 1
        try:
            seen.mark_seen(art.url)
        except Exception:
            logger.exception("Falha ao marcar como visto: %s", art.url)

    minutos = (time.monotonic() - inicio) / 60
    if abortada:
        raise RuntimeError(
            f"Execução encerrada por falhas de entrega seguidas ({entregues} entregue(s) antes)."
        )
    if entregues:
        try:
            deliver_footer(entregues)
        except Exception:
            logger.warning("Não foi possível enviar o fechamento do digest.", exc_info=True)
        logger.info("Execução concluída: %d notícia(s) entregue(s) em %.0f min.", entregues, minutos)
    else:
        logger.warning("Nenhuma notícia entregue nesta execução (%.0f min).", minutos)


if __name__ == "__main__":
    run()
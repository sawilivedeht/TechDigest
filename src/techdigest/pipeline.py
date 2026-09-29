import datetime
import re
from pathlib import Path

from techdigest.ai.summarizer import Summarizer
from techdigest.audio.tts import gerar_podcast
from techdigest.collectors.rss import collect_rss
from techdigest.config import Settings
from techdigest.delivery import deliver
from techdigest.processing.extractor import extract_full_text
from techdigest.storage.dedup import SeenStore
import logging

logger = logging.getLogger("techdigest.pipeline")
settings = Settings()

def run():
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    seen = SeenStore(settings.db_path)
    logger.info("=== TechDigest iniciando ===")
    summarizer = Summarizer()
    items, audios = [], []

    for art in collect_rss():
        if len(items) >= settings.max_news or not seen.is_new(art.url):
            continue

        try:
            text = extract_full_text(art.url, fallback=art.summary)
            if len(text) < 300:
                continue

            principal = {"source": art.source, "title": art.title, "text": text}
            result = summarizer.process(principal)
            result["url"], result["source"] = art.url, art.source

            slug = re.sub(r"\W+", "-", result["titulo_reescrito"].lower())[:50]
            path, dur_s = gerar_podcast(
                result["roteiro_podcast"], result["personagens"],
                f"{settings.audio_dir}/{slug}.mp3",
            )
            audios.append(path)
            items.append(result)
            seen.mark_seen(art.url)
            print(f"{result['titulo_reescrito']} — episódio: {dur_s / 60:.1f} min")

        except Exception as e:
            print(f"Item pulado: {art.title[:60]!r}\n"
                  f"    ↳ {art.url}\n"
                  f"    ↳ {type(e).__name__}: {str(e)[:200]}")

            logger.info("✅ %s — episódio: %.1f min", result['titulo_reescrito'], dur_s / 60)
        except Exception:
            logger.exception(          # .exception = warning/error + traceback COMPLETO
                "Item pulado: %r ↳ %s", art.title, art.url
            )

    if items:
        canal = deliver(items, audios)
        logger.info(" Digest entregue via %s com %d notícia(s).", canal, len(items))
    else:
        logger.warning("Nenhuma notícia processada nesta execução.")

    #if items:
        #canal = deliver(items, audios)
        #print(f"Digest entregue via {canal} com {len(items)} notícias.")

        # ── 3. Persistência e log ───────────────────────────────────
        #items.append(result)
        #seen.mark_seen(art.url)
        #print(f"✅ {result['titulo_reescrito']} — episódio: {dur_s / 60:.1f} min")

    #if items:
        #canal = deliver(items, audios)
        #print(f"Digest entregue via {canal} com {len(items)} notícias.")


if __name__ == "__main__":
    run()
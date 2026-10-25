"""Entrega em arquivos, o canal da simulação (`techdigest --simular`): o que iria ao Telegram fica numa pasta.

Cada item vira `<NN>_<slug>.html`, com o texto exatamente como o Telegram o receberia
(`telegram._render_item`, em HTML), e `<NN>_<slug>.json`, com o episódio inteiro; o mp3, quando
há, é copiado ao lado. `entregas.txt` lista as entregas na ordem e recebe o fechamento do lote. A
pasta é `ARQUIVO_DIR`, que a simulação aponta para `<pasta>/entregas`. O aviso de parada vai para
`<pasta>/AVISO.txt` e para a saída de erro.
"""
import datetime
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

from techdigest.config import Settings
from techdigest.delivery.telegram import _render_item   # o texto que o Telegram receberia; importar não envia nada
from techdigest.simulacao import VARIAVEL

settings = Settings()
logger = logging.getLogger("techdigest.delivery.arquivo")


def _pasta() -> Path:
    pasta = Path(settings.arquivo_dir)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _registrar(pasta: Path, linha: str) -> None:
    with open(pasta / "entregas.txt", "a", encoding="utf-8") as arquivo:
        arquivo.write(f"{datetime.datetime.now():%d/%m %H:%M:%S} · {linha}\n")


def entregar_item(it: dict, audio: str | None) -> None:
    """Grava uma notícia (texto, episódio e áudio) na pasta das entregas."""
    pasta = _pasta()
    numero = len(list(pasta.glob("*.html"))) + 1          # continua a contagem de uma execução anterior na mesma pasta
    slug = re.sub(r"\W+", "-", it["titulo_reescrito"].lower()).strip("-")[:50]
    base = f"{numero:02d}_{slug}"
    (pasta / f"{base}.html").write_text(_render_item(it), encoding="utf-8")
    (pasta / f"{base}.json").write_text(json.dumps(it, ensure_ascii=False, indent=1), encoding="utf-8")
    if audio:
        shutil.copy2(audio, pasta / f"{base}.mp3")
    _registrar(pasta, f"{base} · {it['source']} · {it['url']}" + ("" if audio else " · sem áudio"))
    logger.info("Entregue em arquivo: %s", pasta / f"{base}.html")


def entregar_fechamento(n: int) -> None:
    """O fechamento do lote, como a última linha de `entregas.txt`."""
    _registrar(_pasta(), f"fim do lote: {n} {'notícia' if n == 1 else 'notícias'}")


def registrar_aviso(texto: str) -> None:
    """O aviso de parada na simulação: acrescentado, com a hora, ao `AVISO.txt` da pasta dela, e na saída de erro."""
    pasta = Path(os.environ[VARIAVEL])
    with open(pasta / "AVISO.txt", "a", encoding="utf-8") as arquivo:
        arquivo.write(f"{datetime.datetime.now():%d/%m %H:%M:%S} · {texto}\n")
    print(f"AVISO: {texto}", file=sys.stderr)

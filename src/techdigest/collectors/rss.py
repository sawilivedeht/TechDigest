import calendar
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import requests

from techdigest.config import Settings
from techdigest.models import Article

logger = logging.getLogger("techdigest.collectors.rss")

settings = Settings()

_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TechDigest/0.1"}


def _texto_puro(valor: str) -> str:
    """Tira tags e entidades do summary do RSS: o fallback do extractor não pode ser markup."""
    sem_tags = re.sub(r"<[^>]+>", " ", valor or "")
    return re.sub(r"\s+", " ", html.unescape(sem_tags)).strip()


def _titulo_e_veiculo(entry, titulo: str, nome_do_feed: str) -> tuple[str, str]:
    """Google Notícias: o veículo real vem em <source> (e como sufixo ' - Veículo' no título)."""
    veiculo = (entry.get("source") or {}).get("title")
    if not veiculo:
        return titulo, nome_do_feed
    sufixo = f" - {veiculo}"
    return (titulo[: -len(sufixo)] if titulo.endswith(sufixo) else titulo), veiculo


def _categorias(entry) -> tuple[str, ...]:
    """As categorias da entrada (<category> no RSS, term no Atom), sem repetir, na ordem do feed."""
    termos: list[str] = []
    for tag in entry.get("tags") or []:
        termo = (tag.get("term") or tag.get("label") or "").strip()
        if termo and termo not in termos:
            termos.append(termo)
    return tuple(termos)


def _idade_dias(entry) -> float | None:
    """Idade da notícia em dias pela data do feed (published, senão updated); None se não houver data.

    O feedparser já entrega essas datas normalizadas em UTC.
    """
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    return max(0.0, (time.time() - calendar.timegm(t)) / 86400)


def _publicacao(entry) -> datetime | None:
    """A data da notícia no feed (published, senão updated), em UTC: a que a etapa 3 do agrupamento mostra ao LLM."""
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc) if t else None


def _baixar_feed(feed_url: str):
    # feedparser.parse(url) não tem timeout: um servidor mudo travaria a execução inteira.
    resp = requests.get(feed_url, headers=_HEADERS, timeout=settings.feed_timeout_s)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def _vale_repetir(erro: Exception) -> bool:
    """Se esperar pode consertar o erro: rede fora, tempo esgotado ou servidor com problema (408, 429, 5xx). Um 404, um
    403 ou um 410 não mudam com a espera."""
    if isinstance(erro, (requests.ConnectionError, requests.Timeout)):
        return True
    resposta = getattr(erro, "response", None)
    return isinstance(erro, requests.HTTPError) and resposta is not None and (
        resposta.status_code in (408, 429) or resposta.status_code >= 500)


@dataclass
class ColetaRSS:
    """O que a coleta diz sobre os feeds, para o log, o registro e o aviso (ver `collect_rss`)."""
    total: int = 0
    fora: list[dict] = field(default_factory=list)          # {"url", "erro", "tentativas"}: os que ficaram de fora
    recuperados: list[dict] = field(default_factory=list)   # {"url", "tentativa"}: os que só responderam numa nova tentativa


def _artigos_do_feed(parsed, feed_url: str) -> list[Article]:
    limite_dias = settings.max_idade_dias
    nome_do_feed = parsed.feed.get("title", feed_url)
    artigos, antigas, sem_data = [], 0, 0
    # Filtra a idade ANTES de aplicar o MAX_POR_FEED: o limite vale para notícias dentro do prazo
    # (o Google Notícias ordena por relevância, não por data).
    for entry in parsed.entries:
        if limite_dias:
            idade = _idade_dias(entry)
            if idade is None:
                sem_data += 1
                continue
            if idade > limite_dias:
                antigas += 1
                continue
        if len(artigos) >= settings.max_por_feed:
            continue  # segue só contando as descartadas, para o log
        titulo, veiculo = _titulo_e_veiculo(entry, entry.get("title", ""), nome_do_feed)
        artigos.append(Article(
            title=titulo,
            url=entry.get("link", ""),
            summary=_texto_puro(entry.get("summary", "")),
            source=veiculo,
            published=_publicacao(entry),
            feed=feed_url,
            categorias=_categorias(entry),
        ))
    fora = ""
    if antigas or sem_data:
        fora = f" (fora do prazo de {limite_dias} dia(s): {antigas} antiga(s), {sem_data} sem data)"
    logger.info("Feed OK: %d entrada(s) — %s%s", len(artigos), nome_do_feed, fora)
    return artigos


def collect_rss(feeds: list[str] | None = None, coleta: ColetaRSS | None = None, dormir=time.sleep) -> list[Article]:
    """Baixa os feeds e devolve os artigos, intercalados.

    Um feed que falha por erro de rede (ver `_vale_repetir`) é tentado de novo em rodadas, depois de esperar
    `FEED_ESPERA_S` segundos e o dobro a cada rodada, até `FEED_TENTATIVAS` tentativas no total: depois que a máquina acorda
    a rede pode levar um minuto para voltar, e a falha atinge feeds de hosts diferentes ao mesmo tempo, então a espera é
    entre as rodadas, não dentro do feed. Um feed recuperado volta à posição que tinha na lista, para a intercalação
    não mudar. `coleta`, se vier, é preenchida com os feeds que ficaram de fora e os recuperados.
    """
    urls = list(feeds or settings.feeds)      # ⬅️ .env = fonte de verdade
    coleta = coleta if coleta is not None else ColetaRSS()
    coleta.total = len(urls)
    tentativas = max(1, settings.feed_tentativas)
    resultado: dict[int, list[Article]] = {}
    pendentes = list(range(len(urls)))
    erros: dict[int, str] = {}
    for tentativa in range(1, tentativas + 1):
        if tentativa > 1:
            espera = settings.feed_espera_s * 2 ** (tentativa - 2)
            logger.warning("Nova tentativa dos feeds em %d s: %d feed(s) (rodada %d de %d)",
                           espera, len(pendentes), tentativa - 1, tentativas - 1)
            dormir(espera)
        ainda = []
        for i in pendentes:
            feed_url = urls[i]
            try:
                parsed = _baixar_feed(feed_url)
            except Exception as e:
                erros[i] = f"{type(e).__name__}: {str(e)[:100]}"
                logger.warning("Feed inacessível (%s): %s", erros[i], feed_url)
                if _vale_repetir(e) and tentativa < tentativas:
                    ainda.append(i)
                else:
                    coleta.fora.append({"url": feed_url, "erro": erros[i], "tentativas": tentativa})
                continue
            if parsed.bozo and not parsed.entries:
                logger.warning("Feed sem entradas (verifique a URL): %s", feed_url)
                coleta.fora.append({"url": feed_url, "erro": "sem entradas", "tentativas": tentativa})
                continue
            resultado[i] = _artigos_do_feed(parsed, feed_url)
            if tentativa > 1:
                logger.info("Feed recuperado na tentativa %d de %d: %s", tentativa, tentativas, feed_url)
                coleta.recuperados.append({"url": feed_url, "tentativa": tentativa})
        pendentes = ainda
        if not pendentes:
            break
    if coleta.fora:
        logger.warning("Feeds fora da coleta: %d de %d (%s)", len(coleta.fora), len(urls),
                       "; ".join(f["url"] for f in coleta.fora))
    por_feed = [resultado[i] for i in sorted(resultado)]

    # Intercala os feeds (1º de cada um, depois o 2º de cada um...) para que o limite
    # MAX_NEWS não seja consumido só pelos primeiros feeds (regra 1: boletim duplo).
    # Também descarta URLs repetidas entre feeds.
    vistos: set[str] = set()
    articles: list[Article] = []
    for i in range(max((len(f) for f in por_feed), default=0)):
        for artigos in por_feed:
            if i < len(artigos) and artigos[i].url and artigos[i].url not in vistos:
                vistos.add(artigos[i].url)
                articles.append(artigos[i])
    return articles
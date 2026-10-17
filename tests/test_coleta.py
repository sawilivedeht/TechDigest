"""A coleta: cada artigo leva o feed de onde veio e as categorias da entrada, e a amostra os grava."""
import json
import time
from types import SimpleNamespace

from feedparser import FeedParserDict

import testar_agrupamento as diag
from techdigest.collectors import rss
from techdigest.processing import agrupamento as ag

TECNOBLOG = "https://tecnoblog.example/feed"
GOOGLE = "https://news.google.example/rss/search?q=politica"


def _entrada(titulo, link, categorias=()):
    return FeedParserDict(title=titulo, link=link, summary="", published_parsed=time.gmtime(),
                          tags=[FeedParserDict(term=c, scheme=None, label=None) for c in categorias])


def test_cada_artigo_leva_o_feed_e_as_categorias_da_entrada(monkeypatch):
    entradas = {
        TECNOBLOG: [_entrada("TV com 40% OFF", "https://tecnoblog.example/achados/tv", ["Achados", "Ofertas", "Ofertas"]),
                    _entrada("Pix passa de 1 bilhão de chaves", "https://tecnoblog.example/noticias/pix")],
        GOOGLE: [_entrada("Pix passa de 1 bilhão de chaves", "https://tecnoblog.example/noticias/pix"),
                 _entrada("Câmara vota a PEC", "https://g1.example/politica/pec")],
    }
    monkeypatch.setattr(rss, "_baixar_feed",
                        lambda url: SimpleNamespace(bozo=False, entries=entradas[url], feed={"title": url}))
    artigos = {a.url: a for a in rss.collect_rss([TECNOBLOG, GOOGLE])}
    assert (artigos["https://tecnoblog.example/achados/tv"].feed,
            artigos["https://tecnoblog.example/achados/tv"].categorias) == (TECNOBLOG, ("Achados", "Ofertas"))
    assert artigos["https://g1.example/politica/pec"].categorias == ()
    # o link que está nos dois feeds fica com o da primeira aparição no intercalado: a 1ª entrada do Google
    # vem antes da 2ª do Tecnoblog
    assert artigos["https://tecnoblog.example/noticias/pix"].feed == GOOGLE


def test_a_amostra_grava_e_le_o_feed_e_as_categorias(tmp_path, monkeypatch):
    monkeypatch.setattr(diag, "_pasta", lambda: tmp_path)
    candidato = ag.Candidato(titulo="TV com 40% OFF", veiculo="Tecnoblog", url="https://tecnoblog.example/achados/tv",
                             url_veiculo="https://tecnoblog.example/achados/tv", texto="texto da oferta " * 100,
                             feed=TECNOBLOG, categorias=("Achados", "Ofertas"))
    caminho = diag._gravar_amostra([candidato], True, "20261017-120000")
    gravado = json.loads(caminho.read_text(encoding="utf-8"))["candidatos"][0]
    assert (gravado["feed"], gravado["categorias"]) == (TECNOBLOG, ["Achados", "Ofertas"])
    (lido,), ids = diag._carregar_amostra(str(caminho))
    assert (lido.feed, lido.categorias, ids[lido]) == (TECNOBLOG, ("Achados", "Ofertas"), 1)


def test_uma_amostra_de_antes_da_fase_4_continua_lendo(tmp_path):
    caminho = tmp_path / "amostra_20261011-154002.json"
    caminho.write_text(json.dumps({"criada_em": "2026-10-11T15:40:02-03:00", "incluir_vistos": True, "candidatos": [
        {"id": 1, "veiculo": "Jornal do Vale", "titulo": "Obra da BR-101", "url": "https://jornaldovale.example/obra",
         "url_resolvida": "https://jornaldovale.example/obra", "data": None, "texto": "texto da obra " * 100},
    ]}), encoding="utf-8")
    (lido,), _ = diag._carregar_amostra(str(caminho))
    assert (lido.feed, lido.categorias) == ("", ())

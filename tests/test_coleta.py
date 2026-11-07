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


# Novas tentativas dos feeds que falham por erro de rede (07/11/2026: três feeds de hosts diferentes caíram juntos).
import logging

import pytest
import requests

FEED_A, FEED_B, FEED_C = "https://a.example/feed", "https://b.example/feed", "https://c.example/feed"


def _feed_com(link):
    return SimpleNamespace(bozo=False, entries=[_entrada(f"Notícia {link}", link)], feed={"title": link})


class _Rede:
    """Um `_baixar_feed` falso: cada URL tem uma fila de respostas (um erro ou o feed), na ordem das tentativas."""

    def __init__(self, filas):
        self.filas, self.chamadas, self.esperas = {k: list(v) for k, v in filas.items()}, [], []

    def baixar(self, url):
        self.chamadas.append(url)
        resposta = self.filas[url].pop(0) if len(self.filas[url]) > 1 else self.filas[url][0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def dormir(self, segundos):
        self.esperas.append(segundos)


def _http(status):
    erro = requests.HTTPError(f"{status}")
    erro.response = SimpleNamespace(status_code=status)
    return erro


@pytest.fixture
def rede(monkeypatch):
    def montar(filas):
        r = _Rede(filas)
        monkeypatch.setattr(rss, "_baixar_feed", r.baixar)
        monkeypatch.setattr(rss.settings, "feed_tentativas", 4)
        monkeypatch.setattr(rss.settings, "feed_espera_s", 20)
        return r
    return montar


def test_o_feed_que_cai_por_erro_de_rede_volta_na_posicao_dele_depois_da_espera(rede, caplog):
    r = rede({FEED_A: [_feed_com("https://a.example/1")],
              FEED_B: [requests.ConnectionError("sem rede"), requests.ConnectionError("sem rede"), _feed_com("https://b.example/1")],
              FEED_C: [_feed_com("https://c.example/1")]})
    caplog.set_level(logging.INFO, logger="techdigest")
    coleta = rss.ColetaRSS()
    artigos = rss.collect_rss([FEED_A, FEED_B, FEED_C], coleta=coleta, dormir=r.dormir)
    assert [a.url for a in artigos] == ["https://a.example/1", "https://b.example/1", "https://c.example/1"]   # a ordem dos feeds
    assert r.esperas == [20, 40]                                       # só até o feed responder
    assert r.chamadas == [FEED_A, FEED_B, FEED_C, FEED_B, FEED_B]      # os que responderam não são pedidos de novo
    assert coleta.total == 3 and coleta.fora == [] and coleta.recuperados == [{"url": FEED_B, "tentativa": 3}]
    mensagens = [x.getMessage() for x in caplog.records]
    assert "Nova tentativa dos feeds em 20 s: 1 feed(s) (rodada 1 de 3)" in mensagens
    assert f"Feed recuperado na tentativa 3 de 4: {FEED_B}" in mensagens
    assert not any(m.startswith("Feeds fora da coleta") for m in mensagens)


def test_o_feed_que_continua_fora_depois_das_tentativas_vai_para_a_coleta_e_para_o_log(rede, caplog):
    r = rede({FEED_A: [_feed_com("https://a.example/1")], FEED_B: [requests.Timeout("lento")]})
    caplog.set_level(logging.INFO, logger="techdigest")
    coleta = rss.ColetaRSS()
    artigos = rss.collect_rss([FEED_A, FEED_B], coleta=coleta, dormir=r.dormir)
    assert [a.url for a in artigos] == ["https://a.example/1"]
    assert r.esperas == [20, 40, 80]                                   # 4 tentativas, 140 s de espera no pior caso
    assert coleta.fora == [{"url": FEED_B, "erro": "Timeout: lento", "tentativas": 4}]
    assert f"Feeds fora da coleta: 1 de 2 ({FEED_B})" in [x.getMessage() for x in caplog.records]


@pytest.mark.parametrize("erro, repete", [
    (requests.ConnectionError("x"), True), (requests.Timeout("x"), True), (_http(503), True), (_http(429), True),
    (_http(408), True), (_http(404), False), (_http(403), False), (_http(410), False), (ValueError("xml"), False),
])
def test_so_o_erro_que_a_espera_pode_consertar_repete(rede, erro, repete):
    r = rede({FEED_A: [erro]})
    coleta = rss.ColetaRSS()
    rss.collect_rss([FEED_A], coleta=coleta, dormir=r.dormir)
    assert (len(r.chamadas) == 4) is repete and (len(r.chamadas) == 1) is not repete
    assert coleta.fora[0]["tentativas"] == len(r.chamadas)


def test_com_uma_tentativa_so_a_coleta_e_como_era_antes(rede):
    r = rede({FEED_A: [requests.ConnectionError("x")]})
    rss.settings.feed_tentativas = 1
    coleta = rss.ColetaRSS()
    assert rss.collect_rss([FEED_A], coleta=coleta, dormir=r.dormir) == []
    assert r.esperas == [] and len(r.chamadas) == 1 and len(coleta.fora) == 1

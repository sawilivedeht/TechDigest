"""A lista de feeds em config/feeds.txt e a precedência do RSS_FEEDS (frente 6 das melhorias).

O conftest desliga o .env e tira o RSS_FEEDS do ambiente; os testes da precedência o põem de volta com o monkeypatch, ou
num .env temporário. O caminho do arquivo é trocado com o monkeypatch em `config.CAMINHO_DOS_FEEDS`.
"""
import logging
from pathlib import Path

import pytest

from techdigest import config

RAIZ = Path(__file__).resolve().parents[1]
AVISO = "RSS_FEEDS definido no ambiente ou no .env"
FEED_A = "https://jornaldovale.example/feed"
FEED_B = "https://diariodolitoral.example/rss"


@pytest.fixture
def arquivo(tmp_path, monkeypatch, caplog):
    """Um arquivo de feeds temporário no lugar do do repositório, nenhum RSS_FEEDS no ambiente e o aviso no caplog."""
    caminho = tmp_path / "feeds.txt"
    caminho.write_text(f"# feeds\n{FEED_A}\n{FEED_B}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CAMINHO_DOS_FEEDS", caminho)
    monkeypatch.delenv("RSS_FEEDS", raising=False)
    caplog.set_level(logging.WARNING, logger="techdigest.config")
    return caminho


def _avisos(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "techdigest.config" and AVISO in r.getMessage()]


# ── A leitura do arquivo ──

def test_le_uma_url_por_linha_na_ordem_com_comentarios_e_linhas_vazias(tmp_path):
    caminho = tmp_path / "feeds.txt"
    caminho.write_text("# cabeçalho\n\n  https://b.example/Feed?q=Politica+brasiLeira  \n   # outro\n"
                       "https://a.example/rss\n\n", encoding="utf-8")
    assert config.ler_feeds(caminho) == ("https://b.example/Feed?q=Politica+brasiLeira", "https://a.example/rss")


@pytest.mark.parametrize("linha", [
    "ftp://a.example/feed",                   # esquema que não é http(s)
    "a.example/feed",                         # sem esquema
    "https://",                               # sem host
    "https://a.example/um feed",              # espaço no meio
    "https://a.example/feed # comentário",    # comentário depois da URL
])
def test_recusa_a_linha_que_nao_e_url_com_o_numero_dela(tmp_path, linha):
    caminho = tmp_path / "feeds.txt"
    caminho.write_text(f"{FEED_A}\n{linha}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 2"):
        config.ler_feeds(caminho)


def test_recusa_a_url_repetida_e_compara_o_texto_exato(tmp_path):
    caminho = tmp_path / "feeds.txt"
    caminho.write_text(f"{FEED_A}\n{FEED_B}\n{FEED_A}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 3: .* repete a linha 1"):
        config.ler_feeds(caminho)
    caminho.write_text(f"{FEED_A}\n{FEED_A}/\n", encoding="utf-8")      # com a barra no fim é outro texto
    assert config.ler_feeds(caminho) == (FEED_A, FEED_A + "/")


@pytest.mark.parametrize("conteudo", ["", "# só comentário\n\n   # outro\n"])
def test_recusa_o_arquivo_sem_nenhuma_url(tmp_path, conteudo):
    caminho = tmp_path / "feeds.txt"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError, match="nenhuma URL"):
        config.ler_feeds(caminho)


# ── A precedência ──

def test_sem_rss_feeds_vale_o_arquivo_sem_aviso(arquivo, caplog):
    assert config.Settings().feeds == [FEED_A, FEED_B]
    assert _avisos(caplog) == []


def test_a_troca_do_caminho_por_monkeypatch_muda_o_que_settings_feeds_devolve(arquivo, tmp_path, monkeypatch):
    """O caminho é lido na hora de cada acesso: a mesma instância de Settings segue o arquivo trocado, sem cache."""
    outro = tmp_path / "outro.txt"
    outro.write_text("https://folhadaserra.example/feed\n", encoding="utf-8")
    settings = config.Settings()
    assert settings.feeds == [FEED_A, FEED_B]
    monkeypatch.setattr(config, "CAMINHO_DOS_FEEDS", outro)
    assert settings.feeds == ["https://folhadaserra.example/feed"]
    assert config.ler_feeds() == ("https://folhadaserra.example/feed",)


@pytest.mark.parametrize("valor, esperado", [
    (" https://x.example/a , https://x.example/b ,", ["https://x.example/a", "https://x.example/b"]),
    ("", []),                                 # vazio também manda: é o caso do tests/test_simulacao.py
])
def test_o_rss_feeds_do_ambiente_manda_mesmo_vazio_com_aviso(arquivo, caplog, monkeypatch, valor, esperado):
    monkeypatch.setenv("RSS_FEEDS", valor)
    assert config.Settings().feeds == esperado
    assert _avisos(caplog) == [f"{AVISO}: a coleta usa ele, não o {arquivo}"]


@pytest.mark.parametrize("linha, esperado", [
    ("RSS_FEEDS=https://x.example/a,https://x.example/b", ["https://x.example/a", "https://x.example/b"]),
    ("RSS_FEEDS=", []),
])
def test_o_rss_feeds_do_env_manda_mesmo_vazio_com_aviso(arquivo, caplog, tmp_path, linha, esperado):
    env = tmp_path / "env_de_teste"
    env.write_text(f"MAX_NEWS=3\n{linha}\n", encoding="utf-8")
    assert config.Settings(_env_file=env).feeds == esperado
    assert len(_avisos(caplog)) == 1


def test_o_env_sem_rss_feeds_deixa_o_arquivo_mandar(arquivo, caplog, tmp_path):
    env = tmp_path / "env_de_teste"
    env.write_text("MAX_NEWS=3\n", encoding="utf-8")
    assert config.Settings(_env_file=env).feeds == [FEED_A, FEED_B]
    assert _avisos(caplog) == []


def test_o_rss_feeds_sem_o_arquivo_manda_sem_aviso(arquivo, caplog, monkeypatch):
    arquivo.unlink()
    monkeypatch.setenv("RSS_FEEDS", FEED_B)
    assert config.Settings().feeds == [FEED_B]
    assert _avisos(caplog) == []


def test_sem_rss_feeds_e_sem_arquivo_e_erro(arquivo):
    arquivo.unlink()
    with pytest.raises(FileNotFoundError):
        config.Settings().feeds


def test_o_arquivo_vazio_sem_rss_feeds_e_erro_e_nao_lista_vazia(arquivo):
    """Lista vazia só vem do RSS_FEEDS definido e vazio; o arquivo sem URL é um engano e para a coleta."""
    arquivo.write_text("# feeds\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nenhuma URL"):
        config.Settings().feeds


# ── O arquivo do repositório ──

FEEDS_DO_REPOSITORIO = (
    "https://news.google.com/rss/search?q=politica+brasiLeira+when:2d&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=brasil+when:2d&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://www.tecnologiaeclasse.com.br/feed",
    "https://diolinux.com.br/feed",
    "https://canaltech.com.br/rss/",
    "https://tecnoblog.net/feed/",
    "https://www.hardware.com.br/feed/",
    "https://news.google.com/rss/search?q=pol%C3%ADtica+when:2d&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://news.google.com/rss/search?q=intelig%C3%AAncia+artificial+when:2d&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    # Os aprovados no teste de feeds de 20/11/2026 (frente 10, docs/melhorias/10-teste-feeds.md)
    "https://apublica.org/feed/",
    "https://revistapesquisa.fapesp.br/feed/",
    "https://www.nexojornal.com.br/rss.xml",
    "https://meiobit.com/feed/",
    "https://www.aosfatos.org/noticias/feed/",
    "https://teletime.com.br/feed/",
    "https://folhadolitoral.com.br/feed/",
    "https://www.telesintese.com.br/feed/",
    "https://jblitoral.com.br/feed/",
    "https://www.inovacaotecnologica.com.br/boletim/rss.xml",
    "https://www.rtp.pt/noticias/rss/politica",
    "https://macmagazine.com.br/feed/",
    "https://eco.sapo.pt/feed/",
    "https://olhardigital.com.br/feed/",
    "https://www.jornaldenegocios.pt/rss",
    "https://pplware.sapo.pt/feed/",
    "https://pontofinal-macau.com/feed/",
)


def test_o_arquivo_do_repositorio_tem_os_26_feeds_na_ordem_do_boletim_duplo():
    """A lista em vigor, literal e na ordem: a ordem alimenta a intercalação do boletim duplo (collectors/rss.py).

    Atualize esta tupla junto com qualquer troca de feed em config/feeds.txt (incluir, tirar, reordenar ou corrigir uma
    URL), no mesmo commit: o teste existe para que nenhuma mudança da lista passe sem ser vista.
    """
    assert config.CAMINHO_DOS_FEEDS == RAIZ / "config" / "feeds.txt"
    feeds = config.ler_feeds()
    assert feeds == FEEDS_DO_REPOSITORIO
    assert len(feeds) == 26 and len(set(feeds)) == 26
    assert all(f.startswith("https://") for f in feeds)
    assert config.Settings().feeds == list(FEEDS_DO_REPOSITORIO)      # sem RSS_FEEDS (o conftest o tira), vale o arquivo

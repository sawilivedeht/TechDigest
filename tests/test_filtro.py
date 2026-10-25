"""O filtro de esporte, ofertas e sites de partido: a seção da URL, o site, a categoria do feed e a lista de partidos."""
import pytest

from techdigest.processing import filtro

PARTIDOS = ("pt.org.br", "psd.org.br", "rede23.org")


@pytest.mark.parametrize("url, motivo", [
    ("https://agenciabrasil.ebc.com.br/esportes/noticia/2026-10/rodada", "esporte: seção /esportes/"),
    ("https://www.cnnbrasil.com.br/esporte/futebol/classico/", "esporte: seção /esporte/"),
    ("https://ge.globo.com/futebol/brasileirao/noticia.ghtml", "esporte: site ge.globo.com"),
    ("https://www.lance.com.br/fora-de-campo/ia-crava-resultado.html", "esporte: site lance.com.br"),
    ("https://tecnoblog.net/achados/2026/10/tv-em-oferta/", "ofertas: seção /achados/"),
    ("https://www.hardware.com.br/hardware-indica/fone-com-desconto/", "ofertas: seção /hardware-indica/"),
    ("https://loja.example/OFERTAS/semana", "ofertas: seção /ofertas/"),
    ("https://pt.org.br/alckmin-cobra-isencao/", "site de partido (pt.org.br)"),
    ("https://www.pt.org.br/noticia", "site de partido (pt.org.br)"),
    ("https://bancada.pt.org.br/nota", "site de partido (pt.org.br)"),   # o subdomínio também
    ("https://rede23.org/atos-oficiais/", "site de partido (rede23.org)"),
])
def test_a_url_que_fica_fora_e_o_motivo(url, motivo):
    assert filtro.pela_url(url, PARTIDOS) == motivo


@pytest.mark.parametrize("url", [
    "https://agenciabrasil.ebc.com.br/politica/noticia/2026-10/esportes-no-orcamento",   # a seção é a do primeiro segmento
    "https://g1.globo.com/politica/noticia.ghtml",                # globo.com não é o ge
    "https://apt.org.br/noticia",                                 # outro domínio que termina com as mesmas letras
    "https://psdb.org.br/noticia",                                # psdb não é psd
    "https://pt.org.br.example/noticia",                          # o domínio do partido no meio de outro
    "https://news.google.com/rss/articles/CBMi",                  # o link do Google Notícias, antes de resolver
    "https://canaltech.com.br/produtos/oferta-imperdivel/",       # notícia de preço numa seção de assunto: fica
    "",
])
def test_a_url_que_segue(url):
    assert filtro.pela_url(url, PARTIDOS) == ""


def test_a_categoria_do_feed_compara_sem_acento_sem_caixa_e_sem_espaco_repetido():
    assert filtro.pela_categoria(["Samsung", "Hardware  Indica"]) == "ofertas: categoria Hardware  Indica"
    assert filtro.pela_categoria(["ESPORTES"]) == "esporte: categoria ESPORTES"
    assert filtro.pela_categoria(["Achados"]) == "ofertas: categoria Achados"
    assert filtro.pela_categoria(["Tecnologia", "Esporte eletrônico"]) == ""   # só a categoria inteira
    assert filtro.pela_categoria([]) == ""


def test_o_motivo_olha_a_url_e_a_categoria_e_nunca_o_titulo():
    assert filtro.motivo_do_filtro("https://site.example/politica/x", ["Esportes"], PARTIDOS) == "esporte: categoria Esportes"
    assert filtro.motivo_do_filtro("https://pt.org.br/x", ["Esportes"], PARTIDOS) == "site de partido (pt.org.br)"
    assert filtro.motivo_do_filtro("https://site.example/politica/agenda-de-esportes", (), PARTIDOS) == ""


def test_a_lista_de_partidos_le_um_dominio_por_linha_com_comentarios(tmp_path):
    lista = tmp_path / "sites.txt"
    lista.write_text("# cabeçalho\n\npt.org.br   # 13 PT\nWWW.PSD.org.br\n", encoding="utf-8")
    assert filtro.ler_sites_de_partido(lista) == ("pt.org.br", "psd.org.br")


@pytest.mark.parametrize("linha", ["https://pt.org.br", "pt.org.br/noticias", "pt org.br", "localhost"])
def test_a_lista_de_partidos_recusa_o_que_nao_e_dominio(tmp_path, linha):
    lista = tmp_path / "sites.txt"
    lista.write_text(f"pt.org.br\n{linha}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 2"):
        filtro.ler_sites_de_partido(lista)


def test_o_arquivo_do_repositorio_tem_os_partidos_e_so_dominios():
    sites = filtro.ler_sites_de_partido()
    assert "pt.org.br" in sites and len(sites) == len(set(sites))
    assert filtro.pela_url("https://pt.org.br/noticia") == "site de partido (pt.org.br)"

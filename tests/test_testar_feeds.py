"""O teste dos feeds candidatos (scripts/testar_feeds.py, frente 10 das melhorias): cada veredito e cada motivo, sem rede.

O feed é um RSS escrito aqui e lido pelo feedparser de verdade; a extração e o robots.txt são falsos. Os veículos são
inventados (`.example`), menos o pt.org.br, que está na lista de sites de partido do repositório.
"""
import datetime
import json
from email.utils import format_datetime

import feedparser
import pytest
import requests

import testar_feeds as tf
from techdigest.collectors import rss
from techdigest.processing.extractor import Extracao

AGORA = datetime.datetime.now(datetime.timezone.utc)
FEED = "https://jornaldovale.example/feed"
ATUAIS = ("https://diariodolitoral.example/rss", "https://news.google.com/rss/search?q=brasil")

# Textos inventados, cada um com mais de 1200 caracteres.
TEXTO_PT_BR = ("O usuário da plataforma está usando o celular para acessar a tela do serviço, e a equipe econômica do "
               "governo disse que o fato não muda o registro das contas. A prefeitura também informou que os ônibus "
               "da cidade seguem com o mesmo horário. ") * 6
TEXTO_PT_PT = ("O utilizador da plataforma está a usar o telemóvel para aceder ao ecrã do serviço, e a equipa económica "
               "do governo disse que o facto não muda o registo das contas. A câmara também informou que os autocarros "
               "da cidade seguem com o mesmo horário. ") * 6
TEXTO_EN = ("The company said that the new service will be available to users in the next year, and the board has "
            "approved a plan that is worth 1.5 billion dollars for the expansion of the network in the region. ") * 7
TEXTO_ZH = "公司今天发布了新的手机，营收18.78万元，市值3亿元，用户可以在网上购买这款产品，价格与去年相同。" * 30


def _rss(titulo: str = "Jornal do Vale", itens: list[dict] | None = None) -> bytes:
    """Um RSS 2.0 com os itens: título, link, a idade em dias (None = sem data) e as categorias."""
    partes = []
    for item in itens or []:
        data = ("" if item.get("dias") is None
                else f"<pubDate>{format_datetime(AGORA - datetime.timedelta(days=item['dias']))}</pubDate>")
        categorias = "".join(f"<category>{c}</category>" for c in item.get("categorias", ()))
        partes.append(f"<item><title>{item['title']}</title><link>{item['link']}</link>{data}{categorias}"
                      f"<description>Resumo curto.</description></item>")
    return (f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>{titulo}</title>'
            f'<link>https://jornaldovale.example/</link>{"".join(partes)}</channel></rss>').encode("utf-8")


def _itens(n: int = 5, host: str = "jornaldovale.example", dias: float | None = 1, categorias=()) -> list[dict]:
    return [{"title": f"Notícia {k}", "link": f"https://{host}/noticia-{k}", "dias": dias, "categorias": categorias}
            for k in range(n)]


class Falsa:
    """A rede falsa: o feed (bytes ou exceções, uma por chamada), o texto de cada URL e o robots.txt."""

    def __init__(self, feed: bytes | list = b"", textos: dict | None = None, texto: str = TEXTO_PT_BR,
                 robots: tuple[int, str] | None = None, resolvidas: dict | None = None):
        self.respostas = feed if isinstance(feed, list) else [feed]
        self.textos, self.texto, self.robots, self.resolvidas = textos or {}, texto, robots, resolvidas or {}
        self.chamadas: list[str] = []
        self.pausas: list[float] = []

    def baixar_feed(self, url):
        self.chamadas.append(f"feed {url}")
        resposta = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return feedparser.parse(resposta)

    def extrair(self, url, fallback=""):
        self.chamadas.append(f"extrair {url}")
        texto = self.textos.get(url, self.texto)
        return Extracao(texto or fallback, self.resolvidas.get(url, url), bool(texto))

    def baixar_robots(self, url):
        self.chamadas.append(f"robots {url}")
        return self.robots

    def rede(self) -> tf.Rede:
        return tf.Rede(pausa_s=0.5, baixar_feed=self.baixar_feed, extrair=self.extrair,
                       baixar_robots=self.baixar_robots, dormir=self.pausas.append)


def _candidato(nome: str = "Jornal do Vale", idioma: str = "pt-BR", url: str = FEED) -> tf.Candidato:
    return tf.Candidato("Brasil", "Tecnologia", nome, idioma, url)


def _testar(falsa: Falsa, candidato: tf.Candidato | None = None, atuais=ATUAIS) -> tf.Resultado:
    return tf.testar_feed(candidato or _candidato(), falsa.rede(), atuais)


def _erro_http(status: int) -> requests.HTTPError:
    resposta = requests.Response()
    resposta.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resposta)


# ── Os vereditos ──

def test_feed_em_pt_br_com_nome_certo_e_aprovado_sem_aviso():
    falsa = Falsa(_rss(itens=_itens()))
    r = _testar(falsa)
    assert (r.veredito, r.motivo, r.avisos) == (tf.APROVADO, "", [])
    assert (r.entradas, r.aproveitaveis, r.extraidos, r.com_texto) == (5, 5, 5, 5)
    assert r.idioma.idioma == "pt-BR" and r.nome_bate is True
    assert r.veiculo == "Jornal do Vale" and r.robots_feed == "sem robots.txt"


def test_titulo_generico_do_feed_da_ajuste_com_o_que_o_episodio_citaria():
    r = _testar(Falsa(_rss("República", _itens())), _candidato("Gazeta do Vale"))
    assert r.veredito == tf.AJUSTE
    assert r.motivo == "o episódio citaria 'República' (dito \"republica\"), não \"Gazeta do Vale\""


def test_titulo_em_ideogramas_da_ajuste_porque_o_qa_nao_le_o_nome():
    r = _testar(Falsa(_rss("爱范儿", _itens())), _candidato("ifanr"))
    assert r.veredito == tf.AJUSTE
    assert "não tem letras latinas nem algarismos" in r.motivo


def test_titulo_que_contem_o_nome_bate_e_palavra_generica_contida_no_nome_nao():
    assert tf.comparar_nome("Jornal do Vale", "Jornal do Vale - Notícias do dia")[0] is True
    assert tf.comparar_nome("Revista do Vale", "Revista do Vale")[0] is True
    assert tf.comparar_nome("Revista Ciência do Vale", "Ciência do Vale")[0] is True    # duas palavras ou mais
    assert tf.comparar_nome("Rádio Vale Notícias", "Notícias")[0] is False              # uma palavra só
    assert tf.comparar_nome("巴", "Jornal do Vale")[0] is False


def test_1_5_billion_manda_para_a_etapa_2_com_o_que_numeros_le():
    texto = TEXTO_PT_BR + " A rival anunciou US$ 1.5 billion em investimentos."
    r = _testar(Falsa(_rss(itens=_itens()), texto=texto))
    assert r.veredito == tf.ETAPA_2
    assert ("1.5 billion", "1; 5") in r.casos
    assert r.motivo == "1 expressão(ões) com escala que ai/numeros.py não lê"


def test_texto_em_ingles_vai_para_a_etapa_2_pela_coluna_pelo_texto_e_pela_escala():
    r = _testar(Falsa(_rss("Valley Times", _itens()), texto=TEXTO_EN), _candidato("Valley Times", "en"))
    assert r.veredito == tf.ETAPA_2
    assert r.para_etapa2 == ["idioma da coluna: en", "texto em en",
                             "1 expressão(ões) com escala que ai/numeros.py não lê"]
    assert r.formatos["decimal com ponto"] == 35   # 7 em cada um dos 5 textos extraídos


def test_texto_em_chines_vai_para_a_etapa_2_com_os_casos_de_wan_e_yi():
    r = _testar(Falsa(_rss("Valley Tech", _itens()), texto=TEXTO_ZH), _candidato("Valley Tech", "zh"))
    assert r.veredito == tf.ETAPA_2 and r.idioma.idioma == "zh"
    assert ("18.78万", "18; 78") in r.casos and ("3亿", "3") in r.casos


def test_texto_de_portugal_com_a_coluna_pt_br_vai_para_a_etapa_2():
    r = _testar(Falsa(_rss(itens=_itens()), texto=TEXTO_PT_PT))
    assert r.veredito == tf.ETAPA_2
    assert r.para_etapa2 == ["texto em pt-PT"]


def test_ajuste_do_nome_fica_registrado_mesmo_com_etapa_2():
    r = _testar(Falsa(_rss("Tech", _itens()), texto=TEXTO_PT_PT), _candidato("Vale Tek", "pt-PT"))
    assert r.veredito == tf.ETAPA_2 and r.nome_bate is False


# ── Os motivos de reprovação ──

def test_erro_http_reprova_sem_nova_tentativa():
    falsa = Falsa([_erro_http(404)])
    r = _testar(falsa)
    assert r.veredito == tf.REPROVADO
    assert r.motivo == "acesso: HTTPError: 404 Client Error"
    assert [c for c in falsa.chamadas if c.startswith("feed")] == [f"feed {FEED}"]


def test_tempo_esgotado_nas_duas_tentativas_reprova_e_espera_feed_espera_s():
    falsa = Falsa([requests.Timeout("lento"), requests.Timeout("lento")])
    r = _testar(falsa)
    assert r.veredito == tf.REPROVADO
    assert r.motivo == "acesso: Timeout: lento nas 2 tentativas"
    assert len([c for c in falsa.chamadas if c.startswith("feed")]) == 2
    assert rss.settings.feed_espera_s in falsa.pausas


def test_feed_que_responde_na_segunda_tentativa_segue():
    falsa = Falsa([requests.ConnectionError("rede"), _rss(itens=_itens())])
    r = _testar(falsa)
    assert (r.veredito, r.acesso) == (tf.APROVADO, "ok na tentativa 2")


def test_feed_sem_entradas_reprova():
    r = _testar(Falsa(_rss(itens=[])))
    assert r.motivo == "acesso: o feed não tem entradas"


def test_xml_quebrado_sem_entradas_reprova():
    r = _testar(Falsa(b"<html><body>Pagina</body>"))
    assert r.veredito == tf.REPROVADO and r.motivo.startswith("acesso: o feed não tem entradas")


def test_item_sem_data_da_zero_aproveitaveis_e_reprova():
    r = _testar(Falsa(_rss(itens=_itens(dias=None))))
    assert r.veredito == tf.REPROVADO
    assert r.motivo == "nenhum item aproveitável (5 entrada(s), 5 sem data (a coleta descarta))"


def test_itens_antigos_dao_zero_aproveitaveis():
    r = _testar(Falsa(_rss(itens=_itens(dias=30))))
    assert r.motivo == "nenhum item aproveitável (5 entrada(s), 5 com mais de 7 dias)"


def test_url_ja_no_feeds_txt_reprova():
    r = _testar(Falsa(_rss(itens=_itens())), atuais=(FEED,))
    assert r.motivo == "repetido: a URL já está no config/feeds.txt"


def test_host_ja_no_feeds_txt_reprova_mesmo_com_outro_caminho():
    r = _testar(Falsa(_rss(itens=_itens())), atuais=("https://www.jornaldovale.example/outro-feed",))
    assert r.motivo == "repetido: o host jornaldovale.example já está no config/feeds.txt"


def test_site_de_partido_nos_links_do_feed_reprova():
    r = _testar(Falsa(_rss(itens=_itens(host="pt.org.br"))), _candidato(url="https://pt.org.br/feed/"))
    assert r.veredito == tf.REPROVADO
    assert r.reprovacoes[0] == "site de partido (pt.org.br), no endereço do feed"
    assert "site de partido (pt.org.br), num link do feed" in r.reprovacoes


def test_site_de_partido_na_url_resolvida_reprova():
    resolvidas = {"https://jornaldovale.example/noticia-0": "https://www.pt.org.br/noticia"}
    r = _testar(Falsa(_rss(itens=_itens()), resolvidas=resolvidas))
    assert r.veredito == tf.REPROVADO
    assert "site de partido (pt.org.br), numa URL resolvida" in r.reprovacoes
    assert (r.filtrados_depois, r.considerados, r.com_texto) == (1, 4, 4)


def test_texto_curto_em_3_de_5_reprova_e_em_2_de_5_nao():
    curtos = {f"https://jornaldovale.example/noticia-{k}": "Só a manchete." for k in range(3)}
    r = _testar(Falsa(_rss(itens=_itens()), textos=curtos))
    assert r.veredito == tf.REPROVADO
    assert r.motivo == ("extração: 2 de 5 com 1200 caracteres ou mais (mínimo 3; paywall, bloqueio ou página em "
                        "JavaScript)")
    del curtos["https://jornaldovale.example/noticia-2"]
    assert _testar(Falsa(_rss(itens=_itens()), textos=curtos)).veredito == tf.APROVADO


def test_extrai_os_5_mais_recentes_que_passam_pelo_filtro():
    itens = [{"title": f"N{k}", "link": f"https://jornaldovale.example/n{k}", "dias": k / 10} for k in range(8)]
    itens[0]["categorias"] = ("Ofertas",)   # o mais recente é filtrado: não é extraído
    falsa = Falsa(_rss(itens=itens))
    r = _testar(falsa)
    extraidas = [c.removeprefix("extrair ") for c in falsa.chamadas if c.startswith("extrair")]
    assert extraidas == [f"https://jornaldovale.example/n{k}" for k in range(1, 6)]
    assert r.filtrados_no_feed == 1


# ── Os avisos ──

def test_menos_de_3_itens_e_aviso_e_a_extracao_vale_sobre_o_que_ha():
    r = _testar(Falsa(_rss(itens=_itens(2))))
    assert r.veredito == tf.APROVADO
    assert r.avisos == ["só 2 item(ns) nos últimos 7 dias"]


def test_entradas_sem_data_ao_lado_de_itens_com_data_sao_aviso():
    r = _testar(Falsa(_rss(itens=_itens(4) + [{"title": "Sem data", "link": "https://jornaldovale.example/x"}])))
    assert r.veredito == tf.APROVADO
    assert r.avisos == ["1 entrada(s) sem data, que a coleta descarta"]


def test_mais_da_metade_filtrada_pela_categoria_e_aviso():
    itens = _itens(2) + _itens(3, categorias=("Ofertas",))
    for k, item in enumerate(itens):
        item["link"] += f"-{k}"
    r = _testar(Falsa(_rss(itens=itens)))
    assert "3 de 5 itens filtrados pelo link ou pela categoria" in r.avisos


def test_robots_que_proibe_e_aviso_para_o_feed_e_para_as_materias():
    r = _testar(Falsa(_rss(itens=_itens()), robots=(200, "User-agent: *\nDisallow: /\n")))
    assert r.veredito == tf.APROVADO
    assert r.avisos == ["o robots.txt proíbe o feed para o User-Agent da coleta",
                        "o robots.txt proíbe 5 de 5 matérias para o User-Agent do trafilatura"]


def test_robots_lido_como_o_robotparser_le_os_status():
    assert tf._leitor_de_robots(None) is None
    assert tf._leitor_de_robots((500, "")) is None
    assert tf._leitor_de_robots((403, "")).can_fetch("x", "https://a.example/") is False
    assert tf._leitor_de_robots((404, "")).can_fetch("x", "https://a.example/") is True


def test_uma_requisicao_por_vez_com_pausa_entre_elas_e_robots_uma_vez_por_site():
    falsa = Falsa(_rss(itens=_itens()))
    _testar(falsa)
    assert [c.split()[0] for c in falsa.chamadas] == ["robots", "feed"] + ["extrair"] * 5
    assert falsa.pausas == [0.5] * 6


def test_o_mesmo_host_em_dois_candidatos_e_aviso_nos_dois():
    falsa = Falsa(_rss(itens=_itens()))
    outro = _candidato("Jornal do Vale", url="https://jornaldovale.example/politica.xml")
    resultados = tf.testar([_candidato(), outro], falsa.rede(), ATUAIS, None, mostrar=lambda _: None)
    assert resultados[0].avisos == [f"o mesmo host de Jornal do Vale ({outro.url})"]
    assert resultados[1].avisos == [f"o mesmo host de Jornal do Vale ({FEED})"]


# ── Sobreposição com o Google Notícias ──

def _amostra(pasta, nome: str, candidatos: list[dict]) -> None:
    (pasta / nome).mkdir()
    (pasta / nome / "amostra.json").write_text(json.dumps({"candidatos": candidatos}), encoding="utf-8")


def test_sobreposicao_conta_as_materias_do_google_noticias_no_host_do_candidato(tmp_path):
    google = "https://news.google.com/rss/search?q=brasil"
    _amostra(tmp_path, "20261105-064445", [
        {"feed": google, "url_resolvida": "https://www.jornaldovale.example/a"},
        {"feed": google, "url_resolvida": "https://news.google.com/rss/articles/xyz"},   # não resolvido: não conta
        {"feed": FEED, "url_resolvida": "https://jornaldovale.example/b"},              # feed direto: não conta
    ])
    _amostra(tmp_path, "20261118-211140", [
        {"feed": google, "url_resolvida": "https://www.jornaldovale.example/a"},        # a mesma matéria de novo
        {"feed": google, "url_resolvida": "https://jornaldovale.example/c"},
        {"feed": google, "url_resolvida": "https://diariodolitoral.example/d"},
    ])
    _amostra(tmp_path, "20261107-005542", [])
    registros = tf.ler_registros(tmp_path)
    assert sorted(registros.por_host) == ["diariodolitoral.example", "jornaldovale.example"]   # sem o não resolvido
    assert tf.sobreposicao({"jornaldovale.example"}, registros) == 2
    assert tf.periodo(registros) == ("3 execução(ões) registrada(s), 2 com itens, de 05/11/2026 a 18/11/2026 (14 dias)")

    falsa = Falsa(_rss(itens=_itens()))
    [r] = tf.testar([_candidato()], falsa.rede(), ATUAIS, registros, mostrar=lambda _: None)
    assert r.google_noticias == 2
    assert r.avisos == ["sobreposição com o Google Notícias: 2 matéria(s) destes hosts já vieram por ele nos "
                        "registros da produção (a mesma matéria pode virar dois episódios)"]


# ── O arquivo, o idioma e a saída ──

def test_le_os_candidatos_com_comentarios_e_recusa_linha_errada_e_url_repetida(tmp_path):
    arquivo = tmp_path / "c.txt"
    arquivo.write_text(f"# categoria | subcategoria | nome | idioma | url\n\nBrasil | Tecnologia | Jornal do Vale | pt-BR | "
                       f"{FEED}\n", encoding="utf-8")
    assert tf.ler_candidatos(arquivo) == [_candidato()]
    arquivo.write_text(f"Brasil | Tecnologia | Jornal do Vale | {FEED}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 1: são 5 colunas"):
        tf.ler_candidatos(arquivo)
    arquivo.write_text(f"A | B | C | pt-BR | {FEED}\nA | B | D | pt-BR | {FEED}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="linha 2: .* repete a linha 1"):
        tf.ler_candidatos(arquivo)


def test_o_arquivo_de_candidatos_do_repositorio_le_sem_erro_e_sem_ideogramas_no_nome():
    candidatos = tf.ler_candidatos()
    assert len(candidatos) == 61
    assert all(tf.forma_falada(c.nome) for c in candidatos)


@pytest.mark.parametrize("texto, idioma", [
    (TEXTO_PT_BR, "pt-BR"), (TEXTO_PT_PT, "pt-PT"), (TEXTO_EN, "en"), (TEXTO_ZH, "zh"),
    ("El gobierno anunció que los precios de la energía bajarán este año para las familias.", "es"),
    ("Die Regierung hat angekündigt, dass die Preise für die Energie in diesem Jahr sinken werden.", "de"),
    ("Le gouvernement a annoncé que les prix de l'énergie vont baisser pour les familles.", "fr"),
    ("O governo anunciou que os preços da energia vão cair neste ano para as famílias.", "pt"),
    ("12345 67890", "?"),
])
def test_detecta_o_idioma(texto, idioma):
    assert tf.detectar_idioma([texto]).idioma == idioma


def test_main_grava_o_csv_e_o_md_por_categoria(tmp_path, monkeypatch, capsys):
    candidatos = tmp_path / "candidatos.txt"
    candidatos.write_text(f"Brasil | Tecnologia | Jornal do Vale | pt-BR | {FEED}\n"
                          "Europa | Política | Valley Times | pt-BR | https://valleytimes.example/rss\n", encoding="utf-8")
    rede = Falsa(_rss(itens=_itens())).rede()
    monkeypatch.setattr(tf, "Rede", lambda pausa_s: rede)
    monkeypatch.setattr(tf.config, "ler_feeds", lambda: ATUAIS)
    tf.main(["--candidatos", str(candidatos), "--pasta", str(tmp_path / "saida"), "--registros", str(tmp_path / "nada")])
    md = (tmp_path / "saida" / "etapa1.md").read_text(encoding="utf-8")
    assert "## Brasil: Tecnologia" in md and "## Europa: Política" in md
    assert "Vereditos: APROVADO 1, AJUSTE 1, ETAPA 2 0, REPROVADO 0 (de 2)." in md
    assert "Registros da produção: não lidos." in md
    linhas = (tmp_path / "saida" / "etapa1.csv").read_text(encoding="utf-8").splitlines()
    assert linhas[0].startswith("categoria,subcategoria,nome,idioma_coluna,url,veredito")
    assert len(linhas) == 3
    assert "[1/2] Jornal do Vale" in capsys.readouterr().out

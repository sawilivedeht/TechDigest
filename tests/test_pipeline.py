"""O pipeline com a trava do modelo e as travas da máquina: o que para a execução inteira, e o que fica registrado.

E as partes da fase 4 que valem com o agrupamento desligado: o filtro, o limite de tentativas, o registro de cada
execução, a voz de cada personagem e o aviso de parada. E, com o agrupamento ligado, a pauta gerada junta, na vaga do
seu primeiro artigo, e marcada como vista de uma vez, com as duplicatas e os excedentes."""
import json
import logging
import sqlite3

import pytest

from techdigest import main as entrada
from techdigest import pipeline, simulacao, trava
from techdigest.ai import maquina
from techdigest.ai.prompt import PROMPT_AGRUPADOR
from techdigest.delivery import arquivo
from techdigest.ai.summarizer import QAReprovado
from techdigest.models import Article
from techdigest.processing import agrupamento as ag
from techdigest.processing.extractor import Extracao
from techdigest.storage.dedup import SeenStore

EPISODIO = {
    "titulo_reescrito": "Construtora Alfa entrega a obra da BR-101", "resumo_didatico": "Resumo.",
    "pontos_chave": ["Um ponto."], "por_que_importa": "Importa.",
    "personagens": [{"nome": "Patrícia", "papel": "analista"}, {"nome": "Helena", "papel": "apresentadora"}],
    "roteiro_podcast": [], "houve_divergencia": False, "fontes_citadas": ["Jornal do Vale"],
}


class ProviderFalso:
    model = "modelo"
    ultimo_uso: dict = {}

    def chat_json(self, system, user, **opcoes):
        return {}


class SummarizerFalso:
    """Faz uma chamada ao provider por item, como o de verdade, e devolve sempre o mesmo episódio.

    O título que estiver em `reprovar` levanta QAReprovado, e o que estiver em `quebrar`, um erro qualquer.
    """
    reprovar: set = set()
    quebrar: set = set()
    chamadas: list = []     # (título do principal, títulos dos relacionados), na ordem em que foram gerados

    def __init__(self, provider):
        self.provider = provider
        self.ultimo_diagnostico = {}

    def process(self, principal, relacionados=None):
        self.chamadas.append((principal["title"], [r["title"] for r in relacionados or []]))
        self.provider.chat_json("sistema", principal["text"])
        self.ultimo_diagnostico = {"episodio": dict(EPISODIO, titulo_reescrito=principal["title"]), "problemas": ["curto"]}
        if principal["title"] in self.reprovar:
            raise QAReprovado("revisão ainda reprovada pelo QA: ['curto']")
        if principal["title"] in self.quebrar:
            raise ConnectionError("o Ollama caiu")
        return dict(EPISODIO, titulo_reescrito=principal["title"])


@pytest.fixture
def execucao(monkeypatch, tmp_path):
    """Três artigos novos, a extração e a geração falsas, o modelo remoto (sem GPU) e a entrega em arquivo."""
    artigos = [Article(title=f"Artigo {n}", url=f"https://jornaldovale.example/{n}", source="Jornal do Vale")
               for n in (1, 2, 3)]
    coletas, extraidos = [], []
    resolvidas: dict[str, str] = {}

    def extrair(url, fallback=""):
        extraidos.append(url)
        return Extracao("texto " * 400, resolvidas.get(url, url), True)

    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 12.0)   # as travas não dependem da máquina dos testes
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: 60.0)
    monkeypatch.setattr(pipeline.settings, "db_path", str(tmp_path / "digest.db"))
    monkeypatch.setattr(pipeline.settings, "audio_dir", str(tmp_path / "audio"))
    monkeypatch.setattr(pipeline.settings, "execucoes_dir", str(tmp_path / "execucoes"))
    monkeypatch.setattr(pipeline, "collect_rss", lambda: coletas.append(1) or artigos)
    monkeypatch.setattr(pipeline, "extrair", extrair)
    monkeypatch.setattr(pipeline, "get_provider", lambda settings: ProviderFalso())
    monkeypatch.setattr(pipeline, "Summarizer", SummarizerFalso)
    monkeypatch.setattr(SummarizerFalso, "reprovar", set())
    monkeypatch.setattr(SummarizerFalso, "quebrar", set())
    monkeypatch.setattr(SummarizerFalso, "chamadas", [])
    monkeypatch.setenv(simulacao.VARIAVEL, str(tmp_path))                 # o aviso de parada vai para tmp_path/AVISO.txt
    return {"artigos": artigos, "coletas": coletas, "extraidos": extraidos, "resolvidas": resolvidas,
            "banco": tmp_path / "digest.db", "pasta": tmp_path}


def _relatorios(execucao) -> list[dict]:
    """Os relatórios das execuções, da mais antiga para a mais nova."""
    return [json.loads(next(pasta.glob("relatorio_*.json")).read_text(encoding="utf-8"))
            for pasta in sorted((execucao["pasta"] / "execucoes").iterdir())]


def _aviso(execucao) -> str:
    return (execucao["pasta"] / "AVISO.txt").read_text(encoding="utf-8")


def test_uma_trava_da_maquina_interrompe_a_execucao_inteira_e_o_que_faltou_fica_para_a_proxima(execucao, monkeypatch, caplog):
    memoria = iter([12.0, 3.0])          # o primeiro item passa; antes da chamada do segundo, a memória acabou
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: next(memoria))
    caplog.set_level(logging.INFO, logger="techdigest")
    with pytest.raises(maquina.ExecucaoInterrompida):
        pipeline.run(sem_audio=True)
    vistos = SeenStore(str(execucao["banco"]))
    assert [vistos.is_new(a.url) for a in execucao["artigos"]] == [False, True, True]   # só o entregue foi marcado
    mensagens = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("Execução interrompida: memória disponível em 3.0 GiB, abaixo do mínimo de 4.0 GiB "
                            "(1 notícia(s) entregue(s) antes") for m in mensagens)
    assert not any(m.startswith("Item pulado") for m in mensagens)        # não virou um item pulado
    assert trava.CAMINHO_DA_TRAVA.read_text(encoding="utf-8") == ""         # e a trava do modelo ficou livre
    # o aviso de parada: no log, com texto fixo, e no AVISO.txt da simulação
    assert any(m.startswith("Aviso de parada: TechDigest parou às ") and "memória disponível em 3.0 GiB" in m
               and m.endswith("Entregues: 1 de 20; o resto volta na próxima execução.") for m in mensagens)
    assert "TechDigest parou às " in _aviso(execucao) and "Entregues: 1 de 20" in _aviso(execucao)


def test_com_a_trava_do_modelo_ocupada_a_execucao_nem_comeca(execucao, caplog):
    caplog.set_level(logging.INFO, logger="techdigest")
    with trava.trava_do_modelo("scripts/testar_episodio.py --amostra x"):
        with pytest.raises(trava.TravaOcupada):
            pipeline.run(sem_audio=True)
    assert execucao["coletas"] == []
    assert any(r.getMessage().startswith("Execução não começou: o modelo está em uso por scripts/testar_episodio.py")
               for r in caplog.records)
    assert "TechDigest não começou às " in _aviso(execucao)
    assert "o modelo está em uso por scripts/testar_episodio.py" in _aviso(execucao)


def test_um_erro_inesperado_tambem_avisa_com_o_tipo_do_erro_e_quantos_sairam(execucao, monkeypatch):
    def coleta_quebrada():
        raise KeyError("feed")
    monkeypatch.setattr(pipeline, "collect_rss", coleta_quebrada)
    with pytest.raises(KeyError):
        pipeline.run(sem_audio=True)
    assert ("por um erro inesperado (KeyError). Entregues: 0 de 20; o resto volta na próxima execução. "
            "O detalhe está no log.") in _aviso(execucao)
    assert "feed" not in _aviso(execucao)                                    # a mensagem do erro fica no log, não no aviso


def test_o_aviso_que_falha_fica_no_log_e_a_execucao_sai_como_sairia(execucao, monkeypatch, caplog):
    def canal_fora_do_ar(texto):
        raise ConnectionError("sem rede")

    def coleta_quebrada():
        raise KeyError("feed")
    monkeypatch.setattr(pipeline, "deliver_aviso", canal_fora_do_ar)
    monkeypatch.setattr(pipeline, "collect_rss", coleta_quebrada)
    caplog.set_level(logging.INFO, logger="techdigest")
    with pytest.raises(KeyError):
        pipeline.run(sem_audio=True)
    assert any(r.getMessage() == "Aviso de parada não enviado (ConnectionError: sem rede)" for r in caplog.records)


def test_sem_trava_a_execucao_entrega_e_marca_tudo(execucao, caplog):
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(execucao["banco"]))
    assert all(not vistos.is_new(a.url) for a in execucao["artigos"])
    assert any(r.getMessage().startswith("Execução concluída: 3 notícia(s)") for r in caplog.records)
    assert not (execucao["pasta"] / "AVISO.txt").exists()                   # a execução que termina bem não avisa


def test_o_filtro_tira_o_item_antes_e_depois_da_extracao_e_nao_o_marca_como_visto(execucao, caplog):
    partido = Article(title="Nota do partido", url="https://pt.org.br/nota", source="PT")
    ofertas = Article(title="Fone em promoção", url="https://loja.example/x", source="Loja", categorias=("Achados",))
    esporte = Article(title="Clássico no domingo", url="https://news.google.com/rss/articles/abc", source="ge")
    execucao["resolvidas"][esporte.url] = "https://ge.globo.com/futebol/classico"
    execucao["artigos"][:0] = [partido, ofertas, esporte]
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)

    # o partido e a oferta nem são extraídos; o link do Google Notícias só cai depois de resolvido
    assert execucao["extraidos"] == [esporte.url] + [a.url for a in execucao["artigos"][3:]]
    vistos = SeenStore(str(execucao["banco"]))
    assert [vistos.is_new(a.url) for a in execucao["artigos"]] == [True, True, True, False, False, False]
    mensagens = [r.getMessage() for r in caplog.records]
    assert "Item filtrado (site de partido (pt.org.br)): 'Nota do partido' ↳ https://pt.org.br/nota" in mensagens
    assert "Item filtrado (ofertas: categoria Achados): 'Fone em promoção' ↳ https://loja.example/x" in mensagens
    assert ("Item filtrado (esporte: site ge.globo.com, depois da extração): 'Clássico no domingo' ↳ "
            "https://ge.globo.com/futebol/classico") in mensagens
    [relatorio] = _relatorios(execucao)
    assert [(f["titulo"], f["depois_da_extracao"]) for f in relatorio["filtrados"]] == \
        [("Nota do partido", False), ("Fone em promoção", False), ("Clássico no domingo", True)]


def test_o_item_reprovado_pelo_qa_em_duas_execucoes_e_abandonado_sem_entrar_em_seen(execucao, caplog):
    SummarizerFalso.reprovar = {"Artigo 2"}
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(execucao["banco"]))
    assert vistos.reprovacoes("https://jornaldovale.example/2") == 1 and vistos.is_new("https://jornaldovale.example/2")
    assert not any(r.getMessage().startswith("Item abandonado") for r in caplog.records)

    pipeline.run(sem_audio=True)                                            # a segunda execução: só o 2 volta, e reprova de novo
    assert vistos.reprovacoes("https://jornaldovale.example/2") == 2 and vistos.is_new("https://jornaldovale.example/2")
    abandonado = "Item abandonado (reprovado pelo QA em 2 execuções): 'Artigo 2' ↳ https://jornaldovale.example/2"
    assert any(r.getMessage() == abandonado for r in caplog.records)
    assert _relatorios(execucao)[-1]["abandonados"][0]["titulo"] == "Artigo 2"

    execucao["extraidos"].clear()
    pipeline.run(sem_audio=True)                                            # a terceira nem o extrai
    assert execucao["extraidos"] == [] and vistos.reprovacoes("https://jornaldovale.example/2") == 2


def test_so_o_qareprovado_conta_para_o_limite(execucao):
    SummarizerFalso.quebrar = {"Artigo 3"}                                  # erro de rede ou do Ollama: não conta
    pipeline.run(sem_audio=True)
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(execucao["banco"]))
    assert vistos.reprovacoes("https://jornaldovale.example/3") == 0 and vistos.is_new("https://jornaldovale.example/3")


def test_o_registro_guarda_cada_item_com_a_situacao_as_vozes_e_a_entrega(execucao, caplog):
    SummarizerFalso.reprovar = {"Artigo 2"}
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    [relatorio] = _relatorios(execucao)
    situacoes = [(e["artigos"][0]["titulo"], e["situacao"][:9], e["entregue"]) for e in relatorio["episodios"]]
    assert situacoes == [("Artigo 1", "aprovado", True), ("Artigo 2", "reprovado", False), ("Artigo 3", "aprovado", True)]
    assert relatorio["episodios"][0]["vozes"] == {"Patrícia": "pt-BR-ThalitaNeural", "Helena": "pt-BR-FranciscaNeural"}
    assert any(r.getMessage() == "Vozes: Patrícia → pt-BR-ThalitaNeural; Helena → pt-BR-FranciscaNeural" for r in caplog.records)
    amostra = json.loads(open(relatorio["amostra"], encoding="utf-8").read())
    assert [c["url"] for c in amostra["candidatos"]] == [a.url for a in execucao["artigos"]]


def test_a_tabela_das_reprovacoes_e_aditiva(tmp_path):
    """A master antiga só conhece `seen`: o banco com a tabela nova continua servindo a ela (decisão de 16/10/2026)."""
    banco = tmp_path / "digest.db"
    antigo = sqlite3.connect(banco)                                         # um banco feito pela master, com um visto
    antigo.execute("CREATE TABLE IF NOT EXISTS seen (hash TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    antigo.execute("INSERT INTO seen (hash) VALUES ('h1')")
    antigo.commit()
    antigo.close()
    novo = SeenStore(str(banco))
    assert novo.registrar_reprovacao("https://x.example/a") == 1 and novo.registrar_reprovacao("https://x.example/a") == 2
    assert novo.reprovacoes("https://x.example/b") == 0
    novo.conn.close()
    master = sqlite3.connect(banco)                                         # o que a master faz, com os mesmos comandos
    master.execute("CREATE TABLE IF NOT EXISTS seen (hash TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    master.execute("INSERT OR IGNORE INTO seen (hash) VALUES ('h2')")
    master.commit()
    assert [h for (h,) in master.execute("SELECT hash FROM seen ORDER BY hash")] == ["h1", "h2"]
    assert master.execute("SELECT vezes FROM reprovacoes").fetchall() == [(2,)]


@pytest.mark.parametrize("erro", [trava.TravaOcupada("o modelo está em uso"), maquina.ExecucaoInterrompida("memória")])
def test_main_sai_com_status_1_quando_a_execucao_nao_comeca_ou_e_interrompida(monkeypatch, erro):
    def falha(sem_audio=False):
        raise erro
    monkeypatch.setattr("techdigest.logging_setup.setup_logging", lambda: None)   # sem mexer no logging dos outros testes
    monkeypatch.setattr(pipeline, "run", falha)
    with pytest.raises(SystemExit) as saida:
        entrada.main([])
    assert saida.value.code == 1


def test_main_recusa_as_opcoes_da_simulacao_sem_simular(capsys):
    with pytest.raises(SystemExit) as saida:
        entrada.main(["--sem-audio"])
    assert saida.value.code == 2 and "só valem com --simular" in capsys.readouterr().err


# ── Com o agrupamento ligado ──────────────────────────────────────────────────────────────

FEIRA, PONTE, LITORAL, GAZETA, CORREIO = (
    "https://jornaldovale.example/feira", "https://jornaldovale.example/ponte", "https://diariodolitoral.example/ponte",
    "https://gazeta.example/ponte", "https://correio.example/ponte",
)
# A ponte em três veículos e uma republicação; o texto mais longo é o do Jornal do Vale, que fica como principal.
TEXTOS = {FEIRA: "feira " * 300, PONTE: "ponte " * 400, LITORAL: "ponte " * 350, GAZETA: "ponte " * 400, CORREIO: "ponte " * 300}
# O veredito da etapa 3 sobre a provisória [ponte, litoral, correio]: os três no mesmo acontecimento.
VEREDITO = {"tipos": {"1": "fato_unico", "2": "fato_unico", "3": "fato_unico"},
            "grupos": [{"principal": 1, "membros": [{"id": 2, "relacao": "mesmo_acontecimento"},
                                                     {"id": 3, "relacao": "mesmo_acontecimento"}]}],
            "isolados": [], "motivo": "A mesma ponte."}


class ProviderDoAgrupamento(ProviderFalso):
    """Responde à etapa 3 com `veredito` (ou levanta, se for uma exceção) e a todo o resto com {}."""

    def __init__(self, veredito):
        self.veredito, self.etapa3 = veredito, []

    def chat_json(self, system, user, **opcoes):
        if system != PROMPT_AGRUPADOR:
            return {}
        self.etapa3.append(opcoes)
        if isinstance(self.veredito, Exception):
            raise self.veredito
        return self.veredito


@pytest.fixture
def agrupando(execucao, monkeypatch, tmp_path):
    """O agrupamento ligado, com três textos por pauta no máximo menos um (para haver excedente): a feira sozinha, na
    primeira posição da coleta, e a pauta da ponte, com a republicação da Gazeta. As etapas 1 e 2 dão essas provisórias."""
    monkeypatch.setattr(pipeline.settings, "agrupamento_ativo", True)
    monkeypatch.setattr(pipeline.settings, "agrup_max_artigos", 2)
    monkeypatch.setattr(arquivo.settings, "arquivo_dir", str(tmp_path / "entregas"))
    execucao["artigos"][:] = [
        Article(title="Feira do livro abre no sábado", url=FEIRA, source="Jornal do Vale"),
        Article(title="Ponte de Serra Quieta é entregue", url=PONTE, source="Jornal do Vale"),
        Article(title="Serra Quieta ganha a ponte", url=LITORAL, source="Diário do Litoral"),
        Article(title="Ponte de Serra Quieta é entregue", url=GAZETA, source="Gazeta"),
        Article(title="A ponte nova de Serra Quieta", url=CORREIO, source="Correio"),
    ]
    lotes, tetos = [], []

    def extrair_em_lote(itens):
        lotes.append([url for url, _ in itens])
        return [Extracao(TEXTOS[url], url, True) for url, _ in itens]

    def formar_pautas(candidatos, pares, limiar, max_artigos):
        tetos.append(max_artigos)
        c = {c.url: c for c in candidatos}
        feira = [ag.Pauta(principal=c[FEIRA])] if FEIRA in c else []   # na segunda execução, a feira já foi entregue
        return feira + [ag.Pauta(principal=c[PONTE], relacionados=(c[LITORAL], c[CORREIO]), duplicatas=(c[GAZETA],),
                                 original_de={c[GAZETA]: c[PONTE]})], []

    provider = ProviderDoAgrupamento(VEREDITO)
    monkeypatch.setattr(pipeline, "extrair_em_lote", extrair_em_lote)
    monkeypatch.setattr(pipeline.ag, "formar_pautas", formar_pautas)
    monkeypatch.setattr(pipeline, "get_provider", lambda settings: provider)
    return {**execucao, "lotes": lotes, "tetos": tetos, "provider": provider, "entregas": tmp_path / "entregas"}


def test_desligado_o_pipeline_nao_extrai_em_lote_nem_agrupa(execucao, monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("o agrupamento desligado não extrai em lote")
    monkeypatch.setattr(pipeline, "extrair_em_lote", proibido)
    pipeline.run(sem_audio=True)
    assert SummarizerFalso.chamadas == [("Artigo 1", []), ("Artigo 2", []), ("Artigo 3", [])]


def test_com_o_agrupamento_a_pauta_vai_junta_para_a_geracao_e_e_marcada_de_uma_vez(agrupando, caplog):
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    assert agrupando["lotes"] == [[FEIRA, PONTE, LITORAL, GAZETA, CORREIO]]   # todos extraídos de uma vez
    assert agrupando["tetos"] == [6]                                           # a provisória com AGRUP_MAX_PROVISORIA
    assert agrupando["provider"].etapa3[0]["temperatura"] == ag.TEMPERATURA_ETAPA3
    # a feira na primeira vaga; a ponte com o Diário do Litoral, e o Correio como excedente (2 textos no máximo)
    assert SummarizerFalso.chamadas == [("Feira do livro abre no sábado", []),
                                        ("Ponte de Serra Quieta é entregue", ["Serra Quieta ganha a ponte"])]
    vistos = SeenStore(str(agrupando["banco"]))
    assert not any(vistos.is_new(url) for url in (FEIRA, PONTE, LITORAL, GAZETA, CORREIO))
    texto = (agrupando["entregas"] / "02_ponte-de-serra-quieta-é-entregue.html").read_text(encoding="utf-8")
    assert f'<a href="{PONTE}">🔗 Jornal do Vale</a>\n<a href="{LITORAL}">🔗 Diário do Litoral</a>' in texto
    assert (f'<b>Também noticiaram:</b>\n  • <a href="{GAZETA}">Gazeta</a>: Ponte de Serra Quieta é entregue\n'
            f'  • <a href="{CORREIO}">Correio</a>: A ponte nova de Serra Quieta') in texto
    assert texto.count("Também noticiaram") == 1
    sozinho = (agrupando["entregas"] / "01_feira-do-livro-abre-no-sábado.html").read_text(encoding="utf-8")
    assert sozinho.endswith(f'<a href="{FEIRA}">🔗 Jornal do Vale</a>')   # com uma fonte só, o texto de sempre
    [relatorio] = _relatorios(agrupando)
    pauta = relatorio["episodios"][1]
    assert [(a["veiculo"], a["relacao"]) for a in pauta["artigos"]] == [("Jornal do Vale", "principal"),
                                                                        ("Diário do Litoral", "mesmo_acontecimento")]
    assert [a["url"] for a in pauta["duplicatas"]] == [GAZETA] and [a["url"] for a in pauta["excedentes"]] == [CORREIO]
    assert relatorio["etapa3"] == [{
        "artigos": [{"veiculo": "Jornal do Vale", "titulo": "Ponte de Serra Quieta é entregue", "url": PONTE},
                    {"veiculo": "Diário do Litoral", "titulo": "Serra Quieta ganha a ponte", "url": LITORAL},
                    {"veiculo": "Correio", "titulo": "A ponte nova de Serra Quieta", "url": CORREIO}],
        "duplicatas": [GAZETA], "erro": "", "motivo": "A mesma ponte.",
        "finais": [{"principal": PONTE, "relacionados": [LITORAL], "excedentes": [CORREIO], "duplicatas": [GAZETA]}],
    }]
    assert "Pauta de 2 textos (Jornal do Vale, Diário do Litoral): 'Ponte de Serra Quieta é entregue'" in [
        r.getMessage() for r in caplog.records]


def test_a_etapa_3_que_falha_deixa_os_artigos_separados_e_a_duplicata_com_o_seu_original(agrupando):
    agrupando["provider"].veredito = ConnectionError("o Ollama caiu")
    pipeline.run(sem_audio=True)
    assert SummarizerFalso.chamadas == [("Feira do livro abre no sábado", []), ("Ponte de Serra Quieta é entregue", []),
                                        ("Serra Quieta ganha a ponte", []), ("A ponte nova de Serra Quieta", [])]
    vistos = SeenStore(str(agrupando["banco"]))
    assert not any(vistos.is_new(url) for url in (FEIRA, PONTE, LITORAL, GAZETA, CORREIO))
    [relatorio] = _relatorios(agrupando)
    assert relatorio["etapa3"][0]["erro"].startswith("a chamada falhou (ConnectionError")


def test_a_pauta_que_nao_cabe_em_max_news_nao_e_marcada_e_volta_na_proxima(agrupando, monkeypatch):
    monkeypatch.setattr(pipeline.settings, "max_news", 1)
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(agrupando["banco"]))
    assert not vistos.is_new(FEIRA) and all(vistos.is_new(url) for url in (PONTE, LITORAL, GAZETA, CORREIO))
    pipeline.run(sem_audio=True)
    assert SummarizerFalso.chamadas[-1] == ("Ponte de Serra Quieta é entregue", ["Serra Quieta ganha a ponte"])
    assert not any(vistos.is_new(url) for url in (PONTE, LITORAL, GAZETA, CORREIO))


def test_a_reprovacao_da_pauta_conta_para_os_textos_gerados_e_as_duplicatas(agrupando):
    SummarizerFalso.reprovar = {"Ponte de Serra Quieta é entregue"}
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(agrupando["banco"]))
    assert [vistos.reprovacoes(url) for url in (PONTE, LITORAL, GAZETA, CORREIO)] == [1, 1, 1, 0]
    assert all(vistos.is_new(url) for url in (PONTE, LITORAL, GAZETA, CORREIO))


def test_o_agrupamento_que_quebra_deixa_os_candidatos_um_por_um(agrupando, monkeypatch, caplog):
    def quebrado(*args, **kwargs):
        raise ValueError("erro de programação")
    monkeypatch.setattr(pipeline.ag, "formar_pautas", quebrado)
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    assert [titulo for titulo, _ in SummarizerFalso.chamadas] == [
        "Feira do livro abre no sábado", "Ponte de Serra Quieta é entregue", "Serra Quieta ganha a ponte",
        "Ponte de Serra Quieta é entregue", "A ponte nova de Serra Quieta"]
    assert any(r.getMessage() == "Agrupamento falhou: os 5 candidato(s) seguem um por um" for r in caplog.records)

"""O pipeline com a trava do modelo e as travas da máquina: o que para a execução inteira, e o que fica registrado.

E as partes da fase 4 que valem com o agrupamento desligado: o filtro, o limite de tentativas, o registro de cada
execução, a voz de cada personagem e o aviso de parada."""
import json
import logging
import sqlite3

import pytest

from techdigest import main as entrada
from techdigest import pipeline, simulacao, trava
from techdigest.ai import maquina
from techdigest.ai.summarizer import QAReprovado
from techdigest.models import Article
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

    def __init__(self, provider):
        self.provider = provider
        self.ultimo_diagnostico = {}

    def process(self, principal):
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

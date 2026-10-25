"""A simulação (techdigest --simular): a pasta, a cópia do banco, a entrega em arquivo e nenhum caminho até o Telegram."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from techdigest import config, delivery, simulacao
from techdigest.delivery import telegram
from techdigest.storage.dedup import SeenStore

RAIZ = Path(__file__).resolve().parents[1]
ITEM = {
    "titulo_reescrito": "Construtora Alfa entrega a obra da BR-101", "resumo_didatico": "Resumo da obra.",
    "pontos_chave": ["Um ponto."], "por_que_importa": "Importa.", "url": "https://jornaldovale.example/obra",
    "source": "Jornal do Vale",
}


@pytest.fixture
def ambiente_isolado(monkeypatch):
    """`preparar()` escreve no ambiente do processo: o monkeypatch devolve o que havia depois do teste."""
    for nome in ("DB_PATH", "LOG_DIR", "AUDIO_DIR", "EXECUCOES_DIR", "ARQUIVO_DIR", "DELIVERY_CHANNEL", "TELEGRAM_TOKEN",
                 "TELEGRAM_CHAT_ID", simulacao.VARIAVEL):
        monkeypatch.setenv(nome, os.environ.get(nome, ""))


@pytest.fixture
def banco_de_producao(tmp_path):
    """Um banco com um item visto, só de leitura no disco, como o de produção deve ser para a simulação."""
    caminho = tmp_path / "producao" / "digest.db"
    caminho.parent.mkdir()
    SeenStore(str(caminho)).mark_seen("https://jornaldovale.example/ja-entregue")
    caminho.chmod(0o444)
    yield caminho
    caminho.chmod(0o644)


def test_preparar_copia_o_banco_lendo_a_origem_so_para_leitura(tmp_path, banco_de_producao, ambiente_isolado):
    antes = banco_de_producao.read_bytes()
    pasta = tmp_path / "simulacoes" / "primeira"
    ambiente = simulacao.preparar(pasta, banco_de_producao)
    assert banco_de_producao.read_bytes() == antes
    copia = SeenStore(ambiente["DB_PATH"])
    assert not copia.is_new("https://jornaldovale.example/ja-entregue")
    copia.mark_seen("https://jornaldovale.example/novo")            # a simulação escreve na cópia...
    assert banco_de_producao.read_bytes() == antes                   # ...e a origem não muda
    assert json.loads((pasta / simulacao.MARCA).read_text(encoding="utf-8"))["banco_origem"] == str(banco_de_producao)
    assert ambiente == {
        simulacao.VARIAVEL: str(pasta), "DB_PATH": str(pasta / "digest.db"), "LOG_DIR": str(pasta / "logs"),
        "AUDIO_DIR": str(pasta / "audio"), "EXECUCOES_DIR": str(pasta / "execucoes"), "ARQUIVO_DIR": str(pasta / "entregas"),
        "DELIVERY_CHANNEL": "arquivo",
        "TELEGRAM_TOKEN": "", "TELEGRAM_CHAT_ID": "",
    }
    assert all(os.environ[nome] == valor for nome, valor in ambiente.items())


def test_o_ambiente_da_simulacao_vale_mais_que_o_env(tmp_path, banco_de_producao, ambiente_isolado):
    env = tmp_path / ".env"
    env.write_text(f"DB_PATH={banco_de_producao}\nTELEGRAM_TOKEN=segredo\nTELEGRAM_CHAT_ID=123\n"
                   "DELIVERY_CHANNEL=telegram\n", encoding="utf-8")
    ambiente = simulacao.preparar(tmp_path / "sim", banco_de_producao)
    lida = config.Settings(_env_file=env)
    assert (lida.db_path, lida.delivery_channel, lida.telegram_token, lida.telegram_chat_id) == \
        (ambiente["DB_PATH"], "arquivo", "", "")


def test_preparar_recusa_uma_pasta_que_nao_e_de_simulacao(tmp_path, banco_de_producao, ambiente_isolado):
    with pytest.raises(simulacao.PastaRecusada, match="já existe e não é de uma simulação"):
        simulacao.preparar(banco_de_producao.parent, banco_de_producao)       # a pasta do banco de produção
    with pytest.raises(simulacao.PastaRecusada, match="precisa de --banco-origem"):
        simulacao.preparar(tmp_path / "nova", None)
    with pytest.raises(simulacao.PastaRecusada, match="não existe"):
        simulacao.preparar(tmp_path / "nova", tmp_path / "nao_existe.db")
    assert not (tmp_path / "nova").exists()


def test_uma_simulacao_anterior_continua_com_o_banco_dela(tmp_path, banco_de_producao, ambiente_isolado):
    pasta = tmp_path / "sim"
    simulacao.preparar(pasta, banco_de_producao)
    SeenStore(str(pasta / "digest.db")).mark_seen("https://jornaldovale.example/da-primeira-execucao")
    simulacao.preparar(pasta, None)                                           # a segunda execução da simulação
    assert not SeenStore(str(pasta / "digest.db")).is_new("https://jornaldovale.example/da-primeira-execucao")
    with pytest.raises(simulacao.PastaRecusada, match="já tem o banco dela"):
        simulacao.preparar(pasta, banco_de_producao)


def test_o_telegram_recusa_rodar_numa_simulacao(monkeypatch):
    chamadas = []
    monkeypatch.setattr(telegram.requests, "post", lambda *a, **k: chamadas.append(a) or pytest.fail("chegou ao Telegram"))
    with pytest.raises(RuntimeError, match="recusado numa simulação"):
        telegram._post("sendMessage", {"chat_id": "1", "text": "oi"})
    with pytest.raises(RuntimeError, match="recusado numa simulação"):
        telegram.send_item_telegram(ITEM, None)
    assert chamadas == []


def test_o_canal_arquivo_so_vale_na_simulacao(monkeypatch):
    monkeypatch.delenv(simulacao.VARIAVEL)
    with pytest.raises(RuntimeError, match="só vale na simulação"):
        delivery.deliver_item(ITEM, None)
    with pytest.raises(RuntimeError, match="só vale na simulação"):
        delivery.deliver_footer(1)


def test_a_entrega_em_arquivo_guarda_o_texto_do_telegram_o_episodio_e_o_audio(tmp_path, monkeypatch):
    from techdigest.delivery import arquivo
    monkeypatch.setattr(arquivo.settings, "arquivo_dir", str(tmp_path / "entregas"))
    audio = tmp_path / "obra.mp3"
    audio.write_bytes(b"ID3 falso")
    assert delivery.deliver_item(ITEM, None) == "arquivo"
    delivery.deliver_item(dict(ITEM, titulo_reescrito="Segunda notícia"), str(audio))
    delivery.deliver_footer(2)
    pasta = tmp_path / "entregas"
    primeira = pasta / "01_construtora-alfa-entrega-a-obra-da-br-101"
    assert primeira.with_suffix(".html").read_text(encoding="utf-8") == telegram._render_item(ITEM)
    assert json.loads(primeira.with_suffix(".json").read_text(encoding="utf-8")) == ITEM
    assert not primeira.with_suffix(".mp3").exists()
    assert (pasta / "02_segunda-notícia.mp3").read_bytes() == b"ID3 falso"
    linhas = (pasta / "entregas.txt").read_text(encoding="utf-8").splitlines()
    assert linhas[0].endswith("01_construtora-alfa-entrega-a-obra-da-br-101 · Jornal do Vale · "
                              "https://jornaldovale.example/obra · sem áudio")
    assert linhas[2].endswith("fim do lote: 2 notícias")


# A simulação de ponta a ponta roda num processo novo, como o techdigest de verdade: só assim os
# caminhos da simulação entram no ambiente antes de qualquer módulo ler a configuração. A coleta, a
# extração e a geração são falsas; o requests.post, se alguém o chamar, deixa uma marca e falha.
SIMULACAO_FALSA = """
import sys, types
from pathlib import Path

marca_do_telegram = Path(sys.argv[1])
PARAR_EM = sys.argv[2]          # o título do artigo em que uma trava da máquina dispara ("" = nenhum)
import requests
def _post_proibido(*args, **kwargs):
    marca_do_telegram.write_text("chamado")
    raise AssertionError("a simulação chamou a API do Telegram")
requests.post = _post_proibido

from techdigest.models import Article
coleta = types.ModuleType("techdigest.collectors.rss")
coleta.collect_rss = lambda: [Article(title=f"Artigo {n}", url=f"https://jornaldovale.example/{n}", source="Jornal do Vale")
                              for n in (1, 2)]
sys.modules["techdigest.collectors.rss"] = coleta
from techdigest.processing.extractor import Extracao
extracao = types.ModuleType("techdigest.processing.extractor")
extracao.Extracao = Extracao
extracao.extrair = lambda url, fallback="": Extracao("texto " * 400, url, True)
sys.modules["techdigest.processing.extractor"] = extracao
geracao = types.ModuleType("techdigest.ai.summarizer")
class QAReprovado(Exception):
    pass
class Summarizer:
    def __init__(self, provider=None):
        self.provider = provider
        self.ultimo_diagnostico = {}
    def process(self, principal):
        if principal["title"] == PARAR_EM:
            from techdigest.ai.maquina import ExecucaoInterrompida
            raise ExecucaoInterrompida("memória disponível em 3.1 GiB, abaixo do mínimo de 4.0 GiB")
        return {"titulo_reescrito": principal["title"], "resumo_didatico": "Resumo.", "pontos_chave": ["Ponto."],
                "por_que_importa": "Importa.", "personagens": [], "roteiro_podcast": [], "houve_divergencia": False,
                "fontes_citadas": ["Jornal do Vale"]}
geracao.QAReprovado, geracao.Summarizer = QAReprovado, Summarizer
geracao.TETO_PRINCIPAL, geracao.TETO_RELACIONADO = 5000, 3000   # o registro da execução os importa
sys.modules["techdigest.ai.summarizer"] = geracao

from techdigest.main import main
main(sys.argv[3:])
"""


def _rodar_techdigest(tmp_path, *argumentos, script=None):
    ambiente = dict(os.environ)
    ambiente.update({
        "XDG_STATE_HOME": str(tmp_path / "estado"),       # a trava do modelo do processo filho, longe da de verdade
        "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "nenhuma", "OPENAI_BASE_URL": "http://127.0.0.1:9",
        "RSS_FEEDS": "",                                   # se algo escapar das falsificações, não há feed para coletar
    })
    ambiente.pop(simulacao.VARIAVEL)                       # o processo filho só está numa simulação se o --simular a criar
    comando = [sys.executable, "-c", script, *argumentos] if script else [sys.executable, "-m", "techdigest", *argumentos]
    return subprocess.run(comando, cwd=tmp_path, env=ambiente, capture_output=True, text=True, timeout=120)


def test_a_simulacao_de_ponta_a_ponta_entrega_em_arquivos_e_nao_chama_o_telegram(tmp_path, banco_de_producao):
    antes = banco_de_producao.read_bytes()
    pasta = tmp_path / "simulacoes" / "ponta_a_ponta"
    marca = tmp_path / "telegram_chamado"
    saida = _rodar_techdigest(tmp_path, str(marca), "", "--simular", str(pasta), "--banco-origem", str(banco_de_producao),
                              "--sem-audio", script=SIMULACAO_FALSA)
    assert saida.returncode == 0, saida.stderr[-2000:]
    assert not marca.exists()
    assert banco_de_producao.read_bytes() == antes
    entregas = sorted(p.name for p in (pasta / "entregas").glob("*.html"))
    assert entregas == ["01_artigo-1.html", "02_artigo-2.html"]
    copia = SeenStore(str(pasta / "digest.db"))
    assert not copia.is_new("https://jornaldovale.example/1") and not copia.is_new("https://jornaldovale.example/2")
    log = (pasta / "logs" / "techdigest.log").read_text(encoding="utf-8")
    assert "Simulação em" in log and "Execução concluída: 2 notícia(s) entregue(s)" in log
    assert (tmp_path / "estado" / "techdigest" / "modelo.lock").read_text(encoding="utf-8") == ""
    [registro] = (pasta / "execucoes").iterdir()                     # o registro da execução fica na pasta da simulação
    assert len(json.loads(next(registro.glob("relatorio_*.json")).read_text(encoding="utf-8"))["episodios"]) == 2
    assert not (pasta / "AVISO.txt").exists()


def test_o_aviso_de_parada_da_simulacao_vai_para_o_aviso_txt_e_nunca_para_o_telegram(tmp_path, banco_de_producao):
    pasta = tmp_path / "simulacoes" / "com_parada"
    marca = tmp_path / "telegram_chamado"
    saida = _rodar_techdigest(tmp_path, str(marca), "Artigo 2", "--simular", str(pasta), "--banco-origem",
                              str(banco_de_producao), "--sem-audio", script=SIMULACAO_FALSA)
    assert saida.returncode == 1, saida.stderr[-2000:]
    assert not marca.exists()
    aviso = (pasta / "AVISO.txt").read_text(encoding="utf-8")
    assert "TechDigest parou às " in aviso and "memória disponível em 3.1 GiB" in aviso and "Entregues: 1 de 20" in aviso
    assert "AVISO: TechDigest parou às " in saida.stderr                  # e na saída de erro
    log = (pasta / "logs" / "techdigest.log").read_text(encoding="utf-8")
    assert "Aviso de parada: TechDigest parou às " in log and "Execução interrompida: memória disponível" in log
    copia = SeenStore(str(pasta / "digest.db"))
    assert not copia.is_new("https://jornaldovale.example/1") and copia.is_new("https://jornaldovale.example/2")


def test_techdigest_simular_recusa_a_pasta_sem_rodar_nada(tmp_path, banco_de_producao):
    alheia = tmp_path / "alheia"
    alheia.mkdir()
    (alheia / "notas.txt").write_text("não é de uma simulação", encoding="utf-8")
    saida = _rodar_techdigest(tmp_path, "--simular", str(alheia), "--banco-origem", str(banco_de_producao))
    assert saida.returncode == 1 and "já existe e não é de uma simulação" in saida.stderr
    assert sorted(p.name for p in alheia.iterdir()) == ["notas.txt"]

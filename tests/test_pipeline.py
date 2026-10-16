"""O pipeline com a trava do modelo e as travas da máquina: o que para a execução inteira, e o que fica registrado."""
import logging

import pytest

from techdigest import main as entrada
from techdigest import pipeline, trava
from techdigest.ai import maquina
from techdigest.models import Article
from techdigest.storage.dedup import SeenStore

EPISODIO = {
    "titulo_reescrito": "Construtora Alfa entrega a obra da BR-101", "resumo_didatico": "Resumo.",
    "pontos_chave": ["Um ponto."], "por_que_importa": "Importa.", "personagens": [], "roteiro_podcast": [],
    "houve_divergencia": False, "fontes_citadas": ["Jornal do Vale"],
}


class ProviderFalso:
    model = "modelo"
    ultimo_uso: dict = {}

    def chat_json(self, system, user, **opcoes):
        return {}


class SummarizerFalso:
    """Faz uma chamada ao provider por item, como o de verdade, e devolve sempre o mesmo episódio."""

    def __init__(self, provider):
        self.provider = provider

    def process(self, principal):
        self.provider.chat_json("sistema", principal["text"])
        return dict(EPISODIO)


@pytest.fixture
def execucao(monkeypatch, tmp_path):
    """Três artigos novos, a extração e a geração falsas, o modelo remoto (sem GPU) e a entrega em arquivo."""
    artigos = [Article(title=f"Artigo {n}", url=f"https://jornaldovale.example/{n}", source="Jornal do Vale")
               for n in (1, 2, 3)]
    coletas = []
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 12.0)   # as travas não dependem da máquina dos testes
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: 60.0)
    monkeypatch.setattr(pipeline.settings, "db_path", str(tmp_path / "digest.db"))
    monkeypatch.setattr(pipeline.settings, "audio_dir", str(tmp_path / "audio"))
    monkeypatch.setattr(pipeline, "collect_rss", lambda: coletas.append(1) or artigos)
    monkeypatch.setattr(pipeline, "extract_full_text", lambda url, fallback="": "texto " * 400)
    monkeypatch.setattr(pipeline, "get_provider", lambda settings: ProviderFalso())
    monkeypatch.setattr(pipeline, "Summarizer", SummarizerFalso)
    return {"artigos": artigos, "coletas": coletas, "banco": tmp_path / "digest.db"}


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


def test_com_a_trava_do_modelo_ocupada_a_execucao_nem_comeca(execucao, caplog):
    caplog.set_level(logging.INFO, logger="techdigest")
    with trava.trava_do_modelo("scripts/testar_episodio.py --amostra x"):
        with pytest.raises(trava.TravaOcupada):
            pipeline.run(sem_audio=True)
    assert execucao["coletas"] == []
    assert any(r.getMessage().startswith("Execução não começou: o modelo está em uso por scripts/testar_episodio.py")
               for r in caplog.records)


def test_sem_trava_a_execucao_entrega_e_marca_tudo(execucao, caplog):
    caplog.set_level(logging.INFO, logger="techdigest")
    pipeline.run(sem_audio=True)
    vistos = SeenStore(str(execucao["banco"]))
    assert all(not vistos.is_new(a.url) for a in execucao["artigos"])
    assert any(r.getMessage().startswith("Execução concluída: 3 notícia(s)") for r in caplog.records)


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

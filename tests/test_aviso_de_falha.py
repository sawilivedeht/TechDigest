"""O aviso de falha da execução pelo timer (`aviso_de_falha.py`): quando avisa, quando só registra, e que numa simulação
não envia nada. O ambiente (as variáveis MONITOR_*), o journal e o `deliver_aviso` são falsos."""
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from techdigest import aviso_de_falha as af
from techdigest import pipeline

ID = "75d2d02392404536b7d5b9e2685be993"     # um invocation id do systemd: 32 dígitos hexadecimais
LINHA_DO_PIPELINE = ("01:23:45 │ WARNING  │ techdigest.pipeline │ Aviso de parada: TechDigest parou às 01:23: memória "
                     "disponível em 3.1 GiB, abaixo do mínimo de 4.0 GiB. Entregues: 4 de 20; o resto volta na próxima execução.")


def _ambiente(resultado="exit-code", codigo="exited", status="1", **outras):
    ambiente = {"MONITOR_SERVICE_RESULT": resultado, "MONITOR_EXIT_CODE": codigo, "MONITOR_EXIT_STATUS": status,
                "MONITOR_INVOCATION_ID": ID, "MONITOR_UNIT": "techdigest.service"}
    ambiente.update(outras)
    return ambiente


def _journal(texto):
    """Um journal falso com `texto`, que confere o id da execução que pediram."""
    def ler(execucao):
        assert execucao == ID
        return texto
    return ler


def _journal_que_nao_se_le(execucao):
    raise AssertionError("o journal só é lido numa saída com status 1")


@pytest.fixture
def enviados(monkeypatch):
    """Fora da simulação, com o envio guardado numa lista."""
    lista = []
    monkeypatch.setattr(af, "em_simulacao", lambda: False)
    monkeypatch.setattr(af, "deliver_aviso", lista.append)
    return lista


@pytest.mark.parametrize("resultado, codigo, status, trecho", [
    ("timeout", "killed", "TERM", "passou do tempo máximo da unit (4 horas) e foi encerrado pelo systemd"),
    ("oom-kill", "killed", "KILL", "foi encerrado pelo sistema por falta de memória"),
    ("signal", "killed", "KILL", "foi encerrado pelo sinal KILL"),
    ("core-dump", "dumped", "SEGV", "caiu com o sinal SEGV (core dump)"),
    ("exit-code", "exited", "203", "o systemd não conseguiu iniciar o pipeline (status 203)"),
    ("exit-code", "exited", "2", "saiu com status 2 sem o aviso do pipeline"),
    ("start-limit-hit", "", "", "falhou no systemd (resultado start-limit-hit)"),
    ("resources", "", "", "falhou no systemd (resultado resources)"),
    ("watchdog", "killed", "ABRT", "falhou no systemd (resultado watchdog)"),
])
def test_o_que_o_pipeline_nao_consegue_avisar_sempre_avisa(enviados, resultado, codigo, status, trecho):
    assert af.executar(_ambiente(resultado, codigo, status), ler=_journal_que_nao_se_le) == 0
    assert len(enviados) == 1
    assert enviados[0].startswith("TechDigest (techdigest.service) parou às ")
    assert f": {trecho}. O que não foi entregue volta na próxima execução." in enviados[0]
    assert enviados[0].endswith("Detalhe: journalctl --user -u techdigest.service")


def test_status_1_com_o_aviso_do_pipeline_no_journal_so_registra(enviados, caplog):
    caplog.set_level(logging.INFO, logger="techdigest.aviso_de_falha")
    assert af.executar(_ambiente(), ler=_journal(f"=== TechDigest iniciando ===\n{LINHA_DO_PIPELINE}\n")) == 0
    assert enviados == []
    assert "Falha da techdigest.service já avisada pelo pipeline (saiu com status 1 depois do aviso do pipeline)" in caplog.text
    assert "Aviso de parada:" not in caplog.text


def test_status_1_sem_o_aviso_do_pipeline_avisa(enviados):
    """Um erro antes de o pipeline começar (um módulo que falta na .venv) também sai com status 1, sem aviso."""
    journal = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'edge_tts'\n"
    assert af.executar(_ambiente(), ler=_journal(journal)) == 0
    assert len(enviados) == 1
    assert ": saiu com status 1 sem o aviso do pipeline (provavelmente antes de começar)." in enviados[0]


def test_status_1_com_o_aviso_do_pipeline_nao_enviado_avisa(enviados):
    nao_enviado = "01:23:46 │ ERROR    │ techdigest.pipeline │ Aviso de parada não enviado (FalhaDeRede: Telegram/sendMessage)"
    assert af.executar(_ambiente(), ler=_journal(f"{LINHA_DO_PIPELINE}\n{nao_enviado}\n")) == 0
    assert len(enviados) == 1
    assert ": saiu com status 1, e o aviso do pipeline não foi enviado (o motivo está no journal)." in enviados[0]


def test_status_1_com_o_journal_ilegivel_avisa(enviados):
    assert af.executar(_ambiente(), ler=lambda execucao: None) == 0
    assert len(enviados) == 1
    assert ": saiu com status 1, e o journal não pôde ser lido para saber se o pipeline avisou." in enviados[0]


def test_sem_as_variaveis_do_systemd_avisa_com_o_texto_generico(enviados):
    assert af.executar({}, ler=_journal_que_nao_se_le) == 0
    assert len(enviados) == 1
    assert enviados[0].startswith("TechDigest (techdigest.service) parou às ")
    assert ": falhou, e o systemd não passou o motivo (sem as variáveis MONITOR_*)." in enviados[0]


def test_o_aviso_vai_para_o_log_com_a_linha_do_pipeline(enviados, caplog):
    caplog.set_level(logging.INFO, logger="techdigest.aviso_de_falha")
    af.executar(_ambiente("oom-kill", "killed", "KILL"))
    linhas = [r.getMessage() for r in caplog.records if r.name == "techdigest.aviso_de_falha"]
    assert linhas == [f"Aviso de parada: {enviados[0]}"]      # o resumo_lotes.py mostra as linhas que começam assim


def test_o_envio_que_falha_registra_e_sai_com_1(monkeypatch, caplog):
    def canal_fora_do_ar(texto):
        raise RuntimeError("Telegram/sendMessage: falha de rede")
    monkeypatch.setattr(af, "em_simulacao", lambda: False)
    monkeypatch.setattr(af, "deliver_aviso", canal_fora_do_ar)
    assert af.executar(_ambiente("timeout", "killed", "TERM")) == 1
    assert "Aviso de parada não enviado (RuntimeError: Telegram/sendMessage: falha de rede)" in caplog.text


def test_numa_simulacao_nao_envia_nada(monkeypatch, caplog):
    """Os testes rodam como numa simulação (conftest): o aviso recusa antes de decidir e de enviar."""
    def envio_proibido(texto):
        raise AssertionError("numa simulação o aviso de falha não envia nada")
    monkeypatch.setattr(af, "deliver_aviso", envio_proibido)
    assert af.executar(_ambiente("timeout", "killed", "TERM"), ler=_journal_que_nao_se_le) == 2
    assert "Aviso de falha recusado numa simulação" in caplog.text


def test_main_le_as_variaveis_do_ambiente(enviados, monkeypatch):
    monkeypatch.setattr(af, "setup_logging", lambda: None)    # sem mexer no logging dos outros testes
    for nome, valor in _ambiente("signal", "killed", "TERM", MONITOR_UNIT="techdigest.service").items():
        monkeypatch.setenv(nome, valor)
    assert af.main() == 0
    assert ": foi encerrado pelo sinal TERM." in enviados[0]


def test_as_linhas_procuradas_no_journal_sao_as_que_o_pipeline_escreve(monkeypatch, caplog):
    """O aviso procura no journal o que `pipeline._avisar` escreve no log: se o texto de lá mudar, este teste falha."""
    def canal_fora_do_ar(texto):
        raise RuntimeError("fora do ar")
    monkeypatch.setattr(pipeline, "deliver_aviso", canal_fora_do_ar)
    pipeline._avisar("TechDigest parou às 01:23: teste.")
    mensagens = [r.getMessage() for r in caplog.records if r.name == "techdigest.pipeline"]
    assert mensagens[0].startswith(af.LINHA_DO_AVISO)
    assert mensagens[1].startswith(af.LINHA_DO_AVISO_NAO_ENVIADO)
    assert af.decidir(_ambiente(), ler=_journal(mensagens[0])).avisar is False
    assert af.decidir(_ambiente(), ler=_journal("\n".join(mensagens))).avisar is True


class _Saida:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout = returncode, stdout


def test_ler_journal_pede_so_as_linhas_daquela_execucao(monkeypatch):
    pedidos = []

    def journalctl(argumentos, **opcoes):
        pedidos.append((argumentos, opcoes))
        return _Saida(stdout=LINHA_DO_PIPELINE)
    monkeypatch.setattr(af.subprocess, "run", journalctl)
    assert af.ler_journal(ID) == LINHA_DO_PIPELINE
    argumentos, opcoes = pedidos[0]
    assert argumentos == ["journalctl", "--user", f"_SYSTEMD_INVOCATION_ID={ID}", "--output=cat", "--no-pager", "--quiet"]
    assert opcoes["timeout"] == af.TEMPO_DO_JOURNALCTL


@pytest.mark.parametrize("falha", [
    FileNotFoundError("journalctl"),
    subprocess.TimeoutExpired("journalctl", 30),
    _Saida(returncode=1),
])
def test_ler_journal_que_falha_devolve_none(monkeypatch, falha):
    def journalctl(argumentos, **opcoes):
        if isinstance(falha, Exception):
            raise falha
        return falha
    monkeypatch.setattr(af.subprocess, "run", journalctl)
    assert af.ler_journal(ID) is None


@pytest.mark.parametrize("execucao", [None, "", "abc", ID.upper(), ID + "0", "x" * 32])
def test_ler_journal_sem_um_id_valido_nem_chama_o_journalctl(monkeypatch, execucao):
    def journalctl(argumentos, **opcoes):
        raise AssertionError("sem um invocation id válido, o journalctl não é chamado")
    monkeypatch.setattr(af.subprocess, "run", journalctl)
    assert af.ler_journal(execucao) is None


def test_status_1_sem_o_id_da_execucao_avisa(enviados, monkeypatch):
    monkeypatch.setattr(af.subprocess, "run", lambda *a, **k: pytest.fail("sem o id, o journalctl não é chamado"))
    ambiente = _ambiente()
    del ambiente["MONITOR_INVOCATION_ID"]
    assert af.executar(ambiente) == 0
    assert ": saiu com status 1, e o journal não pôde ser lido para saber se o pipeline avisou." in enviados[0]


# O aviso leve: ele tem de rodar mesmo quando um pacote que só o pipeline usa está quebrado na .venv.

PACOTES_SO_DO_PIPELINE = ("edge_tts", "trafilatura", "feedparser", "aiohttp", "lxml", "techdigest.pipeline")
FRASE_DA_PRODUCAO = ("Um pacote que só o pipeline usa (edge-tts, trafilatura, feedparser, aiohttp, lxml...) quebrado ou "
                     "ausente derruba o pipeline e não o aviso, que avisa.")
PRODUCAO = Path(__file__).resolve().parents[1] / "docs" / "producao.md"
_IMPORTA_O_AVISO = f"""
import json, sys
from techdigest import config
config.Settings.model_config["env_file"] = None      # como no conftest: o .env da pasta não entra
import techdigest.aviso_de_falha
print(json.dumps([nome for nome in {PACOTES_SO_DO_PIPELINE!r} if nome in sys.modules]))
"""


def test_o_aviso_nao_importa_os_pacotes_que_so_o_pipeline_usa():
    """Num processo novo (o Python da .venv, isolado do ambiente com -I), importar o aviso não traz nenhum pacote que só o
    pipeline usa: um deles quebrado na .venv (o ModuleNotFoundError de um erro antes de começar) derruba o pipeline, e o
    aviso ainda roda e avisa. É o que `docs/producao.md` promete em "O que avisa no Telegram"."""
    assert FRASE_DA_PRODUCAO in " ".join(PRODUCAO.read_text(encoding="utf-8").split()), (
        "a frase citada por este teste saiu de docs/producao.md (\"O que avisa no Telegram\"): atualize FRASE_DA_PRODUCAO")
    saida = subprocess.run([sys.executable, "-I", "-c", _IMPORTA_O_AVISO], capture_output=True, text=True, timeout=60)
    assert saida.returncode == 0, f"o import do aviso falhou num processo novo:\n{saida.stderr}"
    importados = json.loads(saida.stdout.strip().splitlines()[-1])
    assert importados == [], (
        f"importar techdigest.aviso_de_falha trouxe {', '.join(importados)}, que só o pipeline usa. Com isso deixa de ser "
        f"verdade a frase de docs/producao.md, em \"O que avisa no Telegram\": \"{FRASE_DA_PRODUCAO}\" Um desses pacotes "
        "quebrado na .venv derrubaria também o aviso, e o erro antes de começar não chegaria ao Telegram.")

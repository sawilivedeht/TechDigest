"""Isola os testes do ambiente: nada do .env nem das variáveis da sessão entra, e nada de produção é tocado.

Cada módulo do techdigest lê as configurações quando é importado (`settings = Settings()`), então
este arquivo roda antes de qualquer outro import do pacote, como o pytest garante para o
conftest.py. Ele desliga a leitura do .env, tira do ambiente toda variável com nome de
configuração, fixa os limites do QA nos valores em vigor e aponta banco, log, áudio, entregas,
registro das execuções, log do Ollama, contagem da parte fixa e trava do modelo para uma pasta temporária. Assim os
testes dão o mesmo resultado em qualquer pasta (a principal, a worktree), com ou sem .env, e
nenhum deles escreve no banco de
produção nem prende a trava de verdade. Os testes também rodam como numa simulação
(TECHDIGEST_SIMULACAO): o envio ao Telegram recusa rodar, mesmo que algum teste chegue até ele.
"""
import os
import tempfile
from pathlib import Path

from techdigest import config

PASTA_DOS_TESTES = Path(tempfile.mkdtemp(prefix="techdigest-testes-"))

# Os limites do QA com que os testes contam: os valores em vigor (o 650 é o teto por personagem do QA,
# acima dos 480 que os prompts pedem, como margem).
QA_DOS_TESTES = {
    "QA_MIN_POR_PERSONAGEM": "240", "QA_MAX_POR_PERSONAGEM": "650", "QA_MIN_HELENA_COM_DEBATE": "180",
    "QA_MIN_LADO_FINO": "120", "QA_MAX_LADO_FINO": "200", "QA_MIN_TOTAL": "600", "QA_MAX_TOTAL": "1300",
    "QA_MIN_FRASES": "7", "QA_MAX_FRASES": "10",
}

config.Settings.model_config["env_file"] = None          # o .env da pasta não conta
for _campo in config.Settings.model_fields:              # nem uma variável exportada na sessão
    for _nome in list(os.environ):
        if _nome.lower() == _campo:
            del os.environ[_nome]
os.environ.update(QA_DOS_TESTES)
os.environ.update({
    "DB_PATH": str(PASTA_DOS_TESTES / "digest.db"),
    "LOG_DIR": str(PASTA_DOS_TESTES / "logs"),
    "AUDIO_DIR": str(PASTA_DOS_TESTES / "audio"),
    "EXECUCOES_DIR": str(PASTA_DOS_TESTES / "execucoes"),
    "OLLAMA_LOG": str(PASTA_DOS_TESTES / "ollama_serve.log"),
    "TOKENS_FIXOS": str(PASTA_DOS_TESTES / "tokens_fixos.json"),
    "ARQUIVO_DIR": str(PASTA_DOS_TESTES / "entregas"),
    "DELIVERY_CHANNEL": "arquivo",                        # nenhum teste chega ao Telegram, nem por engano
    "TECHDIGEST_SIMULACAO": str(PASTA_DOS_TESTES),       # e o _post do Telegram recusa rodar
})
config.settings = config.Settings()

from techdigest import trava  # noqa: E402  (depois das variáveis, como todo import do pacote)

trava.CAMINHO_DA_TRAVA = PASTA_DOS_TESTES / "modelo.lock"


import pytest  # noqa: E402

from techdigest.ai import janela  # noqa: E402


@pytest.fixture(autouse=True)
def _parte_fixa_isolada(monkeypatch, tmp_path):
    """A contagem da parte fixa (ai/janela.py) começa vazia em cada teste: nem a memória nem o arquivo passam de um
    teste para outro, e um provedor falso que conta não empresta a contagem a outro que não conta."""
    monkeypatch.setattr(janela, "_memoria", {})
    monkeypatch.setattr(janela.settings, "tokens_fixos", str(tmp_path / "tokens_fixos.json"))

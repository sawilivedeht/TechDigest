"""O modo de simulação (`techdigest --simular <pasta>`): o pipeline de verdade, sem entregar nada a ninguém.

Coleta, extração, LLM e áudio são reais; a entrega vai para arquivos em `<pasta>/entregas` (o
texto como o Telegram o receberia, o episódio e o mp3), pelo canal `arquivo`; o banco é uma cópia,
feita com o de origem aberto só para leitura; o log, o áudio e o registro de cada execução
(`<pasta>/execucoes`) também ficam na pasta, longe do log que `scripts/resumo_lotes.py` lê por
padrão, e o aviso de parada vai para `<pasta>/AVISO.txt`. A trava do modelo é a de sempre (ver `trava.py`).

`preparar()` roda antes de qualquer import do pacote que leia a configuração: cada módulo cria o
seu `Settings()` ao ser importado, então os caminhos e o canal da simulação têm de estar no
ambiente antes disso (no pydantic-settings, o ambiente vale mais que o .env). Por isso este módulo
só usa a biblioteca padrão.

Nenhum caminho da simulação chama a API do Telegram: o canal é `arquivo`, o token e o chat do
Telegram ficam vazios no ambiente, e `delivery/telegram._post` recusa rodar com `VARIAVEL` no
ambiente.
"""
import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

MARCA = ".simulacao"                  # o arquivo que diz que a pasta é de uma simulação, e de onde veio o banco
VARIAVEL = "TECHDIGEST_SIMULACAO"     # no ambiente durante a simulação: o envio ao Telegram recusa rodar


class PastaRecusada(ValueError):
    """A pasta ou o banco de origem não servem para uma simulação: a mensagem diz por quê."""


def em_simulacao() -> bool:
    """Se esta execução é uma simulação (ou um teste, que o conftest marca do mesmo jeito)."""
    return bool(os.environ.get(VARIAVEL))


def preparar(pasta: str | Path, banco_origem: str | Path | None) -> dict[str, str]:
    """Prepara a pasta da simulação e põe no ambiente os caminhos e o canal dela; devolve o que pôs.

    Uma pasta nova (que não existe, ou vazia) precisa de `banco_origem`, copiado para
    `<pasta>/digest.db` com o original aberto só para leitura. Uma pasta de simulação anterior (com
    a marca) continua de onde parou, com o banco dela, e então `banco_origem` não vale: é assim que
    se simula uma segunda execução. Qualquer outra pasta é recusada, para a simulação nunca
    escrever num banco que não é dela.
    """
    pasta = Path(pasta).expanduser().resolve()
    banco = pasta / "digest.db"
    if (pasta / MARCA).exists():
        if banco_origem:
            raise PastaRecusada(f"{pasta} é de uma simulação anterior e já tem o banco dela: tire --banco-origem "
                                f"para continuar dali, ou use outra pasta")
        if not banco.exists():
            raise PastaRecusada(f"{pasta} é de uma simulação anterior, mas o banco dela ({banco.name}) não está lá")
    else:
        if pasta.exists() and (not pasta.is_dir() or any(pasta.iterdir())):
            raise PastaRecusada(f"{pasta} já existe e não é de uma simulação: use uma pasta nova ou vazia")
        if not banco_origem:
            raise PastaRecusada("uma simulação nova precisa de --banco-origem <digest.db>, o banco de que ela parte, "
                                "aberto só para leitura e copiado para a pasta")
        origem = Path(banco_origem).expanduser().resolve()
        if not origem.is_file():
            raise PastaRecusada(f"o banco de origem {origem} não existe")
        pasta.mkdir(parents=True, exist_ok=True)
        _copiar_somente_leitura(origem, banco)
        (pasta / MARCA).write_text(json.dumps(
            {"criada_em": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}", "banco_origem": str(origem),
             "comando": " ".join(sys.argv)},
            ensure_ascii=False, indent=1), encoding="utf-8")
    ambiente = {
        VARIAVEL: str(pasta),
        "DB_PATH": str(banco),
        "LOG_DIR": str(pasta / "logs"),
        "AUDIO_DIR": str(pasta / "audio"),
        "EXECUCOES_DIR": str(pasta / "execucoes"),
        "ARQUIVO_DIR": str(pasta / "entregas"),
        "DELIVERY_CHANNEL": "arquivo",
        "TELEGRAM_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
    }
    os.environ.update(ambiente)
    return ambiente


def _copiar_somente_leitura(origem: Path, destino: Path) -> None:
    """Copia o banco com o original aberto em mode=ro: nenhuma escrita chega a ele, nem a de um mark_seen."""
    fonte = sqlite3.connect(f"{origem.as_uri()}?mode=ro", uri=True)
    try:
        alvo = sqlite3.connect(destino)
        try:
            fonte.backup(alvo)
        finally:
            alvo.close()
    finally:
        fonte.close()

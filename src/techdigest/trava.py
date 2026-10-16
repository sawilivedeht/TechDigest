"""A trava do modelo: uma execução por vez em tudo o que chama o modelo, nas duas pastas do projeto.

O pipeline (e o `techdigest --simular`), `scripts/testar_episodio.py` e `scripts/testar_agrupamento.py
--etapa3` pegam a mesma trava, um arquivo fixo fora das pastas do projeto, ao lado do log do Ollama:
assim a pasta principal, a worktree e uma simulação nunca disputam o modelo, nem uma simulação e um
script de teste rodando ao mesmo tempo. O caminho não vem do .env de propósito: um .env diferente em
cada pasta separaria as travas.

É um flock sem espera: quem a encontra ocupada não espera, sai com a mensagem de quem a tem. O
sistema solta o flock quando o processo termina, mesmo morto, então não sobra trava velha; o texto
que fica no arquivo só identifica quem a tem enquanto ela está presa.
"""
import datetime
import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from techdigest.config import PASTA_DE_ESTADO

CAMINHO_DA_TRAVA = PASTA_DE_ESTADO / "modelo.lock"


class TravaOcupada(RuntimeError):
    """Outra execução está com a trava do modelo: a mensagem diz quem é."""


def _quem_sou() -> str:
    """O comando desta execução, como aparece para quem encontrar a trava ocupada."""
    comando = " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]) if sys.argv and sys.argv[0] else "python"
    return comando[:200]


@contextmanager
def trava_do_modelo(quem: str | None = None):
    """Prende a trava do modelo enquanto o bloco roda; levanta TravaOcupada se outra execução a tem."""
    caminho = Path(CAMINHO_DA_TRAVA)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    arquivo = open(caminho, "a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            arquivo.seek(0)
            dono = arquivo.read().strip() or "outra execução, que não se identificou"
            raise TravaOcupada(f"o modelo está em uso por {dono}; espere essa execução terminar") from None
        arquivo.seek(0)
        arquivo.truncate()
        arquivo.write(f"{quem or _quem_sou()} (PID {os.getpid()}, desde {datetime.datetime.now():%d/%m %H:%M}, "
                      f"na pasta {Path.cwd()})")
        arquivo.flush()
        try:
            yield
        finally:
            arquivo.seek(0)
            arquivo.truncate()
            arquivo.flush()
    finally:
        arquivo.close()     # fechar o arquivo solta o flock

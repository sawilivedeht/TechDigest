"""A trava do modelo (techdigest.trava): uma execução por vez, e quem a encontra ocupada sabe quem a tem."""
import subprocess
import sys

import pytest

from techdigest import trava


def test_a_trava_ocupada_diz_quem_a_tem_e_fica_livre_depois():
    with trava.trava_do_modelo("scripts/testar_episodio.py --amostra x"):
        with pytest.raises(trava.TravaOcupada,
                           match=r"em uso por scripts/testar_episodio.py --amostra x \(PID \d+, desde .*, na pasta "):
            with trava.trava_do_modelo("techdigest"):
                pass
    with trava.trava_do_modelo("techdigest"):   # solta ao sair do bloco
        assert trava.CAMINHO_DA_TRAVA.read_text(encoding="utf-8").startswith("techdigest (PID ")
    assert trava.CAMINHO_DA_TRAVA.read_text(encoding="utf-8") == ""     # livre, sem a identificação de quem saiu


def test_a_trava_solta_mesmo_quando_o_bloco_falha():
    with pytest.raises(ValueError):
        with trava.trava_do_modelo("a"):
            raise ValueError("falhou")
    with trava.trava_do_modelo("b"):
        pass


def test_a_trava_vale_entre_processos_e_o_sistema_a_solta_quando_o_dono_morre():
    codigo = (
        "import fcntl, sys, time\n"
        f"arquivo = open({str(trava.CAMINHO_DA_TRAVA)!r}, 'a+')\n"
        "fcntl.flock(arquivo, fcntl.LOCK_EX)\n"
        "arquivo.seek(0); arquivo.truncate(); arquivo.write('outro processo (PID 1, desde 16/10 08:00)'); arquivo.flush()\n"
        "print('preso', flush=True)\n"
        "time.sleep(60)\n"
    )
    dono = subprocess.Popen([sys.executable, "-c", codigo], stdout=subprocess.PIPE, text=True)
    try:
        assert dono.stdout.readline().strip() == "preso"
        with pytest.raises(trava.TravaOcupada, match=r"em uso por outro processo \(PID 1, desde 16/10 08:00\)"):
            with trava.trava_do_modelo("eu"):
                pass
    finally:
        dono.kill()
        dono.wait()
    with trava.trava_do_modelo("eu"):   # o dono morreu sem soltar: o flock sai com ele, não sobra trava velha
        pass

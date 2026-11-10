"""A rodada de scripts/rodada.py: a sessão de teste sempre para, o FIM sempre é gravado, o vigia para a sessão.

O systemctl, o nvidia-smi e o systemd-inhibit são falsos (scripts no PATH, com o estado das units em arquivos), a
memória é falsa e os comandos são processos Python inofensivos. O bloqueio do sono falso roda o `tail --pid` de
verdade, como o systemd-inhibit faria.
"""
import datetime
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import rodada
from techdigest.ai import gpu

PY = sys.executable
SCRIPTS = Path(rodada.__file__).resolve().parent

SYSTEMCTL = r"""#!/usr/bin/env bash
E="$RODADA_FALSA"
echo "$*" >> "$E/systemctl.log"
[ "$1" = "--user" ] && shift
acao=$1; unidade=$2
estado() { cat "$E/estado_$1" 2>/dev/null || echo inactive; }
case "$acao" in
  is-active)
    s=$(estado "$unidade"); echo "$s"; [ "$s" = active ] && exit 0; exit 3 ;;
  start)
    if [ -e "$E/start_falha" ]; then      # a subida que falha no meio: o target fica subindo e o Ollama no ar
      echo activating > "$E/estado_techdigest-teste.target"; echo active > "$E/estado_ollama.service"
      echo "Job for ollama.service failed because the control process exited with error code." >&2; exit 1
    fi
    echo active > "$E/estado_techdigest-teste.target"; echo active > "$E/estado_ollama.service" ;;
  stop)
    if [ ! -e "$E/nao_para" ]; then
      echo inactive > "$E/estado_techdigest-teste.target"; echo inactive > "$E/estado_ollama.service"
    fi ;;
esac
exit 0
"""

NVIDIA_SMI = r"""#!/usr/bin/env bash
if [ -e "$RODADA_FALSA/sem_gpu" ]; then
  echo "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver."; exit 9
fi
echo "NVIDIA GeForce Falsa, 8188 MiB"
"""

SYSTEMD_INHIBIT = r"""#!/usr/bin/env bash
E="$RODADA_FALSA"
if [ "$1" = "--list" ]; then
  [ -e "$E/bloqueio_pid" ] && echo "TechDigest 1000 dono $(cat "$E/bloqueio_pid") systemd-inhibit sleep:idle rodada block"
  exit 0
fi
echo "$*" >> "$E/inhibit.log"
if [ -e "$E/bloqueio_recusado" ]; then echo "Failed to inhibit: Access denied" >&2; exit 1; fi
echo $$ > "$E/bloqueio_pid"
while [[ "$1" == --* ]]; do shift; done
exec "$@"
"""

# Um comando que marca que começou e espera a sessão de teste parar (no máximo 10 s): só o vigia a para enquanto o
# comando roda, porque a rodada está esperando ele terminar.
ESPERA_A_SESSAO_PARAR = (
    "import os, sys, time\n"
    "open(sys.argv[1], 'w').close()\n"
    "estado = os.path.join(os.environ['RODADA_FALSA'], 'estado_techdigest-teste.target')\n"
    "fim = time.time() + 10\n"
    "while time.time() < fim and open(estado).read().strip() == 'active':\n"
    "    time.sleep(0.05)\n"
    "print('a sessão parou' if open(estado).read().strip() != 'active' else 'a sessão continuou')\n"
)


class Falsos:
    def __init__(self, base: Path):
        self.base = base
        self.estado = base / "estado"
        self.log = base / "ollama_serve.log"
        self.pasta = base / "agrupamento" / "rodada_teste"

    def chamadas(self) -> list[str]:
        arquivo = self.estado / "systemctl.log"
        return arquivo.read_text().splitlines() if arquivo.exists() else []

    def acoes(self) -> list[str]:
        """As chamadas do systemctl que mudam alguma coisa (start e stop)."""
        return [c for c in self.chamadas() if not c.startswith("--user is-active")]

    def marca(self, nome: str) -> None:
        (self.estado / nome).touch()

    def ativa(self, unidade: str) -> None:
        (self.estado / f"estado_{unidade}").write_text("active\n")

    def estado_de(self, unidade: str) -> str:
        arquivo = self.estado / f"estado_{unidade}"
        return arquivo.read_text().strip() if arquivo.exists() else "inactive"

    def log_do_ollama(self, library: str = "CUDA") -> None:
        agora = datetime.datetime.now().astimezone().isoformat(timespec="milliseconds")
        self.log.write_text(
            f'time={agora} level=INFO source=routes.go:2373 msg="server config" env="map[]"\n'
            f'time={agora} level=INFO source=types.go:32 msg="inference compute" id=0 library={library} '
            'compute=8.6 name=CUDA0 description="NVIDIA GeForce Falsa" total="8.0 GiB" available="7.6 GiB"\n')

    def argumentos(self, *resto: str) -> list[str]:
        return ["--pasta", str(self.pasta), "--pedido", "pedido de teste", "--log-ollama", str(self.log), *resto]

    def arquivo_de_comandos(self, *linhas: str) -> Path:
        arquivo = self.base / "comandos.txt"
        arquivo.write_text("".join(linha + "\n" for linha in linhas), encoding="utf-8")
        return arquivo

    def script(self, texto: str) -> Path:
        """Um script Python numa linha só do arquivo de comandos."""
        arquivo = self.base / "auxiliar.py"
        arquivo.write_text(texto, encoding="utf-8")
        return arquivo

    def fim(self) -> str:
        return (self.pasta / "FIM").read_text(encoding="utf-8")

    def andamento(self) -> str:
        return (self.pasta / "andamento.txt").read_text(encoding="utf-8")


@pytest.fixture
def falsos(tmp_path, monkeypatch):
    binarios = tmp_path / "bin"
    binarios.mkdir()
    for nome, texto in (("systemctl", SYSTEMCTL), ("nvidia-smi", NVIDIA_SMI), ("systemd-inhibit", SYSTEMD_INHIBIT)):
        (binarios / nome).write_text(texto)
        (binarios / nome).chmod(0o755)
    f = Falsos(tmp_path)
    f.estado.mkdir()
    f.log_do_ollama()
    monkeypatch.setenv("PATH", f"{binarios}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("RODADA_FALSA", str(f.estado))
    monkeypatch.setattr(rodada, "PASTAS_PROIBIDAS", ())          # o tmp_path dos testes fica em /tmp
    monkeypatch.setattr(rodada, "memoria_disponivel", lambda: 16.0)
    monkeypatch.setattr(rodada, "INTERVALO_DO_VIGIA", 0.02)
    monkeypatch.setattr(rodada, "ESPERA_DA_PARADA", 0.5)
    monkeypatch.setattr(gpu, "inicio_do_servidor_local", time.time)
    return f


def _morto(pid: int, espera: float = 5.0) -> bool:
    fim = time.time() + espera
    while time.time() < fim:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


# ------------------------------------------------------------ o caminho certo

def test_uma_rodada_com_arquivo_e_repeticao_roda_tudo_registra_e_para_a_sessao(falsos):
    comando_1 = (f"{shlex.quote(PY)} -c \"import os, sys; print(os.getcwd()); "
                 "print(os.environ.get('PYTHONUNBUFFERED')); print(sys.argv[1])\" vez_{vez}")
    arquivo = falsos.arquivo_de_comandos("# a rodada de teste", "", comando_1, f"{shlex.quote(PY)} -c \"print('segundo')\"")
    assert rodada.main(falsos.argumentos("--repetir", "2", "--comandos", str(arquivo))) == 0

    pasta = falsos.pasta
    assert (pasta / "comandos.txt").read_bytes() == arquivo.read_bytes()
    for vez in (1, 2):
        assert (pasta / f"saida_1_vez{vez}.txt").read_text().splitlines() == [str(rodada.RAIZ), "1", f"vez_{vez}"]
        assert (pasta / f"saida_2_vez{vez}.txt").read_text() == "segundo\n"
    andamento = falsos.andamento()
    inicios = [linha.split(" ", 2)[2] for linha in andamento.splitlines() if " início do " in linha]
    assert [i.split(":")[0] for i in inicios] == ["início do comando 1, vez 1", "início do comando 2, vez 1",
                                                 "início do comando 1, vez 2", "início do comando 2, vez 2"]
    commit = subprocess.run(["git", "-C", str(rodada.RAIZ), "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    assert "pedido: pedido de teste" in andamento
    assert f"commit {commit}" in andamento
    assert "GPU pelo nvidia-smi: NVIDIA GeForce Falsa, 8188 MiB" in andamento
    assert "GPU depois da subida: Ollama: NVIDIA GeForce Falsa (8.0 GiB)" in andamento

    assert falsos.acoes() == ["--user start techdigest-teste.target", "--user stop techdigest-teste.target"]
    assert falsos.estado_de(rodada.SESSAO) == "inactive"
    fim = falsos.fim()
    assert fim.splitlines()[0] == "status 0"
    assert "sessão de teste: parada (techdigest-teste.target inactive, ollama.service inactive)" in fim
    assert "memória disponível mínima: 16384 MiB (16.0 GiB)" in fim
    assert "motivo" not in fim

    bloqueio = (falsos.estado / "inhibit.log").read_text()
    assert bloqueio.strip() == (f"--what=sleep:idle --who=TechDigest --why=rodada rodada_teste "
                                f"tail --pid={os.getpid()} -f /dev/null")
    assert _morto(int((falsos.estado / "bloqueio_pid").read_text()))      # o bloqueio foi solto no fim
    vigia = (pasta / "vigia_memoria.log").read_text().splitlines()
    assert vigia[0].endswith("disponível 16384 MiB · mínimo 16384 MiB")
    assert vigia[-1].endswith("rodada terminada · mínimo 16384 MiB")


def test_um_comando_depois_do_traco_duplo_e_gravado_em_comandos_txt(falsos):
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('oi')")) == 0
    assert (falsos.pasta / "comandos.txt").read_text() == shlex.join([PY, "-c", "print('oi')"]) + "\n"
    assert (falsos.pasta / "saida_1.txt").read_text() == "oi\n"
    assert falsos.fim().startswith("status 0\n")


# ------------------------------------------------------------ antes de começar: nada é criado, subido nem parado

@pytest.mark.parametrize("unidade", [rodada.SESSAO, rodada.OLLAMA])
def test_com_a_sessao_de_teste_ou_o_ollama_no_ar_a_rodada_nao_comeca_e_nao_para_nada(falsos, unidade, capsys):
    falsos.ativa(unidade)
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('não devia rodar')")) == 1
    assert "Rodada não começou" in capsys.readouterr().err
    assert not falsos.pasta.exists()
    assert falsos.acoes() == []               # a sessão de outra rodada nunca é parada por esta
    assert falsos.estado_de(unidade) == "active"


def test_sem_o_driver_da_nvidia_a_rodada_nao_comeca(falsos, capsys):
    falsos.marca("sem_gpu")
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('não devia rodar')")) == 1
    assert "NVIDIA" in capsys.readouterr().err
    assert not falsos.pasta.exists()
    assert falsos.acoes() == []


# ------------------------------------------------------------ erros de argumento: status 2, antes de tudo

@pytest.mark.parametrize("resto", [
    ["--comandos", "{arquivo}", "--", PY, "-c", "1"],              # os dois
    [],                                                            # nenhum
    ["--"],                                                        # nada depois de --
    ["--repetir", "3", "--", PY, "-c", "print('sem vez')"],        # --repetir sem {vez}
    ["--", PY, "-c", "print('{vez}')"],                            # {vez} sem --repetir
    ["--repetir", "1", "--", PY, "-c", "print('{vez}')"],          # uma volta só
    ["--comandos", "{base}/nao_existe.txt"],
])
def test_argumentos_errados_saem_com_2_sem_chamar_o_systemctl(falsos, resto):
    arquivo = falsos.arquivo_de_comandos(f"{PY} -c 1")
    resto = [r.replace("{arquivo}", str(arquivo)).replace("{base}", str(falsos.base)) for r in resto]
    with pytest.raises(SystemExit) as saida:
        rodada.main(falsos.argumentos(*resto))
    assert saida.value.code == 2
    assert falsos.chamadas() == []
    assert not falsos.pasta.exists()


def test_a_pasta_que_ja_existe_e_recusada(falsos):
    falsos.pasta.mkdir(parents=True)
    with pytest.raises(SystemExit) as saida:
        rodada.main(falsos.argumentos("--", PY, "-c", "1"))
    assert saida.value.code == 2
    assert falsos.chamadas() == []
    assert list(falsos.pasta.iterdir()) == []


def test_a_pasta_em_tmp_e_recusada_pelo_caminho_resolvido(falsos, monkeypatch, capsys):
    """O data/agrupamento das worktrees é um link: o que conta é para onde ele aponta."""
    proibida = falsos.base / "proibida"
    proibida.mkdir()
    (falsos.base / "link").symlink_to(proibida)
    monkeypatch.setattr(rodada, "PASTAS_PROIBIDAS", (proibida,))
    with pytest.raises(SystemExit) as saida:
        rodada.main(["--pasta", str(falsos.base / "link" / "rodada_x"), "--pedido", "x", "--log-ollama", str(falsos.log),
                     "--", PY, "-c", "1"])
    assert saida.value.code == 2
    assert "fica em /tmp" in capsys.readouterr().err
    assert falsos.chamadas() == []


def test_tmp_e_o_scratchpad_sao_proibidos_e_o_resto_nao():
    assert rodada.PASTAS_PROIBIDAS == (Path("/tmp"),)
    assert rodada.proibida(Path("/tmp"))
    assert rodada.proibida(Path("/tmp/claude-1000/scratchpad/rodada"))
    assert not rodada.proibida(Path("/tmpx/rodada"))
    assert not rodada.proibida(Path("/home/sytw/Projetos/techdigest/data/agrupamento/rodada"))


def test_caminhos_relativos_valem_a_partir_da_raiz_da_worktree():
    assert rodada.resolver("data/agrupamento/x_20261110") == (rodada.RAIZ / "data/agrupamento/x_20261110").resolve()
    assert rodada.resolver("/home/alguem/rodada") == Path("/home/alguem/rodada")


@pytest.mark.parametrize("linha", [
    "a | b", "a || b", "a & b", "a && b", "a ; b",
    "a > f", "a >> f", "a < f", "a 2> f", "a 2>&1", "a &> f",
    "a >f", "a >>f", "a <f", "a 2>f", "a &>f",                     # a forma colada
    'a "sem fim',
])
def test_o_arquivo_com_coisa_do_shell_e_erro_com_a_linha(falsos, linha, capsys):
    arquivo = falsos.arquivo_de_comandos("# comentário", linha)
    with pytest.raises(SystemExit) as saida:
        rodada.main(falsos.argumentos("--comandos", str(arquivo)))
    assert saida.value.code == 2
    assert "linha 2" in capsys.readouterr().err
    assert falsos.chamadas() == []


def test_o_arquivo_nao_expande_nada_e_pula_comentarios(tmp_path):
    arquivo = tmp_path / "comandos.txt"
    arquivo.write_text("# comentário\n\n   # recuado\na \"x|y\" 'p>q' ~/$HOME/* a;b\n", encoding="utf-8")
    assert rodada.ler_comandos(arquivo) == [["a", "x|y", "p>q", "~/$HOME/*", "a;b"]]


def test_o_arquivo_so_com_comentarios_e_erro(falsos):
    arquivo = falsos.arquivo_de_comandos("# só comentário", "")
    with pytest.raises(SystemExit) as saida:
        rodada.main(falsos.argumentos("--comandos", str(arquivo)))
    assert saida.value.code == 2


# ------------------------------------------------------------ falhas depois da pasta: a sessão para, o FIM é gravado

def test_o_comando_que_falha_para_a_rodada_com_o_status_dele(falsos):
    arquivo = falsos.arquivo_de_comandos(f"{PY} -c 'import sys; sys.exit(3)'", f"{PY} -c 'print(2)'")
    assert rodada.main(falsos.argumentos("--comandos", str(arquivo))) == 3
    assert not (falsos.pasta / "saida_2.txt").exists()
    fim = falsos.fim()
    assert fim.splitlines()[0] == "status 3"
    assert "comando 2: " in fim and fim.split("comando 2: ")[1].splitlines()[0].endswith("não rodou")
    assert "--user stop techdigest-teste.target" in falsos.acoes()
    assert falsos.estado_de(rodada.SESSAO) == "inactive"


def test_o_comando_que_nao_existe_sai_com_127(falsos):
    assert rodada.main(falsos.argumentos("--", "/caminho/que/nao/existe")) == 127
    assert "o comando não rodou" in (falsos.pasta / "saida_1.txt").read_text()
    assert falsos.fim().startswith("status 127\n")
    assert "--user stop techdigest-teste.target" in falsos.acoes()


def test_a_subida_que_falha_no_meio_tambem_e_parada(falsos):
    falsos.marca("start_falha")
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('não devia rodar')")) == 1
    assert falsos.acoes() == ["--user start techdigest-teste.target", "--user stop techdigest-teste.target"]
    assert falsos.estado_de(rodada.SESSAO) == "inactive" and falsos.estado_de(rodada.OLLAMA) == "inactive"
    assert not (falsos.pasta / "saida_1.txt").exists()
    fim = falsos.fim()
    assert fim.startswith("status 1\n")
    assert "a sessão de teste não subiu (systemctl saiu com 1: Job for ollama.service failed" in fim
    assert "sessão de teste: parada" in fim


def test_a_gpu_que_nao_passa_depois_da_subida_para_a_sessao(falsos):
    falsos.log_do_ollama(library="cpu")
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('não devia rodar')")) == 1
    assert falsos.acoes() == ["--user start techdigest-teste.target", "--user stop techdigest-teste.target"]
    assert not (falsos.pasta / "saida_1.txt").exists()
    fim = falsos.fim()
    assert fim.startswith("status 1\n")
    assert "a GPU não passou na conferência depois da subida: o Ollama não achou a GPU" in fim


def test_o_bloqueio_do_sono_recusado_nao_sobe_a_sessao(falsos):
    falsos.marca("bloqueio_recusado")
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('não devia rodar')")) == 1
    assert falsos.acoes() == []
    fim = falsos.fim()
    assert fim.startswith("status 1\n")
    assert "o bloqueio do sono foi recusado (systemd-inhibit saiu com 1: Failed to inhibit: Access denied)" in fim
    assert "sessão de teste: não subiu" in fim


def test_a_sessao_que_nao_para_da_status_1_e_fica_no_fim(falsos):
    falsos.marca("nao_para")
    assert rodada.main(falsos.argumentos("--", PY, "-c", "print('ok')")) == 1
    fim = falsos.fim()
    assert fim.startswith("status 1\n")
    assert "sessão de teste: CONTINUA NO AR (techdigest-teste.target active, ollama.service active)" in fim
    assert "pare-a com systemctl --user stop techdigest-teste.target" in fim


# ------------------------------------------------------------ o vigia

def test_o_vigia_para_a_sessao_abaixo_do_limite_e_nenhum_comando_novo_comeca(falsos, monkeypatch):
    comecou = falsos.base / "comecou"
    monkeypatch.setattr(rodada, "memoria_disponivel", lambda: 2.5 if comecou.exists() else 16.0)
    arquivo = falsos.arquivo_de_comandos(shlex.join([PY, str(falsos.script(ESPERA_A_SESSAO_PARAR)), str(comecou)]),
                                         f"{PY} -c 'print(2)'")
    assert rodada.main(falsos.argumentos("--comandos", str(arquivo))) == 1
    assert (falsos.pasta / "saida_1.txt").read_text() == "a sessão parou\n"     # parou durante o comando
    assert not (falsos.pasta / "saida_2.txt").exists()
    vigia = (falsos.pasta / "vigia_memoria.log").read_text()
    assert "memória disponível em 2560 MiB: parando a sessão de teste" in vigia
    assert vigia.splitlines()[-1].endswith("rodada terminada · mínimo 2560 MiB")
    fim = falsos.fim()
    assert fim.startswith("status 1\n")
    assert "o vigia parou a sessão de teste (memória disponível em 2560 MiB, abaixo de 3 GiB)" in fim


def _memoria_que_quebra(comecou: Path):
    def ler():
        if comecou.exists():
            raise RuntimeError("leitura quebrada")
        return 16.0
    return ler


def _memoria_ilegivel(comecou: Path):
    return lambda: None if comecou.exists() else 16.0


@pytest.mark.parametrize("memoria, erro", [
    (_memoria_que_quebra, "RuntimeError: leitura quebrada"),
    (_memoria_ilegivel, "RuntimeError: não deu para ler a memória disponível em /proc/meminfo"),
])
def test_o_vigia_que_morre_para_a_sessao_e_a_rodada_nao_segue_sem_ele(falsos, monkeypatch, memoria, erro):
    comecou = falsos.base / "comecou"
    monkeypatch.setattr(rodada, "memoria_disponivel", memoria(comecou))
    arquivo = falsos.arquivo_de_comandos(shlex.join([PY, str(falsos.script(ESPERA_A_SESSAO_PARAR)), str(comecou)]),
                                         f"{PY} -c 'print(2)'")
    assert rodada.main(falsos.argumentos("--comandos", str(arquivo))) == 1
    assert (falsos.pasta / "saida_1.txt").read_text() == "a sessão parou\n"
    assert not (falsos.pasta / "saida_2.txt").exists()
    assert f"o vigia parou por um erro ({erro}): parando a sessão de teste" in (
        falsos.pasta / "vigia_memoria.log").read_text()
    assert f"o vigia parou por um erro ({erro}): a rodada não continua sem vigia" in falsos.andamento()
    assert falsos.fim().startswith("status 1\n")


# ------------------------------------------------------------ a interrupção

@pytest.mark.parametrize("sinal", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_a_interrupcao_repassa_um_sigint_ao_comando_para_a_sessao_e_grava_o_fim(falsos, sinal):
    antes = {s: signal.getsignal(s) for s in rodada.SINAIS}
    comando = f"import os, time; os.kill(os.getppid(), {int(sinal)}); time.sleep(60)"
    inicio = time.monotonic()
    assert rodada.main(falsos.argumentos("--", PY, "-c", comando)) == 128 + sinal
    assert time.monotonic() - inicio < 20
    assert {s: signal.getsignal(s) for s in rodada.SINAIS} == antes        # os tratadores de antes voltam
    assert "--user stop techdigest-teste.target" in falsos.acoes()
    assert falsos.estado_de(rodada.SESSAO) == "inactive"
    fim = falsos.fim()
    assert fim.startswith(f"status {128 + sinal}\n")
    assert "status 130, morto por SIGINT" in fim                           # o comando recebeu o SIGINT repassado
    assert f"interrompida por {sinal.name}" in fim


ENVOLTORIO = f"""
import sys, time
sys.path.insert(0, {str(SCRIPTS)!r})
import rodada
from techdigest.ai import gpu
gpu.inicio_do_servidor_local = time.time
rodada.memoria_disponivel = lambda: 16.0
rodada.PASTAS_PROIBIDAS = ()
sys.exit(rodada.main(sys.argv[1:]))
"""


@pytest.mark.parametrize("sinal, ao_grupo", [(signal.SIGINT, True), (signal.SIGTERM, False)])
def test_num_processo_novo_o_ctrl_c_para_a_sessao_e_nao_deixa_o_comando_vivo(falsos, sinal, ao_grupo):
    """Como no terminal: o Ctrl+C vai ao grupo de processos da rodada; o SIGTERM, só a ela."""
    marca = falsos.base / "comando_pid"
    comando = ["--", PY, "-c", "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(120)",
               str(marca)]
    processo = subprocess.Popen([PY, "-c", ENVOLTORIO, *falsos.argumentos(*comando)], cwd=falsos.base,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        fim = time.time() + 30
        while not (marca.exists() and marca.read_text()) and time.time() < fim:
            time.sleep(0.05)
        assert marca.exists(), processo.communicate(timeout=5)
        if ao_grupo:
            os.killpg(processo.pid, sinal)
        else:
            os.kill(processo.pid, sinal)
        saida, erro = processo.communicate(timeout=60)
    finally:
        if processo.poll() is None:
            processo.kill()
    assert processo.returncode == 128 + sinal, erro.decode()
    assert _morto(int(marca.read_text()))
    assert _morto(int((falsos.estado / "bloqueio_pid").read_text()))
    assert "--user stop techdigest-teste.target" in falsos.acoes()
    assert falsos.estado_de(rodada.SESSAO) == "inactive"
    assert falsos.fim().startswith(f"status {128 + sinal}\n")

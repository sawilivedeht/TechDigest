"""Uma rodada com o modelo local: a sessão de teste, o bloqueio do sono, o vigia de memória e os comandos.

Faz o que o vigia_memoria.sh e o rodar.sh de cada rodada faziam, copiados e editados à mão (frente 7 das melhorias
de 07/11/2026):

    .venv/bin/python scripts/rodada.py --pasta data/agrupamento/<nome>_<AAAAMMDD> --pedido "<texto>" -- <comando> [args...]
    .venv/bin/python scripts/rodada.py --pasta ... --pedido "..." --comandos <arquivo>
    .venv/bin/python scripts/rodada.py --pasta ... --pedido "..." --repetir 5 -- <comando com {vez}>

1. Antes de tudo, os argumentos: --comandos ou -- <comando>, um dos dois; a pasta não pode existir nem ficar em /tmp;
   o arquivo de comandos tem um comando por linha, sem nada do shell; --repetir pede um {vez} nos comandos. Um erro
   aqui sai com status 2 e não toca em nada.
2. A sessão de teste e a ollama.service têm de estar fora do ar e o nvidia-smi tem de responder; senão a rodada não
   começa (status 1) e nada é criado, subido ou parado: a sessão de outra rodada nunca é parada por esta.
3. Cria a pasta, o comandos.txt e o andamento.txt (pedido, data, worktree, branch, commit e comandos).
4. Bloqueia o sono para a rodada inteira: um systemd-inhibit com um `tail --pid` deste processo, que solta o bloqueio
   sozinho se ele morrer. Liga o vigia de memória, sobe a sessão de teste e confere a GPU como os freios da máquina.
5. Roda os comandos um por vez, sem shell, a partir da raiz desta worktree, cada saída num arquivo da pasta, e para no
   primeiro que falha. Um Ctrl+C (ou SIGTERM, SIGHUP) é repassado ao comando como um único SIGINT.
6. No fim, sempre: para a sessão de teste, confere que ela e o Ollama pararam, solta o bloqueio, grava o FIM com o
   status e o resumo, e imprime o resumo.

Caminhos relativos (--pasta, --comandos, --log-ollama) valem a partir da raiz desta worktree, de onde os comandos rodam.
Os freios da máquina dos comandos continuam valendo: o script não os contorna e não pega a trava do modelo.

Status de saída: 0 com tudo certo; 128 + o sinal numa interrupção (130 no Ctrl+C); o status do comando que falhou (127
se ele não existe); 1 quando a rodada não começa, o vigia para a sessão ou morre, o bloqueio do sono é recusado, a
sessão não sobe, a GPU não passa ou a sessão não para; 2 num erro de argumento.
"""
import argparse
import datetime
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from techdigest.ai import gpu
from techdigest.ai.maquina import memoria_disponivel

RAIZ = Path(__file__).resolve().parents[1]       # a worktree deste script: de onde os comandos rodam
SESSAO = "techdigest-teste.target"
OLLAMA = "ollama.service"
FORA_DO_AR = ("inactive", "failed")              # o que o systemctl is-active diz de uma unit parada
PASTAS_PROIBIDAS = (Path("/tmp"),)               # some no reinício (o scratchpad do Claude Code fica nela)
MIN_MEMORIA_GIB = 3.0                            # o vigia para a sessão de teste abaixo disto
INTERVALO_DO_VIGIA = 2.0                         # segundos entre duas leituras da memória
INTERVALO_DO_LOG = 60.0                          # segundos entre duas linhas do vigia_memoria.log
ESPERA_DO_BLOQUEIO = 10.0                        # segundos para o bloqueio do sono aparecer no systemd-inhibit --list
ESPERA_DA_PARADA = 120.0                         # segundos para a sessão de teste e o Ollama pararem no fim
ESPERA_DO_SIGINT = 30.0                          # segundos que o comando interrompido tem para sair, depois do SIGINT
ESPERA_DO_SIGTERM = 10.0                         # e depois do SIGTERM, antes do SIGKILL
TEMPO_DO_SYSTEMCTL = 120                         # segundos para um systemctl start ou stop
VEZ = "{vez}"                                    # nos comandos, o número da volta do --repetir
OPERADORES = frozenset({"|", "||", "&", "&&", ";"})    # do shell, como palavra solta no arquivo
REDIRECIONAMENTOS = (">", "<", "2>", "&>")             # do shell, no começo de uma palavra do arquivo
SINAIS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Interrompida(Exception):
    """Um Ctrl+C, SIGTERM ou SIGHUP chegou: a rodada para e limpa."""


class FalhaDaRodada(Exception):
    """Algo da própria rodada falhou (o bloqueio do sono, a sessão de teste, a GPU): a mensagem diz o quê."""


@dataclass
class Plano:
    """O que os argumentos pedem, já conferido."""
    pasta: Path
    pedido: str
    comandos: list[list[str]]
    arquivo: Path | None          # o arquivo dos comandos, ou None se o comando veio depois de --
    repetir: int | None
    log_ollama: str


@dataclass
class Execucao:
    """Um comando numa volta: o que rodou e como terminou (status None: não rodou)."""
    numero: int
    vez: int | None
    palavras: list[str]
    status: int | None = None
    segundos: float = 0.0
    sinal: str = ""

    @property
    def rotulo(self) -> str:
        return f"comando {self.numero}" + (f", vez {self.vez}" if self.vez is not None else "")

    @property
    def arquivo_da_saida(self) -> str:
        return f"saida_{self.numero}.txt" if self.vez is None else f"saida_{self.numero}_vez{self.vez}.txt"


def duracao(segundos: float) -> str:
    total = int(round(segundos))
    horas, resto = divmod(total, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min {seg} s" if minutos else f"{seg} s"


def resolver(caminho: str) -> Path:
    """O caminho absoluto, com os links seguidos; um relativo vale a partir da raiz desta worktree."""
    p = Path(caminho)
    return (p if p.is_absolute() else RAIZ / p).resolve()


def proibida(pasta: Path) -> bool:
    """Se a pasta (já resolvida) fica numa das PASTAS_PROIBIDAS."""
    for base in PASTAS_PROIBIDAS:
        base = base.resolve()
        if pasta == base or base in pasta.parents:
            return True
    return False


def ler_comandos(caminho: Path) -> list[list[str]]:
    """Os comandos do arquivo, um por linha, separados como o shlex.split separa; levanta ValueError com a linha.

    Linhas vazias e as que começam com # não contam. Nada é expandido (~, $VAR e * chegam ao comando como estão),
    e uma palavra do shell (|, ||, &, &&, ;, ou uma que começa com >, <, 2> ou &>) é erro: o comando roda sem shell.
    """
    comandos = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        try:
            palavras = shlex.split(linha)
        except ValueError as e:
            raise ValueError(f"{caminho}, linha {numero}: {e}") from None
        for palavra in palavras:
            if palavra in OPERADORES or palavra.startswith(REDIRECIONAMENTOS):
                raise ValueError(f"{caminho}, linha {numero}: {palavra!r} é do shell, e os comandos rodam sem shell "
                                 "(sem |, ;, &, && nem redirecionamento; a saída de cada um já vai para um arquivo "
                                 "da pasta)")
        comandos.append(palavras)
    if not comandos:
        raise ValueError(f"{caminho}: nenhum comando (um por linha; a linha que começa com # é comentário)")
    return comandos


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rodada.py",
        usage="%(prog)s --pasta PASTA --pedido TEXTO [--repetir N] [--log-ollama ARQUIVO] "
              "(--comandos ARQUIVO | -- COMANDO [ARGS...])",
        description="Uma rodada com o modelo local: sobe e sempre para a sessão de teste, bloqueia o sono, vigia a "
                    "memória e roda os comandos, cada saída num arquivo da pasta.")
    p.add_argument("--pasta", required=True,
                   help="a pasta da rodada, que não pode existir (data/agrupamento/<nome>_<AAAAMMDD>)")
    p.add_argument("--pedido", required=True, help="o pedido do dono, para o andamento.txt")
    p.add_argument("--comandos", metavar="ARQUIVO", help="um comando por linha; é copiado para a pasta")
    p.add_argument("--repetir", type=int, metavar="N",
                   help="roda a lista inteira N vezes; {vez} nos comandos vira o número da volta")
    p.add_argument("--log-ollama", metavar="ARQUIVO",
                   help="o log do ollama serve (padrão: OLLAMA_LOG, o da unit ollama.service)")
    return p


def montar_plano(argv: list[str]) -> Plano:
    """Os argumentos conferidos; um erro sai com status 2 (argparse) antes de tocar em qualquer coisa."""
    parser = _parser()
    if "--" in argv:
        corte = argv.index("--")
        opcoes, comando = argv[:corte], argv[corte + 1:]
    else:
        opcoes, comando = argv, None
    args = parser.parse_args(opcoes)
    if args.comandos is not None and comando is not None:
        parser.error("use --comandos ARQUIVO ou -- COMANDO, não os dois")
    if args.comandos is None and comando is None:
        parser.error("falta o comando: -- COMANDO [ARGS...] ou --comandos ARQUIVO")
    if comando == []:
        parser.error("nenhum comando depois de --")
    arquivo = None
    if args.comandos is not None:
        arquivo = resolver(args.comandos)
        try:
            comandos = ler_comandos(arquivo)
        except OSError as e:
            parser.error(f"não deu para ler {arquivo}: {e.strerror}")
        except ValueError as e:
            parser.error(str(e))
    else:
        comandos = [comando]
    tem_vez = any(VEZ in palavra for palavras in comandos for palavra in palavras)
    if args.repetir is not None:
        if args.repetir < 2:
            parser.error("--repetir pede 2 voltas ou mais; para uma volta só, rode sem --repetir")
        if not tem_vez:
            parser.error("--repetir sem nenhum {vez} nos comandos: as voltas gravariam na mesma pasta, e o "
                         "refazer_qa.py só lê o relatório mais recente de cada pasta; ponha o {vez} na pasta de saída "
                         "do comando (por exemplo --pasta <nome>/vez_{vez})")
    elif tem_vez:
        parser.error("{vez} nos comandos sem --repetir")
    pasta = resolver(args.pasta)
    if pasta.exists() or pasta.is_symlink():
        parser.error(f"a pasta {pasta} já existe: cada rodada numa pasta nova")
    if proibida(pasta):
        parser.error(f"a pasta {pasta} fica em /tmp, que some no reinício: use data/agrupamento/<nome>_<AAAAMMDD>")
    if args.log_ollama is not None:
        log = str(resolver(args.log_ollama))
    else:
        from techdigest.config import settings   # só aqui: importar a configuração lê o .env, como nos outros scripts
        log = settings.ollama_log
    return Plano(pasta, args.pedido, comandos, arquivo, args.repetir, log)


def estado_da_unidade(unidade: str) -> str:
    """O que o systemctl --user is-active diz da unit (active, inactive, failed...); 'desconhecido' se não diz nada."""
    try:
        saida = subprocess.run(["systemctl", "--user", "is-active", unidade], capture_output=True, text=True,
                               timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"desconhecido ({type(e).__name__})"
    return saida.stdout.strip() or f"desconhecido (systemctl saiu com {saida.returncode})"


def conferir_antes() -> str:
    """A sessão de teste e o Ollama fora do ar e o driver da NVIDIA respondendo; devolve a GPU, ou levanta FalhaDaRodada."""
    for unidade in (SESSAO, OLLAMA):
        estado = estado_da_unidade(unidade)
        if estado not in FORA_DO_AR:
            raise FalhaDaRodada(f"{unidade} está {estado}: outra rodada, ou a execução real, está no ar (uma rodada "
                                "por vez na máquina inteira)")
    try:
        return gpu.driver_da_nvidia()
    except gpu.SemGPU as e:
        raise FalhaDaRodada(f"sem a GPU, nada sobe: {e}") from None


def _git(*argumentos: str) -> str | None:
    try:
        saida = subprocess.run(["git", "-C", str(RAIZ), *argumentos], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return saida.stdout.strip() if saida.returncode == 0 else None


class Vigia(threading.Thread):
    """Lê a memória disponível a cada INTERVALO_DO_VIGIA e para a sessão de teste abaixo de MIN_MEMORIA_GIB.

    Os freios dos scripts só olham a memória antes de cada chamada; o vigia olha também durante a carga e a geração.
    Se ele morre por um erro (a memória ilegível também é um), a sessão para do mesmo jeito: a rodada não continua
    sem vigia.
    """

    def __init__(self, rodada: "Rodada"):
        super().__init__(name="vigia", daemon=True)
        self.rodada = rodada
        self.log = rodada.plano.pasta / "vigia_memoria.log"
        self.minimo_mib: int | None = None
        self.parou: str | None = None       # por que parou a sessão (a memória baixa)
        self.falhou: str | None = None      # o erro que o matou
        self.encerrado = False
        self._fim = threading.Event()

    def registra(self, texto: str) -> None:
        with open(self.log, "a", encoding="utf-8") as arquivo:
            arquivo.write(f"{datetime.datetime.now():%d/%m %H:%M:%S} {texto}\n")

    def run(self) -> None:
        try:
            ultimo = None
            while not self._fim.is_set():
                disponivel = memoria_disponivel()
                if disponivel is None:
                    raise RuntimeError("não deu para ler a memória disponível em /proc/meminfo")
                mib = int(disponivel * 1024)
                self.minimo_mib = mib if self.minimo_mib is None else min(self.minimo_mib, mib)
                if disponivel < MIN_MEMORIA_GIB:
                    self.parou = f"memória disponível em {mib} MiB, abaixo de {MIN_MEMORIA_GIB:g} GiB"
                    self.registra(f"memória disponível em {mib} MiB: parando a sessão de teste")
                    self.rodada.anota(f"o vigia está parando a sessão de teste: {self.parou}")
                    self.rodada.parar_a_sessao()
                    return
                agora = time.monotonic()
                if ultimo is None or agora - ultimo >= INTERVALO_DO_LOG:
                    self.registra(f"disponível {mib} MiB · mínimo {self.minimo_mib} MiB")
                    ultimo = agora
                self._fim.wait(INTERVALO_DO_VIGIA)
        except BaseException as erro:
            self.falhou = f"{type(erro).__name__}: {erro}"
            passos = (lambda: self.registra(f"o vigia parou por um erro ({self.falhou}): parando a sessão de teste"),
                      lambda: self.rodada.anota(f"o vigia parou por um erro ({self.falhou}): a rodada não continua "
                                                "sem vigia, parando a sessão de teste"),
                      self.rodada.parar_a_sessao)
            for passo in passos:
                try:
                    passo()
                except Exception:
                    traceback.print_exc()

    def problema(self) -> str | None:
        """Por que a rodada não pode seguir por causa do vigia, ou None."""
        if self.parou:
            return f"o vigia parou a sessão de teste ({self.parou})"
        if self.falhou:
            return f"o vigia parou por um erro ({self.falhou}): a rodada não continua sem vigia"
        if self.ident is not None and not self.is_alive() and not self.encerrado:
            return "o vigia não está rodando: a rodada não continua sem vigia"
        return None

    def encerrar(self) -> None:
        """No fim da rodada: para a leitura e grava a última linha, com o mínimo."""
        if self.ident is None:
            return          # não chegou a ligar
        self._fim.set()
        self.join(timeout=TEMPO_DO_SYSTEMCTL + 30)
        self.encerrado = True
        minimo = f"{self.minimo_mib} MiB" if self.minimo_mib is not None else "sem leitura"
        self.registra(f"rodada terminada · mínimo {minimo}")


class Rodada:
    """Uma rodada da pasta criada à limpeza: `executar()` devolve o status de saída."""

    def __init__(self, plano: Plano, driver: str):
        self.plano, self.driver = plano, driver
        voltas = [None] if plano.repetir is None else list(range(1, plano.repetir + 1))
        self.execucoes = [Execucao(numero, vez, [p.replace(VEZ, str(vez)) for p in palavras] if vez else list(palavras))
                          for vez in voltas for numero, palavras in enumerate(plano.comandos, 1)]
        self.inicio = time.monotonic()
        self.pasta_criada = False
        self.sessao_minha = False         # só a sessão que esta rodada subiu é parada por ela
        self.sessao_parada: bool | None = None    # None: a sessão não chegou a subir
        self.estados_no_fim: dict[str, str] = {}
        self.bloqueio: subprocess.Popen | None = None
        self.interrupcao: int | None = None
        self.falhas: list[str] = []
        self.vigia = Vigia(self)
        self.ambiente = dict(os.environ, PYTHONUNBUFFERED="1")
        self._trava_do_andamento = threading.Lock()
        self._trava_da_sessao = threading.Lock()

    # ------------------------------------------------------------ registro

    def _escreve(self, linha: str) -> None:
        with self._trava_do_andamento:
            print(linha, flush=True)
            if self.pasta_criada:
                with open(self.plano.pasta / "andamento.txt", "a", encoding="utf-8") as arquivo:
                    arquivo.write(linha + "\n")

    def anota(self, texto: str) -> None:
        self._escreve(f"{datetime.datetime.now():%d/%m %H:%M:%S} {texto}")

    # ------------------------------------------------------------ etapas

    def _ao_sinal(self, numero, _quadro) -> None:
        for sinal in SINAIS:          # daqui em diante, outro sinal não interrompe a limpeza
            signal.signal(sinal, signal.SIG_IGN)
        if self.interrupcao is None:
            self.interrupcao = numero
        raise Interrompida(signal.Signals(numero).name)

    def executar(self) -> int:
        anteriores = {sinal: signal.signal(sinal, self._ao_sinal) for sinal in SINAIS}
        try:
            try:
                self._etapas()
            except Interrompida:
                pass
            except FalhaDaRodada as e:
                self.falhas.append(str(e))
                self.anota(f"rodada parada: {e}")
            except Exception as e:
                traceback.print_exc()
                self.falhas.append(f"erro inesperado ({type(e).__name__}: {e})")
                self.anota(f"rodada parada por um erro inesperado ({type(e).__name__}: {e})")
        except Interrompida:
            pass        # chegou enquanto outra falha era registrada
        finally:
            for sinal in SINAIS:
                signal.signal(sinal, signal.SIG_IGN)
            self._encerrar()
            for sinal, tratador in anteriores.items():
                signal.signal(sinal, tratador)
        return self.status

    def _etapas(self) -> None:
        self._criar_a_pasta()
        self._bloquear_o_sono()
        self.vigia.start()                # antes da subida: a carga do Ollama também é vigiada
        if self._vigia_em_ordem():
            self.sessao_minha = True      # antes do start: uma subida que falha no meio também é parada no fim
            self._subir_a_sessao()
            self._conferir_a_gpu()
            self._rodar_os_comandos()

    def _criar_a_pasta(self) -> None:
        pasta = self.plano.pasta
        pasta.mkdir(parents=True)
        self.pasta_criada = True
        if self.plano.arquivo is not None:
            shutil.copyfile(self.plano.arquivo, pasta / "comandos.txt")
            origem = f"de {self.plano.arquivo}, copiados para comandos.txt"
        else:
            (pasta / "comandos.txt").write_text(shlex.join(self.plano.comandos[0]) + "\n", encoding="utf-8")
            origem = "da linha de comando, gravado em comandos.txt"
        commit = _git("rev-parse", "--short", "HEAD") or "desconhecido"
        branch = _git("branch", "--show-current") or "sem branch"
        sujo = ", com mudanças fora do commit" if _git("status", "--porcelain") else ""
        self.anota(f"rodada {pasta.name}")
        self._escreve(f"pedido: {self.plano.pedido}")
        self._escreve(f"worktree: {RAIZ} (branch {branch}, commit {commit}{sujo})")
        self._escreve(f"pasta: {pasta}")
        self._escreve(f"comandos ({origem}):")
        for numero, palavras in enumerate(self.plano.comandos, 1):
            self._escreve(f"  {numero}. {shlex.join(palavras)}")
        if self.plano.repetir is not None:
            self._escreve(f"voltas: {self.plano.repetir} ({VEZ} de 1 a {self.plano.repetir})")
        self._escreve(f"GPU pelo nvidia-smi: {self.driver}")

    def _bloquear_o_sono(self) -> None:
        comando = ["systemd-inhibit", "--what=sleep:idle", "--who=TechDigest", f"--why=rodada {self.plano.pasta.name}",
                   "tail", f"--pid={os.getpid()}", "-f", "/dev/null"]
        try:
            self.bloqueio = subprocess.Popen(comando, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.PIPE, start_new_session=True)
        except OSError as e:
            raise FalhaDaRodada(f"o bloqueio do sono não começou ({e}); nada subiu") from None
        limite = time.monotonic() + ESPERA_DO_BLOQUEIO
        while not self._bloqueio_listado():
            if self.bloqueio.poll() is not None:
                erro = self.bloqueio.stderr.read().decode("utf-8", "replace").strip()
                raise FalhaDaRodada(f"o bloqueio do sono foi recusado (systemd-inhibit saiu com "
                                    f"{self.bloqueio.returncode}: {erro or 'sem mensagem'}); nada subiu")
            if time.monotonic() > limite:
                raise FalhaDaRodada(f"o bloqueio do sono não aparece no systemd-inhibit --list depois de "
                                    f"{ESPERA_DO_BLOQUEIO:g} s; nada subiu")
            time.sleep(0.2)
        self.anota(f"sono bloqueado durante a rodada (systemd-inhibit, PID {self.bloqueio.pid})")

    def _bloqueio_listado(self) -> bool:
        try:
            saida = subprocess.run(["systemd-inhibit", "--list", "--no-pager"], capture_output=True, text=True,
                                   timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any("TechDigest" in linha and str(self.bloqueio.pid) in linha.split()
                   for linha in saida.stdout.splitlines())

    def _subir_a_sessao(self) -> None:
        self.anota(f"subindo a sessão de teste (systemctl --user start {SESSAO})")
        try:
            saida = subprocess.run(["systemctl", "--user", "start", SESSAO], capture_output=True, text=True,
                                   timeout=TEMPO_DO_SYSTEMCTL)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise FalhaDaRodada(f"a sessão de teste não subiu ({type(e).__name__}: {e})") from None
        if saida.returncode != 0:
            mensagem = (saida.stderr or saida.stdout).strip().splitlines()
            raise FalhaDaRodada(f"a sessão de teste não subiu (systemctl saiu com {saida.returncode}: "
                                f"{mensagem[0] if mensagem else 'sem mensagem'})")

    def _conferir_a_gpu(self) -> None:
        try:
            linhas = gpu.conferir_antes_de_carregar(self.plano.log_ollama)
        except gpu.SemGPU as e:
            raise FalhaDaRodada(f"a GPU não passou na conferência depois da subida: {e}") from None
        for linha in linhas:
            self.anota(f"GPU depois da subida: {linha}")

    def _vigia_em_ordem(self) -> bool:
        problema = self.vigia.problema()
        if problema:
            self.anota(f"a rodada não segue: {problema}")
        return problema is None

    def _rodar_os_comandos(self) -> None:
        for execucao in self.execucoes:
            if not self._vigia_em_ordem():
                return
            self._rodar(execucao)
            if execucao.status != 0:
                self.anota(f"os comandos seguintes não rodam: o {execucao.rotulo} saiu com status {execucao.status}")
                return
        self._vigia_em_ordem()

    def _rodar(self, execucao: Execucao) -> None:
        self.anota(f"início do {execucao.rotulo}: {shlex.join(execucao.palavras)} (saída em "
                   f"{execucao.arquivo_da_saida})")
        inicio = time.monotonic()
        processo = None
        with open(self.plano.pasta / execucao.arquivo_da_saida, "wb") as arquivo:
            try:
                # No seu grupo de processos: o Ctrl+C do terminal chega só aqui, e o comando recebe um único SIGINT.
                processo = subprocess.Popen(execucao.palavras, cwd=RAIZ, env=self.ambiente, stdin=subprocess.DEVNULL,
                                            stdout=arquivo, stderr=subprocess.STDOUT, process_group=0)
                retorno = processo.wait()
            except Interrompida:
                if processo is not None:
                    retorno = self._encerrar_o_comando(processo, execucao)
                    self._fim_do_comando(execucao, retorno, inicio)
                raise
            except OSError as e:
                arquivo.write(f"rodada.py: o comando não rodou: {e}\n".encode())
                retorno = 127 if isinstance(e, FileNotFoundError) else 126
        self._fim_do_comando(execucao, retorno, inicio)

    def _fim_do_comando(self, execucao: Execucao, retorno: int, inicio: float) -> None:
        execucao.segundos = time.monotonic() - inicio
        if retorno < 0:
            execucao.sinal = signal.Signals(-retorno).name
            execucao.status = 128 - retorno
        else:
            execucao.status = retorno
        sinal = f", morto por {execucao.sinal}" if execucao.sinal else ""
        self.anota(f"fim do {execucao.rotulo}: status {execucao.status}{sinal}, {duracao(execucao.segundos)}")

    def _encerrar_o_comando(self, processo: subprocess.Popen, execucao: Execucao) -> int:
        """Um SIGINT ao grupo do comando; sem saída em ESPERA_DO_SIGINT, SIGTERM; depois, SIGKILL."""
        for sinal, espera in ((signal.SIGINT, ESPERA_DO_SIGINT), (signal.SIGTERM, ESPERA_DO_SIGTERM),
                              (signal.SIGKILL, None)):
            if processo.poll() is not None:
                break
            self.anota(f"mandando {sinal.name} ao {execucao.rotulo}")
            try:
                os.killpg(processo.pid, sinal)
            except ProcessLookupError:
                pass
            try:
                processo.wait(espera)
                break
            except subprocess.TimeoutExpired:
                continue
        return processo.wait()

    # ------------------------------------------------------------ limpeza

    def parar_a_sessao(self) -> None:
        """systemctl stop da sessão de teste, se foi esta rodada que a subiu (o vigia também chama)."""
        if not self.sessao_minha:
            return
        with self._trava_da_sessao:
            self.anota(f"parando a sessão de teste (systemctl --user stop {SESSAO})")
            try:
                saida = subprocess.run(["systemctl", "--user", "stop", SESSAO], capture_output=True, text=True,
                                       timeout=TEMPO_DO_SYSTEMCTL)
            except (OSError, subprocess.TimeoutExpired) as e:
                self.anota(f"o systemctl stop falhou ({type(e).__name__}: {e})")
                return
            if saida.returncode != 0:
                self.anota(f"o systemctl stop saiu com {saida.returncode}: {(saida.stderr or saida.stdout).strip()}")

    def _parar_e_conferir(self) -> None:
        if not self.sessao_minha:
            return
        self.parar_a_sessao()
        limite = time.monotonic() + ESPERA_DA_PARADA
        while True:
            self.estados_no_fim = {unidade: estado_da_unidade(unidade) for unidade in (SESSAO, OLLAMA)}
            if all(estado in FORA_DO_AR for estado in self.estados_no_fim.values()):
                self.sessao_parada = True
                break
            if time.monotonic() > limite:
                self.sessao_parada = False
                break
            time.sleep(1)
        estados = ", ".join(f"{unidade} {estado}" for unidade, estado in self.estados_no_fim.items())
        if self.sessao_parada:
            self.anota(f"sessão de teste parada ({estados})")
        else:
            self.anota(f"A SESSÃO DE TESTE CONTINUA NO AR ({estados}): pare-a com systemctl --user stop {SESSAO}")

    def _soltar_o_bloqueio(self) -> None:
        if self.bloqueio is None:
            return
        if self.bloqueio.poll() is None:
            try:
                os.killpg(self.bloqueio.pid, signal.SIGTERM)
                self.bloqueio.wait(5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(self.bloqueio.pid, signal.SIGKILL)
                self.bloqueio.wait()
        self.bloqueio.stderr.close()

    def _encerrar(self) -> None:
        if self.interrupcao is not None:
            self.anota(f"rodada interrompida por {signal.Signals(self.interrupcao).name}: parando tudo (outro "
                       "Ctrl+C não interrompe a limpeza)")
        for passo in (self._parar_e_conferir, self.vigia.encerrar, self._soltar_o_bloqueio, self._gravar_o_fim):
            try:
                passo()
            except Exception as e:
                traceback.print_exc()
                self.falhas.append(f"erro na limpeza ({type(e).__name__}: {e})")

    @property
    def status(self) -> int:
        if self.interrupcao is not None:
            return 128 + self.interrupcao
        for execucao in self.execucoes:
            if execucao.status not in (None, 0):
                return execucao.status
        if self.vigia.problema() or self.falhas or self.sessao_parada is False:
            return 1
        return 0

    def motivos(self) -> list[str]:
        motivos = []
        if self.interrupcao is not None:
            motivos.append(f"interrompida por {signal.Signals(self.interrupcao).name}")
        falhou = next((e for e in self.execucoes if e.status not in (None, 0)), None)
        if falhou is not None:
            motivos.append(f"o {falhou.rotulo} saiu com status {falhou.status}")
        if problema := self.vigia.problema():
            motivos.append(problema)
        motivos += self.falhas
        if self.sessao_parada is False:
            motivos.append(f"a sessão de teste continua no ar: pare-a com systemctl --user stop {SESSAO}")
        return motivos

    def resumo(self) -> str:
        minimo = self.vigia.minimo_mib
        linhas = [
            f"status {self.status}",
            f"rodada {self.plano.pasta.name}: {self.plano.pedido}",
            f"pasta: {self.plano.pasta}",
            f"duração: {duracao(time.monotonic() - self.inicio)}",
            "memória disponível mínima: " + (f"{minimo} MiB ({minimo / 1024:.1f} GiB)" if minimo is not None
                                             else "sem leitura"),
        ]
        for execucao in self.execucoes:
            if execucao.status is None:
                situacao = "não rodou"
            else:
                sinal = f", morto por {execucao.sinal}" if execucao.sinal else ""
                situacao = f"status {execucao.status}{sinal}, {duracao(execucao.segundos)}"
            linhas.append(f"{execucao.rotulo}: {shlex.join(execucao.palavras)}: {situacao}")
        estados = ", ".join(f"{unidade} {estado}" for unidade, estado in self.estados_no_fim.items())
        if self.sessao_parada is None:
            linhas.append("sessão de teste: não subiu")
        elif self.sessao_parada:
            linhas.append(f"sessão de teste: parada ({estados})")
        else:
            linhas.append(f"sessão de teste: CONTINUA NO AR ({estados})")
        motivos = self.motivos()
        if motivos:
            linhas.append("motivo: " + "; ".join(motivos))
        return "\n".join(linhas)

    def _gravar_o_fim(self) -> None:
        resumo = self.resumo()
        if self.pasta_criada:
            (self.plano.pasta / "FIM").write_text(resumo + "\n", encoding="utf-8")
            self.anota(f"fim da rodada: status {self.status} (resumo no FIM)")
        print(resumo, flush=True)


def main(argv: list[str] | None = None) -> int:
    plano = montar_plano(sys.argv[1:] if argv is None else argv)
    try:
        driver = conferir_antes()
    except FalhaDaRodada as e:
        print(f"Rodada não começou: {e}. Nada foi criado, subido nem parado.", file=sys.stderr, flush=True)
        return 1
    return Rodada(plano, driver).executar()


if __name__ == "__main__":
    sys.exit(main())

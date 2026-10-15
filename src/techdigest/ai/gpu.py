"""Conferências de que o modelo vai rodar na GPU: antes de carregá-lo e depois.

Sem GPU, o Ollama carrega o modelo inteiro na RAM, e nesta máquina a memória acaba durante a
carga: em 13/10/2026 a máquina caiu assim, num kernel sem o driver da NVIDIA. As conferências de
antes param sem chegar a carregar o modelo; a de depois descarrega o modelo e para. Hoje só os
scripts de diagnóstico as usam; o pipeline pode usá-las na Fase 4.
"""
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TEMPO_DO_NVIDIA_SMI = 20        # segundos para o nvidia-smi responder
FOLGA_DO_LOG = 120              # segundos: o log vale para o servidor que subiu até isto antes da última subida registrada
_SUBIDA = 'msg="server config"'           # a primeira linha que o `ollama serve` escreve ao subir
_PLACA = 'msg="inference compute"'        # uma linha por dispositivo que o servidor achou ao subir
_CAMPO = re.compile(r'(\w+)=("[^"]*"|\S+)')
_HORA = re.compile(r"\btime=(\S+)")


class SemGPU(RuntimeError):
    """O modelo não vai rodar, ou não está rodando, na GPU: a mensagem diz por quê."""


def driver_da_nvidia() -> str:
    """A GPU que o driver da NVIDIA informa (nome e memória); levanta SemGPU se o driver não responde."""
    try:
        saida = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=TEMPO_DO_NVIDIA_SMI)
    except FileNotFoundError:
        raise SemGPU("o nvidia-smi não existe nesta máquina: sem o driver da NVIDIA, o modelo carregaria inteiro na RAM") from None
    except subprocess.TimeoutExpired:
        raise SemGPU(f"o nvidia-smi não respondeu em {TEMPO_DO_NVIDIA_SMI} s") from None
    linhas = [linha.strip() for linha in saida.stdout.splitlines() if linha.strip()]
    if saida.returncode != 0 or not linhas:
        mensagem = (saida.stderr or saida.stdout).strip().splitlines()
        raise SemGPU(f"o driver da NVIDIA não responde (nvidia-smi saiu com {saida.returncode}: "
                     f"{mensagem[0] if mensagem else 'sem mensagem'}); o kernel em uso pode não ter o módulo da NVIDIA")
    return linhas[0]


def placas_do_ollama(log: str) -> tuple[list[dict[str, str]], datetime | None]:
    """O que o Ollama achou na última vez que o servidor subiu, pelo log do `ollama serve`.

    Devolve uma linha "inference compute" por dispositivo, como dicionário (library, description,
    total...), e a hora dessa subida. Sem nenhuma subida no log, considera o log inteiro.
    """
    linhas = log.splitlines()
    inicio = max((i for i, linha in enumerate(linhas) if _SUBIDA in linha), default=0)
    hora = _HORA.search(linhas[inicio]) if linhas else None
    try:
        subiu = datetime.fromisoformat(hora.group(1)) if hora else None
    except ValueError:
        subiu = None
    placas = [
        {chave: valor.strip('"') for chave, valor in _CAMPO.findall(linha.split(_PLACA, 1)[1])}
        for linha in linhas[inicio:] if _PLACA in linha
    ]
    return placas, subiu


def inicio_do_servidor_local() -> float | None:
    """Quando o `ollama serve` que está rodando nesta máquina subiu, em segundos desde a época; None se não há."""
    try:
        with open("/proc/stat") as arquivo:
            boot = next(int(linha.split()[1]) for linha in arquivo if linha.startswith("btime"))
    except (OSError, StopIteration, ValueError):
        return None
    inicios = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as arquivo:
                partes = arquivo.read().split(b"\0")
            with open(f"/proc/{pid}/stat") as arquivo:
                campos = arquivo.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if os.path.basename(partes[0]) == b"ollama" and b"serve" in partes[1:]:
            inicios.append(boot + int(campos[19]) / os.sysconf("SC_CLK_TCK"))   # starttime, o 22º campo do stat
    return max(inicios, default=None)


def gpu_do_ollama(log: str, inicio_do_servidor: float | None = None) -> str:
    """A GPU que o Ollama achou ao subir, pela linha "inference compute" do log; levanta SemGPU se não achou.

    O nvidia-smi pode responder com o Ollama caindo para a CPU, e aí a memória acaba durante a
    carga do modelo. Por isso alguma linha "inference compute" da última subida do servidor tem de
    trazer library=CUDA. Com `inicio_do_servidor` (ver `inicio_do_servidor_local`), o log também
    tem de ser dessa subida: o log de uma subida anterior não diz nada do servidor de agora.
    """
    placas, subiu = placas_do_ollama(log)
    if not placas:
        raise SemGPU('o log do ollama serve não traz a linha "inference compute": não dá para saber se o servidor achou a GPU')
    if inicio_do_servidor is not None and (subiu is None or subiu.timestamp() < inicio_do_servidor - FOLGA_DO_LOG):
        quando = f"de {subiu:%d/%m %H:%M}" if subiu else "sem data"
        raise SemGPU(f"o log do ollama serve é de outra subida do servidor ({quando}, e o servidor de agora subiu em "
                     f"{datetime.fromtimestamp(inicio_do_servidor):%d/%m %H:%M}): suba o servidor com a saída gravada nesse log")
    cuda = [p for p in placas if p.get("library", "").upper() == "CUDA"]
    if not cuda:
        achadas = "; ".join(f"library={p.get('library', '?')} ({p.get('description') or p.get('name') or '?'})" for p in placas)
        raise SemGPU(f"o Ollama não achou a GPU ao subir ({achadas}): carregaria o modelo inteiro na RAM")
    return "; ".join(f"{p.get('description') or p.get('name')} ({p.get('total', '?')})" for p in cuda)


def conferir_antes_de_carregar(log: str | Path) -> list[str]:
    """As duas conferências de antes de carregar o modelo: o driver da NVIDIA e o que o Ollama achou ao subir.

    `log` é o arquivo em que o `ollama serve` grava a saída. Devolve o que cada conferência achou;
    levanta SemGPU, com o motivo, se alguma falha.
    """
    try:
        texto = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise SemGPU(f"não deu para ler o log do ollama serve ({log}: {e.strerror})") from None
    inicio = inicio_do_servidor_local()
    if inicio is None:
        raise SemGPU("o ollama serve não está rodando nesta máquina: as conferências da GPU valem para um servidor local")
    return [f"driver da NVIDIA: {driver_da_nvidia()}", f"Ollama: {gpu_do_ollama(texto, inicio)}"]


def descarregar(cliente, modelo: str) -> None:
    """Tira o modelo da memória (keep_alive=0)."""
    cliente.generate(model=modelo, prompt="", keep_alive=0)


# Linhas do log do `ollama serve` que descrevem a carga dos modelos no llama-server.
_CARGA = re.compile(r'msg="loading model via llama-server" model=(\S+)')     # o arquivo do modelo principal
_RASCUNHO = re.compile(r"loading draft model '([^']+)'")                     # daqui em diante, o modelo de rascunho
_METADADOS = re.compile(r"llama_model_loader: loaded meta data .* from (\S+)")
_CAMADAS = re.compile(r"load_tensors: offloaded (\d+)/(\d+) layers to GPU")
_BUFFER = re.compile(r"load_tensors:\s+(\S+) model buffer size =\s+([\d.]+) MiB")


@dataclass(frozen=True)
class Carga:
    """A carga do modelo principal: quantas camadas foram para a GPU e quanto ocupa cada dispositivo."""
    modelo: str                     # o arquivo do modelo
    na_gpu: int                     # camadas na GPU
    camadas: int                    # camadas no total
    buffers: dict[str, float]       # MiB por dispositivo, como o log os nomeia (CUDA0, CPU_Mapped...)

    @property
    def mib_na_gpu(self) -> float:
        return sum(mib for nome, mib in self.buffers.items() if nome.upper().startswith("CUDA"))

    @property
    def mib_na_ram(self) -> float:
        return sum(mib for nome, mib in self.buffers.items() if not nome.upper().startswith("CUDA"))


def carga_do_modelo_principal(log: str) -> Carga | None:
    """A última carga do modelo principal no log do `ollama serve`; None se o log não a traz.

    O modelo principal é o arquivo da última linha "loading model via llama-server". As linhas
    "offloaded N/M layers to GPU" e "model buffer size" que valem são as que vêm depois dos
    metadados desse arquivo; as do modelo de rascunho, que vêm depois de "loading draft model",
    não contam, porque ele cabe todo na GPU e faria passar um modelo principal todo na CPU.
    """
    linhas = log.splitlines()
    inicio = max((i for i, linha in enumerate(linhas) if _CARGA.search(linha)), default=None)
    if inicio is None:
        return None
    modelo = _CARGA.search(linhas[inicio]).group(1).strip('"')
    atual, camadas, buffers = None, None, {}
    for linha in linhas[inicio + 1:]:
        if (achado := _METADADOS.search(linha) or _RASCUNHO.search(linha)) is not None:
            atual = achado.group(1)     # o arquivo cuja carga as linhas seguintes descrevem
        elif atual == modelo and (achado := _CAMADAS.search(linha)) is not None:
            camadas = (int(achado.group(1)), int(achado.group(2)))
        elif atual == modelo and (achado := _BUFFER.search(linha)) is not None:
            buffers[achado.group(1)] = float(achado.group(2))
    return None if camadas is None else Carga(modelo, camadas[0], camadas[1], buffers)


def vram_do_llama_server() -> int | None:
    """Quantos MiB de memória de vídeo os processos llama-server ocupam, pelo nvidia-smi; None se não dá para saber."""
    pids = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as arquivo:
                if os.path.basename(arquivo.read().split(b"\0")[0]) == b"llama-server":
                    pids.add(pid)
        except OSError:
            continue
    try:
        saida = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=TEMPO_DO_NVIDIA_SMI)
    except (OSError, subprocess.TimeoutExpired):
        return None
    usados = [int(mib) for pid, mib in (linha.split(",") for linha in saida.stdout.splitlines() if linha.count(",") == 1)
              if pid.strip() in pids and mib.strip().isdigit()]
    return sum(usados) if usados else None


def modelo_na_gpu(cliente, modelo: str, log: str | Path) -> str:
    """Se o modelo principal carregou com parte na GPU: devolve o que achou, ou levanta SemGPU com o motivo.

    O /api/ps (`cliente.ps()`) só confirma que o modelo está carregado: o tamanho que ele informa
    não descreve este modelo. Quem diz quanto foi para a GPU é o log do `ollama serve` (ver
    `carga_do_modelo_principal`). Com o modelo principal todo na CPU, ou sem a carga dele no log,
    o modelo é descarregado antes de parar. A memória de vídeo do llama-server pelo nvidia-smi vai
    junto, como informação.
    """
    carregados = cliente.ps().models
    if not any(modelo in (getattr(m, "model", None), getattr(m, "name", None)) for m in carregados):
        nomes = ", ".join(str(getattr(m, "model", "?")) for m in carregados) or "nenhum"
        raise SemGPU(f"o modelo {modelo} não aparece no /api/ps depois da carga (carregados: {nomes})")
    try:
        carga = carga_do_modelo_principal(Path(log).read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        carga, motivo = None, f"não deu para ler o log do ollama serve ({log}: {e.strerror})"
    else:
        motivo = "o log do ollama serve não traz a carga do modelo principal (a linha \"offloaded N/M layers to GPU\")"
    if carga is None or carga.na_gpu == 0:
        descarregar(cliente, modelo)
        if carga is not None:
            motivo = (f"o modelo principal carregou todo na CPU (offloaded 0/{carga.camadas} layers to GPU, "
                      f"{carga.mib_na_ram / 1024:.1f} GiB na RAM)")
        raise SemGPU(f"{motivo}: o modelo foi descarregado")
    vram = vram_do_llama_server()
    return (f"modelo principal com {carga.na_gpu} de {carga.camadas} camadas na GPU ({carga.mib_na_gpu / 1024:.1f} GiB na GPU, "
            f"{carga.mib_na_ram / 1024:.1f} GiB na RAM)" + (f"; o llama-server ocupa {vram / 1024:.1f} GiB de memória de vídeo" if vram else ""))

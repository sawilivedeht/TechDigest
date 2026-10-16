"""As travas da máquina: o que interrompe uma execução inteira que chama o modelo.

Memória, temperatura e GPU são da máquina, e não de um item: quando uma trava dispara, a execução
para, em vez de pular o item e seguir para o próximo. `ProviderVigiado` envolve o provider e, antes
de cada chamada, confere a temperatura da CPU (acima de `MAX_CPU`, espera baixar de `RETOMAR_CPU`
por até `ESPERA_MAXIMA_DA_CPU`) e a memória disponível (o mínimo é `MIN_MEMORIA_GIB`). Com o modelo
local (Ollama) confere também a GPU antes da primeira chamada e depois da carga (ver `ai/gpu.py`) e
se o Ollama continua no ar com o modelo carregado. É o mesmo para o pipeline e para os scripts que
chamam o modelo (`scripts/testar_episodio.py` e `scripts/testar_agrupamento.py --etapa3`).

`ExecucaoInterrompida` herda de SystemExit, como um fim de programa pedido: atravessa os `except
Exception` que pulam um item, repetem a chamada da análise de lados ou registram a falha de uma
pauta, e chega a quem roda a execução, que registra o motivo e sai com status 1.
"""
import logging
import time

from techdigest.ai import gpu
from techdigest.ai.llm import OllamaProvider, _amostra_sistema, _temperatura_cpu

logger = logging.getLogger("techdigest.ai.maquina")

MIN_MEMORIA_GIB = 4.0          # memória disponível mínima antes de cada chamada
MAX_CPU = 95.0                 # °C: acima disto, antes de uma chamada, a execução espera a CPU esfriar
RETOMAR_CPU = 85.0             # °C: e continua quando ela baixa disto
ESPERA_MAXIMA_DA_CPU = 900     # segundos: se a CPU não esfria nesse tempo, a execução para
INTERVALO_DA_CPU = 10          # segundos entre duas leituras da temperatura durante a espera


class ExecucaoInterrompida(SystemExit):
    """Uma trava da máquina disparou: a execução inteira para. A mensagem diz qual e por quê."""


def memoria_disponivel() -> float | None:
    """A memória disponível agora (MemAvailable), em GiB; None se não dá para ler."""
    try:
        with open("/proc/meminfo") as arquivo:
            for linha in arquivo:
                if linha.startswith("MemAvailable:"):
                    return int(linha.split()[1]) / 1048576
    except (OSError, ValueError, IndexError):
        pass
    return None


def estado_da_maquina() -> tuple[float | None, str]:
    """A memória disponível em GiB e um resumo com swap e temperaturas, lidos agora."""
    return memoria_disponivel(), _amostra_sistema()


class ProviderVigiado:
    """O provider com as travas da máquina conferidas a cada chamada; o resto (client, model...) é o dele."""

    def __init__(self, provider, log_ollama: str | None = None, min_memoria: float = MIN_MEMORIA_GIB,
                 max_cpu: float = MAX_CPU, retomar_cpu: float = RETOMAR_CPU,
                 espera_maxima: float = ESPERA_MAXIMA_DA_CPU, local: bool | None = None):
        self.provider = provider
        self.local = isinstance(provider, OllamaProvider) if local is None else local   # o modelo roda nesta máquina
        self.log_ollama = log_ollama    # o log do ollama serve, onde as conferências da GPU leem a placa e a carga
        self.min_memoria = min_memoria
        self.max_cpu, self.retomar_cpu, self.espera_maxima = max_cpu, retomar_cpu, espera_maxima
        self.gpu_antes_da_carga: list[str] | None = None    # o que as conferências de antes acharam (None: não rodaram)
        self.gpu_depois_da_carga = ""                       # o que a conferência depois da carga achou
        self.modelo_ja_carregou = False

    def __getattr__(self, nome):
        if nome == "provider":      # ainda não existe (objeto em construção): sem isto, a busca não terminaria
            raise AttributeError(nome)
        return getattr(self.provider, nome)

    @property
    def ultimo_uso(self) -> dict:
        return getattr(self.provider, "ultimo_uso", {})

    @ultimo_uso.setter
    def ultimo_uso(self, valor: dict) -> None:
        self.provider.ultimo_uso = valor

    def conferir_antes_de_carregar(self) -> list[str]:
        """A GPU antes da primeira chamada (só com o modelo local, uma vez); devolve o que as conferências acharam."""
        if self.gpu_antes_da_carga is not None:
            return self.gpu_antes_da_carga
        if not self.local:
            self.gpu_antes_da_carga = []
            return []
        if not self.log_ollama:
            raise ExecucaoInterrompida("antes de carregar o modelo: falta o log do ollama serve (OLLAMA_LOG), "
                                       "onde a conferência da GPU lê a placa que o servidor achou")
        try:
            self.gpu_antes_da_carga = gpu.conferir_antes_de_carregar(self.log_ollama)
        except gpu.SemGPU as e:
            raise ExecucaoInterrompida(f"antes de carregar o modelo: {e}") from None
        for linha in self.gpu_antes_da_carga:
            logger.info("GPU antes da carga: %s", linha)
        return self.gpu_antes_da_carga

    def esperar_a_cpu(self) -> float:
        """Com a CPU acima de `max_cpu`, espera até ela baixar de `retomar_cpu`. Devolve os segundos esperados."""
        temperatura = _temperatura_cpu()
        if temperatura is None or temperatura <= self.max_cpu:
            return 0.0
        logger.warning("CPU a %.0f °C, acima de %.0f °C: esperando baixar de %.0f °C",
                       temperatura, self.max_cpu, self.retomar_cpu)
        inicio = time.monotonic()
        while temperatura is not None and temperatura >= self.retomar_cpu:
            if time.monotonic() - inicio > self.espera_maxima:
                raise ExecucaoInterrompida(f"a CPU continua a {temperatura:.0f} °C depois de "
                                           f"{self.espera_maxima / 60:.0f} minutos de espera")
            time.sleep(INTERVALO_DA_CPU)
            temperatura = _temperatura_cpu()
        esperou = time.monotonic() - inicio
        logger.info("CPU a %.0f °C depois de %.0f s de espera: a execução continua", temperatura or 0, esperou)
        return esperou

    def conferir_memoria(self, disponivel: float | None = None) -> None:
        """Para se a memória disponível (lida agora, se não vier) está abaixo do mínimo."""
        disponivel = memoria_disponivel() if disponivel is None else disponivel
        if disponivel is not None and disponivel < self.min_memoria:
            raise ExecucaoInterrompida(f"memória disponível em {disponivel:.1f} GiB, abaixo do mínimo de "
                                       f"{self.min_memoria:.1f} GiB")

    def conferir_ollama(self) -> list[str]:
        """Para se o Ollama não responde ou se descarregou o modelo, que já tinha carregado; devolve os carregados."""
        if not self.local:
            return []
        try:
            carregados = [m.model for m in self.provider.client.ps().models]
        except Exception as e:
            raise ExecucaoInterrompida(f"o Ollama não responde ({type(e).__name__}: {str(e)[:120]})") from None
        if self.modelo_ja_carregou and self.provider.model not in carregados:
            raise ExecucaoInterrompida(f"o Ollama descarregou o modelo {self.provider.model} no meio da execução "
                                       f"(carregados agora: {', '.join(carregados) or 'nenhum'})")
        return carregados

    def conferir_depois_da_carga(self) -> None:
        """Depois da primeira chamada que carregou o modelo: a carga dele na GPU, uma vez (ver `gpu.modelo_na_gpu`)."""
        self.modelo_ja_carregou = True
        if not self.local or self.gpu_depois_da_carga:
            return
        try:
            self.gpu_depois_da_carga = gpu.modelo_na_gpu(self.provider.client, self.provider.model, self.log_ollama)
        except gpu.SemGPU as e:
            raise ExecucaoInterrompida(f"depois da primeira chamada: {e}") from None
        logger.info("GPU depois da carga: %s", self.gpu_depois_da_carga)

    def antes_da_chamada(self, disponivel: float | None = None) -> float:
        """As travas de antes de uma chamada; devolve os segundos esperados pela CPU."""
        esperou = self.esperar_a_cpu()
        self.conferir_memoria(disponivel)
        self.conferir_antes_de_carregar()
        self.conferir_ollama()
        return esperou

    def depois_da_falha(self) -> None:
        """Depois de uma chamada que falhou: para se foi o servidor que caiu; se o modelo carregou, confere a GPU."""
        if not self.local:
            return
        if self.provider.model in self.conferir_ollama():
            self.conferir_depois_da_carga()   # a resposta veio fora do formato, mas o modelo já está na memória

    def chat_json(self, system: str, user: str, **opcoes) -> dict:
        self.antes_da_chamada()
        try:
            resposta = self.provider.chat_json(system, user, **opcoes)
        except Exception:
            self.depois_da_falha()
            raise
        self.conferir_depois_da_carga()
        return resposta

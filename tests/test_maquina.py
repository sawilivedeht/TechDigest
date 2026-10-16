"""As travas da máquina (techdigest.ai.maquina): o que interrompe uma execução inteira, e quando."""
from types import SimpleNamespace

import pytest

from techdigest.ai import gpu, maquina
from techdigest.ai.maquina import ExecucaoInterrompida, ProviderVigiado


class ClienteFalso:
    """O cliente do Ollama: `ps()` diz o que está carregado, ou falha como um servidor fora do ar."""

    def __init__(self, carregados=("modelo",), fora_do_ar=False):
        self.carregados = list(carregados)
        self.fora_do_ar = fora_do_ar

    def ps(self):
        if self.fora_do_ar:
            raise ConnectionError("conexão recusada")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self.carregados])


class ProviderFalso:
    def __init__(self, erro=None, cliente=None):
        self.model = "modelo"
        self.client = cliente or ClienteFalso()
        self.erro = erro
        self.ultimo_uso = {}
        self.chamadas = 0

    def chat_json(self, system, user, **opcoes):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        self.ultimo_uso = {"prompt": 10, "saida": 5}
        return {"ok": True}


@pytest.fixture(autouse=True)
def maquina_tranquila(monkeypatch):
    """Memória folgada, CPU fria e a GPU em ordem, a não ser que o teste diga outra coisa."""
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 12.0)
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: 60.0)
    monkeypatch.setattr(maquina.gpu, "conferir_antes_de_carregar", lambda log: ["driver da NVIDIA: RTX", "Ollama: RTX"])
    monkeypatch.setattr(maquina.gpu, "modelo_na_gpu", lambda cliente, modelo, log: "27 de 31 camadas na GPU")


def _pular_item_com_except_exception(vigia):
    """O que o pipeline faz com um item que falha: pega `Exception` e segue para o próximo."""
    try:
        vigia.chat_json("sistema", "entrada")
    except Exception:
        return "item pulado"
    return "item gerado"


def test_memoria_abaixo_do_minimo_interrompe_antes_da_chamada_e_atravessa_o_except_exception(monkeypatch):
    provider = ProviderFalso()
    vigia = ProviderVigiado(provider, local=False)
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 3.2)
    with pytest.raises(ExecucaoInterrompida, match=r"memória disponível em 3.2 GiB, abaixo do mínimo de 4.0 GiB"):
        _pular_item_com_except_exception(vigia)
    assert provider.chamadas == 0
    assert issubclass(ExecucaoInterrompida, SystemExit) and not issubclass(ExecucaoInterrompida, Exception)


def test_cpu_quente_espera_esfriar_e_para_se_nao_esfria(monkeypatch):
    leituras = iter([97.0, 92.0, 84.0])
    relogio = iter(range(0, 10_000, 10))
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: next(leituras))
    monkeypatch.setattr(maquina, "time", SimpleNamespace(monotonic=lambda: next(relogio), sleep=lambda s: None))
    provider = ProviderFalso()
    vigia = ProviderVigiado(provider, local=False)
    assert vigia.chat_json("sistema", "entrada") == {"ok": True}       # esperou baixar de 85 °C e seguiu
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: 97.0)
    with pytest.raises(ExecucaoInterrompida, match=r"a CPU continua a 97 °C depois de 15 minutos de espera"):
        vigia.chat_json("sistema", "entrada")
    assert provider.chamadas == 1


def test_a_gpu_antes_da_carga_e_conferida_uma_vez_e_so_com_o_modelo_local(monkeypatch):
    conferencias = []
    monkeypatch.setattr(maquina.gpu, "conferir_antes_de_carregar", lambda log: conferencias.append(log) or ["ok"])
    vigia = ProviderVigiado(ProviderFalso(), log_ollama="/tmp/ollama_serve.log", local=True)
    vigia.chat_json("sistema", "entrada")
    vigia.chat_json("sistema", "entrada")
    assert conferencias == ["/tmp/ollama_serve.log"] and vigia.gpu_antes_da_carga == ["ok"]
    remoto = ProviderVigiado(ProviderFalso(), local=False)
    remoto.chat_json("sistema", "entrada")
    assert remoto.gpu_antes_da_carga == [] and conferencias == ["/tmp/ollama_serve.log"]


def test_sem_gpu_ou_sem_o_log_a_execucao_para_antes_de_carregar_o_modelo(monkeypatch):
    def sem_gpu(log):
        raise gpu.SemGPU("o Ollama não achou a GPU ao subir (library=cpu)")
    monkeypatch.setattr(maquina.gpu, "conferir_antes_de_carregar", sem_gpu)
    provider = ProviderFalso()
    with pytest.raises(ExecucaoInterrompida, match=r"antes de carregar o modelo: o Ollama não achou a GPU"):
        ProviderVigiado(provider, log_ollama="log", local=True).chat_json("sistema", "entrada")
    with pytest.raises(ExecucaoInterrompida, match=r"falta o log do ollama serve"):
        ProviderVigiado(provider, log_ollama=None, local=True).chat_json("sistema", "entrada")
    assert provider.chamadas == 0


def test_a_carga_na_gpu_e_conferida_depois_da_primeira_chamada_e_para_se_foi_toda_para_a_cpu(monkeypatch):
    conferencias = []
    monkeypatch.setattr(maquina.gpu, "modelo_na_gpu", lambda cliente, modelo, log: conferencias.append(modelo) or "27 de 31")
    vigia = ProviderVigiado(ProviderFalso(), log_ollama="log", local=True)
    vigia.chat_json("sistema", "entrada")
    vigia.chat_json("sistema", "entrada")
    assert conferencias == ["modelo"] and vigia.gpu_depois_da_carga == "27 de 31"

    def toda_na_cpu(cliente, modelo, log):
        raise gpu.SemGPU("o modelo principal carregou todo na CPU (offloaded 0/31 layers to GPU): o modelo foi descarregado")
    monkeypatch.setattr(maquina.gpu, "modelo_na_gpu", toda_na_cpu)
    with pytest.raises(ExecucaoInterrompida, match=r"depois da primeira chamada: o modelo principal carregou todo na CPU"):
        ProviderVigiado(ProviderFalso(), log_ollama="log", local=True).chat_json("sistema", "entrada")


def test_uma_chamada_que_falha_com_o_modelo_carregado_tambem_confere_a_gpu(monkeypatch):
    def toda_na_cpu(cliente, modelo, log):
        raise gpu.SemGPU("o modelo principal carregou todo na CPU")
    monkeypatch.setattr(maquina.gpu, "modelo_na_gpu", toda_na_cpu)
    provider = ProviderFalso(erro=ValueError("LLM retornou JSON sem as chaves"))
    with pytest.raises(ExecucaoInterrompida, match="carregou todo na CPU"):    # e não o ValueError da resposta
        ProviderVigiado(provider, log_ollama="log", local=True).chat_json("sistema", "entrada")
    monkeypatch.setattr(maquina.gpu, "modelo_na_gpu", lambda cliente, modelo, log: "27 de 31")
    with pytest.raises(ValueError):                                              # com a GPU em ordem, é só um item que falhou
        ProviderVigiado(provider, log_ollama="log", local=True).chat_json("sistema", "entrada")


def test_ollama_fora_do_ar_ou_sem_o_modelo_interrompe():
    fora = ProviderFalso(cliente=ClienteFalso(fora_do_ar=True))
    with pytest.raises(ExecucaoInterrompida, match=r"o Ollama não responde \(ConnectionError: conexão recusada\)"):
        ProviderVigiado(fora, log_ollama="log", local=True).chat_json("sistema", "entrada")
    cliente = ClienteFalso()
    vigia = ProviderVigiado(ProviderFalso(cliente=cliente), log_ollama="log", local=True)
    vigia.chat_json("sistema", "entrada")
    cliente.carregados = []
    with pytest.raises(ExecucaoInterrompida, match=r"o Ollama descarregou o modelo modelo no meio da execução"):
        vigia.chat_json("sistema", "entrada")


def test_o_vigia_mostra_o_provider_por_baixo():
    provider = ProviderFalso()
    vigia = ProviderVigiado(provider, local=False)
    vigia.ultimo_uso = {}                       # o que o testar_agrupamento faz antes de cada chamada
    vigia.chat_json("sistema", "entrada")
    assert vigia.ultimo_uso == provider.ultimo_uso == {"prompt": 10, "saida": 5}
    assert vigia.model == "modelo" and vigia.client is provider.client

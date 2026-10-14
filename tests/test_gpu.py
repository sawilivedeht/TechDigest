"""Testes de ai/gpu.py sem GPU e sem Ollama: o log do ollama serve, o nvidia-smi e o /api/ps são simulados."""
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from techdigest.ai import gpu
from techdigest.ai.gpu import SemGPU, conferir_antes_de_carregar, gpu_do_ollama, modelo_na_gpu, placas_do_ollama

# Linhas como as do log do ollama serve de 13/10/2026: a subida das 19:31, no kernel sem driver, e a das 19:39, com a GPU.
SEM_GPU = (
    'time=2026-10-13T19:31:04.485-03:00 level=INFO source=routes.go:2373 msg="server config" env="map[CUDA_VISIBLE_DEVICES:]"\n'
    'time=2026-10-13T19:31:04.487-03:00 level=INFO source=runner.go:60 msg="discovering available GPUs..."\n'
    'time=2026-10-13T19:31:10.923-03:00 level=INFO source=types.go:50 msg="inference compute" id=cpu library=cpu compute="" '
    'name=cpu description=cpu libdirs=ollama driver="" pci_id="" type="" total="23.2 GiB" available="14.0 GiB"\n'
)
COM_GPU = (
    'time=2026-10-13T19:39:14.102-03:00 level=INFO source=routes.go:2373 msg="server config" env="map[CUDA_VISIBLE_DEVICES:]"\n'
    'time=2026-10-13T19:39:20.761-03:00 level=INFO source=types.go:32 msg="inference compute" id=0 filter_id=0 library=CUDA '
    'compute=8.6 name=CUDA0 description="NVIDIA GeForce RTX 3050 6GB Laptop GPU" libdirs=ollama,cuda_v13 driver=13.4 '
    'pci_id=0000:01:00.0 type=discrete total="5.7 GiB" available="5.6 GiB"\n'
    'time=2026-10-13T19:39:20.761-03:00 level=INFO source=routes.go:2485 msg="vram-based default context" total_vram="5.7 GiB"\n'
)
SUBIU_COM_GPU = datetime.fromisoformat("2026-10-13T19:39:14.102-03:00").timestamp()


def test_o_log_vale_pela_ultima_subida_do_servidor():
    placas, subiu = placas_do_ollama(SEM_GPU + COM_GPU)
    assert [p["library"] for p in placas] == ["CUDA"] and placas[0]["description"] == "NVIDIA GeForce RTX 3050 6GB Laptop GPU"
    assert subiu == datetime.fromisoformat("2026-10-13T19:39:14.102-03:00")
    assert [p["library"] for p in placas_do_ollama(COM_GPU + SEM_GPU)[0]] == ["cpu"]       # subiu de novo, sem GPU
    assert placas_do_ollama("")[0] == []


def test_com_library_cuda_passa_e_com_library_cpu_para_antes_de_carregar():
    assert gpu_do_ollama(SEM_GPU + COM_GPU, SUBIU_COM_GPU) == "NVIDIA GeForce RTX 3050 6GB Laptop GPU (5.7 GiB)"
    with pytest.raises(SemGPU, match=r"o Ollama não achou a GPU ao subir \(library=cpu \(cpu\)\): carregaria o modelo inteiro na RAM"):
        gpu_do_ollama(COM_GPU + SEM_GPU)
    with pytest.raises(SemGPU, match='não traz a linha "inference compute"'):
        gpu_do_ollama('time=2026-10-13T19:39:14.102-03:00 level=INFO msg="server config"\n')


def test_log_de_outra_subida_do_servidor_nao_vale():
    # o servidor de agora subiu depois do que o log registra: o log é de uma subida anterior
    with pytest.raises(SemGPU, match="o log do ollama serve é de outra subida do servidor"):
        gpu_do_ollama(COM_GPU, SUBIU_COM_GPU + 3600)
    assert gpu_do_ollama(COM_GPU, SUBIU_COM_GPU + gpu.FOLGA_DO_LOG - 1)          # a mesma subida, com a folga


def _nvidia_smi(monkeypatch, retorno=None, erro=None):
    def falso(*args, **kwargs):
        if erro:
            raise erro
        return retorno
    monkeypatch.setattr(gpu.subprocess, "run", falso)


def test_o_driver_da_nvidia_tem_de_responder(monkeypatch):
    _nvidia_smi(monkeypatch, SimpleNamespace(returncode=0, stdout="NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6144 MiB\n", stderr=""))
    assert gpu.driver_da_nvidia() == "NVIDIA GeForce RTX 3050 6GB Laptop GPU, 6144 MiB"
    _nvidia_smi(monkeypatch, SimpleNamespace(returncode=9, stdout="",
                                             stderr="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"))
    with pytest.raises(SemGPU, match=r"o driver da NVIDIA não responde \(nvidia-smi saiu com 9: NVIDIA-SMI has failed"):
        gpu.driver_da_nvidia()
    _nvidia_smi(monkeypatch, erro=FileNotFoundError())
    with pytest.raises(SemGPU, match="o nvidia-smi não existe nesta máquina"):
        gpu.driver_da_nvidia()
    _nvidia_smi(monkeypatch, erro=subprocess.TimeoutExpired("nvidia-smi", 20))
    with pytest.raises(SemGPU, match="não respondeu"):
        gpu.driver_da_nvidia()


def test_as_conferencias_de_antes_leem_o_log_e_param_com_o_motivo(monkeypatch, tmp_path):
    log = tmp_path / "ollama_serve.log"
    log.write_text(SEM_GPU + COM_GPU, encoding="utf-8")
    monkeypatch.setattr(gpu, "driver_da_nvidia", lambda: "RTX 3050, 6144 MiB")
    monkeypatch.setattr(gpu, "inicio_do_servidor_local", lambda: SUBIU_COM_GPU)
    assert conferir_antes_de_carregar(log) == ["driver da NVIDIA: RTX 3050, 6144 MiB",
                                               "Ollama: NVIDIA GeForce RTX 3050 6GB Laptop GPU (5.7 GiB)"]
    log.write_text(COM_GPU + SEM_GPU, encoding="utf-8")                                 # o nvidia-smi responde, o Ollama caiu para a CPU
    monkeypatch.setattr(gpu, "inicio_do_servidor_local", lambda: datetime.fromisoformat("2026-10-13T19:31:04-03:00").timestamp())
    with pytest.raises(SemGPU, match="library=cpu"):
        conferir_antes_de_carregar(log)
    with pytest.raises(SemGPU, match="não deu para ler o log do ollama serve"):
        conferir_antes_de_carregar(tmp_path / "nao_existe.log")
    monkeypatch.setattr(gpu, "inicio_do_servidor_local", lambda: None)
    with pytest.raises(SemGPU, match="o ollama serve não está rodando nesta máquina"):
        conferir_antes_de_carregar(log)


class ClienteFalso:
    """Faz o papel do cliente do Ollama: `ps()` devolve os modelos carregados e `generate` guarda o que recebeu."""

    def __init__(self, *modelos):
        self.modelos = list(modelos)
        self.geracoes = []

    def ps(self):
        return SimpleNamespace(models=self.modelos)

    def generate(self, **opcoes):
        self.geracoes.append(opcoes)


def test_depois_de_carregar_parte_do_modelo_tem_de_estar_na_gpu():
    na_gpu = ClienteFalso(SimpleNamespace(model="gemma4:26b", name="gemma4:26b", size=4 * 2**30, size_vram=3 * 2**30))
    assert modelo_na_gpu(na_gpu, "gemma4:26b") == "75% do modelo na GPU (3.0 de 4.0 GiB)" and na_gpu.geracoes == []

    so_na_ram = ClienteFalso(SimpleNamespace(model="gemma4:26b", name="gemma4:26b", size=17 * 2**30, size_vram=0))
    with pytest.raises(SemGPU, match=r"carregou sem nada na GPU \(size_vram=0 de 17.0 GiB\): foi descarregado"):
        modelo_na_gpu(so_na_ram, "gemma4:26b")
    assert so_na_ram.geracoes == [{"model": "gemma4:26b", "prompt": "", "keep_alive": 0}]   # descarregado antes de parar

    with pytest.raises(SemGPU, match=r"não aparece no /api/ps depois da carga \(carregados: nenhum\)"):
        modelo_na_gpu(ClienteFalso(), "gemma4:26b")

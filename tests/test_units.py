"""As units de usuário de deploy/systemd: o que o código espera delas."""
import os
from pathlib import Path

from techdigest import config

PASTA_DAS_UNITS = Path(__file__).resolve().parents[1] / "deploy" / "systemd"


def _diretivas(arquivo: str) -> dict[str, list[str]]:
    """As diretivas de uma unit, cada uma com a lista dos valores na ordem do arquivo (ExecStartPre se repete)."""
    diretivas: dict[str, list[str]] = {}
    for linha in (PASTA_DAS_UNITS / arquivo).read_text(encoding="utf-8").splitlines():
        if "=" in linha and not linha.startswith(("#", ";", "[")):
            chave, valor = linha.split("=", 1)
            diretivas.setdefault(chave.strip(), []).append(valor.strip())
    return diretivas


def test_o_log_da_unit_do_ollama_e_o_padrao_de_ollama_log():
    unit = _diretivas("ollama.service")
    raiz_de_estado = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")   # o %S de uma unit de usuário
    log = unit["StandardOutput"][0].removeprefix("append:").replace("%S", raiz_de_estado)
    assert log == config.Settings.model_fields["ollama_log"].default == str(config.PASTA_DE_ESTADO / "ollama_serve.log")
    # em modo de acréscimo: com truncate:, o ExecStartPost zeraria o arquivo depois que o servidor escreveu nele
    assert unit["StandardOutput"][0].startswith("append:") and unit["StandardError"] == ["inherit"]
    # o log começa vazio a cada subida, e a espera pela GPU lê esse mesmo arquivo
    assert unit["ExecStartPre"][0] == "/usr/bin/truncate --size=0 %S/techdigest/ollama_serve.log"
    assert unit["ExecStartPost"][0].endswith(" %S/techdigest/ollama_serve.log") and "library=cuda" in unit["ExecStartPost"][0]


def test_a_unit_do_ollama_sobe_o_servidor_que_as_conferencias_da_gpu_procuram():
    unit = _diretivas("ollama.service")
    assert unit["ExecStart"] == ["/usr/local/bin/ollama serve"]       # gpu.inicio_do_servidor_local procura "ollama" com "serve"
    assert "/usr/bin/nvidia-smi -L" in unit["ExecStartPre"]          # sem o driver da NVIDIA, nem sobe
    assert unit["Environment"] == ["LLAMA_ARG_CACHE_RAM=0"]
    assert unit["StopWhenUnneeded"] == ["yes"]


def test_a_sessao_de_teste_mantem_o_ollama_no_ar_e_cai_com_ele():
    target = _diretivas("techdigest-teste.target")
    assert target["BindsTo"] == ["ollama.service"] and target["After"] == ["ollama.service"]

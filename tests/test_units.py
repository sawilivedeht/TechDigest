"""As units de usuário de deploy/systemd: o que o código espera delas."""
import importlib.util
import os
from pathlib import Path

from techdigest import aviso_de_falha, config

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


# As units do timer (frente 5 das melhorias): versionadas e não instaladas; a instalação está em docs/producao.md.

def test_o_pipeline_e_o_processo_principal_da_unit_do_timer():
    unit = _diretivas("techdigest.service")
    # sem o systemd-inhibit na frente: ele devolve 1 quando o filho morre por um sinal, o status do pipeline que já avisou
    assert unit["ExecStart"] == ["%h/Projetos/techdigest/.venv/bin/techdigest"]
    assert unit["Type"] == ["exec"] and unit["WorkingDirectory"] == ["%h/Projetos/techdigest"]


def test_a_unit_do_pipeline_quer_o_ollama_e_o_bloqueio_do_sono_sem_exigir():
    """Com Wants=, um Ollama que não sobe não impede a execução: o pipeline para na conferência da GPU e avisa."""
    unit = _diretivas("techdigest.service")
    quer, depois = unit["Wants"][0].split(), unit["After"][0].split()
    assert set(quer) == set(depois) == {"ollama.service", "techdigest-inibir.service"}
    assert "Requires" not in unit and "BindsTo" not in unit and "Requisite" not in unit
    assert all((PASTA_DAS_UNITS / nome).exists() for nome in quer)


def test_o_bloqueio_do_sono_para_quando_a_execucao_termina():
    unit = _diretivas("techdigest-inibir.service")
    assert unit["StopWhenUnneeded"] == ["yes"]
    assert unit["ExecStart"][0].startswith("/usr/bin/systemd-inhibit --what=sleep:idle --who=TechDigest ")
    assert unit["ExecStart"][0].endswith(" /usr/bin/sleep infinity")


def test_o_aviso_de_falha_e_o_on_failure_so_da_unit_do_pipeline():
    assert _diretivas("techdigest.service")["OnFailure"] == ["techdigest-aviso.service"]
    # com dois serviços apontando para o mesmo OnFailure=, o systemd não passa as variáveis MONITOR_* (systemd.exec(5))
    apontam = sorted(arquivo.name for arquivo in PASTA_DAS_UNITS.iterdir()
                     if "techdigest-aviso.service" in " ".join(_diretivas(arquivo.name).get("OnFailure", [])))
    assert apontam == ["techdigest.service"]
    aviso = _diretivas("techdigest-aviso.service")
    assert aviso["Type"] == ["oneshot"] and "OnFailure" not in aviso
    assert aviso["WorkingDirectory"] == _diretivas("techdigest.service")["WorkingDirectory"]
    programa, modulo = aviso["ExecStart"][0].split(" -m ")
    assert programa == "%h/Projetos/techdigest/.venv/bin/python"
    assert modulo == aviso_de_falha.__name__ and importlib.util.find_spec(modulo) is not None


def test_o_tempo_maximo_da_unit_fica_acima_do_orcamento_e_e_o_que_o_aviso_diz():
    unit = _diretivas("techdigest.service")
    assert unit["RuntimeMaxSec"] == ["4h"]
    horas = int(unit["RuntimeMaxSec"][0].removesuffix("h"))
    assert config.Settings.model_fields["max_runtime_min"].default < horas * 60   # nenhum item novo começa depois
    assert aviso_de_falha.TEMPO_MAXIMO == f"{horas} horas"


def test_o_timer_dispara_a_unit_do_pipeline_a_01h():
    timer = _diretivas("techdigest.timer")
    assert timer["OnCalendar"] == ["*-*-* 01:00:00"] and timer["Persistent"] == ["true"]
    assert timer["WantedBy"] == ["timers.target"]
    assert "Unit" not in timer and (PASTA_DAS_UNITS / "techdigest.service").exists()   # sem Unit=, a do mesmo nome

"""Os scripts que chamam o modelo pegam a trava do modelo e param nas travas da máquina, como o pipeline."""
import sys

import pytest

import testar_agrupamento as diag
import testar_episodio as ep
from techdigest import trava
from techdigest.ai import maquina
from techdigest.processing import agrupamento as ag


class ProviderFalso:
    """Responde ao veredito da etapa 3 juntando os dois artigos."""
    model = "modelo"

    def __init__(self):
        self.ultimo_uso = {}
        self.chamadas = 0

    def chat_json(self, system, user, **opcoes):
        self.chamadas += 1
        self.ultimo_uso = {"prompt": 100, "saida": 20}
        return {"tipos": {"1": "fato_unico", "2": "fato_unico"}, "isolados": [], "motivo": "a mesma obra",
                "grupos": [{"principal": 1, "membros": [{"id": 2, "relacao": "mesmo_acontecimento"}]}]}


@pytest.fixture
def etapa3(monkeypatch):
    provider = ProviderFalso()
    monkeypatch.setattr(diag, "get_provider", lambda settings: provider)
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 12.0)
    monkeypatch.setattr(maquina, "_temperatura_cpu", lambda: 60.0)
    a = ag.Candidato(titulo="Construtora Alfa entrega a obra da BR-101", veiculo="Jornal do Vale",
                     url="https://jornaldovale.example/obra", url_veiculo="https://jornaldovale.example/obra",
                     texto="texto da obra " * 100)
    b = ag.Candidato(titulo="Obra da BR-101 é entregue pela Construtora Alfa", veiculo="Diário do Litoral",
                     url="https://diariodolitoral.example/obra", url_veiculo="https://diariodolitoral.example/obra",
                     texto="texto da entrega " * 80)
    return provider, ag.Pauta(principal=a, relacionados=(b,)), {a: 1, b: 2}


def test_a_etapa_3_pega_a_trava_do_modelo(etapa3):
    provider, pauta, ids = etapa3
    with trava.trava_do_modelo("techdigest --simular data/simulacoes/x"):
        with pytest.raises(trava.TravaOcupada, match=r"em uso por techdigest --simular data/simulacoes/x"):
            diag._rodar_etapa3([pauta], ids, 1)
    assert provider.chamadas == 0
    chamadas = diag._rodar_etapa3([pauta], ids, 1)
    assert provider.chamadas == 1 and chamadas[0].erro == ""


def test_a_etapa_3_para_numa_trava_da_maquina(etapa3, monkeypatch):
    provider, pauta, ids = etapa3
    monkeypatch.setattr(maquina, "memoria_disponivel", lambda: 3.5)
    with pytest.raises(maquina.ExecucaoInterrompida, match="memória disponível em 3.5 GiB"):
        diag._rodar_etapa3([pauta], ids, 1)       # e não um veredito "a chamada falhou" seguido da próxima pauta
    assert provider.chamadas == 0
    assert trava.CAMINHO_DA_TRAVA.read_text(encoding="utf-8") == ""


def test_o_testar_episodio_pega_a_trava_antes_de_tudo(monkeypatch, tmp_path):
    rodadas = []
    monkeypatch.setattr(sys, "argv", ["testar_episodio.py", "--amostra", str(tmp_path / "amostra.json")])
    monkeypatch.setattr(diag, "_log_no_console", lambda: None)      # sem mexer no logging dos outros testes
    monkeypatch.setattr(ep, "_rodar", lambda args, pasta, carimbo: rodadas.append(args.amostra))
    with trava.trava_do_modelo("scripts/testar_agrupamento.py --etapa3"):
        with pytest.raises(trava.TravaOcupada, match=r"testar_agrupamento.py --etapa3"):
            ep.main()
    assert rodadas == []
    ep.main()
    assert rodadas == [str(tmp_path / "amostra.json")]

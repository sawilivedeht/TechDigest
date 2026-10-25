"""O registro de cada execução: a pasta, a amostra e o relatório que os dois diagnósticos já leem, e a limpeza das antigas."""
import contextlib
import datetime
import io
import json
import math
from types import SimpleNamespace

import checar_fidelidade
import pytest
import refazer_qa
from techdigest import registro
from techdigest.ai import qa, summarizer
from techdigest.ai.prompt import PROMPT_LADOS
from techdigest.ai.summarizer import QAReprovado, Summarizer

TEXTO = ("A prefeitura de Curitiba multou a Construtora Alfa por atrasar a entrega da ponte do Bairro Novo.\n\n"
         + "A obra começou há dois anos e tinha prazo para o fim do mês passado. " * 30)


def _episodio(palavras: int) -> dict:
    fala = " ".join(["palavra"] * palavras)
    return {
        "titulo_reescrito": "Prefeitura multa construtora", "resumo_didatico": "Uma frase. " * qa.MIN_FRASES_RESUMO,
        "pontos_chave": ["a", "b"], "por_que_importa": "Importa.",
        "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Otávio", "papel": "analista de obras"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Otávio", "fala": fala}],
        "houve_divergencia": False, "fontes_citadas": ["Jornal do Vale"],
    }


class ProviderFalso:
    """A análise de lados com um lado só, e as respostas do episódio em fila."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.ultimo_uso = {}

    def chat_json(self, system, user, **opcoes):
        self.ultimo_uso = {"prompt": len(system + user) // 4, "saida": 500}
        if system == PROMPT_LADOS:
            return {"lados": [{"posicao": "A prefeitura multou a construtora.", "atores": ["prefeitura de Curitiba"],
                               "veiculos": ["Jornal do Vale"]}], "motivo": "um lado"}
        return self.respostas.pop(0)


@pytest.fixture
def ollama_8192(monkeypatch):
    monkeypatch.setattr(summarizer, "settings", SimpleNamespace(
        llm_provider="ollama", ollama_num_ctx=8192, ollama_num_predict=10240, llm_reserva_saida=3000,
        llm_max_prompt_chars=4096,
    ))


def _artigo(**extras) -> dict:
    return {"veiculo": "Jornal do Vale", "titulo": "Prefeitura multa construtora", "url": "https://news.example/rss/1",
            "url_resolvida": "https://jornaldovale.example/cidade/multa", "texto": TEXTO,
            "data": datetime.datetime(2026, 10, 20, 9, 0, tzinfo=datetime.timezone.utc), "feed": "https://news.example/rss",
            "categorias": ("Cidade",), **extras}


def _gerar(s: Summarizer) -> tuple[str, dict | None]:
    try:
        return "aprovado", s.process({"source": "Jornal do Vale", "title": "Prefeitura multa construtora", "text": TEXTO})
    except QAReprovado as e:
        return f"reprovado pelo QA ({e})", s.ultimo_diagnostico.get("episodio")


def test_o_registro_grava_o_que_os_dois_diagnosticos_leem(tmp_path, ollama_8192):
    bom = _episodio(max(qa.MIN_POR_PERSONAGEM, math.ceil(qa.MIN_TOTAL / 2)))
    curto = _episodio(20)
    s = Summarizer(provider=ProviderFalso(bom, curto, curto))
    reg = registro.RegistroDaExecucao(tmp_path, num_ctx=8192, agora=datetime.datetime(2026, 10, 25, 8, 0, 0))
    assert reg.pasta == tmp_path / "20261025-080000"

    situacao, episodio = _gerar(s)
    primeiro = reg.item([_artigo()], situacao, s.ultimo_diagnostico, episodio, 12.3, ["Otávio"],
                        {"Helena": "pt-BR-FranciscaNeural", "Otávio": "pt-BR-AntonioNeural"})
    reg.entregue(primeiro)
    situacao, episodio = _gerar(s)                          # o segundo fica curto na geração e na revisão
    reg.item([_artigo(url="https://news.example/rss/2")], situacao, s.ultimo_diagnostico, episodio, 20.0)
    reg.filtrado("https://pt.org.br/x", "Nota do partido", "site de partido (pt.org.br)", True, "https://pt.org.br/x")

    relatorio = json.loads(reg.relatorio.read_text(encoding="utf-8"))
    amostra = json.loads(reg.amostra.read_text(encoding="utf-8"))
    assert [c["id"] for c in amostra["candidatos"]] == [1, 2] and amostra["candidatos"][0]["texto"] == TEXTO
    assert amostra["candidatos"][0]["url_resolvida"] == "https://jornaldovale.example/cidade/multa"
    um, dois = relatorio["episodios"]
    assert (um["situacao"], um["entregue"], um["vozes"]["Otávio"]) == ("aprovado", True, "pt-BR-AntonioNeural")
    assert dois["situacao"].startswith("reprovado pelo QA") and not dois["entregue"] and dois["arquivo"].endswith(".json")
    assert um["lados"]["lados"][0]["atores"] == ["prefeitura de Curitiba"] and um["orcamento"]["total"] > 0
    assert um["cortes_na_geracao"][0]["incluido"] > 0 and relatorio["filtrados"][0]["depois_da_extracao"]

    refeitos = refazer_qa.refazer(reg.relatorio)             # o QA de agora dá a mesma situação gravada
    assert [(r.aprovado_antes, r.aprovado_agora) for r in refeitos] == [(True, True), (False, False)]
    with contextlib.redirect_stdout(io.StringIO()):
        casos = checar_fidelidade._carregar(reg.relatorio)
    assert [c.numero for c in casos] == [1, 2] and casos[0].fontes[0].enviado == um["cortes_na_geracao"][0]["incluido"]


def test_a_limpeza_apaga_so_as_pastas_de_execucao_mais_antigas_que_o_prazo(tmp_path):
    agora = datetime.datetime(2026, 10, 25, 8, 0, 0)
    for nome in ("20260920-080000", "20260925-075959", "20260925-075959-2", "20260925-080001", "20261024-200000"):
        (tmp_path / nome).mkdir()
    (tmp_path / "notas").mkdir()                              # nada que não seja pasta de execução sai
    (tmp_path / "20260901-000000.txt").write_text("arquivo", encoding="utf-8")
    apagadas = registro.limpar_antigas(tmp_path, 30, agora)
    assert [p.name for p in apagadas] == ["20260920-080000", "20260925-075959", "20260925-075959-2"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20260901-000000.txt", "20260925-080001", "20261024-200000", "notas"]
    assert registro.limpar_antigas(tmp_path, 0, agora) == []   # 0 guarda tudo


def test_duas_execucoes_no_mesmo_segundo_ganham_pastas_diferentes(tmp_path):
    agora = datetime.datetime(2026, 10, 25, 8, 0, 0)
    pastas = [registro.RegistroDaExecucao(tmp_path, agora=agora).pasta.name for _ in range(3)]
    assert pastas == ["20261025-080000", "20261025-080000-2", "20261025-080000-3"]

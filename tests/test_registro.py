"""O registro de cada execução: a pasta, a amostra e o relatório que os dois diagnósticos já leem, e a limpeza das antigas."""
import builtins
import contextlib
import datetime
import io
import json
import math
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
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


def test_o_aviso_da_janela_e_a_proporcao_do_item_vao_para_o_registro(tmp_path):
    reg = registro.RegistroDaExecucao(tmp_path, agora=datetime.datetime(2026, 10, 29, 8, 0, 0))
    artigo = {"veiculo": "G1", "titulo": "T", "url": "https://g1.example/t", "texto": "texto " * 2000}
    aviso = "o texto de G1 entrou na geração com 669 de 4986 caracteres: a janela, e não o teto, cortou o texto (fonte única)"
    entrada = reg.item([artigo], "aprovado", {"aviso_da_janela": aviso, "proporcao_do_item": 2.3}, None, 1.0)
    assert (entrada["aviso_da_janela"], entrada["proporcao_do_texto"]) == (aviso, 2.3)
    sem_aviso = reg.item([artigo], "aprovado", {}, None, 1.0)
    assert (sem_aviso["aviso_da_janela"], sem_aviso["proporcao_do_texto"]) == ("", None)


# ── A gravação atômica (frente 3 das melhorias de 07/11/2026) ─────────────────────────────────────────────────────

def _arquivos(pasta: Path) -> list[str]:
    return sorted(p.name for p in pasta.iterdir())


def _artigo_curto(titulo: str = "Prefeitura multa construtora") -> dict:
    return {"veiculo": "Jornal do Vale", "titulo": titulo, "url": "https://jornaldovale.example/multa", "texto": "texto " * 300}


def test_a_gravacao_nao_deixa_temporario_e_os_json_sao_validos(tmp_path):
    reg = registro.RegistroDaExecucao(tmp_path, agora=datetime.datetime(2026, 11, 8, 8, 0, 0))
    reg.entregue(reg.item([_artigo_curto()], "aprovado", {}, _episodio(300), 1.0))
    assert _arquivos(reg.pasta) == ["01_aprovado_prefeitura-multa-construtora.json", "amostra.json",
                                    "relatorio_20261108-080000.json"]
    for nome in _arquivos(reg.pasta):
        json.loads((reg.pasta / nome).read_text(encoding="utf-8"))
    assert json.loads(reg.relatorio.read_text(encoding="utf-8"))["episodios"][0]["entregue"]


@pytest.mark.parametrize("onde", ["fsync", "replace"])
def test_uma_falha_no_meio_da_gravacao_deixa_o_arquivo_anterior_inteiro(tmp_path, monkeypatch, onde):
    """O fsync falha com o temporário já escrito; o replace, na troca. Nos dois casos a pasta fica como estava."""
    reg = registro.RegistroDaExecucao(tmp_path, agora=datetime.datetime(2026, 11, 8, 8, 0, 0))
    reg.filtrado("https://pt.org.br/x", "Nota do partido", "site de partido (pt.org.br)", False)
    antes = {nome: (reg.pasta / nome).read_bytes() for nome in _arquivos(reg.pasta)}

    def disco_cheio(*args):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(registro.os, onde, disco_cheio)
        with pytest.raises(OSError):
            reg.abandonado("https://g1.example/a", "Outro item", "reprovado pelo QA em 2 execuções")
        with pytest.raises(OSError):
            reg.item([_artigo_curto()], "aprovado", {}, _episodio(300), 1.0)
    # nenhum arquivo cortado, nenhum temporário e nenhum episódio novo
    assert {nome: (reg.pasta / nome).read_bytes() for nome in _arquivos(reg.pasta)} == antes

    reg.gravar()                                               # a gravação seguinte leva o que ficou na memória
    relatorio = json.loads(reg.relatorio.read_text(encoding="utf-8"))
    assert [a["titulo"] for a in relatorio["abandonados"]] == ["Outro item"] and relatorio["episodios"] == []


def test_os_arquivos_mantem_o_formato_e_a_permissao_de_antes(tmp_path):
    reg = registro.RegistroDaExecucao(tmp_path, agora=datetime.datetime(2026, 11, 8, 8, 0, 0))
    entrada = reg.item([_artigo_curto("Prefeitura de São José multa construtora")], "aprovado", {}, _episodio(300), 1.0)
    referencia = tmp_path / "referencia.txt"                   # como o write_text de antes criava os arquivos
    referencia.write_text("x", encoding="utf-8")
    for caminho in (reg.amostra, reg.relatorio, Path(entrada["arquivo"])):
        bruto = caminho.read_text(encoding="utf-8")
        assert bruto == json.dumps(json.loads(bruto), ensure_ascii=False, indent=1)   # indentação 1, acentos sem escape
        assert caminho.stat().st_mode & 0o777 == referencia.stat().st_mode & 0o777
    assert "São José" in reg.amostra.read_text(encoding="utf-8")


# ── Interrupção no meio da gravação: processo morto (A e B) e falha só no relatório (C) ──────────────────────────────
# A falha entra na escrita do arquivo, pelo open (o do registro e o io.open do write_text): metade do texto vai ao
# arquivo aberto e então o processo morre (A, B) ou o disco enche (C). Assim o teste pega também uma gravação direta no
# próprio caminho, que deixaria o arquivo cortado.

_CARIMBO = "20261108-080000"

# O processo filho de A e B (argumentos: a pasta de trabalho e o começo do nome do arquivo em que morre). Grava um item
# inteiro, copia a pasta do registro como estava para <pasta>/antes, passa a morrer na escrita do arquivo marcado e
# grava o segundo item. Sem rede e sem modelo: só o registro.
_FILHO = textwrap.dedent('''
    import builtins, datetime, io, os, shutil, signal, sys
    from pathlib import Path

    from techdigest import config
    config.Settings.model_config["env_file"] = None          # como no conftest: o .env não conta
    config.settings = config.Settings()
    from techdigest import registro

    pasta, ponto = Path(sys.argv[1]), sys.argv[2]

    def episodio(titulo):
        fala = " ".join(["palavra"] * 300)
        return {"titulo_reescrito": titulo, "resumo_didatico": "Uma frase. " * 8, "pontos_chave": ["a", "b"],
                "por_que_importa": "Importa.",
                "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Otávio", "papel": "analista"}],
                "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Otávio", "fala": fala}],
                "houve_divergencia": False, "fontes_citadas": ["Jornal do Vale"]}

    def artigo(titulo, n):
        return {"veiculo": "Jornal do Vale", "titulo": titulo, "url": f"https://jornaldovale.example/{n}",
                "texto": "A prefeitura multou a construtora pelo atraso da obra. " * 40}

    reg = registro.RegistroDaExecucao(pasta / "execucoes", agora=datetime.datetime(2026, 11, 8, 8, 0, 0))
    reg.entregue(reg.item([artigo("Prefeitura multa construtora", 1)], "aprovado", {},
                          episodio("Prefeitura multa construtora"), 1.0))
    shutil.copytree(reg.pasta, pasta / "antes")

    abrir = io.open

    class MorreNoMeio:
        """O arquivo marcado: metade do texto vai para ele e o processo morre."""
        def __init__(self, arquivo):
            self.arquivo = arquivo
        def write(self, texto):
            self.arquivo.write(texto[: len(texto) // 2])
            self.arquivo.flush()
            os.kill(os.getpid(), signal.SIGKILL)
        def __enter__(self):
            return self
        def __exit__(self, *erro):
            self.arquivo.close()
        def __getattr__(self, nome):
            return getattr(self.arquivo, nome)

    def abrir_que_morre(arquivo, modo="r", *args, **kwargs):
        aberto = abrir(arquivo, modo, *args, **kwargs)
        if "w" in modo and isinstance(arquivo, (str, os.PathLike)) and Path(arquivo).name.startswith(ponto):
            return MorreNoMeio(aberto)
        return aberto

    builtins.open = io.open = abrir_que_morre
    reg.item([artigo("Câmara aprova orçamento", 2)], "aprovado", {}, episodio("Câmara aprova orçamento"), 1.0)
    sys.exit("o processo devia ter morrido antes de chegar aqui")
''')

_SO_POSIX = pytest.mark.skipif(os.name != "posix", reason="mata o processo filho com SIGKILL")


def _bytes(pasta: Path) -> dict[str, bytes]:
    return {nome: (pasta / nome).read_bytes() for nome in _arquivos(pasta)}


def _morrer_no_meio(tmp_path: Path, ponto: str) -> tuple[int, Path]:
    """Roda o filho, que morre na escrita do arquivo cujo nome começa com `ponto`; devolve o pid dele e a pasta."""
    filho = subprocess.Popen([sys.executable, "-c", _FILHO, str(tmp_path), ponto], cwd=tmp_path,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _, erro = filho.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        filho.kill()
        filho.communicate()
        raise
    assert filho.returncode == -signal.SIGKILL, erro           # morreu no ponto marcado, e não por outro erro
    [pasta] = (tmp_path / "execucoes").iterdir()
    return filho.pid, pasta


def _o_que_os_leitores_veem(pasta: Path) -> tuple[Path, list[int], list[int]]:
    """O relatório que o refazer_qa escolhe na pasta e os episódios que ele e o checar_fidelidade leem dele."""
    relatorio = refazer_qa._relatorio(str(pasta))
    refeitos = refazer_qa.refazer(relatorio)
    with contextlib.redirect_stdout(io.StringIO()):
        casos = checar_fidelidade._carregar(relatorio)
    return relatorio, [r.numero for r in refeitos], [c.numero for c in casos]


@_SO_POSIX
def test_processo_morto_no_meio_do_relatorio_deixa_o_anterior_inteiro(tmp_path):
    """A: o processo morre com metade do relatório escrita (o episódio 2 e a amostra nova já foram para o disco)."""
    pid, pasta = _morrer_no_meio(tmp_path, "relatorio_")
    antes, depois = _bytes(tmp_path / "antes"), _bytes(pasta)
    relatorio = f"relatorio_{_CARIMBO}.json"

    assert depois[relatorio] == antes[relatorio]                 # o relatório anterior, byte a byte
    assert [e["episodio"] for e in json.loads(depois[relatorio])["episodios"]] == [1]
    assert [n for n in depois if n.endswith(".tmp")] == [f"{relatorio}.{pid}.tmp"]   # a sobra do processo morto
    assert [c["id"] for c in json.loads(depois["amostra.json"])["candidatos"]] == [1, 2]
    assert (pasta / "02_aprovado_câmara-aprova-orçamento.json").exists()

    escolhido, refeitos, casos = _o_que_os_leitores_veem(pasta)  # os dois leitores ignoram o .tmp
    assert (escolhido, refeitos, casos) == (pasta / relatorio, [1], [1])


@_SO_POSIX
def test_processo_morto_entre_o_episodio_e_o_relatorio_deixa_o_episodio_solto(tmp_path):
    """B: o processo morre na amostra, depois de gravar o episódio 2 e antes do relatório que o citaria."""
    pid, pasta = _morrer_no_meio(tmp_path, "amostra")
    antes, depois = _bytes(tmp_path / "antes"), _bytes(pasta)
    relatorio = f"relatorio_{_CARIMBO}.json"

    assert (depois["amostra.json"], depois[relatorio]) == (antes["amostra.json"], antes[relatorio])
    assert [n for n in depois if n.endswith(".tmp")] == [f"amostra.json.{pid}.tmp"]
    solto = "02_aprovado_câmara-aprova-orçamento.json"
    assert solto not in antes and json.loads(depois[solto])["titulo_reescrito"] == "Câmara aprova orçamento"
    assert [e["episodio"] for e in json.loads(depois[relatorio])["episodios"]] == [1]

    escolhido, refeitos, casos = _o_que_os_leitores_veem(pasta)  # o episódio solto fica fora da leitura
    assert (escolhido, refeitos, casos) == (pasta / relatorio, [1], [1])


def test_falha_so_na_escrita_do_relatorio_deixa_o_anterior_inteiro(tmp_path, monkeypatch):
    """C: o disco enche com metade do relatório escrita; o episódio 2 e a amostra nova já tinham ido para o disco."""
    reg = registro.RegistroDaExecucao(tmp_path, agora=datetime.datetime(2026, 11, 8, 8, 0, 0))
    reg.entregue(reg.item([_artigo_curto()], "aprovado", {}, _episodio(300), 1.0))
    antes = _bytes(reg.pasta)
    relatorio = f"relatorio_{_CARIMBO}.json"
    abrir = io.open

    class DiscoCheioNoMeio:
        def __init__(self, arquivo):
            self.arquivo = arquivo

        def write(self, texto):
            self.arquivo.write(texto[: len(texto) // 2])
            raise OSError(28, "No space left on device")

        def __enter__(self):
            return self

        def __exit__(self, *erro):
            self.arquivo.close()

        def __getattr__(self, nome):
            return getattr(self.arquivo, nome)

    def abrir_que_enche(arquivo, modo="r", *args, **kwargs):
        aberto = abrir(arquivo, modo, *args, **kwargs)
        if "w" in modo and isinstance(arquivo, (str, os.PathLike)) and Path(arquivo).name.startswith("relatorio_"):
            return DiscoCheioNoMeio(aberto)
        return aberto

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", abrir_que_enche)
        m.setattr(io, "open", abrir_que_enche)
        with pytest.raises(OSError):
            reg.item([_artigo_curto("Câmara aprova orçamento")], "aprovado", {}, _episodio(300), 1.0)
    depois = _bytes(reg.pasta)

    assert depois[relatorio] == antes[relatorio]                 # o relatório anterior, byte a byte
    assert [e["episodio"] for e in json.loads(depois[relatorio])["episodios"]] == [1]
    assert [n for n in depois if n.endswith(".tmp")] == []       # a exceção apagou o temporário
    assert [c["id"] for c in json.loads(depois["amostra.json"])["candidatos"]] == [1, 2]
    assert "02_aprovado_prefeitura-multa-construtora.json" in depois   # o episódio 2, solto

    escolhido, refeitos, casos = _o_que_os_leitores_veem(reg.pasta)
    assert (escolhido, refeitos, casos) == (reg.pasta / relatorio, [1], [1])

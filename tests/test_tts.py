"""Testes de audio/tts.py (gerar_podcast): os turnos sintetizados em paralelo, a ordem da lista do ffmpeg, as duas
pausas, as novas tentativas e o roteiro vazio. Sem rede e sem ffmpeg: o edge_tts.Communicate e o subprocess.run são
falsos."""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from edge_tts.exceptions import NoAudioReceived, WebSocketError

from techdigest.audio import tts

PERSONAGENS = [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Otávio", "papel": "analista"}]
DURACAO = 245.5


class FfmpegFalso:
    """Faz o papel do subprocess.run. Guarda as pausas geradas e, na concatenação, as linhas do concat.txt e o
    conteúdo de cada arquivo (a pasta temporária some depois); o ffprobe devolve DURACAO."""

    def __init__(self):
        self.pausas: list[tuple[str, float]] = []
        self.lista: list[str] | None = None
        self.conteudos: list[bytes] = []

    def __call__(self, cmd, **_):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout=f"{DURACAO}\n", returncode=0)
        if "lavfi" in cmd:
            self.pausas.append((Path(cmd[-1]).name, float(cmd[cmd.index("-t") + 1])))
        elif "concat" in cmd:
            linhas = Path(cmd[cmd.index("-i") + 1]).read_text(encoding="utf-8").splitlines()
            arquivos = [linha.removeprefix("file '").removesuffix("'") for linha in linhas]
            self.lista = [Path(a).name for a in arquivos]
            self.conteudos = [Path(a).read_bytes() for a in arquivos]
        Path(cmd[-1]).write_bytes(b"")
        return SimpleNamespace(stdout="", returncode=0)


class EdgeFalso:
    """Faz o papel do edge_tts.Communicate. Cada síntese espera `demora[texto]` segundos (0,01 por padrão), conta
    quantas estão ao mesmo tempo e levanta, uma por tentativa, as exceções de `falhas[texto]`; a que dá certo grava o
    texto."""

    def __init__(self):
        self.demora: dict[str, float] = {}
        self.falhas: dict[str, list[BaseException]] = {}
        self.ativas = self.max_ativas = 0
        self.chamadas: list[tuple[str, str]] = []
        self.terminadas: list[str] = []

    def __call__(self, texto: str, voz: str):
        edge = self

        class Comunicacao:
            async def save(self, out: str) -> None:
                edge.chamadas.append((texto, voz))
                edge.ativas += 1
                edge.max_ativas = max(edge.max_ativas, edge.ativas)
                try:
                    await asyncio.sleep(edge.demora.get(texto, 0.01))
                    if edge.falhas.get(texto):
                        raise edge.falhas[texto].pop(0)
                    Path(out).write_bytes(texto.encode())
                    edge.terminadas.append(texto)
                finally:
                    edge.ativas -= 1

        return Comunicacao()


@pytest.fixture
def falsos(monkeypatch):
    ffmpeg, edge = FfmpegFalso(), EdgeFalso()
    monkeypatch.setattr(tts, "subprocess", SimpleNamespace(run=ffmpeg))
    monkeypatch.setattr(tts, "edge_tts", SimpleNamespace(Communicate=edge))
    monkeypatch.setattr(tts, "PAUSA_ENTRE_TENTATIVAS_TTS_S", 0)
    return ffmpeg, edge


def _roteiro(*quem: str) -> list[dict]:
    return [{"personagem": p, "fala": f"fala {i} de {p}"} for i, p in enumerate(quem)]


def _onze_turnos() -> list[dict]:
    return _roteiro(*["Helena", "Otávio"] * 5, "Helena")


def _recusa_http(status: int) -> aiohttp.WSServerHandshakeError:
    """O erro que o aiohttp levanta quando o serviço recusa o websocket com uma resposta HTTP (o 403 de 05/11)."""
    return aiohttp.WSServerHandshakeError(SimpleNamespace(real_url="wss://servico.invalido/tts"), (), status=status,
                                          message="Invalid response status")


def test_a_lista_segue_a_ordem_dos_turnos_com_a_pausa_certa(falsos, tmp_path):
    ffmpeg, edge = falsos
    turnos = _roteiro("Helena", "Otávio", "Otávio", "Helena", "Otávio", "Helena")
    for i, t in enumerate(turnos):                       # os últimos terminam primeiro
        edge.demora[t["fala"]] = 0.06 - 0.01 * i

    caminho, duracao = tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "ep" / "episodio.mp3"))

    assert (caminho, duracao) == (str(tmp_path / "ep" / "episodio.mp3"), DURACAO)
    assert edge.terminadas != [t["fala"] for t in turnos]
    assert ffmpeg.lista == [
        "turno_000.mp3", "pausa_longa.mp3", "turno_001.mp3", "pausa_curta.mp3", "turno_002.mp3", "pausa_longa.mp3",
        "turno_003.mp3", "pausa_longa.mp3", "turno_004.mp3", "pausa_longa.mp3", "turno_005.mp3",
    ]
    # cada arquivo de turno tem a fala daquele turno, e as pausas vêm do ffmpeg
    assert ffmpeg.conteudos[::2] == [t["fala"].encode() for t in turnos]
    assert set(ffmpeg.conteudos[1::2]) == {b""}
    # a voz de cada personagem não muda
    vozes = dict(edge.chamadas)
    assert vozes["fala 0 de Helena"] == "pt-BR-FranciscaNeural" and vozes["fala 1 de Otávio"] == "pt-BR-AntonioNeural"


def test_nunca_mais_que_concorrencia_tts_sinteses_ao_mesmo_tempo(falsos, tmp_path, monkeypatch):
    _, edge = falsos
    assert tts.CONCORRENCIA_TTS == 3
    tts.gerar_podcast(_onze_turnos(), PERSONAGENS, str(tmp_path / "a.mp3"))
    assert len(edge.chamadas) == 11 and edge.max_ativas == 3

    monkeypatch.setattr(tts, "CONCORRENCIA_TTS", 2)
    edge.max_ativas = 0
    tts.gerar_podcast(_onze_turnos(), PERSONAGENS, str(tmp_path / "b.mp3"))
    assert edge.max_ativas == 2


def test_as_duas_pausas_sao_geradas_uma_vez_cada(falsos, tmp_path):
    ffmpeg, _ = falsos
    tts.gerar_podcast(_onze_turnos(), PERSONAGENS, str(tmp_path / "a.mp3"))
    assert sorted(ffmpeg.pausas) == [("pausa_curta.mp3", tts.PAUSA_MESMO_PERSONAGEM_S),
                                     ("pausa_longa.mp3", tts.PAUSA_TROCA_PERSONAGEM_S)]
    assert ffmpeg.lista.count("pausa_longa.mp3") == 10


@pytest.mark.parametrize("erro", [aiohttp.ServerDisconnectedError(), aiohttp.ServerTimeoutError("tempo de leitura"),
                                  aiohttp.ClientConnectionError("conexão recusada"), TimeoutError(),
                                  WebSocketError("erro no websocket")], ids=lambda e: type(e).__name__)
def test_erro_de_rede_passageiro_e_repetido(falsos, tmp_path, caplog, erro):
    ffmpeg, edge = falsos
    turnos = _onze_turnos()
    edge.falhas[turnos[4]["fala"]] = [erro]

    with caplog.at_level(logging.WARNING, logger="techdigest.audio.tts"):
        tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "a.mp3"))

    assert [c[0] for c in edge.chamadas].count(turnos[4]["fala"]) == 2
    assert ffmpeg.conteudos[8] == turnos[4]["fala"].encode()
    assert [r.getMessage() for r in caplog.records] == [
        f"Síntese do turno 5 falhou (tentativa 1 de 3): {type(erro).__name__}: {erro}"]


def test_erro_de_rede_que_persiste_chega_a_quem_chamou_e_cancela_os_outros_turnos(falsos, tmp_path, caplog):
    ffmpeg, edge = falsos
    turnos = _onze_turnos()
    edge.falhas[turnos[0]["fala"]] = [aiohttp.ServerDisconnectedError() for _ in range(tts.TENTATIVAS_TTS)]
    edge.demora = {t["fala"]: 5.0 for t in turnos[1:]}  # os outros só terminariam depois de 5 s

    with caplog.at_level(logging.WARNING, logger="techdigest.audio.tts"):
        with pytest.raises(aiohttp.ServerDisconnectedError):      # a exceção original, não um ExceptionGroup
            tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "a.mp3"))

    assert [c[0] for c in edge.chamadas].count(turnos[0]["fala"]) == tts.TENTATIVAS_TTS == 3
    assert len(caplog.records) == 2
    assert edge.terminadas == [] and edge.ativas == 0             # os outros turnos foram cancelados
    assert ffmpeg.lista is None and ffmpeg.pausas == []
    assert not (tmp_path / "a.mp3").exists()


@pytest.mark.parametrize("erro", [_recusa_http(403), _recusa_http(429), _recusa_http(503),
                                  NoAudioReceived("nenhum áudio")], ids=["403", "429", "503", "sem_audio"])
def test_resposta_do_servico_nao_e_repetida(falsos, tmp_path, caplog, erro):
    _, edge = falsos
    turnos = _onze_turnos()
    edge.falhas[turnos[2]["fala"]] = [erro, erro, erro]

    with caplog.at_level(logging.WARNING, logger="techdigest.audio.tts"):
        with pytest.raises(type(erro)) as e:
            tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "a.mp3"))

    assert e.value is erro
    assert [c[0] for c in edge.chamadas].count(turnos[2]["fala"]) == 1
    assert caplog.records == []


def test_roteiro_vazio_levanta_value_error(falsos, tmp_path):
    ffmpeg, edge = falsos
    with pytest.raises(ValueError, match="Roteiro vazio"):
        tts.gerar_podcast([], PERSONAGENS, str(tmp_path / "a.mp3"))
    assert edge.chamadas == [] and ffmpeg.pausas == []

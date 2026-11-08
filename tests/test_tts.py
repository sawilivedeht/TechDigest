"""Testes de audio/tts.py (gerar_podcast): os turnos sintetizados em paralelo, o ajuste de cada fala logo depois da
síntese (as pontas e os silêncios de dentro), a ordem da lista do ffmpeg, as duas pausas, as novas tentativas e o
roteiro vazio. Sem rede e sem ffmpeg: o edge_tts.Communicate e o subprocess.run são falsos."""
import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest
from edge_tts.exceptions import NoAudioReceived, WebSocketError

from techdigest.audio import tts

PERSONAGENS = [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Otávio", "papel": "analista"}]
DURACAO = 245.5           # o que o ffprobe falso devolve para o episódio
DURACAO_DA_FALA = 10.0    # o que cada WAV de fala dura, para o ajuste


class FfmpegFalso:
    """Faz o papel do subprocess.run. A decodificação copia o mp3 da fala (que o Edge falso grava com o texto) para o
    WAV; o silencedetect devolve o que `silencios[(arquivo, limiar)]` mandar (nada, por padrão); o corte (atrim) grava
    a entrada com "|cortado"; as pausas ficam vazias. Na concatenação guarda as linhas do concat.txt e o conteúdo de
    cada arquivo (a pasta temporária some depois). O ffprobe devolve DURACAO."""

    def __init__(self, eventos: list):
        self.pausas: list[tuple[str, float]] = []
        self.lista: list[str] | None = None
        self.conteudos: list[bytes] = []
        self.silencios: dict[tuple[str, str], str] = {}
        self.deteccoes: list[tuple[str, str, str]] = []   # (arquivo, limiar, mínimo)
        self.cortes: list[tuple[str, str]] = []           # (arquivo, filter_complex)
        self.eventos = eventos

    def __call__(self, cmd, **_):
        if cmd[0] == "ffprobe":
            return SimpleNamespace(stdout=f"{DURACAO}\n", stderr="", returncode=0)
        entrada = cmd[cmd.index("-i") + 1]
        if "-af" in cmd:   # silencedetect
            filtro = cmd[cmd.index("-af") + 1]
            limiar = re.search(r"noise=(-?\d+)dB", filtro).group(1)
            minimo = re.search(r":d=([\d.]+)", filtro).group(1)
            self.deteccoes.append((Path(entrada).name, limiar, minimo))
            return SimpleNamespace(stdout="", stderr=self.silencios.get((Path(entrada).name, limiar), ""),
                                   returncode=0)
        saida = Path(cmd[-1])
        if "lavfi" in cmd:
            self.pausas.append((saida.name, float(cmd[cmd.index("-t") + 1])))
            saida.write_bytes(b"")
        elif "concat" in cmd:
            linhas = Path(entrada).read_text(encoding="utf-8").splitlines()
            arquivos = [linha.removeprefix("file '").removesuffix("'") for linha in linhas]
            self.lista = [Path(a).name for a in arquivos]
            self.conteudos = [Path(a).read_bytes() for a in arquivos]
            saida.write_bytes(b"")
        elif "-filter_complex" in cmd:
            self.cortes.append((Path(entrada).name, cmd[cmd.index("-filter_complex") + 1]))
            saida.write_bytes(Path(entrada).read_bytes() + b"|cortado")
        else:   # a decodificação da fala
            self.eventos.append(("decodificada", saida.name))
            saida.write_bytes(Path(entrada).read_bytes())
        return SimpleNamespace(stdout="", stderr="", returncode=0)


class EdgeFalso:
    """Faz o papel do edge_tts.Communicate. Cada síntese espera `demora[texto]` segundos (0,01 por padrão), conta
    quantas estão ao mesmo tempo e levanta, uma por tentativa, as exceções de `falhas[texto]`; a que dá certo grava o
    texto."""

    def __init__(self, eventos: list):
        self.demora: dict[str, float] = {}
        self.falhas: dict[str, list[BaseException]] = {}
        self.ativas = self.max_ativas = 0
        self.chamadas: list[tuple[str, str]] = []
        self.terminadas: list[str] = []
        self.eventos = eventos

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
                    edge.eventos.append(("sintetizada", texto))
                finally:
                    edge.ativas -= 1

        return Comunicacao()


@pytest.fixture
def falsos(monkeypatch):
    eventos: list = []
    ffmpeg, edge = FfmpegFalso(eventos), EdgeFalso(eventos)
    monkeypatch.setattr(tts, "subprocess", SimpleNamespace(run=ffmpeg))
    monkeypatch.setattr(tts, "edge_tts", SimpleNamespace(Communicate=edge))
    monkeypatch.setattr(tts, "PAUSA_ENTRE_TENTATIVAS_TTS_S", 0)
    monkeypatch.setattr(tts, "_duracao_wav", lambda arquivo: DURACAO_DA_FALA)
    return ffmpeg, edge


def _roteiro(*quem: str) -> list[dict]:
    return [{"personagem": p, "fala": f"fala {i} de {p}"} for i, p in enumerate(quem)]


def _onze_turnos() -> list[dict]:
    return _roteiro(*["Helena", "Otávio"] * 5, "Helena")


def _recusa_http(status: int) -> aiohttp.WSServerHandshakeError:
    """O erro que o aiohttp levanta quando o serviço recusa o websocket com uma resposta HTTP (o 403 de 05/11)."""
    return aiohttp.WSServerHandshakeError(SimpleNamespace(real_url="wss://servico.invalido/tts"), (), status=status,
                                          message="Invalid response status")


# ------------------------------------------------------------------------------------------- as funções puras do corte
def _plano(trechos) -> list[float]:
    """Os trechos achatados, para comparar com pytest.approx (que não compara lista de tuplas)."""
    return [x for trecho in trechos for x in trecho]


def test_silencios_do_ffmpeg_le_o_silencedetect_e_fecha_o_ultimo_no_fim_da_fala():
    saida = ("[silencedetect @ 0x5] silence_start: -0.00133333\n"
             "[silencedetect @ 0x5] silence_end: 0.1485 | silence_duration: 0.149833\n"
             "[silencedetect @ 0x5] silence_start: 1.21\n"
             "[silencedetect @ 0x5] silence_end: 2.12 | silence_duration: 0.91\n"
             "[silencedetect @ 0x5] silence_start: 26.18\n")
    assert tts._silencios_do_ffmpeg(saida, 27.0) == [(0.0, 0.1485), (1.21, 2.12), (26.18, 27.0)]
    assert tts._silencios_do_ffmpeg("", 27.0) == []


def test_trechos_mantidos_numa_fala_do_otavio():
    # a fala 2 do item 20 de 07/11: 0,15 s antes do som, três fins de frase de ~0,91 s e 0,82 s depois do som
    pontas = [(0.0, 0.1485), (1.25, 2.08), (26.18, 27.0)]            # o silêncio de dentro a -60 dB não conta
    dentro = [(1.21, 2.12), (8.06, 8.98), (16.28, 17.20), (26.17, 27.0)]
    trechos = tts._trechos_mantidos(27.0, pontas, dentro, margem=0.05, teto=0.45)
    assert _plano(trechos) == pytest.approx(_plano([(0.0985, 1.435), (1.895, 8.285), (8.755, 16.505),
                                                    (16.975, 26.23)]))
    # sai só silêncio: o começo e o fim do som, mais a margem, e o miolo de cada fim de frase, com 0,225 s de cada lado
    assert sum(b - a for a, b in trechos) == pytest.approx(27.0 - 0.0985 - 0.77 - (0.46 + 0.47 + 0.47))


def test_trechos_mantidos_so_corta_silencio_de_dentro_maior_que_o_teto():
    trechos = tts._trechos_mantidos(10.0, [], [(3.0, 3.45), (5.0, 5.46)], margem=0.05, teto=0.45)
    assert _plano(trechos) == pytest.approx(_plano([(0.0, 5.225), (5.235, 10.0)]))


def test_trechos_mantidos_nas_pontas():
    # sem silêncio nas pontas, a fala começa e acaba onde já começava e acabava
    assert tts._trechos_mantidos(10.0, [], [], margem=0.05, teto=0.45) == [(0.0, 10.0)]
    # uma ponta menor que a margem fica inteira
    assert tts._trechos_mantidos(10.0, [(0.0, 0.03), (9.98, 10.0)], [], margem=0.05, teto=0.45) == [(0.0, 10.0)]
    # um silêncio do limiar do teto que toca o começo ou o fim é ponta, não é de dentro
    assert _plano(tts._trechos_mantidos(10.0, [(0.0, 0.2), (9.0, 10.0)], [(0.0, 0.6), (8.9, 10.0)],
                                        margem=0.05, teto=0.45)) == pytest.approx([0.15, 9.05])
    # uma fala sem som fica inteira
    assert tts._trechos_mantidos(10.0, [(0.0, 10.0)], [(0.0, 10.0)], margem=0.05, teto=0.45) == [(0.0, 10.0)]


def test_filtro_dos_trechos():
    assert tts._filtro_dos_trechos([(0.15, 4.225), (4.675, 9.05)]) == (
        "[0]atrim=start=0.150000:end=4.225000,asetpts=PTS-STARTPTS[t0];"
        "[0]atrim=start=4.675000:end=9.050000,asetpts=PTS-STARTPTS[t1];"
        "[t0][t1]concat=n=2:v=0:a=1[s]")


# ------------------------------------------------------------------------------------------------------ gerar_podcast
def test_a_lista_segue_a_ordem_dos_turnos_com_a_pausa_certa(falsos, tmp_path):
    ffmpeg, edge = falsos
    turnos = _roteiro("Helena", "Otávio", "Otávio", "Helena", "Otávio", "Helena")
    for i, t in enumerate(turnos):                       # os últimos terminam primeiro
        edge.demora[t["fala"]] = 0.06 - 0.01 * i

    caminho, duracao = tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "ep" / "episodio.mp3"))

    assert (caminho, duracao) == (str(tmp_path / "ep" / "episodio.mp3"), DURACAO)
    assert edge.terminadas != [t["fala"] for t in turnos]
    assert ffmpeg.lista == [
        "turno_000.wav", "pausa_longa.wav", "turno_001.wav", "pausa_curta.wav", "turno_002.wav", "pausa_longa.wav",
        "turno_003.wav", "pausa_longa.wav", "turno_004.wav", "pausa_longa.wav", "turno_005.wav",
    ]
    # cada arquivo de turno tem a fala daquele turno, e as pausas vêm do ffmpeg; sem silêncio a mais, nada é cortado
    assert ffmpeg.conteudos[::2] == [t["fala"].encode() for t in turnos]
    assert set(ffmpeg.conteudos[1::2]) == {b""}
    assert ffmpeg.cortes == []
    # a voz de cada personagem não muda
    vozes = dict(edge.chamadas)
    assert vozes["fala 0 de Helena"] == "pt-BR-FranciscaNeural" and vozes["fala 1 de Otávio"] == "pt-BR-AntonioNeural"


def test_a_fala_com_silencio_a_mais_entra_cortada_na_lista(falsos, tmp_path):
    ffmpeg, _ = falsos
    turnos = _roteiro("Helena", "Otávio", "Helena")
    ffmpeg.silencios[("turno_001.wav", "-60")] = (
        "silence_start: 0\nsilence_end: 0.2 | silence_duration: 0.2\nsilence_start: 9.0\n")
    ffmpeg.silencios[("turno_001.wav", "-50")] = (
        "silence_start: 0\nsilence_end: 0.25 | silence_duration: 0.25\n"
        "silence_start: 4.0\nsilence_end: 4.9 | silence_duration: 0.9\nsilence_start: 8.95\n")

    tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "a.mp3"))

    assert ffmpeg.cortes == [("turno_001.wav", tts._filtro_dos_trechos([(0.15, 4.225), (4.675, 9.05)]))]
    assert ffmpeg.lista == ["turno_000.wav", "pausa_longa.wav", "turno_001_ajustado.wav", "pausa_longa.wav",
                            "turno_002.wav"]
    assert ffmpeg.conteudos[2] == "fala 1 de Otávio|cortado".encode()
    # cada fala passa pelas duas detecções: as pontas a -60 dB e os silêncios de dentro a -50 dB, maiores que o teto
    assert sorted(ffmpeg.deteccoes) == sorted(
        [(f"turno_{i:03d}.wav", "-60", "0.01") for i in range(3)]
        + [(f"turno_{i:03d}.wav", "-50", str(tts.TETO_SILENCIO_INTERNO_S)) for i in range(3)])


def test_cada_fala_e_ajustada_logo_depois_da_sintese_dela(falsos, tmp_path):
    ffmpeg, edge = falsos
    turnos = _roteiro("Helena", "Otávio", "Helena")
    edge.demora[turnos[0]["fala"]] = 0.3          # a primeira fala é a última a ficar pronta
    tts.gerar_podcast(turnos, PERSONAGENS, str(tmp_path / "a.mp3"))
    eventos = ffmpeg.eventos
    assert eventos.index(("decodificada", "turno_001.wav")) < eventos.index(("sintetizada", "fala 0 de Helena"))
    assert eventos.index(("sintetizada", "fala 0 de Helena")) < eventos.index(("decodificada", "turno_000.wav"))


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
    assert sorted(ffmpeg.pausas) == [("pausa_curta.wav", tts.PAUSA_MESMO_PERSONAGEM_S),
                                     ("pausa_longa.wav", tts.PAUSA_TROCA_PERSONAGEM_S)]
    assert ffmpeg.lista.count("pausa_longa.wav") == 10


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

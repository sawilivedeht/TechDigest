"""O mp3 do episódio, gerado pelo ffmpeg de verdade (sem rede: o edge_tts.Communicate é falso e grava um tom curto em mp3
de 24 kHz, como o Edge-TTS). Fica fora do test_tts.py, que roda sem ffmpeg."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from techdigest.audio import tts

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="precisa do ffmpeg e do ffprobe no PATH")


class EdgeComTom:
    """Faz o papel do edge_tts.Communicate: grava meio segundo de tom em mp3 de 24 kHz mono, 48k, como o Edge-TTS."""

    def __init__(self, texto, voz):
        pass

    async def save(self, out):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:sample_rate=24000:duration=0.5",
                        "-ac", "1", "-c:a", "libmp3lame", "-b:a", "48k", out], check=True)


def test_o_mp3_do_episodio_nao_tem_marca_id3_nem_quadro_xing_ou_info(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "edge_tts", SimpleNamespace(Communicate=EdgeComTom))
    turnos = [{"personagem": "Helena", "fala": "Olá."}, {"personagem": "Otávio", "fala": "Bom dia."}]
    personagens = [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Otávio", "papel": "analista"}]
    caminho, duracao = tts.gerar_podcast(turnos, personagens, str(tmp_path / "episodio.mp3"))

    dados = (tmp_path / "episodio.mp3").read_bytes()
    assert caminho == str(tmp_path / "episodio.mp3") and duracao > 1.0   # duas falas de 0,5 s e a pausa de 0,65 s
    assert not dados.startswith(b"ID3")
    # o arquivo começa direto num quadro de áudio (sincronismo de 11 bits), e não num quadro de cabeçalho Xing ou Info,
    # que o ffmpeg poria no primeiro quadro
    assert dados[0] == 0xFF and dados[1] & 0xE0 == 0xE0
    assert b"Xing" not in dados[:2048] and b"Info" not in dados[:2048]

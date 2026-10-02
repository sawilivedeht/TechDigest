"""Geração do episódio de podcast multi-voz — Edge-TTS + concatenação via ffmpeg."""
import asyncio
import subprocess
import tempfile
from pathlib import Path

import edge_tts

import logging
logger = logging.getLogger("techdigest.audio.tts")

VOZ_FIXA = {"Helena": "pt-BR-FranciscaNeural"}   # apresentadora = marca sonora fixa
VOZES_DIVERSIDADE = [
    "pt-BR-AntonioNeural",
    "pt-BR-ThalitaNeural",
    "pt-BR-GustavoNeural",
    "pt-BR-LeticiaNeural",
]

PAUSA_MESMO_PERSONAGEM_S = 0.3   # respiro curto
PAUSA_TROCA_PERSONAGEM_S = 0.65  # pausa de conversa


def atribuir_vozes(personagens: list[dict]) -> dict[str, str]:
    """Helena tem voz fixa; os demais recebem vozes distintas em ordem de declaração."""
    mapeamento, proxima = {}, 0
    for p in personagens:
        if p["nome"] not in VOZ_FIXA:
            mapeamento[p["nome"]] = VOZES_DIVERSIDADE[proxima % len(VOZES_DIVERSIDADE)]
            proxima += 1
    for nome, voz in VOZ_FIXA.items():
        if any(p["nome"] == nome for p in personagens):
            mapeamento[nome] = voz
    return mapeamento


async def _synth(texto: str, voz: str, out: str) -> None:
    await edge_tts.Communicate(texto, voz).save(out)


def _silencio(out: str, duracao_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", str(duracao_s), "-b:a", "48k", out],
        check=True,
    )


def _duracao(arquivo: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", arquivo],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def gerar_podcast(turnos: list[dict], personagens: list[dict], out_path: str) -> tuple[str, float]:
    """Narra cada turno com a voz do personagem, insere pausas de diálogo,
    concatena via ffmpeg e retorna (caminho, duração em segundos)."""
    if not turnos:
        raise ValueError("Roteiro vazio — nada para narrar.")

    vozes = atribuir_vozes(personagens)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        partes: list[str] = []
        for i, turno in enumerate(turnos):
            voz = vozes.get(turno["personagem"], VOZES_DIVERSIDADE[0])
            f = str(Path(tmp) / f"turno_{i:03d}.mp3")
            asyncio.run(_synth(turno["fala"], voz, f))
            partes.append(f)

            if i < len(turnos) - 1:
                mesmo = turno["personagem"] == turnos[i + 1]["personagem"]
                p = str(Path(tmp) / f"pausa_{i:03d}.mp3")
                _silencio(p, PAUSA_MESMO_PERSONAGEM_S if mesmo else PAUSA_TROCA_PERSONAGEM_S)
                partes.append(p)

        lista = Path(tmp) / "concat.txt"
        lista.write_text("\n".join(f"file '{p}'" for p in partes), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(lista),
             "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
            check=True,
        )

    return str(out), _duracao(str(out))
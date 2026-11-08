"""Geração do episódio de podcast multi-voz — Edge-TTS + concatenação via ffmpeg."""
import asyncio
import subprocess
import tempfile
from pathlib import Path

# O aiohttp é o cliente do edge-tts e vem instalado com ele, sem estar no pyproject.toml: entra aqui só para reconhecer
# as falhas de rede da síntese. Quem fixar as versões (a frente 2 das melhorias de 07/11) precisa lembrar dele.
import aiohttp
import edge_tts
from edge_tts.exceptions import WebSocketError

import logging

from techdigest.ai.elenco import vaga

logger = logging.getLogger("techdigest.audio.tts")

VOZ_FIXA = {"Helena": "pt-BR-FranciscaNeural"}   # apresentadora = marca sonora fixa
# A voz de cada vaga de analista (`elenco.VAGAS`, na mesma posição: masculina, feminina, masculina); a última sobra
# para quem não tem nome da lista.
VOZES_DIVERSIDADE = [
    "pt-BR-AntonioNeural",
    "pt-BR-ThalitaNeural",
    "pt-BR-GustavoNeural",
    "pt-BR-LeticiaNeural",
]

PAUSA_MESMO_PERSONAGEM_S = 0.3   # respiro curto
PAUSA_TROCA_PERSONAGEM_S = 0.65  # pausa de conversa

# Os turnos de um episódio são sintetizados em paralelo, no máximo CONCORRENCIA_TTS ao mesmo tempo: o Edge-TTS é um
# serviço não oficial, e muitas conexões juntas podem ser barradas. Um turno de cada vez, na execução real de 07/11, o
# áudio levou 44 s por item em média, quase tudo esperando o serviço (docs/melhorias/01-audio.md).
CONCORRENCIA_TTS = 3
# Um turno é refeito só numa falha de rede ou de tempo, até TENTATIVAS_TTS vezes no total (a primeira e mais duas), com
# uma pausa entre elas. Uma resposta HTTP do serviço não se repete: nem o 403, que em 05/11 foi sinal de versão errada
# do edge-tts (e que o próprio edge-tts já repete uma vez, depois de ajustar o relógio), nem um 429 ou 5xx no handshake.
TENTATIVAS_TTS = 3
PAUSA_ENTRE_TENTATIVAS_TTS_S = 2.0
# ClientConnectionError cobre a conexão recusada, a queda no meio e os tempos do socket (ServerTimeoutError);
# TimeoutError, um tempo esgotado fora do aiohttp; WebSocketError, um erro que chega pelo websocket do serviço.
ERROS_PASSAGEIROS_TTS = (aiohttp.ClientConnectionError, TimeoutError, WebSocketError)


def atribuir_vozes(personagens: list[dict]) -> dict[str, str]:
    """Helena tem voz fixa; o analista com nome da lista (`elenco.VAGAS`) tem a voz da vaga dele, do gênero do nome; os
    demais recebem, em ordem de declaração, as vozes que sobraram (e, sem sobra, as vozes de novo, a partir da primeira)."""
    mapeamento = {}
    for p in personagens:
        if p["nome"] not in VOZ_FIXA and (i := vaga(p["nome"])) is not None:
            mapeamento[p["nome"]] = VOZES_DIVERSIDADE[i]
    livres = [v for v in VOZES_DIVERSIDADE if v not in mapeamento.values()] or VOZES_DIVERSIDADE
    proxima = 0
    for p in personagens:
        if p["nome"] not in VOZ_FIXA and p["nome"] not in mapeamento:
            mapeamento[p["nome"]] = livres[proxima % len(livres)]
            proxima += 1
    for nome, voz in VOZ_FIXA.items():
        if any(p["nome"] == nome for p in personagens):
            mapeamento[nome] = voz
    return mapeamento


async def _synth(texto: str, voz: str, out: str) -> None:
    await edge_tts.Communicate(texto, voz).save(out)


async def _sintetizar_turno(i: int, texto: str, voz: str, out: str, limite: asyncio.Semaphore) -> None:
    """Um turno, com nova tentativa só em falha de rede ou de tempo. A vaga do limite fica com o turno durante a pausa
    entre as tentativas, para não abrir mais conexões enquanto o serviço falha. O `save` reabre o arquivo a cada vez."""
    async with limite:
        for n in range(1, TENTATIVAS_TTS + 1):
            try:
                await _synth(texto, voz, out)
                return
            except ERROS_PASSAGEIROS_TTS as e:
                if n == TENTATIVAS_TTS:
                    raise
                logger.warning("Síntese do turno %d falhou (tentativa %d de %d): %s: %s",
                               i + 1, n, TENTATIVAS_TTS, type(e).__name__, e)
                await asyncio.sleep(PAUSA_ENTRE_TENTATIVAS_TTS_S)


async def _sintetizar_turnos(turnos: list[dict], vozes: dict[str, str], pasta: Path) -> list[str]:
    """Sintetiza os turnos, no máximo CONCORRENCIA_TTS ao mesmo tempo, e devolve os arquivos na ordem dos turnos. Uma
    falha que persiste cancela os outros turnos e chega a quem chamou como a exceção original, não como o
    ExceptionGroup do TaskGroup: o pipeline registra o tipo dela."""
    limite = asyncio.Semaphore(CONCORRENCIA_TTS)
    arquivos = [str(pasta / f"turno_{i:03d}.mp3") for i in range(len(turnos))]
    try:
        async with asyncio.TaskGroup() as tg:
            for i, (turno, arquivo) in enumerate(zip(turnos, arquivos)):
                voz = vozes.get(turno["personagem"], VOZES_DIVERSIDADE[0])
                tg.create_task(_sintetizar_turno(i, turno["fala"], voz, arquivo, limite))
    except ExceptionGroup as grupo:
        raise grupo.exceptions[0] from None
    return arquivos


def _silencio(out: str, duracao_s: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
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
    """Narra cada turno com a voz do personagem (até CONCORRENCIA_TTS turnos ao mesmo tempo, num só asyncio.run),
    insere pausas de diálogo, concatena via ffmpeg na ordem dos turnos e retorna (caminho, duração em segundos)."""
    if not turnos:
        raise ValueError("Roteiro vazio — nada para narrar.")

    vozes = atribuir_vozes(personagens)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        falas = asyncio.run(_sintetizar_turnos(turnos, vozes, Path(tmp)))
        # Só há duas pausas: cada uma é gerada uma vez e repetida na lista.
        curta, longa = str(Path(tmp) / "pausa_curta.mp3"), str(Path(tmp) / "pausa_longa.mp3")
        _silencio(curta, PAUSA_MESMO_PERSONAGEM_S)
        _silencio(longa, PAUSA_TROCA_PERSONAGEM_S)
        partes: list[str] = []
        for i, fala in enumerate(falas):
            partes.append(fala)
            if i < len(turnos) - 1:
                partes.append(curta if turnos[i]["personagem"] == turnos[i + 1]["personagem"] else longa)

        lista = Path(tmp) / "concat.txt"
        lista.write_text("\n".join(f"file '{p}'" for p in partes), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(lista),
             "-c:a", "libmp3lame", "-b:a", "64k", str(out)],
            check=True,
        )

    return str(out), _duracao(str(out))
"""Geração do episódio de podcast multi-voz — Edge-TTS + concatenação via ffmpeg."""
import asyncio
import re
import subprocess
import tempfile
import wave
from pathlib import Path

# O aiohttp é o cliente do edge-tts: entra aqui só para reconhecer as falhas de rede da síntese. Como este módulo o
# importa direto, ele está declarado no pyproject.toml (frente 9 das melhorias de 07/11), além de vir com o edge-tts.
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

# Logo depois da síntese, cada fala perde o silêncio que o Edge-TTS põe a mais (a variante E do experimento das pausas
# de 08/11/2026, escolhida pelo dono de ouvido; docs/melhorias/01-audio.md). O Edge-TTS deixa uns 0,18 s de silêncio no
# começo de cada fala e uns 0,83 s no fim, o que fazia a troca de personagem durar 1,66 s com a pausa de 0,65 s; e a voz
# dos analistas (Antonio) pára uns 0,91 s em cada fim de frase. As pontas ficam com MARGEM_DAS_PONTAS_S de silêncio
# antes e depois do som (o som é o que passa de LIMIAR_DAS_PONTAS_DB); os silêncios de dentro da fala (abaixo de
# LIMIAR_DO_TETO_DB) ficam com no máximo TETO_SILENCIO_INTERNO_S: sai o miolo, e metade do teto fica de cada lado. O
# corte é por instantes (atrim): só sai silêncio, e o resto da fala fica idêntico ao que o Edge-TTS mandou.
MARGEM_DAS_PONTAS_S = 0.05
LIMIAR_DAS_PONTAS_DB = -60
TETO_SILENCIO_INTERNO_S = 0.45
LIMIAR_DO_TETO_DB = -50
_TOLERANCIA_S = 0.001   # um silêncio que começa até aqui toca o começo da fala (e o mesmo no fim)


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


def _silencios_do_ffmpeg(saida: str, duracao: float) -> list[tuple[float, float]]:
    """Os silêncios que o silencedetect do ffmpeg escreveu, (início, fim); um silêncio sem fim vai até o fim da fala."""
    inicios = [max(0.0, float(x)) for x in re.findall(r"silence_start: (\S+)", saida)]
    fins = [float(x) for x in re.findall(r"silence_end: (\S+)", saida)]
    if len(fins) < len(inicios):
        fins.append(duracao)
    return list(zip(inicios, fins))


def _trechos_mantidos(duracao: float, silencios_das_pontas: list[tuple[float, float]],
                      silencios_de_dentro: list[tuple[float, float]], margem: float,
                      teto: float) -> list[tuple[float, float]]:
    """O que fica de uma fala de `duracao` segundos: do começo do som menos a margem ao fim do som mais a margem, sem o
    miolo dos silêncios de dentro maiores que o teto (fica metade do teto de cada lado). Os silêncios das pontas são os
    do limiar das pontas que tocam o começo ou o fim da fala; os de dentro, os do limiar do teto que não tocam nenhum
    dos dois. Uma fala sem som fica inteira."""
    som_ini = next((e for s, e in silencios_das_pontas if s <= _TOLERANCIA_S), 0.0)
    som_fim = next((s for s, e in silencios_das_pontas if e >= duracao - _TOLERANCIA_S), duracao)
    if som_ini >= som_fim:
        return [(0.0, duracao)]
    ini, fim = max(0.0, som_ini - margem), min(duracao, som_fim + margem)
    trechos = []
    for s, e in sorted(silencios_de_dentro):
        if s <= _TOLERANCIA_S or e >= duracao - _TOLERANCIA_S or e - s <= teto:
            continue
        a, b = max(s + teto / 2, ini), min(e - teto / 2, fim)
        if a < b:
            trechos.append((ini, a))
            ini = b
    trechos.append((ini, fim))
    return [(a, b) for a, b in trechos if b > a]


def _filtro_dos_trechos(trechos: list[tuple[float, float]]) -> str:
    """O filter_complex do ffmpeg que junta os trechos mantidos de uma fala, cortados por instantes (atrim)."""
    cortes = ";".join(f"[0]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[t{k}]"
                      for k, (a, b) in enumerate(trechos))
    return cortes + ";" + "".join(f"[t{k}]" for k in range(len(trechos))) + f"concat=n={len(trechos)}:v=0:a=1[s]"


def _duracao_wav(arquivo: str) -> float:
    with wave.open(arquivo) as w:
        return w.getnframes() / w.getframerate()


def _detectar_silencios(arquivo: str, limiar_db: float, minimo_s: float, duracao: float) -> list[tuple[float, float]]:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", arquivo,
         "-af", f"silencedetect=noise={limiar_db}dB:d={minimo_s}", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    return _silencios_do_ffmpeg(r.stderr, duracao)


def _ajustar_fala(mp3: str, wav: str) -> str:
    """A fala sintetizada em WAV, sem o silêncio a mais das pontas e de dentro (ver TETO_SILENCIO_INTERNO_S); devolve o
    arquivo que entra na concatenação. Sem nada a cortar, é o WAV inteiro."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-c:a", "pcm_s16le", wav], check=True)
    duracao = _duracao_wav(wav)
    trechos = _trechos_mantidos(
        duracao,
        _detectar_silencios(wav, LIMIAR_DAS_PONTAS_DB, 0.01, duracao),
        _detectar_silencios(wav, LIMIAR_DO_TETO_DB, TETO_SILENCIO_INTERNO_S, duracao),
        MARGEM_DAS_PONTAS_S, TETO_SILENCIO_INTERNO_S,
    )
    if trechos == [(0.0, duracao)]:
        return wav
    ajustado = wav.removesuffix(".wav") + "_ajustado.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-filter_complex", _filtro_dos_trechos(trechos),
                    "-map", "[s]", "-c:a", "pcm_s16le", ajustado], check=True)
    return ajustado


async def _sintetizar_e_ajustar(i: int, texto: str, voz: str, mp3: str, wav: str, limite: asyncio.Semaphore) -> str:
    """A síntese de um turno e, logo em seguida, o ajuste dele numa thread: o ajuste de uma fala corre enquanto as
    outras ainda são sintetizadas, e não ocupa a vaga do limite de sínteses."""
    await _sintetizar_turno(i, texto, voz, mp3, limite)
    return await asyncio.to_thread(_ajustar_fala, mp3, wav)


async def _sintetizar_turnos(turnos: list[dict], vozes: dict[str, str], pasta: Path) -> list[str]:
    """Sintetiza os turnos, no máximo CONCORRENCIA_TTS ao mesmo tempo, ajusta cada fala logo depois da síntese dela e
    devolve os arquivos ajustados na ordem dos turnos. Uma falha que persiste cancela os outros turnos e chega a quem
    chamou como a exceção original, não como o ExceptionGroup do TaskGroup: o pipeline registra o tipo dela."""
    limite = asyncio.Semaphore(CONCORRENCIA_TTS)
    tarefas = []
    try:
        async with asyncio.TaskGroup() as tg:
            for i, turno in enumerate(turnos):
                voz = vozes.get(turno["personagem"], VOZES_DIVERSIDADE[0])
                tarefas.append(tg.create_task(_sintetizar_e_ajustar(
                    i, turno["fala"], voz, str(pasta / f"turno_{i:03d}.mp3"), str(pasta / f"turno_{i:03d}.wav"),
                    limite)))
    except ExceptionGroup as grupo:
        raise grupo.exceptions[0] from None
    return [t.result() for t in tarefas]


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
    """Narra cada turno com a voz do personagem (até CONCORRENCIA_TTS turnos ao mesmo tempo, num só asyncio.run), tira
    o silêncio a mais de cada fala, insere pausas de diálogo, concatena via ffmpeg na ordem dos turnos e retorna
    (caminho, duração em segundos)."""
    if not turnos:
        raise ValueError("Roteiro vazio — nada para narrar.")

    vozes = atribuir_vozes(personagens)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        falas = asyncio.run(_sintetizar_turnos(turnos, vozes, Path(tmp)))
        # Só há duas pausas: cada uma é gerada uma vez e repetida na lista. Saem em WAV, como as falas ajustadas (pela
        # extensão: o -b:a do _silencio não vale para WAV), e só a concatenação codifica em mp3.
        curta, longa = str(Path(tmp) / "pausa_curta.wav"), str(Path(tmp) / "pausa_longa.wav")
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
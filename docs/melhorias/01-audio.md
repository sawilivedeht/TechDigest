# Frente 1: áudio

Arquivo no Projeto: `claude/frentes/01-audio.md` · no repositório: `docs/melhorias/01-audio.md`

| | |
|---|---|
| Branch | `melhoria/audio` |
| Worktree | `/home/sytw/Projetos/techdigest-audio` |
| Onda | 1 |
| Depende de | nada |
| Conflita com | frente 4, na linha 55 do `tts.py` |

## Objetivo

Medir quanto do tempo de cada item vai para o áudio e, com o ok do dono, sintetizar os turnos do roteiro em paralelo.

## Por que

- Nas medidas de 14/10 do roteiro, um item leva uns 3,2 min: 28 s de análise de lados, 95 s de geração, 25 s de correção
  em média, 35 s de áudio e 10 s de Telegram. Na produção de 07/10, o áudio levou de 28 a 48 s. É perto de um quinto do
  item.
- `src/techdigest/audio/tts.py` sintetiza um turno de cada vez: um `asyncio.run(_synth(...))` por turno (linha 85) e um
  processo ffmpeg por pausa (`_silencio`, linha 91), embora só existam duas durações de pausa
  (`PAUSA_MESMO_PERSONAGEM_S`, 0,3 s, e `PAUSA_TROCA_PERSONAGEM_S`, 0,65 s).

## Etapa 1: medição (só leitura, sem código)

No log da produção, `/home/sytw/Projetos/techdigest/data/logs/techdigest.log` e os rotacionados (`.1` a `.7`), a execução
real de 07/11 (01h01, 59 min). Por item:
- o áudio: do `Vozes: ...` (`pipeline.py`, linha 230) ao `✅ <título> — episódio: N min` (linha 242), que é a síntese e o
  ffmpeg;
- a duração do episódio, que vem na linha do `✅`;
- o upload: `Áudio enviado: X MB em Ns` (`delivery/telegram.py`).

Resultado: média, mínimo, máximo e a soma do áudio contra os 59 min. O script fica fora do git, em
`/home/sytw/Projetos/techdigest/data/agrupamento/medicao_audio_20261107/`.

Decisão do dono: seguir para a etapa 2 se o áudio passar de uns 20 s por item.

## Etapa 2: implementação

Só em `src/techdigest/audio/tts.py` e num teste novo:
- `gerar_podcast(turnos, personagens, out_path)` mantém a assinatura e o retorno `(caminho, duração)`; o pipeline não muda.
- Um só `asyncio.run` por episódio. Os turnos são sintetizados com no máximo `CONCORRENCIA_TTS` ao mesmo tempo (constante
  do módulo; começar com 3), num `asyncio.TaskGroup` com `asyncio.Semaphore`. Cada turno grava `turno_NNN.mp3`, e a ordem
  do `concat.txt` é a dos turnos.
- Nova tentativa por turno só para erro de rede ou de tempo (até 2, com uma pausa curta), como o Telegram já faz com a
  `FalhaDeRede`. Um 403 não se repete: em 05/11 ele foi sinal de versão errada do `edge-tts`. Conferir que exceções o
  `edge-tts` 7.3.1 levanta.
- As duas pausas geradas uma vez cada (`pausa_curta.mp3` e `pausa_longa.mp3`) e repetidas na lista do ffmpeg.
- A string do `_silencio` sem o `f` (`"anullsrc=r=24000:cl=mono"`); a frente 4 faz a mesma correção.
- Vozes, bitrate e concatenação não mudam.

Fora do escopo: sintetizar o áudio de um item enquanto o modelo gera o seguinte. Mexe na ordem da entrega, no freio da
máquina e no orçamento de tempo; fica como ideia para depois.

## Testes

`tests/test_tts.py`, novo (hoje só o `tests/test_elenco.py` testa o `atribuir_vozes`), com o `edge_tts.Communicate` e o
`subprocess.run` falsos:
- a ordem das linhas do `concat.txt` segue a dos turnos, com a pausa certa entre eles;
- nunca há mais que `CONCORRENCIA_TTS` sínteses ao mesmo tempo;
- o `_silencio` roda duas vezes por episódio;
- um erro de rede passageiro é repetido; um que persiste chega a quem chamou; um 403 não é repetido;
- roteiro vazio continua levantando `ValueError`.

## Aceite separado

- A suíte inteira.
- Áudio real, sem o modelo e sem o Telegram: um script fora do git, em
  `/home/sytw/Projetos/techdigest/data/agrupamento/audio_paralelo_AAAAMMDD/`, pega 3 episódios aprovados da pasta de 07/11
  em `/home/sytw/Projetos/techdigest/data/execucoes/` e gera o áudio com o código da `master` e com o da branch. Compara o
  tempo e a duração (ffprobe), que deve ficar igual, com folga de 1 a 2%. O dono ouve um deles.

## Riscos

- O Edge-TTS é um serviço não oficial: muitas conexões ao mesmo tempo podem ser barradas. Por isso o limite começa em 3.
- A versão do `edge-tts` importa (o 403 de 05/11); a frente 2 cuida de fixar as versões.

## Documentação

- `CLAUDE.md`, "Architecture", passo 5: uma frase sobre os turnos em paralelo.
- Este arquivo: os números da medição e do aceite.

## Prompt inicial para o Claude Code

```text
Frente 1 (áudio) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-audio, branch
melhoria/audio. Leia docs/plano-melhorias.md, docs/melhorias/01-audio.md e docs/regras-de-sessao.md.
Agora só a etapa 1, só leitura e sem mudar código: meça o áudio da execução real de 07/11 (01h01) no log da produção,
/home/sytw/Projetos/techdigest/data/logs/techdigest.log e os rotacionados .1 a .7. Por item: o tempo entre a linha
"Vozes:" e a linha "✅ ... episódio:", a duração do episódio que essa linha traz e o "Áudio enviado: ... em Ns". Quero
média, mínimo, máximo e a soma do áudio contra os 59 minutos. O script fica em
/home/sytw/Projetos/techdigest/data/agrupamento/medicao_audio_20261107/, fora do git.
Depois me mostre os números e o plano da etapa 2, com a lista "Leituras minhas, para você corrigir", e espere a
aprovação. Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit,
a suíte inteira e a seção "Estado" de docs/melhorias/01-audio.md atualizada.
```

## Estado

- 07/11/2026: não começada.

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
- 08/11/2026: etapa 1 (medição) feita; etapa 2 aprovada pelo dono, em implementação. Branch `melhoria/audio`, sobre
  `64bd21b`. 667 testes passam.

### Medição (etapa 1)

Execução real de 07/11, 01:01:36 a 02:00:33 (3537 s, "20 notícia(s) entregue(s) em 59 min"), 20 itens, todos
aprovados. Está toda no `techdigest.log`, linhas 16012 a 16237: os rotacionados `.1` a `.7` ainda não existem (o log tem
1,6 MB e gira aos 2 MB). O script e o resultado ficam em
`/home/sytw/Projetos/techdigest/data/agrupamento/medicao_audio_20261107/` (`medir_audio.py`, `medicao.csv`,
`resumo.txt`); a soma foi conferida por um segundo pareamento das linhas `Vozes:` e `✅`. O log tem resolução de 1 s.

| | média | mín. | máx. | soma |
|---|---|---|---|---|
| Áudio (`Vozes:` → `✅`) | 44 s | 27 s (item 19) | 64 s (item 20) | 875 s = 14,6 min |
| Duração do episódio (linha do `✅`) | 4,0 min | 2,8 min | 4,8 min | 79,9 min |
| Upload (`Áudio enviado`) | 3 s | 2 s | 3 s | 59 s |
| Telegram inteiro (`✅` → `Entregue`) | 3 s | 3 s | 5 s | 68 s |
| Item inteiro (`Resumindo` → `Entregue`) | 170 s | 123 s | 225 s | 3400 s |

- O áudio é 24,7% dos 59 min da execução e 25,7% do tempo somado dos itens; a mediana é 42,5 s (entre o item 17, com
  42 s, e o 12, com 43 s), e todos os 20 itens passam de 20 s. O upload é 1,7% da execução.
- 216 turnos (11 por episódio, 9 nos itens 2 e 19): 4,0 s de síntese por turno em média (3,0 a 5,8 s), uns 10,9 s por
  minuto de episódio.
- O ffmpeg, medido à parte na máquina, sem rede e sem o modelo: as 10 pausas de um episódio de 11 turnos levam 0,28 s,
  a concatenação de 4,2 min (recodificada em 64k) 0,54 s e o ffprobe 0,03 s. Uns 98% dos 44 s são a síntese no
  Edge-TTS, um turno de cada vez; gerar as pausas uma vez só poupa uns 0,2 s por episódio.
- Estimativa para a etapa 2, a conferir no aceite: com 3 sínteses ao mesmo tempo, uns 15 a 20 s por item, uns 8 min a
  menos numa execução de 20 itens (perto de 14%), se o Edge-TTS não ficar mais lento com 3 conexões.

### Decisões do dono (08/11/2026)

- Seguir para a etapa 2: o áudio passa de 20 s por item (média 44 s).
- Leituras do plano da etapa 2, aprovadas como propostas:
  - `TENTATIVAS_TTS = 3` (a primeira e mais duas) e 2 s de pausa entre elas, constantes do `tts.py`, fora do
    `config.py` (que é da frente 6);
  - repetem: `aiohttp.ClientConnectionError`, `TimeoutError` e o `WebSocketError` do edge-tts; não repetem: qualquer
    `aiohttp.ClientResponseError` (o 403, e também 429 e 5xx no handshake), `NoAudioReceived`, `UnexpectedResponse`,
    `UnknownResponse` e `SkewAdjustmentError`. O edge-tts 7.3.1 já repete um 403 uma vez sozinho (ajusta o relógio
    pelo cabeçalho `Date`); o nosso código não acrescenta outra;
  - uma falha que persiste cancela os outros turnos e chega ao pipeline como a exceção original, não como
    `ExceptionGroup`;
  - `import aiohttp` direto no `tts.py`, sem declarar no `pyproject.toml` (vem com o edge-tts);
  - as duas pausas geradas sempre, uma vez cada;
  - nenhuma linha nova em INFO; só um WARNING por nova tentativa;
  - dois commits: este, só com a medição, e o da implementação.
- Aceite separado só depois do ok do dono ao commit da implementação: os itens 19 (o mais curto), um mediano e 20 (o
  mais longo) de 07/11, rodadas alternadas entre a `master` e a branch, pelo menos duas de cada versão, com as novas
  tentativas registradas.

### Pendências

- O commit da implementação (`tts.py` e `tests/test_tts.py`), depois de conferir que o `scripts/resumo_lotes.py` não lê
  o WARNING novo e que a linha do `✅` fica idêntica.
- O aceite separado, com o ok do dono.

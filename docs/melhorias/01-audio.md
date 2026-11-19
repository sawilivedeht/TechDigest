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
- 08/11/2026: etapa 2 implementada, à espera do ok do dono para o aceite separado. Branch `melhoria/audio`, sobre
  `336dbde` (a medição). 681 testes passam (os 667 e os 14 de `tests/test_tts.py`).
- 08/11/2026: aceite separado medido (24 gerações, nenhuma falha, nenhuma nova tentativa), à espera de o dono ouvir um
  episódio. Branch `melhoria/audio`, sobre `d8dc640` (a implementação). 681 testes passam.
- 08/11/2026: **pronta para integração.** O dono ouviu `rodada_4/branch/20.mp3` e aprovou o aceite. Branch
  `melhoria/audio`, sobre `f03ef9b` (o aceite). 681 testes passam.
- 08/11/2026: o dono achou longas as pausas "entre falas do mesmo personagem"; a frente voltou a "em implementação".
  Medição das pausas, cinco variantes do item 20 e a escolha do dono, de ouvido: a variante E, implementada em
  `8492af8` e conferida contra a variante ouvida. **De novo pronta para integração.** Branch `melhoria/audio`, sobre
  `8492af8`. 688 testes passam (os 681 e 7 novos de `tests/test_tts.py`).
- 08/11/2026: nada em curso: nenhum script rodando, sessão de teste `inactive`, branch limpa (fora o
  `src/techdigest.egg-info/SOURCES.txt`, que não entra nos commits). Pronta para integração, sobre `a1fe305`. A
  variante escolhida pelo dono é a E: pontas de cada fala aparadas com `atrim` (0,05 s de margem) e teto de 0,45 s
  nos silêncios de dentro das falas. Conferência do código novo (`E_final/20.mp3`) contra a variante E ouvida:
  235,08 s contra 234,83 s (+0,11%) e silêncio na troca de 0,77 s contra 0,75 s. 688 testes passam; os 7 novos de
  `tests/test_tts.py` cobrem as funções puras dos cortes (a leitura do silencedetect, os trechos mantidos nas pontas e
  no meio da fala, o filtro do `atrim`), a fala cortada entrando na lista do ffmpeg com as WAV e o ajuste de cada fala
  logo depois da síntese dela. Os instantes para ouvir (trocas e pausas do Otávio) estão em
  `/home/sytw/Projetos/techdigest/data/agrupamento/pausas_20261108/conferencia_E_final.md`. Próximo passo: avisar a
  frente 0 de que a frente está pronta, agora com o corte das pausas (`8492af8`).
- 08/11/2026: rebaseada sobre a `testes` em `4bce887` (com as frentes 2 e 3), sem conflito; os hashes deste arquivo
  são os de depois do rebase. A `.venv` da worktree passou para o uv (`uv sync --locked --extra dev`; a do pip ficou em
  `.venv.pip-20261108`), e `uv sync --locked --check --extra dev` dá `Would make no changes`. 695 testes passam: 674
  da `testes` e 21 do `tests/test_tts.py`.
- 17/11/2026: na escuta do dono (passo 3 da Integração), o player do celular tocava um ruído no começo do episódio,
  e os turnos crus do Edge-TTS, que não têm a marca ID3 nem o quadro Xing/Info, tocavam limpos. Correção `1b7a308`,
  feita direto na `testes` (a `melhoria/audio` não recebe mais commits): a concatenação do ffmpeg grava o mp3 com
  `-write_xing 0 -id3v2_version 0`. Sem a marca LAME, os players tocam também as 1105 amostras de silêncio do começo do
  codificador (46 ms), e a duração sai do bitrate, que é constante. Teste novo, `tests/test_tts_mp3.py`, com o ffmpeg
  de verdade e o `edge_tts.Communicate` falso (um tom de 0,5 s em mp3 de 24 kHz): o arquivo não começa com `ID3`,
  começa num quadro de áudio e não tem `Xing` nem `Info` nos primeiros 2048 bytes; sem o ffmpeg ou o ffprobe no PATH, o
  teste é pulado. 806 testes passam na `testes`.
  - Hashes atuais, na `testes` (os da `melhoria/audio` depois do rebase sobre `4bce887`): `336dbde` (medição),
    `d8dc640` (turnos em paralelo), `f03ef9b` (aceite), `deb7e24` (pronta para integração), `8492af8` (variante E),
    `a1fe305` (pausas), `e129203` (estado) e `63ea31f` (hashes depois do rebase); e o `1b7a308`, que não está na
    branch da frente. Na `testes`, o `tts.py` mudou também nos commits `3b81457` e `c11e9f9` da frente 9 (tipos).
    `testes` em `1b7a308`.
- 19/11/2026: **na `master`.** A `testes` entrou na `master` em 18/11, por avanço rápido para `17b4390` (o
  `fechamento.sh` do dono), e a `melhoria/audio` sai com a limpeza da frente 0. A medição da primeira execução real,
  pedida em "Pendências", foi feita na execução de 18/11, das 21:11 às 22:05, com 20 de 20 entregues.
  - O áudio, do `Vozes:` ao `✅`, medido com uma cópia do `medir_audio.py`:
    - 20 s por item em média (15 a 28 s), 1,9 s por turno (216 turnos) e 5,5 s por minuto de episódio;
    - na execução real de 07/11, foram 44 s, 4,0 s e 10,9 s;
    - a síntese caiu de 24,7% para 12,7% do tempo da execução;
    - episódios de 3,7 min em média (2,7 a 4,7 min).
  - As emendas, medidas no 01 e no 20 com o silencedetect a -50 dB:
    - as trocas de personagem ficaram em 0,78 s em média no 01 (0,76 a 0,88 s) e em 0,77 s no 20 (0,76 a 0,80 s); no
      E_final de 08/11, ficaram entre 0,75 e 0,80 s;
    - o maior silêncio de dentro das falas foi de 0,45 s e de 0,47 s, contra o teto de 0,45 s; no E_final, foi de
      0,46 s.
  - Os 20 mp3 começam num quadro de áudio (`ff f3`), sem `ID3` e sem `Xing`/`Info`.
  - As saídas e os scripts estão em `data/agrupamento/fechamento_20261118/medicao/` da pasta principal: o
    `medir_audio.py` com `resumo.txt` e `medicao.csv`, e o `medir_trocas.py` com `trocas.txt`.

### Pausas (08/11/2026, depois do aceite)

Fora do git, em `/home/sytw/Projetos/techdigest/data/agrupamento/pausas_20261108/`: `medir_pausas.py` e `medicao.txt`
(a medição, com os instantes de cada troca e de cada pausa longa), `variantes.py`, `gerar_variante.py`, `variantes.md`
(as variantes), `conferencia_E_final.md` e os mp3 em `<variante>/20.mp3` (`A`, `C`, `D`, `E`, `F` e `E_final`, o do
código commitado). As WAV de conferência de cada fala foram apagadas depois do commit.

**Medição** (silencedetect a -50 dB; -60 e -40 dB mudam no máximo 0,04 s), nos mp3 da branch da rodada 4 do aceite:
- Não existe emenda entre falas do mesmo personagem: nos itens 19, 17 e 20, e em todos os 108 episódios gravados em
  `data/execucoes/` (1030 emendas), a Helena e o analista se alternam. A `PAUSA_MESMO_PERSONAGEM_S` nunca é usada.
- O que o dono ouviu são as pausas de fim de frase dentro das falas do Otávio: a voz `pt-BR-AntonioNeural` pára uns
  0,91 s em cada fim de frase de dentro da fala (10 por episódio, todas dele); a Helena (`FranciscaNeural`), no máximo
  0,31 s. É da voz do Edge-TTS, não do `tts.py`.
- A troca de personagem dura 1,66 s: a pausa de 0,65 s e uns 1,01 s de silêncio do próprio Edge-TTS, uns 0,18 s no
  começo de cada fala e uns 0,83 s no fim. A pausa e as pontas são silêncio digital, e não dá para separá-las pelo
  nível: as pontas foram medidas no começo e no fim do arquivo, onde não há pausa ao lado.

**Variantes do item 20** (cópias do código da branch, `PAUSA_MESMO_PERSONAGEM_S` e troca de 0,65 s em todas; a B, com
0,15 s para o mesmo personagem, foi descartada porque sairia igual à A):

| variante | o que muda | duração | silêncio na troca | pausas do Otávio | maior pico removido |
|---|---|---|---|---|---|
| A | nada | 249,45 s | 1,66 s | 0,91 s | — |
| C | pontas aparadas (`silenceremove`, -60 dB, margem de 0,05 s) | 239,42 s | 0,75 s | 0,91 s | -60,2 dBFS |
| D | teto de 0,45 s dentro das falas (silencedetect e `atrim`) | 244,87 s | 1,66 s | 0,45 s | -60,5 dBFS |
| **E** | **C + D (a escolhida)** | **234,83 s** | **0,75 s** | **0,45 s** | **-59,4 dBFS** |
| F | teto de 0,35 s dentro das falas | 243,87 s | 1,66 s | 0,35 s | -57,6 dBFS |

Em todas, o que ficou de cada fala é idêntico ao original fora das margens de 0,05 s; o `silenceremove` da C e da E
altera essas margens em até 282 de 32768 (pico delas -38 dBFS), e por isso o código usa `atrim` também nas pontas.

**O código commitado (`8492af8`) contra a variante E:**
- Nas 11 falas originais guardadas da variante E, o `_ajustar_fala` deixou o que fica idêntico ao original, amostra
  por amostra, e tirou 14,39 s com pico de no máximo -59,4 dBFS; cada fala ficou de 5 a 68 ms mais longa que na E (o
  `atrim` começa no primeiro instante acima de -60 dB; o `silenceremove` media em janelas de 20 ms).
- Gerado de novo pelo Edge-TTS: 235,08 s contra 234,83 s (+0,11%); trocas de 0,77 s (0,75 a 0,80) contra 0,75; pausas do
  Otávio de no máximo 0,46 s contra 0,45; Helena igual (0,31 s). O tempo de geração foi 6,0 s, o mesmo do aceite sem o
  corte (5,9 a 6,1 s): o ajuste de cada fala corre enquanto as outras são sintetizadas.
- Os instantes das trocas e das pausas do Otávio no `E_final/20.mp3` estão em `conferencia_E_final.md`.

### Aceite separado (08/11/2026, 13:18 a 13:23)

Os itens 19 (o mais curto, 9 turnos), 17 (o mediano, 11) e 20 (o mais longo, 11) da execução de 07/11, com o código
da `master` (`64bd21b`) e o da branch (`d8dc640`), cada versão num processo, na mesma `.venv` (edge-tts 7.3.1), de uma
cópia tirada por `git archive` (nada mudou em `src/`). 4 rodadas, cada uma com as duas versões, a ordem trocando
entre elas (M B, B M, M B, B M). Só o Edge-TTS e o ffmpeg: sem o modelo e sem o Telegram. Scripts, mp3 e resultado em
`/home/sytw/Projetos/techdigest/data/agrupamento/audio_paralelo_20261108/` (`aceite.py`, `gerar.py`,
`comparar_envelope.py`, `resultado.md`, `envelope.txt`, `rodada_N/<versao>/<item>.mp3`).

| item | turnos | master: tempo médio (mín.–máx.) | branch: tempo médio (mín.–máx.) | ganho | duração (ffprobe) nas 8 gerações | produção 07/11 |
|---|---|---|---|---|---|---|
| 19 | 9 | 12,6 s (12,1–12,9) | 4,6 s (4,6–4,7) | 8,0 s (63%) | 168,50 s | 168,50 s |
| 17 | 11 | 15,3 s (14,9–15,7) | 5,8 s (5,7–5,9) | 9,5 s (62%) | 217,36 s | 217,36 s |
| 20 | 11 | 15,9 s (15,5–16,4) | 6,0 s (5,9–6,1) | 9,9 s (62%) | 249,45 s | 249,45 s |
| os 3 | 31 | 43,8 s | 16,4 s | 27,4 s (62%) | | |

- A branch levou 0,375 do tempo da `master` (2,7 vezes mais rápida, com 3 sínteses ao mesmo tempo), estável nas 4
  rodadas, fosse qual fosse a versão que saísse primeiro.
- Duração: igual nas 8 gerações de cada episódio e igual à do mp3 da produção de 07/11 (diferença 0,00%, folga de 2%).
- Nenhuma falha e nenhuma nova tentativa nas 24 gerações; o Edge-TTS não barrou as 3 conexões ao mesmo tempo.
- A ordem dos turnos: o md5 do mp3 (e do PCM) muda a cada geração, até entre duas da `master`, porque o Edge-TTS
  devolve bytes um pouco diferentes a cada chamada. Pelo áudio decodificado, as 8 gerações de cada episódio têm o mesmo
  número de amostras, e o envelope de volume (janelas de 100 ms) da primeira da `master` tem correlação 0,9999 com as
  outras três da `master` e com as quatro da branch; com dois blocos de 20 s trocados, cai para 0,77 a 0,84.
- **A `master` foi muito mais rápida hoje que na produção:** os mesmos episódios levaram 27, 42 e 64 s em 07/11 às
  01h (3,0 a 5,8 s por turno), e 12,6 a 15,9 s agora (1,4 s por turno). A causa não está medida: a hora, a rede, ou a
  máquina com o modelo carregado. Aplicada aos 875 s de áudio de 07/11, a proporção do aceite daria uns 328 s, uns
  9 min a menos dos 59; o ganho real na produção se confere na primeira execução real depois da integração, com o
  `medir_audio.py` da etapa 1 (`--inicio` e `--registro` da execução).
- Para o dono ouvir: `rodada_4/branch/20.mp3` (o mais longo, 11 turnos, 4,2 min), e, para comparar,
  `rodada_4/master/20.mp3`. Ouvido e aprovado pelo dono em 08/11.

### Implementação (etapa 2)

- `src/techdigest/audio/tts.py`: um só `asyncio.run` por episódio (`_sintetizar_turnos`), com um `asyncio.TaskGroup` e
  um `asyncio.Semaphore(CONCORRENCIA_TTS)`; cada turno grava `turno_NNN.mp3` e a lista do ffmpeg segue a ordem dos turnos.
  `_sintetizar_turno` repete um turno só nas `ERROS_PASSAGEIROS_TTS` (`aiohttp.ClientConnectionError`, `TimeoutError`,
  `WebSocketError`), até `TENTATIVAS_TTS` (3) vezes no total, com `PAUSA_ENTRE_TENTATIVAS_TTS_S` (2 s) entre elas e um
  WARNING por nova tentativa (`Síntese do turno N falhou (tentativa k de 3): <tipo>: <mensagem>`). Uma falha que persiste
  cancela os outros turnos e chega ao pipeline como a exceção original. As pausas `pausa_curta.mp3` e `pausa_longa.mp3`
  são geradas uma vez cada; a string do `_silencio` ficou sem o `f`. Assinatura, retorno, vozes, bitrate e concatenação
  não mudam; o `pipeline.py` não mudou.
- `tests/test_tts.py` (14 testes, com o `edge_tts.Communicate` e o `subprocess.run` falsos): a ordem da lista e a pausa
  certa, com as sínteses terminando fora de ordem; no máximo 3 (ou o valor da constante) ao mesmo tempo; as duas pausas;
  cinco erros passageiros repetidos; o erro que persiste chegando como ele mesmo e cancelando os outros turnos; 403, 429,
  503 e `NoAudioReceived` sem nova tentativa; o roteiro vazio. Sem o desembrulho do `ExceptionGroup`, 5 deles falham.
- Conferido antes do commit: o `scripts/resumo_lotes.py` não lê o WARNING novo (com 40 deles injetados no log de 07/11,
  a saída fica idêntica) e a linha do `✅` não muda (o `pipeline.py` e o `_duracao` são os mesmos).
- `CLAUDE.md`, "Architecture", passo 5: os turnos em paralelo, as novas tentativas e as duas pausas.
- **Para a frente 2:** o `tts.py` importa o `aiohttp` direto, sem ele estar no `pyproject.toml` (vem com o edge-tts;
  3.14.5 nas duas `.venv`). Ao fixar as versões, lembrar dele.

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
- Ok ao commit `d8dc640` (08/11). Aceite com os itens 19, 17 e 20, 4 rodadas com a ordem de partida trocando entre
  elas, processos separados na mesma `.venv`; uma falha de episódio (403, 429 etc.) registrada como resultado, sem
  parar as rodadas; nada em `src/` durante o aceite.
- Aceite aprovado (08/11), depois de ouvir `rodada_4/branch/20.mp3`: a frente fica pronta para integração.
- Pausas (08/11, depois do aceite): as pausas pareceram longas ao dono. Variantes A, C, D, E e F (a B descartada, a F
  acrescentada com o teto de 0,35 s, o maior silêncio da Helena), `PAUSA_MESMO_PERSONAGEM_S` sem mudança, WAV até a
  concatenação. O dono ouviu as cinco e escolheu a **E**, com o `atrim` no lugar do `silenceremove` nas pontas.

### Pendências

Nenhuma desde 19/11/2026: as duas abaixo foram feitas. A integração foi pela `testes`, que está na `master` desde
18/11, e a medição da primeira execução real está no "Estado", em 19/11.

- Avisar a frente 0 de que a frente está pronta, agora com o corte das pausas (`8492af8`). Na integração, a sessão
  desta frente faz o rebase da `melhoria/audio` sobre a `testes`. A linha do `_silencio` no `tts.py` já está sem o
  `f`, como a frente 4 também deixa, e o corte das pausas não mexeu no `_silencio`; o conflito, se vier, se resolve
  com a string sem o `f`. Antes do avanço rápido da `master`, a frente 2 precisa ter lembrado do `aiohttp` (ver
  "Implementação").
- Depois da integração, na primeira execução real: medir o áudio (`Vozes:` → `✅`) com o `medir_audio.py` da etapa 1,
  numa cópia em pasta nova (ele grava `medicao.csv` e `resumo.txt` na própria pasta), para saber o ganho na produção,
  onde o Edge-TTS foi 2 a 4 vezes mais lento por turno que no aceite; e conferir num episódio dela, com o
  `medir_pausas.py` adaptado, a troca de uns 0,77 s e as pausas do analista de no máximo 0,45 s.

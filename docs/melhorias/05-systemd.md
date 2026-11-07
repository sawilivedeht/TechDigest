# Frente 5: systemd

Arquivo no Projeto: `claude/frentes/05-systemd.md` · no repositório: `docs/melhorias/05-systemd.md`

| | |
|---|---|
| Branch | `melhoria/systemd` |
| Worktree | `/home/sytw/Projetos/techdigest-systemd` |
| Onda | 2 |
| Depende de | nada para os arquivos; uma rodada com o modelo para calibrar a memória |
| Conflita com | frente 2 (`docs/producao.md`); frente 7 (`docs/referencia/scripts.md`) |

## Objetivo

Deixar versionados e prontos para o dono instalar quando decidir ligar o timer: a unit do pipeline, o timer, o aviso de
falha e o limite de memória do Ollama. **A sessão não instala nem liga nada.** A unit do Ollama só muda de verdade quando o
dono a copia para `~/.config/systemd/user`, e o timer continua sendo decisão dele.

## Por que

- A unit do pipeline e o timer não existem (`CLAUDE.md`, `claude/andamento.md`). O plano anotado era
  `Requires=`/`After=ollama.service`.
- O pipeline já avisa no Telegram e sai com status 1 quando para sozinho (`pipeline.run` e `_avisar`): trava ocupada,
  freio da máquina, erro inesperado, todos os feeds fora. Um `OnFailure=` sem filtro mandaria um segundo aviso nesses
  casos. O systemd passa ao manipulador do `OnFailure=` as variáveis `MONITOR_SERVICE_RESULT`, `MONITOR_EXIT_CODE`,
  `MONITOR_EXIT_STATUS` e `MONITOR_UNIT` (conferidas no systemd 255). Com `exit-code`, o pipeline já avisou; com `timeout`,
  `signal`, `oom-kill` ou `core-dump`, ele não pôde.
- Com `Requires=ollama.service`, se o Ollama não sobe (o `nvidia-smi` do `ExecStartPre` falha), o pipeline nem começa e
  também não entra em falha: nenhum aviso sai. Com `Wants=`, ele começa, e a conferência de GPU dele (`ai/gpu.py`) para e
  avisa pelo caminho que já existe e já é testado.
- A execução real à mão não tem vigia de memória (`docs/producao.md`): só o freio de 4 GiB antes de cada chamada
  (`ai/maquina.py`), e uma geração leva de 1,5 a 5 min nas medidas do roteiro. O comentário do `LLAMA_ARG_CACHE_RAM=0` na
  unit do Ollama registra que a memória já cresceu durante uma rodada.

## Decisões do dono

- O horário do timer (`OnCalendar=`) e se uma execução perdida roda depois (`Persistent=`).
- `Wants=` (recomendado) ou `Requires=`.
- `loginctl enable-linger`, para o timer rodar sem sessão aberta.
- Os valores de `MemoryHigh=` e `MemoryMax=`, depois da calibração.

## Arquivos (rascunho para a sessão conferir)

`deploy/systemd/techdigest.service`:

```ini
[Unit]
Description=TechDigest: coleta, gera e entrega os episódios
Wants=ollama.service
After=ollama.service
OnFailure=techdigest-aviso.service

[Service]
Type=exec
WorkingDirectory=%h/Projetos/techdigest
ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle --who=TechDigest --why="execucao do timer" %h/Projetos/techdigest/.venv/bin/techdigest
RuntimeMaxSec=4h
```

`deploy/systemd/techdigest.timer`:

```ini
[Unit]
Description=Horário do TechDigest

[Timer]
OnCalendar=*-*-* 01:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

`deploy/systemd/techdigest-aviso.service`:

```ini
[Unit]
Description=Aviso de falha do TechDigest no Telegram

[Service]
Type=oneshot
WorkingDirectory=%h/Projetos/techdigest
ExecStart=%h/Projetos/techdigest/.venv/bin/python -m techdigest.aviso_de_falha
```

Em `deploy/systemd/ollama.service`: `MemoryHigh=` e `MemoryMax=`, com os valores calibrados e um comentário com a data e a
medida.

A conferir: se o `systemd-inhibit` funciona numa unit de usuário disparada pelo timer sem sessão gráfica (pode exigir regra
do polkit); e, se a máquina dorme no horário, como acordá-la. `systemd-analyze --user verify` em cada arquivo.

## O aviso de falha

`src/techdigest/aviso_de_falha.py`, novo:
- lê `MONITOR_SERVICE_RESULT`, `MONITOR_EXIT_CODE`, `MONITOR_EXIT_STATUS` e `MONITOR_UNIT`;
- com `exit-code`, só registra no log (o pipeline já avisou, ou registrou que não conseguiu);
- com qualquer outro resultado, manda pelo `delivery.deliver_aviso` um texto curto: a hora, a unit e o motivo em palavras
  ("passou de 4 horas", "encerrado pelo sistema por falta de memória", "encerrado por sinal");
- usa o mesmo `_post` do Telegram, que esconde o token, e nunca roda numa simulação.

Testes em `tests/test_aviso_de_falha.py`, com as variáveis de ambiente e o `deliver_aviso` falsos.

## Calibração da memória

Uma rodada pedida ao dono, pela skill da rodada (ou pelo `scripts/rodada.py`, se a frente 7 já tiver entrado): o
`scripts/testar_episodio.py` numa amostra pequena, com o pico de memória da unit do Ollama medido (o `memory.peak` do cgroup
dela). Antes, conferir se o controlador de memória está delegado às units de usuário: `memory` deve aparecer em
`/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers`. O `MemoryMax=` fica no pico com
folga, e o `MemoryHigh=` um pouco abaixo. Se o limite estourar, o Ollama cai, e o freio "o Ollama não responde" para a
execução e avisa.

## Aceite separado

- A suíte inteira, com os testes novos.
- `systemd-analyze --user verify` sem erros nos arquivos novos.
- A rodada de calibração, com os números neste arquivo.
- Nada instalado nem ligado.

## Documentação

- `docs/producao.md`: uma seção nova, "Com o timer", com a instalação (cópia dos arquivos, `daemon-reload`, `linger`,
  `enable --now techdigest.timer`), para o dono fazer quando decidir.
- `docs/referencia/scripts.md`: o limite de memória da unit do Ollama.
- `CLAUDE.md`: o invariante do aviso de parada passa a citar os arquivos do `OnFailure=`.

## Prompt inicial para o Claude Code

```text
Frente 5 (systemd) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-systemd, branch
melhoria/systemd. Leia docs/plano-melhorias.md, docs/melhorias/05-systemd.md, docs/regras-de-sessao.md,
docs/producao.md e a parte da unit do Ollama em docs/referencia/scripts.md.
Primeiro, só leitura: deploy/systemd/, pipeline.run e _avisar, delivery.deliver_aviso, ai/gpu.py e ai/maquina.py; e
confira se o controlador de memória está delegado às units de usuário. Não instale, não copie e não ligue nenhuma unit.
Depois me pergunte as decisões do arquivo da frente e apresente o plano, com a lista "Leituras minhas, para você
corrigir". Espere a aprovação. A calibração da memória é uma rodada com o modelo: só quando eu pedir.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/05-systemd.md atualizada.
```

## Estado

- 07/11/2026: não começada.

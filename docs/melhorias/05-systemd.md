# Frente 5: systemd

Arquivo no Projeto: `claude/frentes/05-systemd.md` · no repositório: `docs/melhorias/05-systemd.md`

| | |
|---|---|
| Branch | `melhoria/systemd` |
| Worktree | `/home/sytw/Projetos/techdigest-systemd` |
| Onda | 2 |
| Depende de | nada (a rodada de calibração da memória foi dispensada em 09/11/2026: os valores vêm do journal) |
| Conflita com | frente 2 (`docs/producao.md`); frente 7 (`docs/referencia/scripts.md`) |

## Objetivo

Deixar versionados e prontos para o dono instalar quando decidir ligar o timer: a unit do pipeline, o timer, o aviso de
falha e o limite de memória do Ollama. **A sessão não instala nem liga nada.** A unit do Ollama só muda de verdade quando o
dono a copia para `~/.config/systemd/user`, e o timer continua sendo decisão dele.

## Por que

- A unit do pipeline e o timer não existiam (`CLAUDE.md`, `claude/andamento.md`). O plano anotado era
  `Requires=`/`After=ollama.service`.
- O pipeline já avisa no Telegram e sai com status 1 quando para sozinho (`pipeline.run` e `_avisar`): trava ocupada,
  freio da máquina, erro inesperado, todos os feeds fora. Um `OnFailure=` sem filtro mandaria um segundo aviso nesses
  casos. O systemd passa ao manipulador do `OnFailure=` as variáveis `MONITOR_SERVICE_RESULT`, `MONITOR_EXIT_CODE`,
  `MONITOR_EXIT_STATUS`, `MONITOR_INVOCATION_ID` e `MONITOR_UNIT` (conferidas no systemd 255 e, em 09/11/2026, no 262
  desta máquina, pelo `systemd.exec(5)` instalado), mas só quando um único serviço aponta para ele.
- Com `Requires=ollama.service`, se o Ollama não sobe (o `nvidia-smi` do `ExecStartPre` falha), o pipeline nem começa e
  também não entra em falha: nenhum aviso sai. Com `Wants=`, ele começa, e a conferência de GPU dele (`ai/gpu.py`) para e
  avisa pelo caminho que já existe e já é testado.
- A execução real à mão não tem vigia de memória (`docs/producao.md`): só o freio de 4 GiB antes de cada chamada
  (`ai/maquina.py`), e uma geração leva de 1,5 a 5 min nas medidas do roteiro. O comentário do `LLAMA_ARG_CACHE_RAM=0` na
  unit do Ollama registra que a memória já cresceu durante uma rodada.

## Decisões do dono (09/11/2026)

- Timer: `OnCalendar=*-*-* 01:00:00` e `Persistent=true`.
- `Wants=` com `After=ollama.service` (não `Requires=`).
- Sem `loginctl enable-linger`: o timer só roda com sessão aberta, e o bloqueio do sono depende dela (documentado em
  `docs/producao.md`).
- Bloqueio do sono numa unit à parte, `techdigest-inibir.service`, com `StopWhenUnneeded=yes`; o pipeline é o processo
  principal da `techdigest.service`.
- Saída com status 1: o aviso de falha procura `Aviso de parada:` no journal daquela execução (pelo
  `_SYSTEMD_INVOCATION_ID`). Achou, só registra. Não achou, achou também `Aviso de parada não enviado`, ou não conseguiu
  ler o journal: avisa. Os outros status e os resultados `timeout`, `signal`, `oom-kill` e `core-dump` sempre avisam. Sem
  as variáveis `MONITOR_*`, avisa com um texto genérico. Um aviso duplicado vale mais que um silêncio.
- Memória: `MemoryMax=20G` na `ollama.service`, pelos picos a frio do journal, sem `MemoryHigh=` e sem rodada de
  calibração; o limite vale também para as execuções à mão (commit 2, depois da revisão do commit 1).
- `LOG_LEVEL` do `.env`: INFO ou DEBUG (conferido pelo dono), então a linha `Aviso de parada:` vai para o journal.
- Não mexer no `pipeline.py`: o docstring do `pipeline.run` fica para a frente 0 trocar na integração (ver "Estado").
- Teste do polkit sem sessão: pelo dono, depois da instalação; nenhuma unit transitória para ele.

## Arquivos

Em `deploy/systemd/`, todos com um cabeçalho em comentário que explica a escolha:

- `techdigest.service`: `Wants=` e `After=` para `ollama.service` e `techdigest-inibir.service`,
  `OnFailure=techdigest-aviso.service`, `Type=exec`, `ExecStart=%h/Projetos/techdigest/.venv/bin/techdigest` (sem o
  `systemd-inhibit` na frente), `RuntimeMaxSec=4h`.
- `techdigest-inibir.service`: `StopWhenUnneeded=yes`, `ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle
  --who=TechDigest --why="execucao do timer" /usr/bin/sleep infinity`.
- `techdigest.timer`: `OnCalendar=*-*-* 01:00:00`, `Persistent=true`, `WantedBy=timers.target`.
- `techdigest-aviso.service`: `Type=oneshot`, `ExecStart=%h/Projetos/techdigest/.venv/bin/python -m
  techdigest.aviso_de_falha`.
- Commit 2: `MemoryMax=20G` em `ollama.service`, com a data e a medida no comentário.

Diferenças do rascunho de 07/11, pela leitura de 08 e 09/11:
- o `systemd-inhibit` saiu do `ExecStart` do pipeline: ele devolve 1 quando o filho morre por um sinal (medido:
  `exit 3 → 3`, `SIGKILL → 1`, `SIGTERM → 1`), o mesmo status do pipeline que já avisou; e, sem sessão aberta, o polkit
  pediria administrador para bloquear o sono (`inhibit-block-sleep`: `allow_any=auth_admin_keep`), e o pipeline nem
  começaria;
- o `Wants=` também puxa a `techdigest-inibir.service`;
- o aviso de falha olha o journal no status 1, porque um erro antes de o pipeline começar (uma `.venv` fora do lock)
  também sai com 1, sem aviso.

## O aviso de falha

`src/techdigest/aviso_de_falha.py`:
- lê `MONITOR_SERVICE_RESULT`, `MONITOR_EXIT_CODE`, `MONITOR_EXIT_STATUS`, `MONITOR_INVOCATION_ID` e `MONITOR_UNIT`;
- decide pela regra das decisões acima; o journal é lido com
  `journalctl --user _SYSTEMD_INVOCATION_ID=<id> --output=cat --no-pager --quiet` (30 s no máximo; sem um id de 32
  dígitos hexadecimais, nem chama);
- quando avisa, manda pelo `delivery.deliver_aviso` "TechDigest (<unit>) parou às HH:MM: <motivo>. O que não foi
  entregue volta na próxima execução. Detalhe: journalctl --user -u <unit>", e escreve no log a mesma linha do pipeline
  (`Aviso de parada: ...`), que o `scripts/resumo_lotes.py` já mostra;
- motivos: o tempo máximo da unit (4 horas), falta de memória, o sinal, o core dump, status 1 sem o aviso do pipeline,
  com o aviso não enviado ou com o journal ilegível, o systemd que não conseguiu iniciar o pipeline (status de 200 em
  diante), outro status, outro resultado da unit, e o texto genérico sem as variáveis;
- sai com 0 quando avisou ou só registrou, com 1 quando o envio falhou e com 2 numa simulação, onde recusa antes de
  decidir.

Testes em `tests/test_aviso_de_falha.py` (30), com as variáveis de ambiente, o journal e o `deliver_aviso` falsos, e
em `tests/test_units.py` (6 novos).

## Calibração da memória

Dispensada (decisão do dono de 09/11/2026). O journal já guarda o pico de cada subida da `ollama.service` (a linha
"Consumed ... memory peak" da parada, que é o `memory.peak` do cgroup), de 17/10 a 07/11:
- primeira carga do modelo em cada boot: 17,0 a 18,7G em 10 de 11 boots (a exceção, 21/10 21h27, deu 2,5G); maior pico,
  18,7G em 24/10 19h20; a execução real de 07/11, 18,2G;
- subidas seguintes no mesmo boot: 1,1 a 7G, com algumas intermediárias de 9,8 a 14,9G. A primeira subida lê o arquivo
  do modelo e fica com o cache dele (15,9 GiB mapeados) na conta do próprio cgroup; as seguintes não. Por isso o limite
  vem dos picos a frio: um calibrado com o cache quente estrangularia uma execução fria;
- o "G" do systemd é base 1024 e truncado (10022912 bytes aparecem como 9.5M), como o do `MemoryMax=`
  (`systemd.resource-control(5)`): o pico de 18,7G fica entre 18,7 e 18,8 GiB, e o `MemoryMax=20G` deixa de 1,2 a 1,3 GiB
  (6 a 7%). A máquina tem 23,2 GiB de RAM e 4 GiB de swap.

O controlador de memória está delegado às units de usuário: `user@1000.service` com `Delegate=yes` e
`DelegateControllers=cpu memory pids`, e `memory` em `cgroup.controllers` e `subtree_control` dela e do `app.slice`.

## Aceite separado

- A suíte inteira, com os testes novos, e o `ruff check .`.
- `systemd-analyze --user verify` sem erros com todos os arquivos de `deploy/systemd/` juntos.
- Provas por mutação temporária: o teste pega o defeito.
- Os números da memória, do journal, neste arquivo (a rodada de calibração foi dispensada).
- Nada instalado nem ligado.

## Documentação

- `docs/producao.md`: a seção "Com o timer" (instalação, sem linger, a primeira execução, o que avisa, sono e tampa,
  junto com a execução à mão, desligar e desinstalar); no commit 2, o limite de memória, que vale também para as
  execuções à mão.
- `docs/referencia/scripts.md`: o que os testes cobrem (commit 1); o limite de memória da unit do Ollama (commit 2).
- `CLAUDE.md`: as units em "What this is", o invariante do aviso de parada com os arquivos do `OnFailure=`, o
  `RuntimeMaxSec=4h` no orçamento de tempo e as linhas que o aviso procura no journal. O estado de produção ("Repo
  notes") fica para a integração.

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
- 08/11/2026: em plano. Leitura feita (só leitura; nada instalado, copiado nem ligado) e plano apresentado ao dono.
- 09/11/2026: em implementação. Commit 1 feito na `melhoria/systemd`, a partir de `121fa7b` (a `testes` com as frentes
  1 a 4): as quatro units, o `aviso_de_falha.py`, os testes e os documentos. O commit 2 (`MemoryMax=20G` na
  `ollama.service`) espera a revisão do dono.
  - Testes: 731 passam (695 antes e 36 novos: 30 em `tests/test_aviso_de_falha.py`, 6 em `tests/test_units.py`). O
    `ruff check .` não dá avisos. O `systemd-analyze --user verify` com os seis arquivos de `deploy/systemd/` não dá
    mensagens (status 0); com o `ExecStart=` trocado por um caminho que não existe, ele acusa ("is not executable"),
    então o `.venv/bin/techdigest` e o `.venv/bin/python` da pasta principal existem.
  - `Wants=` contando para o `StopWhenUnneeded=`, conferido em 09/11/2026 com duas units transitórias de `sleep` por
    `systemd-run --user` (nada de ollama nem de techdigest): a `teste-g5-alvo`, com `StopWhenUnneeded=yes`, ficou ativa
    de 18:43:37,735 a 18:43:44,376 enquanto a `teste-g5-quer`, com `Wants=` apontando para ela, estava ativa, e parou
    1 ms depois da parada da `teste-g5-quer`, sem pedido de parada para ela. As duas saíram da memória (`--collect`).
    O `systemd.unit(5)` instalado não diz isso com todas as letras.
  - Provas por mutação (cada uma desfeita em seguida, e a suíte voltou aos 39 passando nos dois arquivos):
    o status 1 sem a linha do pipeline passando a só registrar → falha
    `test_status_1_sem_o_aviso_do_pipeline_avisa`; o `OnFailure=` retirado da `techdigest.service` → falha
    `test_o_aviso_de_falha_e_o_on_failure_so_da_unit_do_pipeline`; o `ExecStart=` envolvido no `systemd-inhibit` →
    falha `test_o_pipeline_e_o_processo_principal_da_unit_do_timer`; a linha do aviso não enviado deixando de ser
    procurada → falham `test_status_1_com_o_aviso_do_pipeline_nao_enviado_avisa` e
    `test_as_linhas_procuradas_no_journal_sao_as_que_o_pipeline_escreve`.
  - Nada instalado: `~/.config/systemd/user` só com `ollama.service` e `techdigest-teste.target`, nenhum techdigest em
    `systemctl --user list-timers --all`, `Linger=no`.
  - Para a frente 0, na integração (o dono pediu para não mexer no `pipeline.py` nesta frente): o docstring de
    `pipeline.run`, em `src/techdigest/pipeline.py`, linhas 48 e 49, diz hoje "O `OnFailure=` da futura unit / fica só
    com o que o processo não consegue avisar (OOM, tempo esgotado, sinal)." Deveria dizer: "O `OnFailure=` da
    `techdigest.service` (`deploy/systemd/`) dispara o `aviso_de_falha.py`, que avisa o que o processo não consegue
    avisar (tempo esgotado, OOM, sinal, core dump, erro antes de começar)." Na integração também: o estado de produção
    do `CLAUDE.md` ("Repo notes" ainda diz que não há timer nem unit do pipeline).
  - Pendências: o commit 2, depois da revisão do dono; depois da instalação, pelo dono, o caso sem sessão do polkit e a
    conferência da primeira execução (`docs/producao.md`, "A primeira execução").

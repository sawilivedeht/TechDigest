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
- `ollama.service` (commit 2): `MemoryMax=20G`, sem `MemoryHigh=`, com a data e a medida no comentário.

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
- 09/11/2026: em implementação. Commit 1, `c07229f`, na `melhoria/systemd`, a partir de `121fa7b` (a `testes` com as
  frentes 1 a 4): as quatro units, o `aviso_de_falha.py`, os testes e os documentos. Aceito pelo dono pelo relatório; a
  revisão dos arquivos continua no chat da frente, e uma correção, se houver, entra num commit à parte.
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
- 09/11/2026: commit 2 (o dono autorizou sem esperar a revisão do commit 1): `MemoryMax=20G` na `ollama.service`, sem
  `MemoryHigh=`, com a data e a medida no comentário; o teste em `tests/test_units.py` (o teto acima do maior pico
  medido, 18,8 GiB, e nenhum `MemoryHigh=`); o trecho da unit do Ollama em `docs/referencia/scripts.md`; e em
  `docs/producao.md` o teto valendo também para a execução à mão (passo 1 de "Rodar", com o modo de atualizar a cópia
  instalada, e "Com o timer"). Commit 2: `dee29cb`.
  - Testes: 732 passam (731 e o teste do teto). O `ruff check .` não dá avisos. O `systemd-analyze --user verify` com
    os seis arquivos de `deploy/systemd/` não dá mensagens (status 0).
  - Prova por mutação: o `MemoryMax=` retirado da `ollama.service` → falha
    `test_a_unit_do_ollama_tem_teto_de_memoria_acima_do_maior_pico_medido` (`KeyError: 'MemoryMax'`); desfeita, os 10
    testes de `tests/test_units.py` voltaram a passar.
  - Nada instalado: `~/.config/systemd/user` só com `ollama.service` e `techdigest-teste.target` (a cópia instalada da
    `ollama.service` continua sem o teto, igual à da `master`), nenhum techdigest em `systemctl --user list-timers
    --all`, `Linger=no`.
  - Etapa: aceite separado. A frente fica pronta para integração com o ok do dono à revisão dos dois commits.
  - Pendências: a revisão do dono; depois da instalação, pelo dono, o caso sem sessão do polkit e a conferência da
    primeira execução (`docs/producao.md`, "A primeira execução"); na integração, pela frente 0, a cópia da
    `ollama.service` com o teto para `~/.config/systemd/user` e o docstring do `pipeline.run` (acima).
- 09/11/2026: quatro perguntas do dono na revisão dos dois commits (só leitura, menos a frase da 4).
  1. O `deliver_aviso` levanta exceção em toda falha, sem devolver valor: o `_post` levanta `FalhaDeRede` (erro do
     requests), `RuntimeError` (resposta não-JSON, `ok` falso, simulação), e um canal desconhecido levanta
     `NotImplementedError`. O falso de `tests/test_aviso_de_falha.py` levanta `RuntimeError`, como o real. Nada muda.
  2. A `ollama.service` só fica ativa depois que o `ExecStartPost` acha a linha `inference compute` com `library=CUDA`,
     e no log dela o `Listening on 127.0.0.1:11434` vem uns 2 s antes dessa linha (07/11: 01:00:10,328 e 01:00:12,272):
     com o `After=`, o servidor já ouve quando o pipeline começa. A conferência da GPU antes da coleta não chama a API
     (lê o `/proc`, o log e o `nvidia-smi`). A primeira chamada (o `client.ps()` de `conferir_ollama`) não tem nova
     tentativa, mas só vem depois da coleta e da extração do primeiro item: na execução real de 07/11, início às
     01:01:36, GPU às 01:01:38, coleta até 01:02:39 (com feeds fora), primeira chamada terminada às 01:03:14 (34,3 s, com
     a carga do modelo). Sem risco à vista; nada muda.
  3. A pasta `~/.local/state/techdigest` é usada: o log da `ollama.service` (`ExecStartPre=truncate` e
     `StandardOutput=append:`, que o systemd abre antes de criar qualquer pasta), a trava do modelo (`trava.py`) e a
     parte fixa (`ai/janela.py`). Os dois últimos criam a pasta, mas só rodam depois que o Ollama subiu. O `mkdir -p`
     fica, para uma instalação do zero.
  4. O aviso importa o pacote `techdigest`, o pydantic, o pydantic-core, o pydantic-settings, o python-dotenv, o
     annotated-types, o typing-extensions e o typing-inspection; para enviar, o requests, o urllib3, o idna, o certifi e
     o charset-normalizer. O pipeline puxa também o edge-tts, o trafilatura, o feedparser, o aiohttp, o lxml e outros.
     Uma `.venv` quebrada só nos pacotes do pipeline derruba o pipeline e não o aviso; quebrada nos do aviso, ou na
     própria `.venv`, derruba os dois. Commit à parte, `735b9b3`: a frase em `docs/producao.md`, "O que avisa no
     Telegram".
  - Observação levada ao dono, fora do escopo da frente: a execução de 05/11 com o edge-tts errado (403) terminou com
    "Nenhuma notícia entregue nesta execução (181 min)" e status 0. Nem o pipeline nem o `OnFailure=` avisam esse caso;
    com o timer, ele passaria calado.
  - Testes: 732 passam; `ruff check .` sem avisos; `systemd-analyze --user verify` com os seis arquivos, status 0.
- 09/11/2026: o teste que mantém o aviso leve (proposta aceita pelo dono), num commit à parte:
  `test_o_aviso_nao_importa_os_pacotes_que_so_o_pipeline_usa`, em `tests/test_aviso_de_falha.py`. Ele importa o
  `techdigest.aviso_de_falha` num processo novo (o Python da `.venv`, com `-I`, e o `.env` desligado como no conftest) e
  falha se `edge_tts`, `trafilatura`, `feedparser`, `aiohttp`, `lxml` ou `techdigest.pipeline` estiverem em
  `sys.modules`. A mensagem de falha cita a frase de `docs/producao.md` que deixaria de ser verdadeira, e o teste
  também confere que essa frase continua lá. A cobertura está em `docs/referencia/scripts.md`.
  - Prova por mutação: com `import techdigest.pipeline` no `aviso_de_falha.py`, o teste falha com "importar
    techdigest.aviso_de_falha trouxe edge_tts, trafilatura, feedparser, aiohttp, lxml, techdigest.pipeline, que só o
    pipeline usa. Com isso deixa de ser verdade a frase de docs/producao.md, em "O que avisa no Telegram": ..."; desfeita,
    o `src/` voltou igual ao commit e os 31 testes do arquivo passam.
  - Testes: 733 passam; `ruff check .` sem avisos; `systemd-analyze --user verify` com os seis arquivos, status 0; nada
    instalado.
  - Etapa: aceite separado; pronta para o aceite do dono.
- 09/11/2026: aceite aprovado pelo dono em 09/11, 19:24. Pronta para integração: rebaseada sobre a `testes` em
  `fe6b66e` (a frente 6 na `testes`), sem conflito; o git juntou sozinho os trechos das duas frentes em `CLAUDE.md` e
  `docs/producao.md`, conferidos depois (nenhuma remoção de texto da frente 6).
  - Hashes depois do rebase (as entradas acima citam os de antes): `c07229f` → `1f64fdc`, `dee29cb` → `2d95c21`,
    `735b9b3` → `6b92a21`, `fc27ac7` → `a50eadf`.
  - Conferências na `.venv` do uv: `uv sync --locked --check --extra dev` deu `Would make no changes`; 753 testes passam
    em duas rodadas (733 desta frente e 20 da frente 6); `ruff check .` sem avisos; `systemd-analyze --user verify` com
    os seis arquivos de `deploy/systemd/`, status 0. O `git diff --stat testes..HEAD` traz só `deploy/systemd/*`,
    `src/techdigest/aviso_de_falha.py`, `tests/test_aviso_de_falha.py`, `tests/test_units.py`, `CLAUDE.md`,
    `docs/producao.md`, `docs/referencia/scripts.md` e este arquivo; nada em `pipeline.py`, `pyproject.toml` ou `uv.lock`.
  - O avanço rápido da `testes` é da frente 0, assim como o docstring do `pipeline.run` e o estado de produção do
    `CLAUDE.md` (G13).

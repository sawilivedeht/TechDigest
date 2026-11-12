# Execução real à mão

Para o dono. Só você roda isto: as sessões do Claude Code não rodam o pipeline, que entrega no Telegram e marca as
notícias como vistas em `data/digest.db`. Não há timer; cada execução sai deste passo a passo.

## Antes

1. A `master` e a `.venv` da pasta principal (`/home/sytw/Projetos/techdigest`) são as que rodam, e a `.venv` segue o
   `uv.lock` da `master`. Depois de qualquer atualização da `master`, na pasta principal,
   `uv sync --locked --check --extra dev` tem de terminar em `Would make no changes`. Se listar pacotes, rode
   `uv sync --locked --extra dev` e confira de novo (sempre com o `--extra dev`: sem ele o pytest sai da `.venv`). Em
   05/11 o edge-tts 7.2.8 da produção derrubou a execução inteira (403) enquanto a simulação passava com o 7.3.1: o
   `--check` acusa exatamente esse caso.
2. Nenhuma outra rodada no ar: `systemctl --user is-active techdigest-teste.target` deve dar `inactive`. O pipeline também
   recusa começar (e avisa no Telegram) se a trava do modelo estiver ocupada.
3. `nvidia-smi` tem de responder. Se não responder, não suba nada: sem GPU a carga do modelo esgota a memória.

## Rodar

1. Suba o Ollama pela unit, nunca com `ollama serve` à mão:
   `systemctl --user start techdigest-teste.target`
   A unit do Ollama tem um teto de memória (`MemoryMax=20G`, frente 5, decisão de 09/11/2026), que vale também para
   esta execução à mão: se o servidor passar dele, o kernel primeiro tira o modelo da memória (tudo fica lento) e
   depois encerra o servidor, e o pipeline para com "o Ollama não responde" e avisa. A cópia instalada só ganha o teto
   quando a unit é copiada de novo, com a sessão de teste parada:
   `cp deploy/systemd/ollama.service ~/.config/systemd/user/ && systemctl --user daemon-reload`.
2. Confira a GPU no log da unit:
   `grep "inference compute" ~/.local/state/techdigest/ollama_serve.log | tail -1` deve trazer `library=CUDA`. Sem essa
   linha o pipeline para antes de carregar o modelo (foi o que aconteceu nas tentativas de 07/11 à 0h55).
3. Na pasta principal, a execução, sem deixar a máquina dormir:
   `cd /home/sytw/Projetos/techdigest && systemd-inhibit --what=sleep:idle --who=TechDigest --why="execucao real" .venv/bin/techdigest`
   Sempre pelo `techdigest` (ou `python -m techdigest`), que liga o log em arquivo. Uma execução de 20 itens leva
   uns 60 a 110 minutos; nenhum item novo começa depois de 180 minutos.
4. Quando terminar, ou quando falhar, pare a sessão: `systemctl --user stop techdigest-teste.target` e confira com
   `is-active`.

## Depois

- Resumo da execução: `.venv/bin/python scripts/resumo_lotes.py` (do dia; `07/11` para outro dia; `--log <arquivo>`).
  Mostra entregues, pulados pelo QA, filtrados, abandonados, feeds fora da coleta e paradas.
- Status de saída 1 quer dizer que a execução parou: trava ocupada, freio da máquina (memória, temperatura, GPU), erro
  inesperado, falhas seguidas de entrega ou todos os feeds fora. Nesses casos chega um aviso curto no chat do Telegram;
  o que não foi entregue volta na próxima execução. Se a causa foi o Ollama subido à mão, comece de novo pelo passo 1.
- Item reprovado pelo QA em 2 execuções é abandonado (`reprovacoes` no banco).

## Trocar um feed

A lista de feeds fica em `config/feeds.txt`, versionada: uma URL por linha, na ordem da intercalação do boletim duplo
(a ordem decide quais feeds entram primeiro no `MAX_NEWS`). A linha que começa com `#` é comentário; uma linha que não é
URL, uma URL repetida ou um arquivo sem URL param a execução (aviso de parada, status 1). Para incluir, tirar, reordenar
ou corrigir um feed:

1. Edite o `config/feeds.txt` numa branch de trabalho, nunca direto na `master`.
2. No mesmo commit, atualize a lista literal `FEEDS_DO_REPOSITORIO` de `tests/test_feeds.py`: o teste do arquivo do
   repositório confere as URLs uma a uma, na ordem, e falha com qualquer troca até a lista dele acompanhar.
3. A suíte inteira, o `ruff check .` e o `.venv/bin/pyright`, o commit e, com o seu ok, o avanço rápido da `master`.

Enquanto o `RSS_FEEDS` estiver no `.env`, vale ele, e não o arquivo: a cada execução o log traz
`RSS_FEEDS definido no ambiente ou no .env: a coleta usa ele, não o .../config/feeds.txt`. Depois do merge da frente 6
na `master`, apague a linha `RSS_FEEDS` do `.env` inteira: um `RSS_FEEDS=` vazio também conta como definido e deixa a
coleta sem nenhum feed.

## Onde ficam os registros

| O quê | Onde |
|---|---|
| Log da execução | `data/logs/techdigest.log` (rotativo, 2 MB x 7) |
| Registro de cada execução | `data/execucoes/<data-hora>/`: `amostra.json`, `relatorio_<data-hora>.json` e um JSON por episódio (30 dias) |
| Áudio e texto entregues | `data/audio/<slug>.mp3` |
| Banco de notícias vistas | `data/digest.db` (não editar à mão) |
| Log do Ollama e trava do modelo | `~/.local/state/techdigest/` |
| Lista de feeds | `config/feeds.txt` (versionada; o `RSS_FEEDS` do `.env`, se definido, vale no lugar dela) |

Chaves em vigor: `AGRUPAMENTO_ATIVO=false` e `DISPUTA_FONTE_UNICA=false`. Ligar qualquer uma depende do dono
(`docs/roteiro-fase4.md`).

## Com o timer

As units do timer estão em `deploy/systemd/` e não vêm instaladas: o timer só roda depois que você instalar e ligar
(frente 5 das melhorias, decisões de 09/11/2026). São quatro, além das duas do Ollama, que já estão instaladas
(`ollama.service` e `techdigest-teste.target`):

| Unit | O que faz |
|---|---|
| `techdigest.timer` | Dispara a `techdigest.service` todo dia à 01:00 (`OnCalendar=*-*-* 01:00:00`, `Persistent=true`) |
| `techdigest.service` | A execução: o `.venv/bin/techdigest` da pasta principal como processo principal; `Wants=` e `After=` para o Ollama e para o bloqueio do sono; no máximo 4 horas (`RuntimeMaxSec=4h`) |
| `techdigest-inibir.service` | O bloqueio do sono durante a execução (`systemd-inhibit --what=sleep:idle`); para sozinha quando a execução termina (`StopWhenUnneeded=yes`) |
| `techdigest-aviso.service` | O aviso de falha (`python -m techdigest.aviso_de_falha`), disparado pelo `OnFailure=` da `techdigest.service` |

### Instalar e ligar

Na pasta principal, com a `master` já com a frente 5:

    mkdir -p ~/.config/systemd/user ~/.local/state/techdigest
    cp deploy/systemd/techdigest.service deploy/systemd/techdigest.timer deploy/systemd/techdigest-inibir.service deploy/systemd/techdigest-aviso.service ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now techdigest.timer
    systemctl --user list-timers techdigest.timer      # a próxima execução

A `ollama.service` com o teto de memória vai junto, se ainda não foi copiada (passo 1 de "Rodar").

Sem `loginctl enable-linger` (decisão de 09/11/2026). Sem linger, o gerenciador de units do usuário só existe enquanto
há uma sessão sua aberta (a tela bloqueada conta como sessão aberta): o timer só dispara com você logado, e uma
execução perdida roda no login seguinte (`Persistent=true`). O bloqueio do sono também depende da sessão: o polkit só
deixa uma unit de usuário bloquear o sono com uma sessão sua aberta, e sem ela pede senha de administrador. O caso sem
sessão fica para conferir depois da instalação.

### A primeira execução

Durante a primeira execução pelo timer (ou por `systemctl --user start techdigest.service`, que é uma execução real,
com Telegram), confira que o Ollama e o bloqueio do sono ficam no ar enquanto ela roda:

    systemctl --user is-active ollama.service techdigest-inibir.service   # active, active
    systemd-inhibit --list                                                 # uma linha TechDigest, sleep:idle, block

Depois: `systemctl --user status techdigest.service` e `journalctl --user -u techdigest.service`. O
`scripts/resumo_lotes.py` lê o log de sempre, `data/logs/techdigest.log`.

### O que avisa no Telegram

- **O pipeline parou sozinho** (trava ocupada, freio da máquina, erro inesperado, falhas seguidas de entrega, todos os
  feeds fora): ele avisa, como na execução à mão, e sai com status 1. O aviso de falha acha a linha `Aviso de parada:`
  no journal daquela execução e só registra.
- **O que o pipeline não consegue avisar**: o aviso de falha manda uma mensagem curta, "TechDigest (techdigest.service)
  parou às HH:MM: <motivo>". Os motivos: passou das 4 horas, encerrado por falta de memória, encerrado por um sinal,
  core dump, status 1 sem o aviso do pipeline (um erro antes de começar, como uma `.venv` fora do `uv.lock`), o aviso
  do pipeline que não foi enviado, o journal que não pôde ser lido, o systemd que não conseguiu iniciar o pipeline
  (status de 200 em diante) e qualquer outra falha da unit. Um aviso duplicado vale mais que um silêncio.
- **Sem aviso**: um `systemctl --user stop`, um logout ou um desligamento no meio da execução. Para o systemd, SIGTERM,
  SIGINT, SIGHUP e SIGPIPE vindos de fora são uma saída limpa (`SuccessExitStatus=`, `systemd.service(5)`), e o
  `OnFailure=` não dispara. O que não foi entregue volta na próxima execução.
- Se o Ollama não sobe (sem o driver da NVIDIA, por exemplo), a execução começa mesmo assim (`Wants=`), para na
  conferência da GPU e o pipeline avisa.
- Se o próprio aviso de falha não consegue enviar, a `techdigest-aviso.service` fica em falha
  (`systemctl --user --failed`) e o log traz `Aviso de parada não enviado`.
- O erro antes de começar só avisa se o próprio aviso consegue rodar. Ele usa a mesma `.venv`, mas importa muito
  menos que o pipeline: o pacote `techdigest` com a configuração (pydantic, pydantic-settings, python-dotenv) e, para
  enviar, o requests (conferido em 09/11/2026). Um pacote que só o pipeline usa (edge-tts, trafilatura, feedparser,
  aiohttp, lxml...) quebrado ou ausente derruba o pipeline e não o aviso, que avisa. Se o problema estiver num dos
  pacotes do aviso, ou na própria `.venv` (o Python dela, o pacote `techdigest`), o aviso também não roda: a
  `techdigest-aviso.service` fica em falha, o que só aparece em `systemctl --user --failed`, e nada chega ao Telegram.

### Sono e tampa

- A tampa ignora o bloqueio do sono: `LidSwitchIgnoreInhibited=` é `yes` por padrão no logind. Nesta máquina a tampa só
  suspende na bateria (`/etc/systemd/logind.conf.d/10-tampa.conf`); na tomada, com a tampa fechada, ela fica acordada.
- Com a máquina suspensa à 01:00, a execução roda quando ela volta: um horário que passou durante a suspensão é
  processado na volta (`systemd.timer(5)`). O `Persistent=true` cobre a máquina desligada à 01:00 e você deslogado.
- O `WakeSystem=` não serve num timer de usuário: acordar a máquina exige privilégio e só funciona no gerenciador do
  sistema (`systemd.timer(5)`). Nenhum timer acorda a máquina.
- Não há suspensão por ociosidade (o Hyprland roda sem hypridle). O bloqueio segura um `systemctl suspend` seu, sem
  root, e os programas que respeitam bloqueios.

### Junto com a execução à mão

A execução à mão continua como está acima. A trava do modelo impede duas ao mesmo tempo: a que chega depois para e
avisa. O mesmo vale para uma rodada de teste que esteja segurando a trava à 01:00: a execução do timer para e avisa.
O teto de memória do Ollama (`MemoryMax=20G`) vale para as duas, porque as duas sobem a mesma `ollama.service`.

### Desligar e desinstalar

    systemctl --user disable --now techdigest.timer
    systemctl --user clean --what=state techdigest.timer    # antes de apagar a unit: a data da última execução
    rm ~/.config/systemd/user/techdigest.service ~/.config/systemd/user/techdigest.timer ~/.config/systemd/user/techdigest-inibir.service ~/.config/systemd/user/techdigest-aviso.service
    systemctl --user daemon-reload

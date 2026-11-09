# Plano das melhorias de 07/11/2026: frentes em paralelo

O mesmo texto fica no Projeto do claude.ai (`claude/plano-melhorias.md`) e no repositório (`docs/plano-melhorias.md`).
Quem o mantém é a frente 0. Origem: a análise de linguagens e ferramentas de 07/11/2026, feita sobre o código da `master`
em `0bdf41f`, com o ruff e o pyright rodados nele. Conclusão dela: o núcleo continua em Python; as nove melhorias abaixo
são de ferramentas, operação e uso do Python.

## Como usar

- Cada melhoria é uma **frente**: uma branch, uma worktree, uma sessão do Claude Code e um chat do navegador.
- O **chat do navegador** da frente lê este plano e o arquivo da frente, passa ao dono os prompts para a sessão do Claude
  Code, revisa o que ela fizer e mantém o arquivo da frente no Projeto (`claude/frentes/NN-nome.md`). É o único chat que
  escreve nesse arquivo.
- A **sessão do Claude Code** trabalha só na worktree da frente e mantém o espelho do arquivo no repositório
  (`docs/melhorias/NN-nome.md`), na branch da frente.
- A **frente 0** cuida deste plano, do `claude/andamento.md`, da branch `testes` e do merge na `master`.
- Para abrir o chat de uma frente, num chat novo deste Projeto: "Sou o chat da frente N (nome). Leia
  `claude/plano-melhorias.md` e `claude/frentes/NN-nome.md` e me diga o primeiro passo."

## Estado de partida (07/11/2026)

- `master` em `0bdf41f`. A produção é a pasta principal, `/home/sytw/Projetos/techdigest`: execuções reais à mão pelo dono
  (`docs/producao.md`), `AGRUPAMENTO_ATIVO=false`, `DISPUTA_FONTE_UNICA=false`, sem timer. Continua rodando assim até o
  merge das frentes (decisão do dono de 07/11).
- A worktree `/home/sytw/Projetos/techdigest-fase4`, na branch `trabalho`, fica para o trabalho do roteiro (diagnóstico
  A/B, coleta 6) e não entra neste plano.
- 667 testes passam offline. Python 3.14 nas duas `.venv`. Não há linter, lockfile nem unit do pipeline.

## As frentes

| Frente | Branch | Worktree (em `/home/sytw/Projetos/`) | Onda | Entrega |
|---|---|---|---|---|
| 0 Coordenação e integração | `coordenacao`, depois `testes` | `techdigest-testes` | 0 e fim | regras, worktrees, integração e merge |
| 1 Áudio | `melhoria/audio` | `techdigest-audio` | 1 | medição do áudio; turnos sintetizados em paralelo |
| 2 Versões | `melhoria/versoes` | `techdigest-versoes` | 1 | versões fixas e egg-info fora do git |
| 3 Registro | `melhoria/registro` | `techdigest-registro` | 1 | gravação atômica do registro de cada execução |
| 4 ruff | `melhoria/ruff` | `techdigest-ruff` | 1 | linter, sem mudança de estilo |
| 5 systemd | `melhoria/systemd` | `techdigest-systemd` | 2 | unit, timer, aviso de falha e limite de memória, versionados e não ligados |
| 6 Feeds | `melhoria/feeds` | `techdigest-feeds` | 2 | lista de feeds em `config/feeds.txt` |
| 7 Rodada | `melhoria/rodada` | `techdigest-rodada` | 2 | `scripts/rodada.py` no lugar do vigia e do `rodar.sh` copiados |
| 8 Schema | `melhoria/schema` | `techdigest-schema` | 1 (medição) e 3 | quantas chamadas são refeitas por JSON incompleto; schema no `format`, se valer |
| 9 Tipos | `melhoria/tipos` | `techdigest-tipos` | 3 | `TypedDict` do episódio e pyright, se o dono quiser |

Arquivos das frentes: `00-coordenacao.md`, `01-audio.md`, `02-versoes.md`, `03-registro.md`, `04-ruff.md`,
`05-systemd.md`, `06-feeds.md`, `07-rodada.md`, `08-schema.md`, `09-tipos.md`.

## Ondas

A ordem é a sugerida em 07/11; o que não depende de outra frente roda em paralelo.

- **Onda 0:** frente 0. Os documentos entram na `master` (só documentos), as regras mudam, a `testes` e as worktrees da
  onda 1 são criadas.
- **Onda 1:** frentes 1, 2, 3 e 4, e a medição da frente 8. Nenhuma chama o modelo.
- **Onda 2:** frentes 5, 6 e 7. A 5 precisa de uma rodada para calibrar a memória; a 6, da lista de feeds do dono.
- **Onda 3:** o experimento da frente 8 (só se a medição justificar) e a frente 9, depois que as outras estiverem
  integradas.

As worktrees das ondas 2 e 3 só são criadas quando o dono abrir o chat delas. Sugestão: no máximo 3 ou 4 frentes abertas
ao mesmo tempo, porque cada sessão espera a aprovação do dono antes de editar.

## Regras das frentes

Valem junto com `docs/regras-de-sessao.md` (a frente 0 as copia para lá):

1. A sessão trabalha só na worktree e na branch da sua frente. Nunca na pasta principal, na `master`, na `trabalho` ou na
   branch de outra frente. Commits sem push.
2. Só os arquivos do escopo da frente. Se precisar de outro, anota no arquivo da frente e pergunta ao dono.
3. Nenhuma mudança de estilo em massa (formatador, ordem dos imports) enquanto houver frente aberta: ela vira conflito em
   todas as outras.
4. Documentos compartilhados (`CLAUDE.md`, `docs/producao.md`, `docs/regras-de-sessao.md`, `docs/referencia/`): cada
   frente muda só o trecho do seu assunto. O estado de produção do `CLAUDE.md` ("Repo notes"), as skills
   (`~/.claude/skills`) e o `CLAUDE.local.md` mudam só na integração, pela frente 0.
5. Sem commit de `src/techdigest.egg-info`, que muda a cada instalação, até a frente 2 tirá-lo do git. (Feita na frente 2, 08/11:
   o `egg-info` saiu do git e está no `.gitignore`.)
6. A cada commit: a suíte inteira passa (`.venv/bin/pytest`) e a seção "Estado" do arquivo da frente é atualizada. As
   suítes de várias worktrees podem rodar ao mesmo tempo: o `tests/conftest.py` cria uma pasta temporária nova a cada vez.
7. Modelo: uma rodada por vez na máquina inteira, e nenhuma durante uma execução real do dono. Antes,
   `systemctl --user is-active techdigest-teste.target` deve dar `inactive`. Quem precisa de rodada pede ao dono e anota no
   arquivo da frente.
8. A produção só é lida: os logs e registros de `/home/sytw/Projetos/techdigest/data/` são lidos por caminho absoluto e
   nunca escritos. A exceção são as pastas novas de medição e de rodada em `data/agrupamento/`, como já é hoje.
9. O `.env` continua fechado: ninguém lê nem edita. Valor real, só pelo dono.

## Fluxo de uma frente

1. O chat do navegador lê o plano e o arquivo da frente e passa ao dono o prompt inicial (no fim de cada arquivo).
2. A sessão do Claude Code lê os mesmos documentos no repositório, faz o que for só leitura e apresenta o plano com a lista
   "Leituras minhas, para você corrigir".
3. Com o ok do dono: implementa, roda a suíte, faz o aceite separado descrito no arquivo da frente, faz o commit e atualiza
   `docs/melhorias/NN-nome.md`.
4. O chat do navegador atualiza `claude/frentes/NN-nome.md` com o mesmo estado.
5. Com o aceite separado aprovado pelo dono, a frente fica "pronta para integração" e a frente 0 é avisada.

Uma frente também pode terminar sem código (a medição da frente 8 pode mostrar que o experimento não vale; o dono pode
dispensar a frente 9): fica "fechada", com o motivo no arquivo dela, e não segura a integração.

## Integração (frente 0, branch `testes`)

A `master` segue rodando até as frentes terminarem (decisão do dono de 07/11). Por padrão, a integração é uma rodada só,
no fim; se o dono quiser antecipar um grupo de frentes, o procedimento é o mesmo.

1. A `testes` nasce da `master` no fim da onda 0.
2. Cada frente pronta entra uma por vez: rebase da branch dela sobre a `testes` (na worktree dela, com a sessão dela) e
   avanço rápido da `testes`. Depois de cada uma: a suíte inteira e, depois da frente 4, o `ruff check .`.
3. Teste conjunto, com as frentes da rodada na `testes`: a suíte; uma simulação com áudio
   (`.venv/bin/techdigest --simular data/simulacoes/testes_AAAAMMDD --banco-origem /home/sytw/Projetos/techdigest/data/digest.db`,
   dentro da sessão de teste, como numa rodada); o `scripts/resumo_lotes.py` com o `--log` da simulação; o
   `scripts/checar_fidelidade.py --relatorio` no registro dela; o dono ouve alguns episódios.
4. Com o ok do dono: avanço rápido da `master` para a `testes` na pasta principal; a `.venv` de produção alinhada pela
   decisão da frente 2; só a `ollama.service` com `MemoryMax=20G` é copiada para `~/.config/systemd/user`, com a sessão de teste parada
   (`systemctl --user is-active techdigest-teste.target` deve dar `inactive`); as quatro units do timer (`techdigest.service`,
   `techdigest.timer`, `techdigest-inibir.service` e `techdigest-aviso.service`) NÃO são copiadas nem ligadas pelo merge
   (decisão do dono, seção "Com o timer" de `docs/producao.md`);
   as skills, o `CLAUDE.local.md` e o estado de produção do `CLAUDE.md` atualizados; a primeira execução real à mão pelo
   dono. Depois do merge, o dono apaga a linha `RSS_FEEDS` INTEIRA do `.env` da pasta principal, nunca esvaziada: um `RSS_FEEDS=` vazio
   conta como definido e a execução termina sem coletar nenhum feed (status 0, "Nenhuma notícia entregue"). Enquanto a linha
   existir, vale ela e não o `config/feeds.txt`, com o aviso no log a cada execução. Só depois do merge: o código da `master`
   de hoje não lê o `config/feeds.txt`, e sem a linha cairia nos feeds padrão do código, que não são os que rodam. No merge,
   conferir também se as skills e o `CLAUDE.local.md` citam `RSS_FEEDS`. Depois que o dono ligar o timer, conferir a primeira execução real (`systemctl --user is-active ollama.service
   techdigest-inibir.service` dá `active` duas vezes; `systemd-inhibit --list` mostra o bloqueio) e testar o caso sem
   sessão do polkit.
5. Depois do merge de uma frente: `git worktree remove` e a branch apagada.

## Mapa de conflitos

| Arquivo | Frentes | Como evitar |
|---|---|---|
| `pyproject.toml` | 2, 4, 9 | Cada uma mexe só na sua seção. Se a 2 adotar lockfile, a que entrar depois na `testes` refaz o lock. Resolvido para a 4: ela já refez o `uv.lock` (65 pacotes) sobre o da 2 |
| `.gitignore` | 2 | — |
| `src/techdigest/audio/tts.py` | 1, 4 | Resolvido: a frente 1 tirou o `f` no `d8dc640`; a frente 4 não toca o `tts.py` |
| `src/techdigest/config.py` | 6; 8 e 9 na onda 3 | A 6 já entrou (`ler_feeds` e `CAMINHO_DOS_FEEDS`); a 8 e a 9 só mexem no `config.py` depois dela |
| `src/techdigest/registro.py` | 3 | — |
| `src/techdigest/delivery/email_smtp.py`, `scripts/refazer_qa.py` | 4 | — |
| `deploy/systemd/` | 5 | — |
| `docs/producao.md` | 2, 5, 6 | Trechos diferentes: a instalação (2), o timer (5) e "Trocar um feed" (6) |
| `docs/referencia/scripts.md` | 5, 7 | Trechos diferentes: a unit do Ollama (5) e a rodada (7) |
| `docs/regras-de-sessao.md` | 0, 2 | A 2 só troca a regra do `pip freeze`, e só se o dono adotar o lockfile |
| `CLAUDE.md` | todas | Só o trecho do assunto; o estado de produção, na integração |

## Documentação: quem atualiza o quê

| Onde | Quem | Quando |
|---|---|---|
| `docs/melhorias/NN-nome.md`, na branch da frente | a sessão do Claude Code da frente | a cada commit |
| `claude/frentes/NN-nome.md`, no Projeto | o chat do navegador da frente, o único que escreve nele | a cada etapa da sessão |
| `docs/plano-melhorias.md` e `claude/plano-melhorias.md` | a frente 0 | quando uma frente abre, fecha, fica pronta, entra na `testes` ou na `master` |
| `claude/andamento.md`, no Projeto | a frente 0 | a cada integração e merge |
| Estado de produção do `CLAUDE.md`, skills, `CLAUDE.local.md` e as cópias `claude/CLAUDE.md` e `skills` do Projeto | a frente 0 | no merge na `master` |

A seção "Estado" de cada arquivo de frente traz: data; etapa (não começada, em plano, em implementação, aceite separado,
pronta para integração, na `testes`, na `master`, fechada); branch e último commit; quantos testes passam; números
medidos; decisões do dono; pendências.

Os documentos do Projeto são reescritos inteiros a cada gravação. Por isso cada chat só escreve no seu arquivo: dois chats
gravando o mesmo arquivo apagam a atualização um do outro.

Os chats do navegador só enxergam a `master`, pelo GitHub sincronizado com o Projeto. Se o dono der push nas branches das
frentes, o chat de cada uma consegue ler o código dela; senão, o dono cola o `git diff` ou o resumo da sessão.

## Decisões do dono

| Decisão | Frente | Quando |
|---|---|---|
| Aprovar os documentos na `master` e as regras novas | 0 | onda 0 |
| Seguir com os turnos em paralelo, depois da medição | 1 | onda 1 |
| uv, pip-tools ou só fixar o `edge-tts` | 2 | onda 1 |
| As regras do ruff e o destino do `email_smtp.py` (corrigir duas linhas ou apagar o módulo) | 4 | onda 1; decidida em 08/11: só F e ISC, e corrigir as duas linhas do `email_smtp.py` |
| Um único merge na `master` no fim, com todas as frentes | 0 | 08/11 |
| Horário do timer, `Wants=` ou `Requires=`, os valores de memória, `linger` | 5 | onda 2 |
| A lista de feeds (copiada do `.env`) e a precedência entre o arquivo e o `RSS_FEEDS` | 6 | onda 2; lista copiada do `.env` em 08/11; precedência: o `RSS_FEEDS` definido manda, mesmo vazio, com aviso no log; aprovada em 09/11 |
| O formato dos comandos da rodada e se a execução real à mão também usa o script | 7 | onda 2 |
| Rodar o experimento do schema, se a medição justificar | 8 | onda 3 |
| Fazer ou não a frente 9 | 9 | onda 3 |

## Instruções do Projeto (texto sugerido)

Para colar nas instruções do Projeto techdigest no claude.ai, e todo chat novo já seguir o protocolo:

> Melhorias de 07/11/2026 em frentes paralelas. Antes de responder, leia `claude/plano-melhorias.md` e o arquivo da sua
> frente em `claude/frentes/`. Cada chat cuida de uma frente e só escreve no arquivo dela; o chat da frente 0 também cuida
> do plano e do `claude/andamento.md`. Depois de cada etapa da sessão do Claude Code, atualize a seção "Estado" do arquivo
> da frente. Nenhuma frente mexe na `master`: a integração é na branch `testes`.

## Estado do plano

| Frente | Etapa | Branch e último commit | Observação |
|---|---|---|---|
| 0 | onda 0 concluída; integrando as frentes na `testes` | `testes`, nascida da `master` em `64bd21b`; frentes 1, 2, 3, 4, 5 e 6 integradas; `testes` em `7f73972` antes deste commit de documentos | `coordenacao` apagada depois do passo 7; 753 testes e `ruff check .` limpo na `testes` |
| 1 Áudio | na `testes` | `melhoria/audio`, `63ea31f` | turnos sintetizados em paralelo, integrados por avanço rápido; 715 testes passam na `testes` |
| 2 Versões | na `testes` | `melhoria/versoes`, `2c4c899` | `uv.lock` e `.python-version`; `egg-info` fora do git; `.venv` da `testes` refeita pelo uv, versões idênticas às da produção; 715 testes passam na `testes` |
| 3 Registro | na `testes` | `melhoria/registro`, `a482b0a` | gravação atômica integrada; aceite estendido: processo morto, três testes que falham com a gravação direta; 715 testes passam na `testes` |
| 4 ruff | na `testes` | `melhoria/ruff`, `a0db7a8` | ruff 0.17.4 só com as regras F e ISC, 3 avisos corrigidos (duas linhas do `email_smtp.py` e uma do `refazer_qa.py`); `uv.lock` com 65 pacotes; 715 testes passam na `testes` |
| 8 Schema | não começada (medição na onda 1) | `melhoria/schema`, `64bd21b` | worktree `techdigest-schema` pronta: 667 testes, versões da produção |
| 6 Feeds | na `testes` | `melhoria/feeds`, `d05cb23` | `config/feeds.txt` com 9 URLs; o `RSS_FEEDS` definido no ambiente ou no `.env` manda, mesmo vazio, com aviso no log; 715 testes passam na `testes` |
| 5 systemd | na `testes` | `melhoria/systemd`: `1f64fdc`, `2d95c21`, `6b92a21`, `a50eadf` e `7f73972` | units do pipeline, do timer, do bloqueio do sono e do aviso de falha em `deploy/systemd/`, versionadas e não instaladas; `MemoryMax=20G` na `ollama.service`; rebaseada sobre `fe6b66e` (o merge-base era `121fa7b`); aceite do dono de 09/11, 19:24, como informa o `05-systemd.md`; 753 testes passam na `testes` |
| 7 e 9 | não começadas | — | worktrees criadas quando o dono abrir o chat delas (passos 8 e 9 da onda 0) |

- 07/11/2026: plano criado.
- 07/11/2026: onda 0 concluída. O commit `64bd21b` (o plano, os arquivos das frentes, as regras e o `CLAUDE.md`, só
  documentos) entrou na `master` e na `trabalho` por avanço rápido, com o ok do dono. A `testes` nasceu da `master`. As
  worktrees da onda 1 e a `techdigest-testes` têm `.venv` com as versões da produção (60 pacotes, `pip freeze` igual), o
  link `data/agrupamento` para a pasta principal e 667 testes passando. As skills `techdigest-retomar` e
  `techdigest-rodada-modelo` foram atualizadas para as frentes. A onda 1 pode abrir.
- 08/11/2026: frente 3 (registro) na `testes`. `git merge --ff-only melhoria/registro` levou a `testes` de `7d8760b` a
  `b181d3d`; a suíte inteira deu 671 passando. A `master` não mudou.
- 08/11/2026: frente 3 com os testes de processo morto. `git merge --ff-only melhoria/registro` levou a `testes` de
  `5a913e1` a `a482b0a` (só o commit dos testes); a suíte deu 674 passando, em duas execuções. A `master` não mudou.
- 08/11/2026: frente 2 (versões) na `testes`. `git merge --ff-only melhoria/versoes` levou a `testes` de `9aec835` a
  `2c4c899`. A `.venv` da `testes` passou para o uv (`uv sync --locked --extra dev`, Python 3.14.9 do sistema, `Would make
  no changes`); o `pip freeze` da produção e o `uv pip freeze` da `testes` não têm nenhuma linha diferente. A suíte deu 674
  passando, em duas execuções. O `egg-info` saiu do git (regra 5 feita). A `master` não mudou.
- 08/11/2026: frente 1 (áudio) na `testes`. `git merge --ff-only melhoria/audio` levou a `testes` de `4bce887` a `63ea31f`
  (`audio/tts.py`, `tests/test_tts.py`, o passo 5 da Architecture no `CLAUDE.md` e `docs/melhorias/01-audio.md`). O `uv sync
  --locked --check --extra dev` deu `Would make no changes` e a suíte deu 695 passando, em duas execuções. A `master` e a
  `trabalho` seguem em `64bd21b`.
- 08/11/2026: frente 4 (ruff) na `testes`. `git merge --ff-only melhoria/ruff` levou a `testes` de `3278e70` a `a0db7a8`
  (`pyproject.toml`, `uv.lock`, `CLAUDE.md`, `email_smtp.py`, `scripts/refazer_qa.py` e `docs/melhorias/04-ruff.md`; o
  `tts.py` não aparece). A `.venv` não tinha o ruff: `uv sync --locked --extra dev` o instalou (0.17.4) e o `--check`
  deu `Would make no changes`. A suíte deu 695 passando em duas execuções e o `ruff check .` não teve avisos; tirar uma
  vírgula da linha 25 de `ai/verbos.py` dá ISC001 e ISC004 (desfeito). O dono decidiu fazer um único merge na `master`
  no fim, com todas as frentes. A `master` e a `trabalho` seguem em `64bd21b`.
- 09/11/2026: frente 6 (feeds) na `testes`. `git merge --ff-only melhoria/feeds` levou a `testes` de `121fa7b` a `d05cb23`
  (`config.py`, `collectors/rss.py`, `config/feeds.txt`, `tests/test_feeds.py`, `CLAUDE.md`, `docs/producao.md` e
  `docs/melhorias/06-feeds.md`; `pyproject.toml` e `uv.lock` não mudaram). `Would make no changes`, 715 testes em duas
  execuções, `ruff check .` limpo e `config.ler_feeds()` com 9 URLs (sem ler o `.env`). Aprovada pelo dono em 09/11: o
  `RSS_FEEDS` definido manda, mesmo vazio, com aviso no log. No merge na `master`, o dono apaga a linha `RSS_FEEDS` inteira
  do `.env` da pasta principal (ver o passo 4 da Integração). A `master` e a `trabalho` seguem em `64bd21b`.
- 09/11/2026: frente 5 (systemd) na `testes`. `git merge --ff-only melhoria/systemd` levou a `testes` de `fe6b66e` a `7f73972`,
  em dois avanços: `a50eadf`, e depois o commit de documentos da frente (`7f73972`, sem hash antigo), que ela fez depois do
  primeiro avanço. Hashes finais da branch: `1f64fdc`, `2d95c21`, `6b92a21`, `a50eadf` e `7f73972`; antes do rebase sobre
  `fe6b66e`, os quatro primeiros eram `c07229f`, `dee29cb`, `735b9b3` e `fc27ac7`. Aceite do dono de 09/11, 19:24, como informa
  o `05-systemd.md`. `Would make no changes`, 753 testes em duas rodadas (733 da frente e 20 da frente 6), `ruff check .`
  limpo; o diff `fe6b66e..7f73972` tem 12 arquivos, sem `pipeline.py`, `pyproject.toml` nem `uv.lock`. Neste commit, por
  decisão G13 da frente 5 (ver `05-systemd.md`): o docstring de `pipeline.run` passa a citar o `OnFailure=` da
  `techdigest.service` e o estado de produção do `CLAUDE.md` deixa de dizer que não há unit nem timer (as units estão
  versionadas e não instaladas; o timer segue desligado). Nada foi instalado nem copiado. `testes` em `7f73972` antes deste
  commit de documentos. A `master` e a `trabalho` seguem em `64bd21b`.
- Melhoria futura, depois do merge e sem segurar a integração (lacuna C10 da frente 5): com o timer, uma noite sem nenhuma
  entrega passa calada. Na execução real de 05/11, com o edge-tts dando 403, cada item falhou isolado e o pipeline terminou
  com status 0 depois de 181 min ("Nenhuma notícia entregue nesta execução (181 min)"); nem o pipeline nem o `OnFailure=`
  avisam esse caso. Corrigir é mexer no `pipeline.py` (por exemplo, um aviso quando sai 0 de N com candidatos).

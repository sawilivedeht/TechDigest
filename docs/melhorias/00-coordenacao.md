# Frente 0: coordenação e integração

Arquivo no Projeto: `claude/frentes/00-coordenacao.md` · no repositório: `docs/melhorias/00-coordenacao.md`

| | |
|---|---|
| Branch | `coordenacao` (só documentos), depois `testes` (integração) |
| Worktree | `/home/sytw/Projetos/techdigest-testes` |
| Onda | 0, e depois a integração |
| No Projeto, escreve em | este arquivo, `claude/plano-melhorias.md` e `claude/andamento.md` |

## Objetivo

Preparar o terreno para as frentes trabalharem em paralelo sem se atrapalhar e, depois, juntar e testar o que elas
entregarem antes do merge na `master`.

## Onda 0: preparação

0. Antes de abrir a sessão, o dono, no terminal:
   `git -C /home/sytw/Projetos/techdigest worktree add /home/sytw/Projetos/techdigest-testes -b coordenacao master`,
   põe o pacote `techdigest-plano-melhorias-20261107.zip` (enviado no chat de 07/11; o mesmo conteúdo está no Projeto) dentro
   da `techdigest-testes` e abre o Claude Code nela.
1. Só leitura: o commit da `master` na pasta principal (`git log --oneline -1`), `git worktree list`, `git status` na pasta
   principal e na `techdigest-fase4`, `systemctl --user is-active techdigest-teste.target`.
2. Descompactar o pacote na raiz da worktree: cria `docs/plano-melhorias.md` e `docs/melhorias/`. Apagar o zip.
3. `docs/regras-de-sessao.md`: trocar a linha "A branch de trabalho da worktree é sempre `trabalho`" por "A branch
   `trabalho`, na worktree `techdigest-fase4`, continua para o trabalho do roteiro; as melhorias seguem a seção abaixo" e
   acrescentar a seção do fim deste arquivo. `CLAUDE.md`: citar `docs/plano-melhorias.md` em "Session rules and reference"
   e numa linha de "Repo notes".
4. As duas skills, fora do git, com uma linha no `CHANGELOG.md` de cada:
   - `techdigest-retomar`: numa worktree de frente, retomar pela branch da pasta atual e por `docs/melhorias/<frente>.md`, e
     salvar o progresso nesse arquivo, não no roteiro;
   - `techdigest-rodada-modelo`: os comandos saem da worktree da frente que pediu a rodada, não só da `techdigest-fase4`.
5. Plano com a lista "Leituras minhas, para você corrigir"; com o ok, commit
   `docs: plano das melhorias em frentes paralelas`.
6. Com o ok do dono, avanço rápido da `master` (só documentos: a produção não muda e nenhuma dependência muda).
7. Na `techdigest-testes`: `git switch -c testes master`.
8. As versões da produção, para as worktrees novas não instalarem versões mais novas que as dela (até a frente 2 decidir):
   `/home/sytw/Projetos/techdigest/.venv/bin/pip freeze --exclude-editable > /tmp/techdigest-producao.txt`.
9. A `.venv` da `techdigest-testes` e as worktrees da onda 1, todas da `master`:
   `git worktree add /home/sytw/Projetos/techdigest-<nome> -b melhoria/<nome> master` para `audio`, `versoes`, `registro`,
   `ruff` e `schema`. Em cada uma (e na `techdigest-testes`): `python3.14 -m venv .venv`,
   `.venv/bin/pip install -e '.[dev]' -c /tmp/techdigest-producao.txt` e `.venv/bin/pytest -q` (667 devem passar).
10. Atualizar a tabela "Estado do plano" em `docs/plano-melhorias.md` (commit na `testes`) e, pelo chat do navegador,
    `claude/plano-melhorias.md` e `claude/andamento.md` no Projeto.

As worktrees das ondas 2 e 3 (`systemd`, `feeds`, `rodada`, `tipos`) seguem os passos 8 e 9 quando o dono abrir o chat
delas.

## Integração

A `master` segue rodando até as frentes terminarem. Por padrão, uma rodada de integração só, no fim; se o dono quiser
antecipar um grupo, o procedimento é o mesmo.

1. Frente pronta (aceite separado aprovado pelo dono): na worktree dela, com a sessão dela, `git rebase testes` e a suíte.
2. Na `techdigest-testes`: `git merge --ff-only melhoria/<nome>`, a suíte, depois da frente 4, `.venv/bin/ruff check .` e,
   depois da frente 9, `.venv/bin/pyright`.
   Se a frente mudou dependências, refazer a `.venv` da `testes` antes (pela decisão da frente 2).
3. Teste conjunto, dentro da sessão de teste e pela skill da rodada (ou pelo `scripts/rodada.py`, se a frente 7 entrou):
   - a simulação com áudio: `.venv/bin/techdigest --simular data/simulacoes/testes_AAAAMMDD --banco-origem
     /home/sytw/Projetos/techdigest/data/digest.db`;
   - `.venv/bin/python scripts/resumo_lotes.py <DD/MM> --log <pasta da simulação>/logs/techdigest.log`;
   - `.venv/bin/python scripts/checar_fidelidade.py --relatorio <relatório da simulação>`;
   - o dono ouve alguns episódios.
4. Com o ok do dono, na pasta principal: `git merge --ff-only testes`; a `.venv` de produção alinhada pela decisão da
   frente 2 (comparar as versões com as da `testes`); só a `ollama.service` com `MemoryMax=20G` é copiada para `~/.config/systemd/user`, com a sessão de teste parada
   (`systemctl --user is-active techdigest-teste.target` deve dar `inactive`); as quatro units do timer (`techdigest.service`,
   `techdigest.timer`, `techdigest-inibir.service` e `techdigest-aviso.service`) NÃO são copiadas nem ligadas pelo merge
   (decisão do dono, seção "Com o timer" de `docs/producao.md`); `daemon-reload` depois da cópia; as skills, o `CLAUDE.local.md` e o estado de produção do `CLAUDE.md`
   atualizados; as cópias `claude/CLAUDE.md` e `skills` do Projeto também. A primeira execução real depois disso é do dono.
   Depois do merge, o dono apaga a linha `RSS_FEEDS` INTEIRA do `.env` da pasta principal, nunca esvaziada: um `RSS_FEEDS=` vazio
   conta como definido e a execução termina sem coletar nenhum feed (status 0, "Nenhuma notícia entregue"). Enquanto a linha
   existir, vale ela e não o `config/feeds.txt`, com o aviso no log a cada execução. Só depois do merge: o código da `master`
   de hoje não lê o `config/feeds.txt`, e sem a linha cairia nos feeds padrão do código, que não são os que rodam. No merge,
   conferir também se as skills e o `CLAUDE.local.md` citam `RSS_FEEDS`. Depois que o dono ligar o timer, conferir a primeira execução real (`systemctl --user is-active ollama.service
   techdigest-inibir.service` dá `active` duas vezes; `systemd-inhibit --list` mostra o bloqueio) e testar o caso sem
   sessão do polkit.
   A skill `techdigest-rodada-modelo` só é trocada neste passo: a versão nova (o texto proposto em
   `docs/melhorias/07-rodada.md`) chama o `scripts/rodada.py`, que a `master` ainda não tem; a antiga fica guardada, com
   uma linha no `CHANGELOG.md` da skill. O teste conjunto do passo 3 é o primeiro uso do `rodada.py` com o modelo e do
   vigia sob carga (conferir o `vigia_memoria.log` e o `FIM`), feito com a skill antiga, ainda no lugar, e o comando do
   `rodada.py` escrito à mão.
   Na troca da `.venv` da produção (roteiro na seção "Troca da `.venv` da produção" do `docs/melhorias/02-versoes.md`), a
   `.venv` nova recebe pelo `uv sync --locked --extra dev` o `nodeenv`, o `nodejs-wheel-binaries` e o `pyright`, da frente
   9; o `ruff` já veio da frente 4. Por isso o `diff` das versões do roteiro não sai mais vazio: o esperado são exatamente
   4 linhas a mais (`nodeenv`, `nodejs-wheel-binaries`, `pyright` e `ruff`) e nenhuma versão diferente. O roteiro manda
   tratar cada linha do `diff` como uma diferença, que fica listada, e só seguir com o ok do dono.
5. `git worktree remove` das frentes integradas e as branches apagadas. O plano e o andamento registram o merge.

## Texto para `docs/regras-de-sessao.md`

```markdown
## Melhorias em frentes paralelas (desde 07/11/2026)

- Cada melhoria é uma frente, com branch `melhoria/<nome>` e worktree `/home/sytw/Projetos/techdigest-<nome>`. O plano
  está em `docs/plano-melhorias.md` e o estado de cada frente em `docs/melhorias/`.
- A sessão trabalha só na worktree e na branch da sua frente: nunca na pasta principal, na `master`, na `trabalho` ou na
  branch de outra frente.
- Só os arquivos do escopo da frente. Nenhuma mudança de estilo em massa (formatador, ordem dos imports) enquanto houver
  frente aberta.
- Nos documentos compartilhados (`CLAUDE.md`, `docs/producao.md`, este arquivo, `docs/referencia/`), só o trecho do
  assunto da frente. O estado de produção do `CLAUDE.md`, as skills e o `CLAUDE.local.md` mudam só na integração.
- Sem commit de `src/techdigest.egg-info` até a frente 2 decidir.
- A cada commit, a suíte inteira passa e a seção "Estado" do arquivo da frente é atualizada.
- Uma rodada com o modelo por vez na máquina inteira, e nenhuma durante a execução real do dono:
  `systemctl --user is-active techdigest-teste.target` deve dar `inactive` antes.
- A produção só é lida: logs e registros da pasta principal, por caminho absoluto. As pastas de medição e de rodada
  continuam em `data/agrupamento/` da pasta principal.
- A integração é só pela branch `testes`, da frente 0. A `master` recebe a `testes` por avanço rápido, com o ok do dono.
```

## Prompt inicial para o Claude Code

Para a sessão aberta na `techdigest-testes`, depois do passo 0:

```text
Frente 0 (coordenação e integração) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-testes,
branch coordenacao. Hoje é só a onda 0: preparar o terreno.
Leia docs/regras-de-sessao.md e o CLAUDE.md. O plano está no pacote techdigest-plano-melhorias-20261107.zip, na raiz desta
worktree: antes de qualquer coisa, leia de dentro dele docs/plano-melhorias.md e docs/melhorias/00-coordenacao.md.
Primeiro, só leitura: o commit da master na pasta principal, git worktree list, git status na pasta principal e na
techdigest-fase4, e systemctl --user is-active techdigest-teste.target.
Depois apresente o plano dos passos 2 a 10 da "Onda 0" do 00-coordenacao.md, com a lista "Leituras minhas, para você
corrigir", e espere a aprovação. Nada de push. A master só recebe o commit de documentos por avanço rápido, com o meu ok.
```

## Estado

- 07/11/2026: não começada.
- 07/11/2026: onda 0 concluída. Etapa seguinte: a integração, quando houver frente pronta.
  - Branch: `coordenacao` até o passo 7 (commit `64bd21b`, apagada depois); agora `testes`, nascida da `master` em
    `64bd21b`.
  - Passo 1: `master` em `0bdf41f`; a pasta principal, a `techdigest-fase4` e a `techdigest-testes` no mesmo commit e
    limpas, fora o zip solto; sessão de teste `inactive`.
  - Passo 2: pacote descompactado na raiz com `unzip -n` (11 arquivos, 57.864 bytes); zip apagado.
  - Passo 3: `docs/regras-de-sessao.md` com a linha da `trabalho` do plano, o commit na branch da worktree (a `trabalho`
    no roteiro, a da frente nas melhorias), o `pip freeze` comparado com a worktree de onde vem o avanço e a seção das
    frentes; `CLAUDE.md` com o plano em "Session rules and reference" e em "Repo notes".
  - Passo 4: skills `techdigest-retomar` e `techdigest-rodada-modelo` (fora do git), com uma linha no `CHANGELOG.md` de
    cada.
  - Passo 8: `pip freeze --exclude-editable` da produção, 60 pacotes (`edge-tts==7.3.1`, `pytest==9.1.1`).
  - Passo 9, só a `techdigest-testes`, antes do commit: `.venv` com Python 3.14.9 e as versões da produção, link
    `data/agrupamento`, 667 testes.
  - Passo 5: commit `64bd21b` (`docs: plano das melhorias em frentes paralelas`, 13 arquivos, só documentos).
  - Passo 6, com o ok do dono: `pip freeze` da pasta principal igual ao da `techdigest-testes`; avanço rápido da `master`
    (`0bdf41f..64bd21b`) e da `trabalho` na `techdigest-fase4`; as três pastas em `64bd21b`.
  - Passo 7: `testes` criada da `master`; `coordenacao` apagada.
  - Passo 9: worktrees `techdigest-audio`, `-versoes`, `-registro`, `-ruff` e `-schema`, nas branches `melhoria/<nome>`
    em `64bd21b`, cada uma com `.venv`, `pip freeze` igual ao da produção, link `data/agrupamento` (fora do `git status`)
    e 667 testes. O `pip install -e` acrescenta 10 linhas a `src/techdigest.egg-info/SOURCES.txt` em todas: fica sem
    commit até a frente 2.
  - Passo 10: este estado e a tabela "Estado do plano", commit na `testes`.
  - Decisões do dono: documentos e regras na `master`; o commit na branch da worktree e o `pip freeze` com a worktree de
    onde vem o avanço; o link `data/agrupamento` nas seis pastas; o avanço rápido da `trabalho`; a `coordenacao` apagada.
  - Pendências: `claude/plano-melhorias.md` e `claude/andamento.md` no Projeto (chat do navegador); o push da `master`
    (do dono); as worktrees das ondas 2 e 3
    quando o dono abrir o chat delas.
- 08/11/2026: frente 1 (áudio) na `testes`: `melhoria/audio` em `63ea31f`, avanço rápido de `4bce887`; `Would make no
  changes` e 695 testes, em duas execuções. Resolvidos hoje: o zip solto da `techdigest-fase4` (apagado; a cópia de `~/dumb`
  fica) e o `.env` da `techdigest-testes` (conferido pelo dono).
- 08/11/2026: frente 4 (ruff) na `testes`: `melhoria/ruff` em `a0db7a8`, avanço rápido de `3278e70`; ruff 0.17.4 só com F
  e ISC, `uv.lock` com 65 pacotes, 695 testes em duas execuções e `ruff check .` limpo. Decisão do dono: um único merge na
  `master` no fim, com todas as frentes.
- 09/11/2026: frente 6 (feeds) na `testes`: `melhoria/feeds` em `d05cb23`, avanço rápido, levou a `testes` de `121fa7b` a `d05cb23`
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
- 10/11/2026: frente 8 (schema) fechada, sem código, por decisão do dono de 10/11: a etapa 2 (o JSON Schema no `format`)
  não acontece. A medição (só leitura, sem modelo; os números estão no `08-schema.md`) leu o log da produção de 05/10 a
  07/11, com 53 inícios, os 10 relatórios da produção, as simulações e as rodadas. Só 2 execuções da produção, 05/11 (89
  itens) e 07/11 (20), rodaram com a nova tentativa do JSON incompleto, e nenhuma chamada foi refeita. Em 885 itens no
  total (491 da produção, 128 das simulações e 266 das rodadas), 1 caso: o C3.48 da regressão de 29/10, numa rodada antes
  da nova tentativa: a geração fechou o JSON com 2 das 8 chaves e derrubou o item, 21 s perdidos. A essa taxa, cerca de
  0,1 evento numa execução de 89 itens e 0,02 numa de 20. `git merge --ff-only melhoria/schema` levou a `testes` de
  `3e1045e` a `653c51f` (só `docs/melhorias/08-schema.md`, 96 inserções). `Would make no changes`, 753 testes em duas
  execuções e `ruff check .` limpo. `testes` em `653c51f` antes deste commit de documentos. A `master` e a `trabalho`
  seguem em `64bd21b`.
- Melhoria futura, depois do merge e sem segurar a integração (vista na medição da frente 8): na execução real de 05/11,
  às 09:32, uma geração falhou com `RuntimeError: Ollama respondeu HTTP 500: prediction aborted, token repeat limit reached`
  (o Ollama interrompe a geração quando detecta repetição). Uma ocorrência em cerca de 885 itens, nenhuma em simulação ou
  rodada. O código converte o erro em `RuntimeError` (`ai/llm.py:213`): só aquele item é pulado, a execução segue e o item
  volta na seguinte; não conta como `QAReprovado`. A nova tentativa do JSON incompleto não cobre esse erro.
- 11/11/2026: frente 7 (rodada) na `testes`. A branch nasceu da `testes` em `3e1045e`; como a `testes` avançou para
  `a940eb9` com a frente 8, a frente a rebaseou sobre `a940eb9`, sem conflito, e o `git range-diff` mostra os dois
  commits iguais (`=`): `293fe9f` → `101e842` (script, testes e documentos) e `34c9e64` → `ac0922e` (aceite, leituras e
  teardown dos testes de interrupção), mais o `ced5d8f` (o estado depois do rebase).
  `git merge --ff-only melhoria/rodada` levou a `testes` de `a940eb9` a `ced5d8f` (`CLAUDE.md`,
  `docs/melhorias/07-rodada.md`, `docs/referencia/scripts.md`, `scripts/rodada.py` e `tests/test_rodada.py`; sem
  `pyproject.toml`, `uv.lock` nem `docs/producao.md`). `Would make no changes`, 802 testes em duas execuções (753 mais 49
  de `tests/test_rodada.py`), `ruff check .` limpo e, depois da suíte, nenhum `tail --pid` nem `sleep 300` sobrando.
  Rodada de aceite em 10/11 às 19:33; aprovação do dono em 10/11 (hora não registrada). As pastas do aceite,
  `rodada_aceite_20261110_a` e `rodada_aceite_20261110_b`, estão em `data/agrupamento` da pasta principal; sugestão: ficam
  até o merge e depois saem, por decisão do dono. O `docs/producao.md` não mudou: a execução real à mão não usa o
  `rodada.py` por ora, e a decisão volta depois do merge. Neste commit, no item dos testes do `docs/referencia/scripts.md`,
  as duas frases desatualizadas: a do linter (desde a frente 4) e a das versões, que estão no `uv.lock` (desde a frente
  2). Fora do git, o link `data/agrupamento` da `techdigest-rodada`, como nas worktrees da onda 1. `testes` em `ced5d8f`
  antes deste commit de documentos. A `master` e a `trabalho` seguem em `64bd21b`.
- 11/11/2026: frente 9 (tipos) na `testes`. A branch nasceu da `testes` em `9c76afb` e não precisou de rebase:
  `git merge --ff-only melhoria/tipos` levou a `testes` de `9c76afb` a `93c3a77`, com os cinco commits da frente
  (`3b81457` build, `bda5035` os 21 lugares do basic, `c11e9f9` o tipo do episódio, `dce1bd6` documentos e `93c3a77` o
  "Estado"): 24 arquivos, 388 inserções e 75 remoções, sem o `config.py`. O `uv sync --locked --extra dev` instalou o
  `pyright` 1.1.414, o `nodeenv` 1.12.0 e o `nodejs-wheel-binaries` 24.19.0, e o `--check` deu `Would make no changes`;
  o `uv.lock` foi de 65 a 68 pacotes, só com inserções, e o `pyproject.toml` ganhou o `aiohttp>=3.8`, o
  `pyright[nodejs]==1.1.414` no extra `dev` e o `[tool.pyright]`. 805 testes em duas execuções (802 mais 3 de
  `tests/test_models.py`), `ruff check .` limpo e `.venv/bin/pyright` com 0 erros, rodado com o `PATH` só com a
  `.venv/bin` (o node do wheel). Cinco `# pyright: ignore` no pacote, cada um com a regra e o motivo na mesma linha
  (`ai/gpu.py:168`, `ai/maquina.py:141`, `processing/agrupamento.py:633`, `delivery/email_smtp.py:16` e
  `delivery/telegram.py:89`), e nenhum nos scripts. Fecha a pendência do `aiohttp` declarado, anotada pela frente 1 no
  `01-audio.md`. Decisão do dono de 11/11: o `.venv/bin/pyright` entra nas verificações de cada commit. Neste commit: o
  pyright na regra 6 do plano, no passo 2 da Integração e no passo 3 de "Trocar um feed" do `docs/producao.md`, e a
  troca da `.venv` da produção no passo 4 (os passos 2 e 4 no plano e no `00-coordenacao.md`). O
  `docs/regras-de-sessao.md` não muda: a regra de cada commit fala da suíte e do "Estado", sem listar o ruff. O `diff`
  das versões do roteiro do `02-versoes.md`, rodado hoje só para leitura entre a `.venv` da produção e a da `testes`,
  deu as 4 linhas a mais esperadas e nenhuma versão diferente. `testes` em `93c3a77` antes deste commit de documentos.
  A `master` e a `trabalho` seguem em `64bd21b`.
  - Em aberto: (b) a troca da `.venv` da produção e o estado de produção do `CLAUDE.md`; (c) a escuta, pelo dono, de
    alguns episódios do teste conjunto (passo 3 da Integração); (d) o merge único na `master` (passo 4).
- 11/11/2026: o "Estado" do `docs/melhorias/02-versoes.md` passa a trazer os hashes que entraram na `testes`. Escrito
  antes do rebase, ele trazia a base `64bd21b`, os commits `0e23a55`, `df67c9d` e `558391c` e 667 testes; agora traz a
  base `9aec835`, os commits `19d47e0`, `96c85a9` e `2c4c899` (conferidos com `git log 9aec835..2c4c899`) e 674 testes,
  os da `testes` depois do avanço. O `git range-diff 64bd21b..558391c 9aec835..2c4c899` mostra os três iguais (`=`):
  `0e23a55` → `19d47e0`, `df67c9d` → `96c85a9` e `558391c` → `2c4c899`. A regra de cada commit do
  `docs/regras-de-sessao.md` passa a citar o `.venv/bin/ruff check .` sem avisos e o `.venv/bin/pyright` sem erros, e a
  regra 6 do plano ganha o ruff, para as duas ficarem iguais. O item (a) do "Em aberto" de 11/11, no
  `00-coordenacao.md`, sai da lista. `testes` em `cd84f52` antes deste commit de documentos. A `master` e a `trabalho`
  seguem em `64bd21b`.
- 12/11/2026: teste conjunto (passo 3 da Integração) na `testes` em `6034c77`: a rodada `teste_conjunto_20261111`, de
  11/11, das 22:32 às 23:31, com o `scripts/rodada.py` e a skill antiga no lugar, rodada pelo dono no terminal dele (a
  permissão do Claude Code recusou o comando, que traz o `.venv/bin/techdigest` depois do `--`). Comando:
  `.venv/bin/techdigest --simular data/simulacoes/testes_20261111 --banco-origem /home/sytw/Projetos/techdigest/data/digest.db`.
  `FIM` com status 0 (58 min 35 s); o sono bloqueado pelo `systemd-inhibit` e solto no fim; `library=CUDA` no log do
  Ollama e o modelo com 27 de 31 camadas na GPU; memória disponível mínima de 17.393 MiB (17,0 GiB), longe dos 3 GiB do
  vigia; no fim, `techdigest-teste.target` e `ollama.service` `inactive`, nenhum processo da rodada sobrando e a trava
  do modelo livre. A coleta usou o `RSS_FEEDS` do `.env`, com o aviso no log, como previsto no passo 4: os 9 feeds do
  log são os do `config/feeds.txt`, na mesma ordem, e nenhum ficou fora. `scripts/resumo_lotes.py`: 20 entregues, 1
  reprovado pelo QA, 1 descartado (texto curto), 1 filtrado (ofertas, `/achados/`), nenhum abandonado, 2 erros e
  nenhuma falha de entrega; 26,3 tok/s em média (mínimo 20,4), CPU até 87 °C, GPU até 65 °C. No registro, 23 episódios
  gerados e 22 aprovados pelo QA (12 na primeira versão, 9 depois da revisão do roteiro e 1 depois da correção do
  resumo); o reprovado ficou, depois da revisão do roteiro, com o analista em 197 palavras, abaixo das 204. Os 2 erros
  são de áudio: dois episódios aprovados (o PS5, do Canaltech, e a palestra da Ufes) caíram no Edge-TTS com
  `NoAudioReceived`, que não tem nova tentativa por decisão do dono de 08/11 (`01-audio.md`); nenhum turno teve nova
  tentativa na rodada. No log da produção (05/10 a 07/11) há um só `NoAudioReceived`, em 07/10, com a síntese de um
  turno por vez. `scripts/checar_fidelidade.py --relatorio`: nenhum número sem fonte; 7 nomes próprios sem fonte em 5
  episódios ("Congresso" e os séculos "XX" e "XIX"; "China"; "Partido dos Trabalhadores de Pernambuco"; "Rio Grande do
  Sul"; "Brasil"), 1 número arredondado (no PS5, não entregue) e 2 nomes com fonte só depois do corte; o relatório está
  em `data/agrupamento/fidelidade_20261112-060624.txt` da pasta principal. Áudio, do `Vozes:` ao `✅` (a medição da
  frente 1, adaptada à entrega em arquivo): 20 s por item em média (13 a 28 s), contra 44 s na execução real de 07/11;
  1,89 s por turno (212 turnos), contra 4,0 s; 5,4 s por minuto de episódio, contra 10,9 s. A hora e a rede não são as
  de 07/11 (01h); no aceite da frente 1, a `master` já fazia 1,4 s por turno. Episódios de 3,7 min em média (2,2 a
  4,4 min), contra 4,0 min em 07/11. Para o dono ouvir, em `data/simulacoes/testes_20261111/entregas/` da
  `techdigest-testes`: o 04 (Nintendo, o mais curto, 2,2 min e 7 turnos), o 05 (QLED, o mais longo, 4,4 min) e o 11
  (tradução do Linux, 10 trocas de personagem em 3,3 min). O item (c) do "Em aberto" de 11/11, acima, fica só com a
  escuta do dono. `testes` em `6034c77` antes deste commit de documentos. A `master` e a `trabalho` seguem em `64bd21b`.
- 18/11/2026: etapa 3 feita (a preparação do merge); etapa: merge preparado. Do "Em aberto" de 11/11: (c) a escuta do
  dono achou em 17/11 o ruído no começo dos episódios no player do celular, corrigido no `1b7a308`, direto na `testes`
  (o mp3 sem a marca ID3 e sem o quadro Xing/Info, ver o `01-audio.md`); (b) o estado de produção do `CLAUDE.md` vai
  neste commit, e a troca da `.venv` da produção, com (d) o merge, fica com o script do dono,
  `data/agrupamento/fechamento_20261118/fechamento.sh` da pasta principal. Verificação na `testes` em `1b7a308`, com
  estes documentos fora do commit: 806 testes, `ruff check .` limpo, `.venv/bin/pyright` com 0 erros, `Would make no
  changes`; o `diff` das versões entre a `.venv` da produção e a da `testes` dá só as 4 linhas a mais esperadas; o
  `diff -u` da `ollama.service` instalada contra a `deploy/systemd/` dá só o `MemoryMax=20G` e o comentário dele.
  O que mudou neste commit e nas skills está no registro de 18/11 do `docs/plano-melhorias.md`. A `master` e a
  `trabalho` seguem em `64bd21b` até o script rodar.
- 19/11/2026: etapa: encerrada. O "Em aberto" de 11/11 está vazio: (b) e (d) foram feitos pelo `fechamento.sh` em
  18/11 (fim às 20:46), e (c) foi feito em 17/11.
  - O que o script fez:
    - a `master` e a `trabalho` foram para `17b4390` por avanço rápido;
    - a `.venv` da produção passou a ser a do uv (edge-tts 7.3.1), e o `diff` das versões deu só as 4 linhas esperadas;
    - 806 testes passaram na `testes` e na pasta principal;
    - `MemoryMax=21474836480` na `ollama.service`;
    - a skill `techdigest-rodada-modelo` foi trocada.
  - Depois do script, o dono:
    - fez o push (`origin/master` em `17b4390`) e tirou a linha `RSS_FEEDS` do `.env`;
    - refez pelo lock a `.venv` da `techdigest-fase4` (a do pip ficou lá) e a da pasta principal, e apagou a
      `.venv.pip-20261118` da pasta principal.
  - O estado de produção do `CLAUDE.md` muda com isso: a `.venv` do pip apagada, os feeds pelo `config/feeds.txt` e
    a execução de 18/11.
  - A primeira execução real depois do merge foi em 18/11, das 21:11 às 22:05 (54 min):
    - 20 de 20 entregues e aprovados, 6 deles depois de uma correção;
    - 3 descartados, 1 filtrado, nenhum erro;
    - a coleta pelo `config/feeds.txt`, sem o aviso do `RSS_FEEDS`, com os 9 feeds na ordem do arquivo.
  - O áudio:
    - 20 s por item, 1,9 s por turno e 5,5 s por minuto de episódio, contra 44 s, 4,0 s e 10,9 s em 07/11;
    - trocas de personagem de 0,77 e 0,78 s em média nos episódios 01 e 20;
    - os 20 mp3 sem `ID3` e sem `Xing`/`Info`.
  - Os números completos estão no registro de 19/11 do `docs/plano-melhorias.md`, e as saídas em
    `data/agrupamento/fechamento_20261118/medicao/` da pasta principal.
  - O "Estado" do `01-audio.md`, do `03-registro.md`, do `07-rodada.md` e do `09-tipos.md` diz "na `master`", e a
    tabela "Estado do plano" também.
  - A limpeza das worktrees e das branches `melhoria/*` vem depois deste commit. `testes` em `17b4390` antes dele.
- 19/11/2026, depois do `e1e4194`: limpeza feita e as branches no commit do encerramento.
  - O dono levou a `master` a `e1e4194` por avanço rápido e fez o push (`origin/master` em `e1e4194`). Na pasta
    principal, o `uv sync --locked --check --extra dev` deu `Would make no changes`. Depois ele levou a `trabalho` ao
    mesmo commit, e a `techdigest-fase4` também dá `Would make no changes`.
  - A limpeza:
    - as 9 worktrees das frentes (`techdigest-audio`, `-versoes`, `-registro`, `-ruff`, `-systemd`, `-feeds`,
      `-rodada`, `-schema` e `-tipos`) saíram com `git worktree remove`, cada uma com `git status` limpo antes. Juntas
      tinham 2.339 MiB, só de `.venv`, caches e o link `data/agrupamento`, desfeito com `unlink` antes da remoção;
    - as 9 branches `melhoria/*` saíram com `git branch -d`, sem nenhuma recusa;
    - saíram também as rodadas `rodada_aceite_20261110_a` e `_b`, as `falas/` de `pausas_20261108/C`, `D`, `E` e `F`
      (uns 9 KiB) e a `.venv.pip-20261108` da `techdigest-testes` (167 MiB).
  - Continuam: as worktrees `techdigest-testes` (branch `testes`) e `techdigest-fase4` (branch `trabalho`), a
    `.venv.pip-20261118` da `techdigest-fase4` e as branches `agrupamento-fase1` a `agrupamento-fase4`.
  - Depois da limpeza, 806 testes passam na `testes`.
  - A frente 0 não tem pendências. O que resta é uma decisão do dono, fora da frente: ligar o timer
    (`docs/producao.md`, "Com o timer").

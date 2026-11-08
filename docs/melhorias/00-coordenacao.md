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
2. Na `techdigest-testes`: `git merge --ff-only melhoria/<nome>`, a suíte e, depois da frente 4, `.venv/bin/ruff check .`.
   Se a frente mudou dependências, refazer a `.venv` da `testes` antes (pela decisão da frente 2).
3. Teste conjunto, dentro da sessão de teste e pela skill da rodada (ou pelo `scripts/rodada.py`, se a frente 7 entrou):
   - a simulação com áudio: `.venv/bin/techdigest --simular data/simulacoes/testes_AAAAMMDD --banco-origem
     /home/sytw/Projetos/techdigest/data/digest.db`;
   - `.venv/bin/python scripts/resumo_lotes.py <DD/MM> --log <pasta da simulação>/logs/techdigest.log`;
   - `.venv/bin/python scripts/checar_fidelidade.py --relatorio <relatório da simulação>`;
   - o dono ouve alguns episódios.
4. Com o ok do dono, na pasta principal: `git merge --ff-only testes`; a `.venv` de produção alinhada pela decisão da
   frente 2 (comparar as versões com as da `testes`); as units copiadas para `~/.config/systemd/user` e `daemon-reload` se a
   frente 5 entrou (o timer continua com o dono); as skills, o `CLAUDE.local.md` e o estado de produção do `CLAUDE.md`
   atualizados; as cópias `claude/CLAUDE.md` e `skills` do Projeto também. A primeira execução real depois disso é do dono.
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

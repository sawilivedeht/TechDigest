# Frente 4: ruff

Arquivo no Projeto: `claude/frentes/04-ruff.md` · no repositório: `docs/melhorias/04-ruff.md`

| | |
|---|---|
| Branch | `melhoria/ruff` |
| Worktree | `/home/sytw/Projetos/techdigest-ruff` |
| Onda | 1 |
| Depende de | nada |
| Conflita com | frente 1 (linha 55 do `tts.py`; resolvido: a correção já estava na `testes`); frentes 2 e 9 no `pyproject.toml` |

## Objetivo

Um linter configurado que pega erro de verdade, sem mudar o estilo do código.

## Por que (ruff 0.16, rodado na `master` em 07/11)

- Com as regras padrão do ruff, o repositório tem 129 avisos, 56 deles no pacote, e nenhum é bug: ordem dos imports, datas
  sem fuso, os 13 `except Exception` que existem de propósito e o código morto do e-mail.
- O valor é preventivo. As listas fechadas do QA escritas como tuplas de textos (as formas de `ai/verbos.py`, por exemplo)
  aceitam uma vírgula esquecida sem erro nenhum: `"afirmam" "afirmou"` vira `"afirmamafirmou"`, e a regra muda em
  silêncio. A regra ISC004 pega isso; foi testada num exemplo.
- O formatador reescreveria 61 dos 67 arquivos: fica de fora.

## Configuração recomendada

```toml
[tool.ruff.lint]
select = ["F", "ISC"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ISC004"]     # textos longos partidos de propósito
"scripts/**" = ["ISC004"]
```

O ruff lê o `requires-python` do `pyproject.toml`. No extra `dev`, o `ruff` com a versão fixa (a instalada na hora), para as
regras não mudarem sozinhas.

Com essa configuração, a `master` de 07/11 tinha 4 avisos; 3 são corrigidos nesta frente:
- `src/techdigest/delivery/email_smtp.py:5`: `re` importado e não usado;
- `src/techdigest/delivery/email_smtp.py:31`: `html` atribuída e não usada (o `send_digest_email` não faz nada);
- `src/techdigest/audio/tts.py:55`: f-string sem variável (`f"anullsrc=r=24000:cl=mono"`): fora desta frente, porque já
  estava corrigido na `testes` (`d8dc640`, da frente 1);
- `scripts/refazer_qa.py:27`: `dataclasses.field` importado e não usado.

## Decisões do dono

- As regras: só `F` e `ISC` (recomendado) ou mais. O `B` (bugbear) traz uns 40 avisos, 35 deles de `zip()` sem `strict=`,
  e 3 falsos positivos de closure no `scripts/testar_episodio.py`.
- O `email_smtp.py`: corrigir as duas linhas (recomendado agora) ou apagar o módulo, que o `CLAUDE.md` descreve como nunca
  terminado (aí entram também o `delivery/__init__.py` e a documentação).

## Aceite separado

- `.venv/bin/ruff check .` sem avisos.
- A suíte inteira.
- Uma vírgula tirada de propósito de uma tupla de `ai/verbos.py` faz o ruff reclamar; a mudança é desfeita.

## Documentação

- `CLAUDE.md`, "Commands": `.venv/bin/ruff check .`. A frase "There is no linter and no formatter configured" passa a dizer
  que há linter (só `F` e `ISC`) e não há formatador.
- Este arquivo.

Ideia para depois da integração: um hook do Claude Code (no `.claude/settings.json`) que roda o `ruff check` nos arquivos
editados.

## Prompt inicial para o Claude Code

```text
Frente 4 (ruff) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-ruff, branch melhoria/ruff.
Leia docs/plano-melhorias.md, docs/melhorias/04-ruff.md e docs/regras-de-sessao.md.
Primeiro, só leitura: instale o ruff na .venv desta worktree, rode-o com as regras padrão e com a configuração recomendada
do arquivo da frente (sem gravar nada no pyproject.toml ainda) e confira os números de lá. Nada de --fix e nada de
formatador.
Depois me pergunte as duas decisões do arquivo da frente (as regras e o email_smtp.py) e apresente o plano, com a lista
"Leituras minhas, para você corrigir". Espere a aprovação. Nenhuma mudança de estilo fora dos 4 avisos.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/04-ruff.md atualizada.
```

## Estado

- 07/11/2026: não começada.
- 08/11/2026: aceite separado, esperando o ok do dono. Branch `melhoria/ruff`, um commit sobre `64bd21b` (o hash fica com
  o chat do navegador). 667 testes passam.
  - Decisões do dono (08/11): só `F` e `ISC`; o `email_smtp.py` fica, com as duas linhas corrigidas.
  - Feito: o `ruff==0.17.4` no extra `dev` e o `[tool.ruff.lint]` no `pyproject.toml`, como na configuração recomendada;
    os 4 avisos corrigidos, uma linha cada (o corpo do `send_digest_email` virou só a docstring; o `datetime` continua em
    uso no `render_html`, e nenhum F401 novo apareceu); no `CLAUDE.md`, a linha `.venv/bin/ruff check .`, a frase do
    linter e o comentário do extra `dev`.
  - Números do ruff 0.17.4 (o "Por que" traz os do 0.16, de 07/11): com as regras padrão, 111 avisos (o 0.16 dava 129),
    46 no pacote (o 0.16 dava 56), 11 em `scripts/` e 54 em `tests/`; os 13 `BLE001` do pacote são os 13
    `except Exception`. Com a configuração recomendada, exatamente os 4 avisos. O `B` traria 39 a mais: 35 `B905`, 3
    `B023` em `scripts/testar_episodio.py:433-434` e 1 `B020` em `src/techdigest/ai/lados.py:440`, os 4 últimos falsos
    positivos. O formatador não foi rodado, nem com `--check`: o "61 dos 67 arquivos" não foi conferido.
  - Os 22 `ISC004` que o `per-file-ignores` esconde (20 em `tests/`, 2 em `scripts/`) foram conferidos um por um: todos
    são textos longos partidos de propósito, nenhum é vírgula esquecida.
  - Prévia do aceite, antes de editar, numa cópia de `ai/verbos.py` passada pela entrada padrão: sem a vírgula do meio da
    linha 25, `ISC001` e `ISC004`; sem a vírgula do fim da linha 73, `ISC004`.
  - Aceite separado (08/11): o `pyproject.toml` lido pelo `tomllib`; `.venv/bin/ruff check .`, só com o `pyproject.toml`,
    sem avisos; `.venv/bin/pytest`, 667 passam; a vírgula da linha 25 de `ai/verbos.py` tirada de verdade dá `ISC001` e
    `ISC004`, e a mudança desfeita deixa o `git diff --exit-code` do arquivo em 0.
  - Revisão do dono (08/11): a frase do linter no `CLAUDE.md` ficou mais curta, sem o exemplo do `ISC`, no mesmo commit
    (amend); `ruff check .` e a suíte rodados de novo.
  - Pendências: na `testes`, o `uv.lock` é refeito com o `ruff` do extra `dev` (esta frente não rodou `pip install` nem
    `uv lock`); antes do rebase sobre a `testes`, `git restore src/techdigest.egg-info` (o `SOURCES.txt` já vinha
    modificado antes da sessão e ficou fora do commit); no rebase, a frente 1 mantém a linha 55 do `tts.py` sem o `f`, e
    a linha do extra `dev` pode conflitar com a frente 2; depois da integração, o hook do Claude Code com o
    `ruff check`.
- 08/11/2026, rebase sobre a `testes` (`3278e70`): pronta para integração; o avanço rápido da `testes` é da frente 0.
  Branch `melhoria/ruff`: `bc827ea` (o `chore(ruff)`, antes `15b4367`) e o commit deste registro. 695 testes passam, em
  duas rodadas: são os 695 da `testes` (667 da `master`, 7 da frente 3 e 21 da frente 1), porque esta frente não muda
  nenhum teste.
  - O `tts.py` saiu desta frente: o `f` sem variável da linha 55 já estava corrigido na `testes`, pelo `d8dc640`
    (`feat(audio): sintetiza turnos em paralelo e gera as pausas uma vez`, da frente 1, na `melhoria/audio`), achado com
    `git log testes -S'f"anullsrc=r=24000:cl=mono"'`. O rebase mesclou o `tts.py` sozinho, e o commit desta frente não o
    toca mais. São 3 avisos corrigidos aqui, e não 4: o `import re` e a atribuição `html` do `email_smtp.py` e o `field`
    do `refazer_qa.py`.
  - Conflito só no `CLAUDE.md`, resolvido com o ok do dono: ficam as duas linhas do `uv sync` da frente 2, com "pytest and
    ruff" no comentário de `uv sync --locked --extra dev`; a frase do linter troca a "There is no linter and no formatter
    configured." da `testes`, e o trecho do `requirements.txt` fica no item "Versions" da frente 2. O `pyproject.toml` não
    conflitou: a `testes` não o mudou.
  - O `uv.lock` entrou no próprio `chore(ruff)`, em amend, como manda a regra da frente 2: refeito pelo `uv lock` (uv
    0.13.7), ganhou só o `ruff 0.17.4` (64 pacotes antes, 65 depois, nenhum saiu). A `.venv` foi refeita pelo lock
    (`uv sync --locked --extra dev`; a antiga, feita pelo pip, ficou em `.venv.pip-20261108`), e `uv lock --check` e
    `uv sync --locked --check --extra dev` (`Would make no changes`) passam. O `src/techdigest.egg-info` saiu do git na
    `testes`; o `uv sync` o recria no disco, ignorado pelo `.gitignore`.
  - Aceite de novo: `.venv/bin/ruff check .` sem avisos; a suíte, 695 em duas rodadas; a vírgula da linha 25 de
    `ai/verbos.py` tirada de verdade dá `ISC001` e `ISC004`, e o `git checkout --` do arquivo deixa o
    `git diff --exit-code` em 0.
  - Pendências: o avanço rápido da `testes` (frente 0), com o `ruff check .` depois de cada frente que entrar; apagar a
    `.venv.pip-20261108` quando o dono quiser; depois da integração, o hook do Claude Code com o `ruff check`. As
    pendências da entrada anterior foram resolvidas nesta.

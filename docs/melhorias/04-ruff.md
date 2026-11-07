# Frente 4: ruff

Arquivo no Projeto: `claude/frentes/04-ruff.md` · no repositório: `docs/melhorias/04-ruff.md`

| | |
|---|---|
| Branch | `melhoria/ruff` |
| Worktree | `/home/sytw/Projetos/techdigest-ruff` |
| Onda | 1 |
| Depende de | nada |
| Conflita com | frente 1 (linha 55 do `tts.py`); frentes 2 e 9 no `pyproject.toml` |

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

Com essa configuração, sobram 4 avisos para corrigir:
- `src/techdigest/delivery/email_smtp.py:5`: `re` importado e não usado;
- `src/techdigest/delivery/email_smtp.py:31`: `html` atribuída e não usada (o `send_digest_email` não faz nada);
- `src/techdigest/audio/tts.py:55`: f-string sem variável (`f"anullsrc=r=24000:cl=mono"`); a frente 1 faz a mesma correção;
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

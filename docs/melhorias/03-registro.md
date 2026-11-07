# Frente 3: registro

Arquivo no Projeto: `claude/frentes/03-registro.md` · no repositório: `docs/melhorias/03-registro.md`

| | |
|---|---|
| Branch | `melhoria/registro` |
| Worktree | `/home/sytw/Projetos/techdigest-registro` |
| Onda | 1 |
| Depende de | nada |
| Conflita com | nada |

## Objetivo

O registro de cada execução nunca fica cortado, mesmo quando o processo morre no meio da gravação.

## Por que

- `RegistroDaExecucao.gravar()` (`src/techdigest/registro.py`) reescreve `amostra.json` e `relatorio_<data-hora>.json` no
  lugar, com `write_text`, depois de cada item. O `item()` grava o JSON de cada episódio do mesmo jeito.
- Se o processo morrer durante a gravação (OOM, o limite de 4 h da unit, um sinal), o arquivo fica cortado, justamente na
  execução que deu errado. O `scripts/checar_fidelidade.py --relatorio` e o `scripts/refazer_qa.py` leem esses arquivos.

## Escopo

- `src/techdigest/registro.py`: uma função `_gravar_atomico(caminho, texto)` que grava num arquivo temporário na mesma
  pasta e o troca pelo definitivo com `os.replace`, que é atômico no mesmo sistema de arquivos. Usada no `gravar()` (os
  dois arquivos) e no `item()` (o JSON do episódio). Opcional: `flush` e `os.fsync` antes da troca, contra queda de
  energia; custa pouco em umas 20 gravações por execução.
- `tests/test_registro.py`.

Fora do escopo (pode virar outra frente, se o dono quiser): um bloco `execucao` no relatório, com o desfecho da execução e
as métricas da máquina, e o `scripts/resumo_lotes.py` lendo o JSON em vez do log.

## Testes

- Depois do `gravar()`, nenhum arquivo temporário sobra e os dois JSON são válidos.
- Uma falha no meio da gravação (o `os.replace` ou a escrita levantando erro) deixa o arquivo anterior inteiro.
- O conteúdo gravado é o mesmo de antes da mudança.

## Aceite separado

- A suíte inteira.
- Um relatório gerado pelos testes antes e depois da mudança tem o mesmo conteúdo, fora a data de criação.

## Documentação

- `CLAUDE.md`, "Architecture", passo 7: o relatório é reescrito de forma atômica.
- Este arquivo.

## Prompt inicial para o Claude Code

```text
Frente 3 (registro) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-registro, branch
melhoria/registro. Leia docs/plano-melhorias.md, docs/melhorias/03-registro.md e docs/regras-de-sessao.md.
Primeiro, só leitura: src/techdigest/registro.py inteiro, tests/test_registro.py e quem lê os arquivos do registro
(scripts/checar_fidelidade.py e scripts/refazer_qa.py). Depois apresente o plano da gravação atômica, com a lista
"Leituras minhas, para você corrigir", e espere a aprovação.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/03-registro.md atualizada.
```

## Estado

- 07/11/2026: não começada.

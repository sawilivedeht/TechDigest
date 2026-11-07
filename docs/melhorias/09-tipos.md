# Frente 9: tipos

Arquivo no Projeto: `claude/frentes/09-tipos.md` · no repositório: `docs/melhorias/09-tipos.md`

| | |
|---|---|
| Branch | `melhoria/tipos` |
| Worktree | `/home/sytw/Projetos/techdigest-tipos` |
| Onda | 3, depois das outras integradas; opcional |
| Depende de | as frentes que mexem no mesmo código já integradas (1, 3, 4, 6) |
| Conflita com | quase todas, por isso é a última |

## Objetivo

Um tipo para o episódio, para o verificador de tipos conferir as chaves que os consumidores leem. É a de menor retorno das
nove: o dono decide se faz.

## Por que

- O pyright, no modo standard, acha 18 erros na `master` de 07/11, e nenhum é bug: são lugares em que a lógica do código
  garante o que o verificador não enxerga. No pacote são 8: `main.py:49` (três vezes), `ai/gpu.py:168`, `ai/llm.py:401`,
  `ai/maquina.py:141`, `ai/orcamento.py:84` e `processing/agrupamento.py:633`; os outros 10 estão nos scripts de
  diagnóstico. As bibliotecas não estavam instaladas na medição, então o número real pode ser maior.
- O episódio circula como `dict`, e o verificador não confere chave por chave. É aí que um tipo ajuda: `ai/qa.py`,
  `audio/tts.py` e `delivery/telegram.py` leem as 8 chaves.

## Escopo

- `TypedDict` para o episódio (`Episodio`, com `Personagem` e `Turno`), em `src/techdigest/models.py`; as funções que
  devolvem ou recebem o episódio anotadas com ele.
- pyright no extra `dev` e `[tool.pyright]` com `typeCheckingMode = "basic"`. Os 15 erros do modo basic corrigidos na
  anotação ou marcados com `# pyright: ignore[regra]` e o motivo.
- Nenhuma mudança de comportamento. O pydantic não entra: duplicaria a validação que o código já faz (o QA trata o JSON
  malformado do episódio, e `ai/lados.py` e `processing/agrupamento.py` validam as respostas deles).

## Aceite separado

- `pyright` sem erros no modo basic.
- A suíte inteira.

## Prompt inicial para o Claude Code

```text
Frente 9 (tipos) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-tipos, branch melhoria/tipos.
Leia docs/plano-melhorias.md, docs/melhorias/09-tipos.md e docs/regras-de-sessao.md.
Primeiro, só leitura: instale o pyright na .venv desta worktree, rode-o nos modos basic e standard e compare com os
números do arquivo da frente; liste quem lê e quem escreve o episódio (as 8 chaves). Nada de mudar código ainda.
Depois apresente o plano, com a lista "Leituras minhas, para você corrigir", e espere a aprovação.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/09-tipos.md atualizada.
```

## Estado

- 07/11/2026: não começada (opcional; espera a decisão do dono).

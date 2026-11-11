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
- 11/11/2026: em implementação. Branch `melhoria/tipos`, nascida da `testes` em `9c76afb` (frentes 1 a 7 integradas).
  - Medição (só leitura, pyright 1.1.414): a `master` de 07/11, sem as bibliotecas, só `src` e `scripts` e sem os
    imports não resolvidos, reproduz os 15 erros do basic e os 18 do standard deste arquivo. Na `testes`, nas mesmas
    condições, 20 e 23 (os 5 a mais são do `scripts/rodada.py`, da frente 7). Com as bibliotecas da `.venv`, 63 e 66: 48
    no pacote, em 8 lugares (41 deles no `create(**kwargs)` da OpenAI, `ai/llm.py:403`, pelo mesmo `kwargs` do
    `llm.py:401`; mais o `llm.py:280` e o `email_smtp.py:16`, o `settings.recipients` do código dormente), e 15 nos
    scripts, em 13 lugares. A diferença entre basic e standard são os 3 `possibly unbound` do `main.py:49`. Os testes,
    fora do escopo, têm 57.
  - Decisões do dono (11/11): plano aprovado; `pyright[nodejs]` no extra `dev`, em vez do node do sistema; nos scripts,
    `cast` nos 13 lugares e nenhum `ignore`, com um comentário em cada `cast` que só tira um `None`; no
    `testar_agrupamento.py`, a anotação `Veredito.resposta: dict | None` no pacote, mais o `cast` do `motivo`; no pacote,
    `ignore` com a regra e o motivo nos 4 lugares que não se resolvem na anotação (`gpu.py:168`, `maquina.py:141`,
    `agrupamento.py:633`, `email_smtp.py:16`); o `ItemEntregue`, o `parse_json(text: str | None)` e o docstring do
    `models.py` como propostos.
  - Commit 1 (build): `aiohttp>=3.8` nas dependências (a pendência da frente 1: o `tts.py` o importa direto; o mínimo
    é o que o edge-tts 7.3.1 pede), `pyright[nodejs]==1.1.414` no extra `dev`, `[tool.pyright]` (basic, `src` e
    `scripts`, a `.venv` da pasta) e o comentário do `tts.py` sobre o aiohttp. O `uv lock` levou o lock de 65 a 68
    pacotes: entram `pyright` 1.1.414, `nodeenv` 1.12.0 e `nodejs-wheel-binaries` 24.19.0; nenhuma versão muda, o
    aiohttp segue em 3.14.5, e o diff do lock só tem inserções (47). `uv sync --locked --check --extra dev`: `Would make
    no changes`. Os 60 pacotes da `.venv` da produção (o `freeze` dela sem o `pip` e o `techdigest`) estão todos na
    `.venv` da frente, nas mesmas versões. O pyright roda com o `PATH` só com a `.venv/bin` (usa o node do wheel). Pela
    configuração, `.venv/bin/pyright` dá os mesmos 63 erros da medição. 802 testes passam; `ruff check .` sem avisos.
  - Commit 2 (os 21 lugares do basic): `.venv/bin/pyright` com 0 erros, 0 avisos.
    - Pacote, na anotação: `kwargs: dict[str, Any]` no `llm.py` (o 401 e os 41 do 403), `parse_json(text: str | None)`
      (o corpo já trata `None` como resposta vazia: `ValueError`, como hoje), `cast(list[float], alvos)` no
      `orcamento.py:84` e `Veredito.resposta: dict | None` no `agrupamento.py:760` (só vem do `chat_json` ou é `None`).
    - Pacote, `# pyright: ignore[regra]` com o motivo na mesma linha: `gpu.py:168` (`reportOptionalMemberAccess`),
      `maquina.py:141` (`reportArgumentType`), `agrupamento.py:633` (`reportReturnType`) e `email_smtp.py:16`
      (`reportAttributeAccessIssue`). Conferido numa cópia sem os 4 `ignore`: o pyright acha no pacote exatamente esses
      4 erros, e nenhum outro.
    - Scripts, os 13 lugares com `cast` e nenhum `ignore`. Os `cast` que só tiram um `None` levam o motivo na linha:
      além dos 4 combinados (`rodada.py:437`, `452` e `589`, `checar_fidelidade.py:646`), também `rodada.py:196`
      (`comando`), `checar_fidelidade.py:557` (o `get` do `max`) e `testar_agrupamento.py:476` (`de_outra`), e o do
      `orcamento.py:84`, no pacote. Os outros 4 (`checar_fidelidade.py:446` e `565`, `testar_episodio.py:569`,
      `testar_agrupamento.py:403`) ficam sem comentário: o `isinstance` da mesma linha é o motivo.
    - No standard, sobram os 3 `possibly unbound` do `main.py:49`, fora do aceite.
    - 802 testes passam; `ruff check .` sem avisos.
  - Pendências: commits 3 (`models.py` e as anotações do episódio) e 4 (documentos); no merge, a `.venv` da produção
    ganha os 3 pacotes novos pelo `uv sync --locked --extra dev`.

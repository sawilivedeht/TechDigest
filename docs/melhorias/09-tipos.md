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
- 11/11/2026: aceite separado, esperando o ok do dono. Branch `melhoria/tipos`, nascida da `testes` em `9c76afb`
  (frentes 1 a 7 integradas), com quatro commits: `3b81457` (build), `bda5035` (os 21 lugares do basic), `c11e9f9` (o
  tipo do episódio) e `dce1bd6` (documentos). 805 testes passam; `.venv/bin/pyright` com
  0 erros; `ruff check .` sem avisos.
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
  - Commit 1, `3b81457` (build): `aiohttp>=3.8` nas dependências (a pendência da frente 1: o `tts.py` o importa direto; o mínimo
    é o que o edge-tts 7.3.1 pede), `pyright[nodejs]==1.1.414` no extra `dev`, `[tool.pyright]` (basic, `src` e
    `scripts`, a `.venv` da pasta) e o comentário do `tts.py` sobre o aiohttp. O `uv lock` levou o lock de 65 a 68
    pacotes: entram `pyright` 1.1.414, `nodeenv` 1.12.0 e `nodejs-wheel-binaries` 24.19.0; nenhuma versão muda, o
    aiohttp segue em 3.14.5, e o diff do lock só tem inserções (47). `uv sync --locked --check --extra dev`: `Would make
    no changes`. Os 60 pacotes da `.venv` da produção (o `freeze` dela sem o `pip` e o `techdigest`) estão todos na
    `.venv` da frente, nas mesmas versões. O pyright roda com o `PATH` só com a `.venv/bin` (usa o node do wheel). Pela
    configuração, `.venv/bin/pyright` dá os mesmos 63 erros da medição. 802 testes passam; `ruff check .` sem avisos.
  - Commit 2, `bda5035` (os 21 lugares do basic): `.venv/bin/pyright` com 0 erros, 0 avisos.
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
  - Decisão do dono (11/11, commit 2 aprovado): ficam os 8 comentários dos `cast` de `None`; os 4 `cast` com
    `isinstance` na mesma linha ficam sem comentário.
  - Commit 3, `c11e9f9` (o tipo do episódio): `Personagem`, `Turno`, `Episodio` e `ItemEntregue` no `src/techdigest/models.py`,
    depois do `Article`, que já estava lá (as 14 linhas dele não mudam; entram a docstring do módulo, com o texto
    aprovado sobre o `cast`, e o import do `typing`). No `ItemEntregue`, `url`, `source` e `vozes` obrigatórias,
    `outras_fontes` e `tambem_noticiaram` `NotRequired`.
    - Anotados: `summarizer._qa`, `_com_os_papeis`, `_corrigir_titulo`, `_corrigir_resumo`, `_revisar_roteiro`,
      `_revisar` e `process`; as 20 funções do `qa.py` que recebem o episódio e o `palavras_por_personagem`, todas sem
      mudar o corpo; `tts.atribuir_vozes`, `_sintetizar_turnos` e `gerar_podcast`; `deliver_item`, `_render_item`,
      `send_item_telegram`, `_enviar_audio` e `arquivo.entregar_item`; e, nos scripts, as três funções do
      `testar_episodio.py` que recebem o episódio do `process`.
    - `cast(Episodio, ...)` onde o JSON do modelo vira episódio: a geração em `process` (as duas chamadas) e a revisão
      completa em `_revisar`; nos scripts, as duas chamadas ao `qa` do `checar_fidelidade.py`, que lê o episódio de um
      JSON gravado e segue com `dict`. `cast(ItemEntregue, result)` no pipeline, antes das atribuições, no mesmo dict.
    - Um `ignore` novo, por causa do tipo: `telegram.py:89` (`reportTypedDictNotRequiredAccess`), o
      `it["tambem_noticiaram"]` dentro do `if it.get("tambem_noticiaram")`, que o pyright não estreita.
    - Continuam `dict`: o `registro.item`, o `llm.parse_json`/`chat_json`, o `email_smtp` (dormente) e o episódio dos
      scripts que leem JSON.
    - `tests/test_models.py` (3 testes): as chaves e os tipos do `Episodio`, do `Personagem` e do `Turno` contra o
      `SCHEMA` e o `REQUIRED_KEYS`, e as chaves do `ItemEntregue`.
    - Prova por mutação, desfeita com o `cmp` igual ao original: `it['resumo']` no lugar de `it['resumo_didatico']` no
      `_render_item` dá 1 erro no pyright (`"resumo" is not a defined key in "ItemEntregue"`) e 15 testes quebrados
      (`test_pipeline.py` e `test_simulacao.py`); sem `fontes_citadas` no `Episodio`, os 3 testes do `test_models.py`
      falham e o pyright dá 2 erros no `qa.py:612`.
    - `.venv/bin/pyright`: 0 erros. 805 testes passam (802 e os 3 novos); `ruff check .` sem avisos.
  - Decisão do dono (11/11, commit 3 aprovado): ficam o `ignore` do `telegram.py:89` e os dois `cast` do
    `checar_fidelidade.py`.
  - Commit 4 (documentos): no `CLAUDE.md`, só o trecho do assunto: o `.venv/bin/pyright` em "Commands", o pyright no
    comentário do `uv sync` e uma frase depois da do linter, e o `models.py` no parágrafo do contrato de saída (o estado
    de produção não muda); no `docs/referencia/contrato-de-saida.md`, os tipos do `models.py` e a frase de que são só
    anotações; e este arquivo.
  - Os 5 `ignore` do pacote, cada um com a regra e o motivo na mesma linha (nos scripts não há nenhum):
    - `ai/gpu.py:168`, `reportOptionalMemberAccess`: `` `inicio` é uma linha em que o _CARGA achou ``.
    - `ai/maquina.py:141`, `reportArgumentType`: `com o modelo local e sem log, a conferência antes da carga já parou a
      execução`.
    - `processing/agrupamento.py:633`, `reportReturnType`: `com problemas, as listas podem trazer None, e o resto não é
      usado`.
    - `delivery/email_smtp.py:16`, `reportAttributeAccessIssue`: ``código dormente: o Settings não tem `recipients`
      (CLAUDE.md)``.
    - `delivery/telegram.py:89`, `reportTypedDictNotRequiredAccess`: `dentro do if it.get("tambem_noticiaram") acima`
      (o único que veio com o tipo, no commit 3).
  - O incidente do `models.py` (commit 3): o arquivo já existia, versionado, com o `Article` da coleta (14 linhas), e a
    sessão não o leu antes: a primeira versão, só com os tipos novos, foi escrita por cima dele com o `Write`, que não
    recusou. O pyright apontou o `Article` sumido (`collectors/rss.py:13`, `"Article" is unknown import symbol`), e o
    arquivo foi restaurado com `git restore` antes de qualquer commit; os tipos entraram depois do `Article`, e o diff do
    arquivo só tem inserções. Por isso a docstring aprovada ganhou a primeira frase sobre o `Article`, e o "São só
    anotações" virou "Os tipos do episódio são só anotações". Desde então, cada arquivo que já existe é lido antes de
    qualquer `Write`.
  - Onde os documentos citam o ruff como verificação (levantamento com grep; só o `CLAUDE.md` mudou aqui):
    - `CLAUDE.md`, "Commands": o comentário do `uv sync`, a linha `.venv/bin/ruff check .` e a frase do linter; o
      pyright entrou nos três lugares neste commit.
    - `docs/producao.md:56`, passo 3 de "Trocar um feed": "A suíte inteira e o `ruff check .`, o commit e, com o seu
      ok, o avanço rápido da `master`".
    - `docs/plano-melhorias.md:104`, integração (frente 0): "Depois de cada uma: a suíte inteira e, depois da frente
      4, o `ruff check .`".
    - `docs/referencia/scripts.md`, item dos testes: "The linter is ruff (front 4 of the improvements)...", a
      descrição do linter, não uma verificação por commit.
    - O `docs/regras-de-sessao.md` não cita o ruff (a regra de cada commit fala da suíte e do "Estado"), nem as skills
      `techdigest-retomar` e `techdigest-rodada-modelo`, nem o `CLAUDE.local.md`.
  - Aceite separado: os comandos para o dono rodar na worktree, com a saída esperada no comentário. As duas mutações são
    desfeitas pelo `git restore`, e o último comando tem de sair vazio.

    ```bash
    cd /home/sytw/Projetos/techdigest-tipos
    git --no-pager log --oneline 9c76afb..melhoria/tipos   # os 4 commits da frente
    uv sync --locked --check --extra dev                   # Would make no changes
    .venv/bin/pyright                                      # 0 errors, 0 warnings, 0 informations
    .venv/bin/pytest -q                                    # 805 passed
    .venv/bin/ruff check .                                 # All checks passed!
    # Mutação (a): uma chave errada no _render_item; o pyright tem de pegar
    sed -i "s/escape(it\['resumo_didatico'\])/escape(it['resumo'])/" src/techdigest/delivery/telegram.py
    .venv/bin/pyright                                      # 1 error: "resumo" is not a defined key in "ItemEntregue"
    git restore src/techdigest/delivery/telegram.py
    # Mutação (b): uma chave a menos no Episodio; o teste e o pyright têm de pegar
    sed -i '/^    fontes_citadas: list\[str\]$/d' src/techdigest/models.py
    .venv/bin/pytest -q tests/test_models.py               # 3 failed
    .venv/bin/pyright                                      # 2 errors, os dois em qa.py:612
    git restore src/techdigest/models.py
    git status --short                                     # vazio
    ```

  - Pendências: no merge, a `.venv` da produção ganha os 3 pacotes novos (`pyright`, `nodeenv`,
    `nodejs-wheel-binaries`) pelo `uv sync --locked --extra dev`; se o pyright entra nas verificações escritas de cada
    commit (`docs/regras-de-sessao.md`, `docs/producao.md`, `docs/plano-melhorias.md`) é decisão do dono, na integração
    (frente 0); no modo standard ficam os 3 `possibly unbound` do `main.py:49`, fora do aceite.
- 11/11/2026: pronta para integração. Aceite separado aprovado pelo dono em 11/11.
  - Branch `melhoria/tipos`: os quatro commits da frente, `3b81457` (build), `bda5035` (os 21 lugares do basic),
    `c11e9f9` (o tipo do episódio) e `dce1bd6` (documentos), e depois deles o commit só deste "Estado". A `testes`
    continua em `9c76afb`, a base da frente: o avanço rápido não pede rebase.
  - O dono rodou no terminal, às 21h50, as verificações do bloco do aceite (o `uv sync --locked --check --extra dev`,
    o pyright, a suíte e o `ruff check .`) e aprovou o aceite.
  - A sessão rodou as duas mutações, uma de cada vez, cada uma desfeita com `git restore`:
    - (a) `it['resumo']` no lugar de `it['resumo_didatico']` no `_render_item`: o diff, uma linha trocada só no
      `telegram.py`; o pyright, 1 erro (`telegram.py:82:19`, `"resumo" is not a defined key in "ItemEntregue"`); a
      suíte, 15 falhas (12 no `test_pipeline.py`, 3 no `test_simulacao.py`) e 790 passando.
    - (b) sem `fontes_citadas` no `Episodio`: o diff, uma linha removida só no `models.py`; o `tests/test_models.py`,
      os 3 testes falham (dois `AssertionError` e um `KeyError: 'fontes_citadas'`); o pyright, 2 erros, os dois em
      `qa.py:612` (colunas 19 e 58).
    - Com as duas desfeitas: o pyright com 0 erros, 805 testes passando, o `ruff check .` sem avisos, o
      `git status --short` vazio e o HEAD em `dce1bd6`.
  - Daqui em diante, nenhum commit nesta branch sem avisar o dono (obrigaria rebase). As pendências são as do item
    anterior: a `.venv` da produção no merge e o pyright nas verificações escritas, na integração (frente 0).
- 19/11/2026: **na `master`.**
  - A `testes` entrou na `master` em 18/11, por avanço rápido para `17b4390` (o `fechamento.sh` do dono).
  - As duas pendências foram feitas.
    - A `.venv` da produção foi refeita pelo lock no merge, com o `pyright[nodejs]` do extra `dev`.
    - O `.venv/bin/pyright` está nas verificações escritas: nos comandos do `CLAUDE.md` e na regra de cada commit do
      `docs/regras-de-sessao.md`.
  - A `melhoria/tipos` sai com a limpeza da frente 0.

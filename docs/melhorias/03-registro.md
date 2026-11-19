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
- 08/11/2026: **aceite separado** (falta o ok do dono para ficar pronta para integração). Branch `melhoria/registro`, um
  commit sobre `64bd21b` (`fix(registro): grava o registro de cada execução de forma atômica`). 671 testes passam (667 +
  4).
  - Feito: `registro._gravar_atomico(caminho, texto)` grava em `<nome>.<pid>.tmp` na mesma pasta, faz `flush` e
    `os.fsync` do arquivo e troca com `os.replace`; numa falha apaga o temporário e deixa o erro subir (o `_anotar` do
    pipeline o registra no log, como antes). Usada no `gravar()` (amostra e relatório, nessa ordem) e no `item()` (o JSON
    do episódio, antes do relatório). `CLAUDE.md`, passo 7, e o docstring do módulo dizem que a reescrita é atômica.
  - Testes novos em `tests/test_registro.py`: sem temporário e com os JSON válidos depois da gravação; uma falha no
    `os.fsync` (temporário já escrito) ou no `os.replace` deixa a pasta byte a byte como estava, sem temporário e sem
    episódio novo, e a gravação seguinte leva o que ficou na memória; o formato (indentação 1, acentos sem escape) e a
    permissão iguais aos de um `write_text`.
  - Aceite separado: um script fora do repositório roda o mesmo cenário (todos os métodos do registro, dois itens com o
    provider falso, sem LLM) com o `registro.py` de `64bd21b` e com o novo, na mesma base: os quatro arquivos
    (`amostra.json`, o relatório e os dois episódios) têm os mesmos bytes, fora o `criada_em` da amostra.
  - Medido no registro real de 07/11 (`/home/sytw/Projetos/techdigest/data/execucoes/20261107-010136/`, só leitura):
    uns 42 `gravar()` (criação, coleta, 20 itens e 20 entregas) e 20 episódios, ou seja, uns 104 arquivos gravados e
    104 `fsync` numa execução de 59 minutos, e não umas 20 gravações; no fim, amostra de 103 KB e relatório de 127 KB.
  - Decisões do dono (08/11): temporário visível `<nome>.<pid>.tmp`, `open` em vez de `tempfile` (mantém a permissão
    644), `fsync` só do arquivo, não da pasta (sem ele a troca pode voltar à versão anterior inteira numa queda de
    energia, nunca a uma cortada), a sobra de um processo morto fica até a pasta sair, e a falha em `item()` segue como
    antes (os candidatos já entraram na amostra, a entrada não entra no relatório).
  - Fora do escopo, não feito: `scripts/testar_episodio.py`, que grava os relatórios dele com `write_text`; unificar com
    a troca de `ai/janela.py`; `docs/referencia/scripts.md`.
- 08/11/2026: **pronta para integração**. O dono aprovou o aceite separado. Branch `melhoria/registro`, código em
  `f6f54e9`, sem push. 671 testes passam. Próximo passo, com a frente 0: rebase sobre a `testes` e avanço rápido dela.
  Sem pendência nesta frente.
- 08/11/2026: **rebaseada sobre a `testes`** (`7d8760b`, só documentos a mais: `docs/plano-melhorias.md` e
  `docs/melhorias/00-coordenacao.md`), sem conflito. Os commits da branch passaram a ser `b89b5aa` (o código, antes
  `f6f54e9`) e `e5299da` (o estado, antes `3a13a54`), mais o deste registro. 671 testes passam depois do rebase; a suíte
  não pediu pacote nenhum, então a `.venv` não foi reinstalada. O `src/techdigest.egg-info` foi restaurado antes do
  rebase e não entrou em commit. Sem push. Próximo passo, da frente 0: o avanço rápido da `testes` para esta branch.
- 08/11/2026: **aceite estendido** (pedido pelo dono depois da pergunta de aceite: o aceite anterior simulava a falha
  por exceção no `fsync` ou no `os.replace`, sempre na primeira gravação da chamada, e nunca um processo morto nem uma
  falha na gravação do próprio relatório). Três testes novos em `tests/test_registro.py`, só testes, sem mudança de
  código:
  - A, `test_processo_morto_no_meio_do_relatorio_deixa_o_anterior_inteiro`: um subprocesso (`sys.executable`, timeout de
    30 s, a pasta e o ponto da morte por argumento, sem rede nem modelo) grava um item, copia a pasta e se mata com
    `os.kill(os.getpid(), signal.SIGKILL)` com metade do relatório escrita. O pai confere: o relatório tem os bytes de
    antes e passa no `json.loads`; sobra só o `relatorio_<carimbo>.json.<pid>.tmp`; o `refazer_qa._relatorio` escolhe
    o relatório verdadeiro, e o `refazer_qa.refazer` e o `checar_fidelidade._carregar` leem só o episódio 1.
  - B, `test_processo_morto_entre_o_episodio_e_o_relatorio_deixa_o_episodio_solto`: o mesmo filho morre na amostra,
    depois do episódio 2. A amostra e o relatório ficam com os bytes de antes, sobra o `amostra.json.<pid>.tmp`, o
    episódio 2 fica inteiro e solto, e os dois leitores o ignoram.
  - C, `test_falha_so_na_escrita_do_relatorio_deixa_o_anterior_inteiro`: no mesmo processo, o disco enche (`OSError`)
    com metade do relatório escrita. O relatório fica com os bytes de antes, sem temporário, a amostra é a nova, e os
    leitores leem só o episódio 1.
  - A falha entra na escrita, pelo `open` (o `builtins.open` do registro e o `io.open` do `write_text`), e não no
    `fsync` (A) nem no `os.replace` (C), como dizia a proposta: assim os testes também pegam uma gravação direta, que
    não chama nenhum dos dois. A e B são pulados fora de POSIX; C não usa sinal nem subprocesso.
  - Verificação: com o `_gravar_atomico` trocado temporariamente por um `write_text` no próprio caminho (sem commit),
    os três falham na comparação byte a byte. Em A e C o relatório fica cortado no meio; em B, a amostra. O arquivo
    voltou com `git checkout -- src/techdigest/registro.py`.
  - 674 testes passam (671 + 3), em duas rodadas seguidas da suíte.
- 19/11/2026: **na `master`.**
  - A `testes` entrou na `master` em 18/11, por avanço rápido para `17b4390` (o `fechamento.sh` do dono).
  - A `melhoria/registro` sai com a limpeza da frente 0.
  - Primeira execução real com a gravação atômica: 18/11, das 21:11 às 22:05.
    - O registro `data/execucoes/20261118-211140/` tem a amostra, o relatório e os 20 episódios, todos lidos como JSON
      inteiro.
    - Nenhum `.tmp` ficou na pasta.

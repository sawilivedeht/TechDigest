# Frente 6: feeds em arquivo

Arquivo no Projeto: `claude/frentes/06-feeds.md` · no repositório: `docs/melhorias/06-feeds.md`

| | |
|---|---|
| Branch | `melhoria/feeds` |
| Worktree | `/home/sytw/Projetos/techdigest-feeds` |
| Onda | 2 |
| Depende de | a lista de feeds, que só o dono tem (está no `.env`) |
| Conflita com | frentes 8 e 9 no `config.py` (onda 3) |

## Objetivo

A lista de feeds versionada em `config/feeds.txt`, no padrão do `config/sites_de_partido.txt`, para o Claude Code ler o
que roda e cada mudança ficar no git.

## Por que

- Os feeds vêm só do `RSS_FEEDS` do `.env` (`Settings.rss_feeds` e `Settings.feeds`, em `src/techdigest/config.py`), que o
  Claude Code não lê; os padrões do código não são o que roda (`CLAUDE.md`).
- O repositório já tem o precedente: `config/sites_de_partido.txt`, versionado, um domínio por linha, com validação
  (`processing/filtro.ler_sites_de_partido`, lido uma vez por processo).

## Como fica

- `config/feeds.txt`: uma URL por linha, na ordem de hoje (a intercalação do boletim duplo depende dela). Linhas vazias e
  comentários com `#` são ignorados; uma linha que não é URL http(s) é erro, como no arquivo de partidos; URL repetida
  também é erro.
- `Settings.feeds` continua sendo a interface: o `collectors/rss.py` não muda, só o comentário "`.env` = fonte de verdade"
  da linha 132.
- Precedência: o `RSS_FEEDS` definido no ambiente ou no `.env`, **mesmo vazio**, continua mandando, com um aviso no log
  quando o arquivo também existe. Motivo: o `tests/test_simulacao.py` (linha 184) põe `RSS_FEEDS` vazio para garantir que
  nada é coletado se uma falsificação escapar. Sem o `RSS_FEEDS`, vale o arquivo (no pydantic-settings, um campo vindo do
  ambiente aparece em `model_fields_set`). Depois do merge, o dono tira o `RSS_FEEDS` do `.env`.

## Decisões do dono

- Copiar o `RSS_FEEDS` atual do `.env` para o `config/feeds.txt` da branch, na mesma ordem (a sessão não lê o `.env`).
- A precedência acima, ou outra.
- TOML fica para depois, se os feeds ganharem campos (nome, boletim) ou se as chaves não secretas saírem do `.env`.

## Testes

- A leitura do arquivo: comentários, linhas vazias, ordem mantida; linha inválida e URL repetida são erro.
- A precedência: `RSS_FEEDS` definido (vazio ou não) manda; sem ele, o arquivo; o aviso quando há os dois.
- Os testes de coleta e de simulação continuam passando.

## Aceite separado

- A suíte inteira.
- Com o arquivo do dono, `Settings().feeds` na worktree dá a mesma lista, na mesma ordem, que o dono tem no `.env`.

## Documentação

- `CLAUDE.md`, "Configuration": a lista de feeds em `config/feeds.txt` e a precedência.
- `docs/producao.md`: para trocar um feed, editar o arquivo, commit e avanço rápido; depois do merge, tirar o `RSS_FEEDS`
  do `.env`.

## Prompt inicial para o Claude Code

```text
Frente 6 (feeds em arquivo) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-feeds, branch
melhoria/feeds. Leia docs/plano-melhorias.md, docs/melhorias/06-feeds.md e docs/regras-de-sessao.md.
Primeiro, só leitura: src/techdigest/config.py, collectors/rss.py (onde usa settings.feeds), processing/filtro.py (como lê
config/sites_de_partido.txt), tests/conftest.py e tests/test_simulacao.py. O .env continua fechado: a lista de feeds eu
mesmo vou pôr no config/feeds.txt.
Depois apresente o plano, com a precedência proposta no arquivo da frente e a lista "Leituras minhas, para você
corrigir", e espere a aprovação.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/06-feeds.md atualizada.
```

## Estado

- 07/11/2026: não começada.
- 08/11/2026: em plano. Ambiente conferido na `melhoria/feeds` (nascida da `testes` em `121fa7b`): `git status` limpo,
  `uv sync --locked --check --extra dev` deu `Would make no changes`, 695 testes passando e `ruff check .` sem avisos. O
  pydantic-settings 2.15.0 põe o `rss_feeds` em `model_fields_set` quando o `RSS_FEEDS` vem do ambiente ou do `.env`,
  mesmo vazio, e não o põe quando falta (conferido com um `.env` de teste, sem ler o do dono).
- 09/11/2026: em implementação, depois da aprovação do plano pelo dono, com quatro ajustes:
  1. O caminho é resolvido na hora da chamada: `ler_feeds(caminho=None)` usa o `CAMINHO_DOS_FEEDS` do módulo, e não um
     padrão fixado na definição da função; um teste prova que a troca por monkeypatch muda o que a mesma instância de
     `Settings` devolve.
  2. O arquivo sem nenhuma URL (vazio ou só comentários) é `ValueError`; a lista vazia só vem do `RSS_FEEDS` definido e
     vazio. Os dois casos têm teste.
  3. O aviso da precedência fica como está, porque o `settings.feeds` é lido uma vez por execução: o único leitor é o
     `collect_rss` (`rss.py:132`, `feeds or settings.feeds`, que nem lê o settings quando recebe a lista); o
     `pipeline.run` chama o `_coletar` uma vez, num `if/else` (agrupamento ligado ou desligado); o
     `scripts/testar_agrupamento.py` chama o `collect_rss()` uma vez no `main` (nenhuma com `--amostra`); a intercalação
     do boletim duplo usa a lista `urls` já lida. Sem cache da lista.
  4. O teste das 9 URLs literais, na ordem, diz no docstring que é atualizado junto com qualquer troca de feed; o
     `docs/producao.md` diz o mesmo em "Trocar um feed".
  - O que mudou: `config.py` (`CAMINHO_DOS_FEEDS`, `ler_feeds`, `Settings.feeds` com a precedência e o aviso; o padrão do
    `rss_feeds` passou de The Verge/Ars/HN para `""`, porque nunca vira lista), o comentário da linha 132 do
    `collectors/rss.py`, o `config/feeds.txt` com as 9 URLs do dono (copiadas da mensagem dele, não do `.env`), o
    `tests/test_feeds.py` (20 testes), o `CLAUDE.md` ("Configuration") e o `docs/producao.md` ("Trocar um feed" e a linha
    da tabela).
  - Suíte: 715 passando (695 + 20). `ruff check .` sem avisos.
  - Um erro no arquivo só aparece na coleta, depois da trava e da conferência da GPU: vira o aviso de parada com o tipo
    do erro e status 1, com a mensagem inteira no log. Validar antes exigiria mexer no `pipeline.py`, fora do escopo.
  - Risco anotado no `docs/producao.md`: um `RSS_FEEDS=` vazio no `.env` conta como definido e deixa a coleta sem feed;
    a execução termina com "Nenhuma notícia entregue" e status 0. Depois do merge, a linha inteira sai do `.env`.
  - Pendente: a prova por mutação (depois do commit, para o `git checkout --` voltar ao código commitado) e o aceite
    separado, que é do dono (ele lê o `.env`; a sessão não).
- 09/11/2026: aceite separado. Commit `0de125d` na `melhoria/feeds` (sem push): 715 testes passando (695 + 20) e
  `ruff check .` sem avisos, antes do commit e de novo depois das mutações. Prova por mutação no código commitado, cada
  uma desfeita com `git checkout -- src/techdigest/config.py` (`git status` vazio depois de cada uma), rodando
  `pytest tests/test_feeds.py -q --tb=no -rf`:
  1. Precedência pelo valor (`if self.rss_feeds:` no lugar de `if "rss_feeds" in self.model_fields_set:`):
     ```
     FAILED tests/test_feeds.py::test_o_rss_feeds_do_ambiente_manda_mesmo_vazio_com_aviso[-esperado1]
     FAILED tests/test_feeds.py::test_o_rss_feeds_do_env_manda_mesmo_vazio_com_aviso[RSS_FEEDS=-esperado1]
     2 failed, 18 passed in 0.04s
     ```
  2. Sem a checagem de URL repetida (as duas linhas do `if url in linha_de:` tiradas):
     ```
     FAILED tests/test_feeds.py::test_recusa_a_url_repetida_e_compara_o_texto_exato
     1 failed, 19 passed in 0.03s
     ```
  3. Sem a checagem de esquema (`if not partes.netloc` no lugar de
     `if partes.scheme not in ("http", "https") or not partes.netloc`):
     ```
     FAILED tests/test_feeds.py::test_recusa_a_linha_que_nao_e_url_com_o_numero_dela[ftp://a.example/feed]
     1 failed, 19 passed in 0.04s
     ```
  4. Extra, o defeito do ajuste 1 (`def ler_feeds(caminho: str | Path = CAMINHO_DOS_FEEDS)`, sem resolver o `None`):
     ```
     FAILED tests/test_feeds.py::test_sem_rss_feeds_vale_o_arquivo_sem_aviso - Ass...
     FAILED tests/test_feeds.py::test_a_troca_do_caminho_por_monkeypatch_muda_o_que_settings_feeds_devolve
     FAILED tests/test_feeds.py::test_o_env_sem_rss_feeds_deixa_o_arquivo_mandar
     FAILED tests/test_feeds.py::test_sem_rss_feeds_e_sem_arquivo_e_erro - Failed:...
     FAILED tests/test_feeds.py::test_o_arquivo_vazio_sem_rss_feeds_e_erro_e_nao_lista_vazia
     5 failed, 15 passed in 0.03s
     ```
  - Pendente: o aceite do dono, que compara o `RSS_FEEDS` do `.env` dele com o `config/feeds.txt` da worktree,
    imprimindo só se o `RSS_FEEDS` veio do `.env`, as contagens e se as listas são iguais, sem nenhuma URL. Esperado
    `True 9 9 True`, mais a linha do aviso da precedência no stderr. O primeiro `True` diz que a lista `a` veio mesmo do
    `.env`: sem ele, o `Settings` cairia no próprio arquivo, e o `9 9 True` sairia sem provar nada.
    `cd /home/sytw/Projetos/techdigest-feeds && .venv/bin/python -c 'from techdigest import config; s = config.Settings(_env_file="/home/sytw/Projetos/techdigest/.env"); a = s.feeds; b = list(config.ler_feeds()); print("rss_feeds" in s.model_fields_set, len(a), len(b), a == b)'`
- 09/11/2026: aceite do dono feito, rodado por ele na worktree, com o `.env` da pasta principal. Saída:
  ```
  RSS_FEEDS definido no ambiente ou no .env: a coleta usa ele, não o /home/sytw/Projetos/techdigest-feeds/config/feeds.txt
  True 9 9 True
  ```
  O `RSS_FEEDS` veio do `.env` (primeiro `True`), as duas listas têm 9 URLs e são iguais, na mesma ordem, e o aviso da
  precedência saiu. Etapa: aceite separado concluído; "pronta para integração" com o ok do dono, e então a frente 0 é
  avisada. Depois do merge na `master`, a linha `RSS_FEEDS` sai inteira do `.env` (ver `docs/producao.md`).

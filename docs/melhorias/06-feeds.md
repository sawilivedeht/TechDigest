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

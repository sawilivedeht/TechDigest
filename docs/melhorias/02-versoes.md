# Frente 2: versões

Arquivo no Projeto: `claude/frentes/02-versoes.md` · no repositório: `docs/melhorias/02-versoes.md`

| | |
|---|---|
| Branch | `melhoria/versoes` |
| Worktree | `/home/sytw/Projetos/techdigest-versoes` |
| Onda | 1 |
| Depende de | nada |
| Conflita com | frentes 4 e 9 no `pyproject.toml`; frente 0 no `docs/regras-de-sessao.md` |

## Objetivo

As versões instaladas na produção e nas worktrees iguais por construção, sem comparar o `pip freeze` à mão, e o
`src/techdigest.egg-info` fora do git.

## Por que

- O `requirements.txt` está vazio e fora do git; o `pyproject.toml` só dá versão mínima (`edge-tts>=6.1`, por exemplo).
- Em 05/11 a produção tinha o `edge-tts` 7.2.8 e a worktree o 7.3.1: a primeira execução real perdeu todos os itens com
  403. Daí a regra de comparar o `pip freeze` das duas `.venv` antes de cada avanço rápido (`docs/regras-de-sessao.md` e
  `docs/producao.md`).
- Em 07/11 as duas `.venv` ainda diferiam em patch de openai, pydantic, pydantic-settings, truststore e pluggy (aceitas
  pelo dono). Com várias worktrees, as diferenças se multiplicam. Até esta frente decidir, a frente 0 instala as worktrees
  com o `pip freeze` da produção como restrição.
- O `src/techdigest.egg-info` está no git e muda a cada `pip install -e .`, como o `CLAUDE.md` já avisa.

## Decisão do dono, antes de implementar

| Opção | O que muda | Prós | Contras |
|---|---|---|---|
| **uv** (recomendada) | `uv.lock` versionado e `.python-version` (3.14); instalação por `uv sync --locked --extra dev` | Versões e Python iguais em toda `.venv`; o `--locked` falha se o lock estiver velho; instalação rápida | Ferramenta nova (`pacman -S uv`, pelo dono); muda os comandos dos documentos e das skills; a `.venv` de produção é recriada |
| pip-tools | `requirements-lock.txt` gerado pelo `pip-compile` a partir do `pyproject.toml`; instalação por `pip-sync` | Continua no pip | Mais um passo manual para regenerar; o Python não fica fixo |
| Só fixar | `edge-tts==7.3.1` no `pyproject.toml` | Uma linha | As outras dependências continuam soltas, e a comparação do `pip freeze` continua |

## Passos (se a escolha for o uv)

1. Só leitura: o `pip freeze` das `.venv` da pasta principal, da `techdigest-fase4` e desta worktree, e `uv --version`.
2. `.python-version` com 3.14. O lock tem de sair **com as versões que a produção usa hoje**, não com as mais novas: usar o
   `pip freeze` da produção como restrição na hora de travar e conferir versão por versão. Diferença, só com o ok do dono.
3. `uv sync --locked --extra dev` na worktree e a suíte inteira.
4. `git rm -r --cached src/techdigest.egg-info` e `*.egg-info/` no `.gitignore`.
5. Documentos: os comandos do `CLAUDE.md`; o passo 1 de "Antes" do `docs/producao.md`; a regra do `pip freeze` em
   `docs/regras-de-sessao.md`, que passa a ser "o `uv.lock` da branch é o que roda". As skills, na integração.
6. Escrever, neste arquivo, a troca da `.venv` de produção para a frente 0 fazer no merge: guardar a atual
   (`mv .venv .venv.pip-AAAAMMDD`), `uv sync --locked --extra dev`, a suíte e a comparação das versões com o freeze antigo.
   Para voltar atrás, a `.venv` guardada volta para o lugar.

Com pip-tools, os mesmos passos com `requirements-lock.txt` (o `requirements.txt` está no `.gitignore`). Só fixando, o
passo 4 (o egg-info) continua valendo.

## Aceite separado

- A suíte inteira numa `.venv` feita do lock.
- Reprodutível: apagar a `.venv` e refazer dá as mesmas versões.
- Todas as versões do lock iguais às do `pip freeze` da produção (ou as diferenças listadas e aprovadas), com o `edge-tts`
  em 7.3.1.

## Riscos

- O lock subir versões sem ninguém notar: daí o passo 2.
- Se a frente 4 entrar na `testes` depois desta, com o `ruff` no extra `dev`, o lock precisa ser refeito lá, e vice-versa.

## Prompt inicial para o Claude Code

```text
Frente 2 (versões) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-versoes, branch
melhoria/versoes. Leia docs/plano-melhorias.md, docs/melhorias/02-versoes.md e docs/regras-de-sessao.md.
Agora só leitura: compare o pip freeze da .venv da pasta principal (/home/sytw/Projetos/techdigest) com o da
techdigest-fase4 e com o desta worktree, liste as diferenças e confira se o uv está instalado (uv --version).
Depois me apresente as três opções do arquivo da frente (uv, pip-tools, só fixar o edge-tts), com o que muda em cada uma
neste repositório, e espere a minha decisão. Só então o plano, com a lista "Leituras minhas, para você corrigir".
Trabalhe só nesta worktree e nesta branch, sem push. A cada commit, a suíte inteira e a seção "Estado" de
docs/melhorias/02-versoes.md atualizada.
```

## Estado

- 07/11/2026: não começada.

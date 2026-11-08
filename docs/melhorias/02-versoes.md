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

- **08/11/2026: pronta para integração.** Aceite separado aprovado pelo dono em 08/11/2026. Branch `melhoria/versoes`,
  a partir da `64bd21b`. Commit 1: `0e23a55` ("chore: tira o src/techdigest.egg-info do git"). Commit 2: `df67c9d`
  ("build: versões travadas pelo uv.lock e Python pelo .python-version"). Depois deles, só o commit deste Estado, sem
  código. Suíte: 667 passam na `.venv` nova, feita pelo uv a partir do lock (e 667 na `.venv` do pip, no commit 1).
- **Decisão do dono (08/11/2026):** uv, com lock universal (sem `environments` no `[tool.uv]`), porque quem baixar o
  projeto do GitHub pode usar Windows ou macOS. Aceite do lock: os 60 pacotes do `pip freeze` da produção com a mesma
  versão; os extras, só os de outras plataformas (`colorama`, `tzdata`, `httpx2-jsfetch`), listados; qualquer outro
  extra, perguntar ao dono.
- **Medido (08/11, só leitura):**
  - As três `.venv` (pasta principal, `techdigest-fase4` e esta) no Python 3.14.9 do sistema (`/usr/bin/python3.14`),
    com 62 linhas de `pip freeze` cada e o `edge-tts` 7.3.1.
  - Esta worktree igual à produção, menos o `pip` (26.2.2 contra 26.3).
  - A `techdigest-fase4` com as seis diferenças de patch aceitas em 07/11: openai 3.31.0 (3.28.0 na produção), pydantic
    2.14.1 (2.14.0), pydantic_core 2.50.1 (2.50.0), pydantic-settings 2.16.0 (2.15.0), truststore 0.10.5 (0.10.4) e
    pluggy 1.7.0 (1.6.0); o `pip` 26.2.1.
  - uv 0.13.7 (316c827e0 2026-11-03), pacote `uv 0.13.7-1` do pacman. O pip-tools não está instalado (nem no PATH, nem
    nas `.venv`, nem por pipx ou `uv tool`).
  - Teste numa cópia do `pyproject.toml`, fora do repositório: o lock universal, com o freeze da produção como restrição,
    traz os 60 pacotes com a mesma versão, e um novo `uv lock` sem a restrição as mantém. Os extras: `colorama` 0.4.6
    (só `win32`, pelo pytest), `tzdata` 2026.6 (só `win32`, pelo tzlocal) e `httpx2-jsfetch` 1.0 (só `emscripten` com
    Python 3.12 ou mais, pelo httpx2). Uma `.venv` feita do lock sai com as versões da produção e sem `pip`; o
    `uv sync --locked --check --extra dev` acusa um `edge-tts` 7.2.8 instalado (status 1) e, sem o `--extra dev`, tiraria
    o pytest e as quatro dependências dele.
  - A instalação editável das `.venv` é a do PEP 660 (`__editable__.techdigest-0.1.0.pth` e o `dist-info` no
    `site-packages`): o `src/techdigest.egg-info` é só um resto do build, e apagá-lo do disco não quebra a `.venv`.
- **Medido no commit 2 (08/11):**
  - O freeze da produção, relido antes de travar, igual ao da primeira leitura.
  - O lock: os 60 pacotes entraram como `constraint-dependencies` temporárias no `[tool.uv]`; sem a seção, um novo
    `uv lock` manteve as versões; o `uv lock --check` passa; o `pyproject.toml` ficou sem diff; o `uv.lock` final não tem
    `[manifest]` (o da etapa com a restrição tinha `[manifest]` com `constraints`).
  - Aceite por script (na scratchpad, fora do commit): 64 pacotes no lock; os 60 do freeze com a mesma versão, nenhum
    diferente e nenhum ausente; o `edge-tts` em 7.3.1; os extras só `colorama` 0.4.6 (`sys_platform == 'win32'`, pelo
    pytest), `tzdata` 2026.6 (`sys_platform == 'win32'`, pelo tzlocal) e `httpx2-jsfetch` 1.0
    (`python_full_version >= '3.12' and sys_platform == 'emscripten'`, pelo httpx2).
  - A `.venv` desta worktree: a do pip guardada em `.venv.pip-20261108` (ignorada pelo git), a nova feita por
    `uv sync --locked --extra dev`. O `.venv/bin/python` aponta para `/usr/bin/python3.14`, 3.14.9, sem free-threading
    (`Py_GIL_DISABLED` falso), com `home = /usr/bin` no `pyvenv.cfg`, e o uv não baixou Python nenhum
    (`~/.local/share/uv/python` não existe). O `uv sync --locked --check --extra dev` dá `Would make no changes`
    (61 pacotes conferidos: os 60 e o techdigest); o `uv pip freeze` é igual ao freeze da produção (60 pacotes, com os
    nomes normalizados); não há `pip`.
  - Reprodutível: apagada e refeita, a `.venv` saiu com as mesmas versões.
- **Feito:**
  - Commit 1: o `src/techdigest.egg-info` saiu do índice do git (os arquivos continuam no disco) e o `.gitignore` ganhou
    `*.egg-info/` e `.venv.pip-*/` (a cópia da `.venv` antiga, aqui e na troca da `.venv` da produção).
  - Commit 2: `.python-version` (3.14) e `uv.lock`, sem mudança no `pyproject.toml`. Documentos: `CLAUDE.md`
    ("Commands": a instalação e o `--check`, um item sobre as versões, o `uv` nos requisitos de sistema),
    `docs/producao.md` (passo 1 de "Antes": o `--check` no lugar da comparação do `pip freeze`) e
    `docs/regras-de-sessao.md` (a regra do `pip freeze` vira a do `uv.lock`).
- **Próximo:** a frente 0 é avisada e integra a frente na `testes`. A `.venv.pip-20261108` desta worktree fica até a
  frente 0 integrar (decisão do dono de 08/11/2026).
- **Pendências para a frente 0 (integração):**
  - `CLAUDE.md`, "Repo notes": a nota "`src/techdigest.egg-info/` is committed, so reinstalling the package can produce
    diffs there" fica falsa; sugestão: "`src/techdigest.egg-info/` is gitignored: every install regenerates it".
  - `docs/regras-de-sessao.md` ("Sem commit de `src/techdigest.egg-info` até a frente 2 decidir") e a regra 5 de
    `docs/plano-melhorias.md` deixam de ser necessárias.
  - As outras worktrees descartam as mudanças locais em `src/techdigest.egg-info` antes de rebasear sobre uma branch com
    este commit (`git restore src/techdigest.egg-info`). Em 08/11 tinham o `SOURCES.txt` modificado: `techdigest-testes`,
    `techdigest-audio`, `techdigest-registro`, `techdigest-ruff` e `techdigest-schema`; a pasta principal e a
    `techdigest-fase4` estavam limpas. O rebase (e, na pasta principal, o avanço rápido) apaga os arquivos do disco, o
    que não quebra a `.venv` (PEP 660, acima).
  - Grep por `pip` (palavra inteira) em `~/.claude/skills` e no `CLAUDE.local.md` da pasta principal, sem editar:
    nenhuma ocorrência nas skills `techdigest-retomar` e `techdigest-rodada-modelo` nem no `CLAUDE.local.md` (a única
    ocorrência como trecho de palavra é "pipeline", na `techdigest-rodada-modelo`). Fora do TechDigest, só as skills
    genéricas sincronizadas `pdf`, `pptx` e `xlsx` e uma cópia da `pdf` na lixeira (`~/.claude/skills/.trash/`), que não
    são do projeto. A `techdigest-rodada-modelo` cita "a `.venv` e o código dela" (linha 10), que continua valendo com o
    uv; nenhuma cita `egg-info`, `freeze` ou `requirements`.
  - A troca da `.venv` da produção, abaixo, logo depois do avanço rápido da `master`.
  - Uma worktree que ainda não recebeu estes commits continua com a `.venv` do pip. Ao receber a `testes` ou a
    `master`, ela refaz a `.venv` pelo lock: `mv .venv .venv.pip-AAAAMMDD`, `uv sync --locked --extra dev` e a suíte.
  - Se a frente 4 entrar na `testes` com o `ruff` no extra `dev` (antes ou depois desta), o lock é refeito na `testes`
    com `uv lock` e vai num commit. O aceite por script vale de novo: os 60 com as versões da produção e o `ruff` (com o
    que ele puxar) como diferença listada. Um conflito no `uv.lock` se resolve refazendo o lock com `uv lock`, nunca à
    mão.
  - O estado de produção do `CLAUDE.md` ("Production state") passa a dizer que a `.venv` da produção é do uv.

### Troca da `.venv` da produção (frente 0, no merge)

Na pasta principal, logo depois do avanço rápido da `master` para a `testes`, sem rodada nem execução no ar.
`AAAAMMDD` é a data do dia. Testado nesta worktree em 08/11, com a `.venv.pip-20261108` no papel da antiga.

```bash
cd /home/sytw/Projetos/techdigest
systemctl --user is-active techdigest-teste.target   # tem de dar inactive
ls uv.lock .python-version                           # a master já traz os dois
.venv/bin/pip freeze --all | sort -f > .venv/freeze-antes-do-uv.txt   # as versões do pip, guardadas com a .venv
mv .venv .venv.pip-AAAAMMDD                          # a .venv do pip, guardada (o .gitignore a ignora)
uv sync --locked --extra dev                         # a .venv nova, do lock
readlink -f .venv/bin/python                         # /usr/bin/python3.14 (nunca o python3.14t)
.venv/bin/python -c "import sys, sysconfig; print(sys.version.split()[0], bool(sysconfig.get_config_var('Py_GIL_DISABLED')))"   # 3.14.x False
uv sync --locked --check --extra dev                 # Would make no changes
uv pip show --python .venv/bin/python edge-tts | grep Version   # a do lock (7.3.1 em 08/11)
.venv/bin/pytest -q                                  # a suíte inteira
diff <(grep -v -E '^(-e |pip==)' .venv.pip-AAAAMMDD/freeze-antes-do-uv.txt | tr 'A-Z_' 'a-z-' | sort) \
     <(uv pip freeze --python .venv/bin/python | grep -v -E '^(-e |techdigest)' | tr 'A-Z_' 'a-z-' | sort)
```

O `diff` sem saída quer dizer as mesmas versões. Cada linha dele é uma diferença: fica listada e só segue com o ok do
dono (por exemplo o `ruff`, se a frente 4 entrar com ele no extra `dev`). A `.venv.pip-AAAAMMDD` fica até a primeira
execução real do dono passar; apagá-la é decisão dele.

Para voltar atrás, a `.venv` do pip de volta ao lugar:

```bash
cd /home/sytw/Projetos/techdigest
rm -rf .venv                                         # só a .venv do uv, que o lock refaz
mv .venv.pip-AAAAMMDD .venv
.venv/bin/pytest -q
```

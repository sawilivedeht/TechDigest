# Frente 7: rodada em Python

Arquivo no Projeto: `claude/frentes/07-rodada.md` · no repositório: `docs/melhorias/07-rodada.md`

| | |
|---|---|
| Branch | `melhoria/rodada` |
| Worktree | `/home/sytw/Projetos/techdigest-rodada` |
| Onda | 2 |
| Depende de | nada. A calibração de memória da frente 5 foi dispensada em 09/11 (decisão C6), então deixou de ser o primeiro uso com o modelo; esse uso fica para o teste conjunto da frente 0 ou para a próxima rodada que o dono pedir |
| Conflita com | frente 5 em `docs/referencia/scripts.md`: resolvido. O trecho da frente 5 já estava na `testes`, e esta frente só acrescentou a seção do `rodada.py` e uma frase no item dos testes |

## Objetivo

Um script versionado e testado para as rodadas com o modelo, no lugar do `vigia_memoria.sh` e do `rodar.sh` copiados e
editados a cada rodada.

## Por que

A skill `techdigest-rodada-modelo` montava cada rodada à mão:
- copiava o `vigia_memoria.sh` da rodada anterior e trocava o `R=`;
- escrevia um `rodar.sh` novo (`set -u`, `cd`, `PYTHONUNBUFFERED`, `anota` no `andamento.txt`, `touch FIM` também na
  falha);
- subia e parava a sessão de teste;
- rodava tudo sob `systemd-inhibit`.

Ela também listava quatro armadilhas do zsh desta máquina. Nada disso estava no git, e esquecer de parar a sessão de teste
deixava o Ollama no ar.

## Como ficou

```
.venv/bin/python scripts/rodada.py --pasta <pasta> --pedido "<texto>" [--repetir N] [--log-ollama <arquivo>]
    (--comandos <arquivo> | -- <comando> [args...])
```

Caminhos relativos (`--pasta`, `--comandos`, `--log-ollama`) são resolvidos contra a raiz da worktree do script, que
também é o cwd dos comandos. Os links são seguidos: a recusa do `/tmp` vale para o caminho resolvido, porque o
`data/agrupamento` das worktrees é um link.

1. **Argumentos** (status 2, sem tocar em nada). Entram aqui:
   - `--comandos` ou `-- <comando>`, exatamente um dos dois;
   - a pasta, que não pode existir nem ficar em `/tmp`;
   - o arquivo de comandos: um por linha, separado pelo `shlex.split`. Linhas vazias e as que começam com `#` não contam.
     É erro, com o número da linha, `|`, `||`, `&`, `&&` ou `;` como palavra solta, e a palavra que começa com `>`, `<`,
     `2>` ou `&>`. Nada é expandido: `~`, `$VAR` e `*` chegam literais;
   - `--repetir N`: N de 2 em diante e, nos comandos, pelo menos um `{vez}`;
   - `{vez}` sem `--repetir` também é erro.
2. **Antes de criar qualquer coisa** (status 1): `techdigest-teste.target` e `ollama.service` em `inactive` ou `failed`,
   e o `nvidia-smi` respondendo (`ai/gpu.driver_da_nvidia`). Uma rodada que não começa nunca para a sessão de outra.
3. **A pasta**:
   - o `comandos.txt`: o arquivo copiado ou, no modo `--`, a linha pelo `shlex.join`;
   - o `andamento.txt`, com o pedido, a data, a worktree, a branch e o commit (`git rev-parse --short HEAD`), "com
     mudanças fora do commit" quando houver, e os comandos.
4. **Bloqueio do sono**, um para a rodada inteira: `systemd-inhibit --what=sleep:idle --who=TechDigest --why="rodada
   <nome>" tail --pid=<PID do rodada.py> -f /dev/null`, numa sessão própria, confirmado pelo PID no
   `systemd-inhibit --list`. Recusado, a rodada para sem subir a sessão. Em 10/11 conferi numa máquina de verdade que o
   PID listado é o do `systemd-inhibit` e que um SIGTERM nele solta o bloqueio e encerra o `tail`.
5. **O vigia**, numa thread com `ai/maquina.memoria_disponivel()`:
   - lê a memória a cada 2 s e grava no `vigia_memoria.log` a cada 60 s e no fim, com o mínimo, em MiB como o vigia em
     bash;
   - liga antes da subida, para vigiar também a carga do Ollama;
   - abaixo de 3 GiB, para a sessão de teste e nenhum comando novo começa. O comando em curso não é morto: sem o Ollama,
     os freios dele param a chamada;
   - se o vigia morre por exceção (a memória ilegível conta como uma), a exceção vai para o `vigia_memoria.log` e para o
     `andamento.txt`, a sessão para, nenhum comando novo começa e o status é 1.
6. **A sessão**: a rodada se marca como dona da sessão antes do `systemctl --user start techdigest-teste.target`, de
   modo que uma subida que falha no meio também é parada. Depois vem a conferência da GPU com
   `gpu.conferir_antes_de_carregar`: o driver, o `ollama serve` rodando, o log desta subida e o `library=CUDA`.
7. **Os comandos**, um por vez:
   - sem shell, cada um no seu grupo de processos, com stdin em `/dev/null` e `PYTHONUNBUFFERED=1`;
   - a saída vai para `saida_<n>.txt`, ou `saida_<n>_vez<v>.txt` com `--repetir`;
   - uma linha de início e uma de fim (status, duração) no `andamento.txt`;
   - o primeiro que falha para a rodada.
8. **Interrupção** (Ctrl+C, SIGTERM ou SIGHUP): só o `rodada.py` recebe o sinal. Ele repassa ao comando um único SIGINT;
   depois de 30 s manda SIGTERM, e depois de mais 10 s, SIGKILL. A partir do primeiro sinal, os seguintes são ignorados
   para não cortar a limpeza.
9. **No `finally`**:
   - para a sessão que subiu e espera até 2 min o target e a `ollama.service` saírem do ar;
   - encerra o vigia e solta o bloqueio;
   - grava o `FIM` (`status N` e o resumo) e imprime o resumo. O resumo traz a duração, a memória mínima, o status e a
     duração de cada comando ou "não rodou", a situação da sessão e os motivos.

**Status de saída**:
- 0 só com tudo certo;
- 128 + o sinal numa interrupção (130 no Ctrl+C);
- o status do comando que falhou (127 se ele não existe);
- 1 quando a rodada não começa, o vigia para a sessão ou morre, o bloqueio é recusado, a sessão não sobe, a GPU não passa
  ou a sessão não para (o resumo diz "CONTINUA NO AR");
- 2 num erro de argumento.

O script não pega a trava do modelo (os comandos pegam) e não contorna os freios da máquina dos comandos. Um SIGKILL no
`rodada.py` não tem limpeza, como no `rodar.sh`: a sessão e o comando ficam no ar, e só o bloqueio sai sozinho.

## Decisões do dono

- 10/11/2026, os comandos: pelos dois caminhos, `-- <comando>` para um e `--comandos <arquivo>` para vários.
  - O arquivo fica fora da pasta da rodada, e o script o copia para dentro.
  - A pasta que já existe é erro.
  - Os dois juntos, ou nenhum, é erro antes de subir a sessão.
  - Um comando por linha, pelo `shlex.split`; linhas vazias e as que começam com `#` são ignoradas; coisa do shell como
    palavra solta é erro na leitura.
  - Se um comando falha, os seguintes não rodam, e o `FIM` é gravado com o status.
  - A repetição da CC.102 era um laço do `rodar.sh`, que dava a cada volta a sua `--pasta` (`vez_$i`). Daí o
    `--repetir N` com `{vez}`, cada volta numa saída numerada.
- 10/11/2026, a execução real à mão: não usa o script por ora. O `docs/producao.md` não muda, e a decisão volta depois do
  merge, quando o script já tiver uso nas rodadas de teste e na integração.
- 10/11/2026, ajustes ao plano:
  - (A) a rodada se marca como dona da sessão antes do `systemctl start`: uma subida que falha no meio, ou a GPU que não
    passa, também é parada;
  - (B) o vigia que morre por exceção para a sessão, e a rodada não segue sem ele (status 1);
  - (C) recusar também a forma colada (`>saida.txt`, `2>erro`, `&>tudo`, `<entrada`), só no arquivo, e documentar que nada
    é expandido;
  - (D) caminhos relativos resolvidos contra a raiz da worktree do script, e a recusa do `/tmp` no caminho resolvido;
  - (E) `--repetir` sem nenhum `{vez}` é erro de argumento.
- Confirmados: um bloqueio do sono para a rodada inteira com `tail --pid` (desvio do texto original, que pedia um
  `systemd-inhibit` por comando) e os dois commits, o do código e o dos documentos depois do aceite. O segundo vem antes
  do avanço da `testes`.

## Testes

`tests/test_rodada.py`, 49 testes. O `systemctl`, o `nvidia-smi` e o `systemd-inhibit` são falsos (scripts no `PATH`,
com o estado das units em arquivos), e a memória também; os comandos são processos Python inofensivos. Os testes cobrem:
- a sessão sempre para, também nestes casos:
  - um comando que falha ou que não existe;
  - uma subida que falha no meio;
  - a GPU que não passa;
  - uma interrupção por SIGINT, SIGTERM ou SIGHUP, no mesmo processo e num processo novo, onde o Ctrl+C vai ao grupo,
    como no terminal. O comando recebe um único SIGINT e não fica vivo, o bloqueio é solto e os tratadores de sinal de
    antes voltam;
- o `FIM` sempre é gravado depois que a pasta existe;
- o vigia para a sessão abaixo do limite durante um comando;
- o vigia que morre por exceção, ou com a memória ilegível, também para a sessão. Depois de qualquer um dos dois, nenhum
  comando novo começa;
- com a sessão de teste ou a `ollama.service` já ativas, ou sem o driver da NVIDIA, a rodada não começa, não cria a pasta
  e não para nada;
- com o bloqueio do sono recusado, a sessão não sobe;
- a sessão que não para dá status 1;
- os erros de argumento, a coisa do shell no arquivo (solta e colada), nada expandido, `--repetir` e `{vez}`, e a recusa
  do `/tmp` através de um link.

Prova por mutação temporária (10/11): 12 defeitos postos um de cada vez no `rodada.py`, e todos derrubaram os testes que
dizem pegá-los:
- a dona da sessão marcada depois da GPU;
- a limpeza sem parar a sessão;
- o `FIM` só com status 0;
- o vigia cego à memória baixa;
- o vigia morto sem parar a sessão;
- a rodada seguindo com o vigia morto;
- a sessão de outra rodada não conferida;
- a forma colada aceita;
- `--repetir` sem `{vez}` aceito;
- o comando interrompido sem o SIGINT;
- os tratadores de sinal não restaurados;
- a sessão que não para dando status 0.

O arquivo voltou idêntico (sha256 conferido).

## Aceite separado

- A suíte inteira e o `ruff check .`.
- Uma rodada de verdade sem carga do modelo, pedida ao dono, em duas partes:
  - (a) um arquivo com `ollama ps`, `systemd-inhibit --list --no-pager` e `false`. Esperado: para no terceiro com status
    1, a sessão `inactive` no fim e o bloqueio TechDigest na saída do segundo;
  - (b) `-- sleep 300`, interrompido com `kill -INT` no processo do `rodada.py`. Esperado: status 130, a sessão parada e
    o `sleep` morto.
- O primeiro uso com o modelo é o teste conjunto da frente 0 (a simulação com áudio pelo `rodada.py`) ou a próxima rodada
  que o dono pedir.
- Esta worktree não tem `data/agrupamento` (o link para a pasta principal das outras worktrees). Para o aceite, a
  `--pasta` vai como caminho absoluto em `/home/sytw/Projetos/techdigest/data/agrupamento/`, ou o dono cria o link.

## Documentação

- `docs/referencia/scripts.md`: a seção do `rodada.py` e uma frase no item dos testes (feito).
- `CLAUDE.md`, "Commands": uma linha e o `rodada.py` na lista dos manuais (feito).
- A skill `techdigest-rodada-modelo` e as armadilhas do zsh, na integração, pela frente 0. Texto proposto abaixo.

### Proposta para a skill (frente 0, na integração)

Os passos 4 a 11 viram uma chamada do script:

> 4. Comandos: um só vai depois de `--`; vários, num arquivo fora da pasta da rodada (um por linha, sem shell: nada de
>    `|`, `;`, `&&` nem redirecionamento, e nada é expandido). Para repetir, `--repetir N` com `{vez}` na pasta de saída
>    de cada volta (`--pasta <nome>/vez_{vez}` no `testar_episodio.py`).
> 5. Mostre o plano da rodada e espere a aprovação: o que roda, quantas chamadas e o tempo estimado (cerca de 2 minutos
>    por geração no modelo local).
> 6. A rodada, em segundo plano, da worktree que a pediu:
>    `.venv/bin/python scripts/rodada.py --pasta data/agrupamento/<nome>_<AAAAMMDD> --pedido "<pedido do dono, data>" -- <comando>`
>    (ou `--comandos <arquivo>`). O script confere a sessão e o `nvidia-smi`, cria a pasta (que não pode existir) com o
>    `andamento.txt`, bloqueia o sono, liga o vigia, sobe a sessão, confere `library=CUDA`, roda e, sempre, para a sessão
>    e grava o `FIM`. Acompanhe pelo `andamento.txt`, sem conferir a cada poucos segundos. Os freios da máquina dos
>    scripts param a rodada sozinhos: não os contorne.
> 7. No fim, leia o `FIM`: o status, a memória mínima, cada comando e a sessão. Se ele disser "CONTINUA NO AR", pare-a
>    com `systemctl --user stop techdigest-teste.target` e confira com `is-active`.

Os passos 1 a 3 (nenhuma outra rodada, a GPU e a pasta fora do `/tmp`) o script confere, mas continuam valendo como
leitura antes de pedir a rodada. As armadilhas do zsh não valem dentro do script, que não usa shell; continuam valendo
para os comandos avulsos da sessão.

## Prompt inicial para o Claude Code

```text
Frente 7 (rodada em Python) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-rodada, branch
melhoria/rodada. Leia docs/plano-melhorias.md, docs/melhorias/07-rodada.md, docs/regras-de-sessao.md e a skill
techdigest-rodada-modelo.
Primeiro, só leitura: o vigia_memoria.sh e o rodar.sh da rodada mais recente em
/home/sytw/Projetos/techdigest/data/agrupamento/, ai/gpu.py, ai/maquina.py e deploy/systemd/. Não suba a sessão de teste.
Depois me pergunte as decisões do arquivo da frente e apresente o plano, com a lista "Leituras minhas, para você
corrigir". Espere a aprovação.
Trabalhe só nesta worktree e nesta branch, sem push e sem commit de src/techdigest.egg-info. A cada commit, a suíte
inteira e a seção "Estado" de docs/melhorias/07-rodada.md atualizada.
```

## Estado

- 07/11/2026: não começada.
- 10/11/2026: aceite separado pendente. Branch `melhoria/rodada`, criada da `testes` em `3e1045e`; o commit do código é
  este (`scripts/rodada.py`, `tests/test_rodada.py`, `docs/referencia/scripts.md`, `CLAUDE.md` e este arquivo).
  - Verificação: 802 testes passam (753 da `testes` e 49 novos), o `ruff check .` não dá aviso e o `uv sync --locked
    --check --extra dev` dá `Would make no changes`. A prova por mutação está em "Testes".
  - Decisões do dono de 10/11: em "Decisões do dono". Nada foi subido, instalado nem rodado com o modelo.
  - Pendências:
    - o aceite separado (a rodada sem modelo, pedida ao dono);
    - o commit de documentos com o resultado do aceite, antes do avanço da `testes`;
    - a skill, pela frente 0 na integração.

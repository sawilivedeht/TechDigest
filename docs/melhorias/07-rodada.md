# Frente 7: rodada em Python

Arquivo no Projeto: `claude/frentes/07-rodada.md` · no repositório: `docs/melhorias/07-rodada.md`

| | |
|---|---|
| Branch | `melhoria/rodada` |
| Worktree | `/home/sytw/Projetos/techdigest-rodada` |
| Onda | 2 |
| Depende de | nada; o primeiro uso com o modelo pode ser a calibração da frente 5 |
| Conflita com | frente 5 em `docs/referencia/scripts.md` |

## Objetivo

Um script versionado e testado para as rodadas com o modelo, no lugar do `vigia_memoria.sh` e do `rodar.sh` copiados e
editados a cada rodada.

## Por que

A skill `techdigest-rodada-modelo` monta cada rodada à mão: copia o `vigia_memoria.sh` da rodada anterior e troca o `R=`;
escreve um `rodar.sh` novo (`set -u`, `cd`, `PYTHONUNBUFFERED`, `anota` no `andamento.txt`, `touch FIM` também na falha);
sobe e para a sessão de teste; roda tudo sob `systemd-inhibit`. Ela também lista quatro armadilhas do zsh desta máquina.
Nada disso está no git, e esquecer de parar a sessão de teste deixa o Ollama no ar.

## Como fica

`scripts/rodada.py --pasta <data/agrupamento/nome_AAAAMMDD> --pedido "<texto>" -- <comando> [args...]` (ou um arquivo com
um comando por linha, se o dono preferir):
1. Confere: sessão de teste `inactive`; `nvidia-smi` responde (`ai/gpu.driver_da_nvidia`).
2. Cria a pasta e o `andamento.txt`, com o pedido, a data, o commit (`git rev-parse --short HEAD`) e os comandos.
3. Sobe a sessão de teste e confere `library=CUDA` no log da unit (`ai/gpu.placas_do_ollama`).
4. Liga o vigia numa thread, com `ai/maquina.memoria_disponivel()`: anota o mínimo em `vigia_memoria.log` e, abaixo de
   3 GiB (o limite de hoje), para a sessão de teste.
5. Roda cada comando sem deixar a máquina dormir (`systemd-inhibit --what=sleep:idle`), com a saída de cada um num arquivo
   da pasta e uma linha no `andamento.txt` no começo e no fim.
6. Num `finally`: para a sessão de teste, confere `inactive`, grava o `FIM` (com o status) e imprime o resumo (memória
   mínima, duração e status de cada comando).

Os freios da máquina dos scripts continuam valendo; o script não os contorna.

## Decisões do dono

- Comandos como argumentos ou num arquivo.
- Se a execução real à mão (`docs/producao.md`) também passa a usar o script, o que daria a ela o vigia que hoje não tem. O
  pipeline continua sendo rodado só pelo dono.

## Testes

Com `systemctl`, `nvidia-smi`, a memória e os comandos falsos:
- a sessão de teste sempre para, também com erro no comando e com interrupção (Ctrl+C);
- o `FIM` sempre é gravado;
- o vigia para a sessão abaixo do limite;
- com a sessão de teste já ativa, o script não começa.

## Aceite separado

- A suíte inteira.
- Uma rodada de verdade com um comando que não chama o modelo (sobe e para a sessão de teste, sem carga), pedida ao dono.
- O primeiro uso com o modelo pode ser a calibração da frente 5.

## Documentação

- `docs/referencia/scripts.md`: uma seção sobre o `rodada.py`.
- `CLAUDE.md`, "Commands": uma linha.
- A skill `techdigest-rodada-modelo` (os passos 4 a 11 viram uma chamada do script) e as armadilhas do zsh: na integração,
  pela frente 0.

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

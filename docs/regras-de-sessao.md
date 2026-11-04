# Regras de sessão

Regras do dono para toda sessão e todo worker neste repositório. O `CLAUDE.md` importa este
arquivo, e a pasta principal o importa pelo `CLAUDE.local.md`. Uma regra muda aqui, num commit,
e não no texto de cada tarefa. Quando a fase mudar, troque o nome da branch abaixo.

## Sempre

- Não rode o pipeline (a simulação, só quando a tarefa pedir), não envie nada ao Telegram, não
  chame `mark_seen` no banco de produção e não altere `OLLAMA_NUM_CTX`.
- Testes e commit na `agrupamento-fase4`, sem push e sem merge na `master`.
- Chamada ao modelo só com a sessão de teste no ar (`systemctl --user start
  techdigest-teste.target`), sob `systemd-inhibit --what=sleep:idle` e com o vigia de memória.
  Antes, confira o `nvidia-smi` e a linha `library=CUDA` no log da unit. No fim, pare a sessão.
  O passo a passo está na skill `techdigest-rodada-modelo`.
- Os exemplos dos prompts que o modelo lê são inventados: nenhum nome, pergunta, número ou
  situação tirados das amostras, e nenhum veículo que exista. Antes de pôr um exemplo novo,
  confira cada nome com grep em todas as amostras, não só nas antigas:
  `grep -lF "<nome>" data/agrupamento/amostra_*.json` (a lista cresce a cada coleta). Testes e
  documentação podem usar nomes reais, porque o modelo não os lê.
- Uma regra nova que reprova passa antes pelo diagnóstico; uma que relaxa pode entrar direto.
- Antes de editar, apresente um plano curto com a lista "Leituras minhas, para você corrigir" e
  espere a aprovação.

## Bloqueado nas permissões

O `.claude/settings.json` recusa `git push`, o pipeline rodado sem `--simular` e qualquer edição
do `.env`. O bloqueio pega a forma comum do comando, não todas as variações: a regra escrita
continua valendo.

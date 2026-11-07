# Regras de sessão

Regras do dono para toda sessão e todo worker neste repositório. O `CLAUDE.md` importa este
arquivo, e a pasta principal o importa pelo `CLAUDE.local.md`. Uma regra muda aqui, num commit,
e não no texto de cada tarefa. A branch `trabalho`, na worktree `techdigest-fase4`, continua para o
trabalho do roteiro; as melhorias seguem a seção abaixo.

## Sempre

- Não rode o pipeline (a simulação, só quando a tarefa pedir), não envie nada ao Telegram, não
  chame `mark_seen` no banco de produção e não altere `OLLAMA_NUM_CTX`.
- Testes e commit na branch da worktree (a `trabalho` para o roteiro; a da frente para as
  melhorias), sem push. Merge na `master` só com o ok do dono, por avanço rápido (fast-forward).
- Antes de qualquer avanço rápido na `master`, compare o `pip freeze` das duas `.venv` (a da pasta principal e a da
  worktree de onde vem o avanço: a `techdigest-fase4` no roteiro, a `techdigest-testes` nas melhorias): em 05/11 uma
  versão diferente do edge-tts derrubou a primeira execução real.
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

## Melhorias em frentes paralelas (desde 07/11/2026)

- Cada melhoria é uma frente, com branch `melhoria/<nome>` e worktree `/home/sytw/Projetos/techdigest-<nome>`. O plano
  está em `docs/plano-melhorias.md` e o estado de cada frente em `docs/melhorias/`.
- A sessão trabalha só na worktree e na branch da sua frente: nunca na pasta principal, na `master`, na `trabalho` ou na
  branch de outra frente.
- Só os arquivos do escopo da frente. Nenhuma mudança de estilo em massa (formatador, ordem dos imports) enquanto houver
  frente aberta.
- Nos documentos compartilhados (`CLAUDE.md`, `docs/producao.md`, este arquivo, `docs/referencia/`), só o trecho do
  assunto da frente. O estado de produção do `CLAUDE.md`, as skills e o `CLAUDE.local.md` mudam só na integração.
- Sem commit de `src/techdigest.egg-info` até a frente 2 decidir.
- A cada commit, a suíte inteira passa e a seção "Estado" do arquivo da frente é atualizada.
- Uma rodada com o modelo por vez na máquina inteira, e nenhuma durante a execução real do dono:
  `systemctl --user is-active techdigest-teste.target` deve dar `inactive` antes.
- A produção só é lida: logs e registros da pasta principal, por caminho absoluto. As pastas de medição e de rodada
  continuam em `data/agrupamento/` da pasta principal.
- A integração é só pela branch `testes`, da frente 0. A `master` recebe a `testes` por avanço rápido, com o ok do dono.

# Execução real à mão

Para o dono. Só você roda isto: as sessões do Claude Code não rodam o pipeline, que entrega no Telegram e marca as
notícias como vistas em `data/digest.db`. Não há timer; cada execução sai deste passo a passo.

## Antes

1. A `master` e a `.venv` da pasta principal (`/home/sytw/Projetos/techdigest`) são as que rodam. Depois de qualquer
   atualização da `master`, compare as versões instaladas nas duas pastas
   (`diff <(.venv/bin/pip freeze) <(../techdigest-fase4/.venv/bin/pip freeze)`): em 05/11 o edge-tts 7.2.8 da produção
   derrubou a execução inteira (403) enquanto a simulação passava com o 7.3.1.
2. Nenhuma outra rodada no ar: `systemctl --user is-active techdigest-teste.target` deve dar `inactive`. O pipeline também
   recusa começar (e avisa no Telegram) se a trava do modelo estiver ocupada.
3. `nvidia-smi` tem de responder. Se não responder, não suba nada: sem GPU a carga do modelo esgota a memória.

## Rodar

1. Suba o Ollama pela unit, nunca com `ollama serve` à mão:
   `systemctl --user start techdigest-teste.target`
2. Confira a GPU no log da unit:
   `grep "inference compute" ~/.local/state/techdigest/ollama_serve.log | tail -1` deve trazer `library=CUDA`. Sem essa
   linha o pipeline para antes de carregar o modelo (foi o que aconteceu nas tentativas de 07/11 à 0h55).
3. Na pasta principal, a execução, sem deixar a máquina dormir:
   `cd /home/sytw/Projetos/techdigest && systemd-inhibit --what=sleep:idle --who=TechDigest --why="execucao real" .venv/bin/techdigest`
   Sempre pelo `techdigest` (ou `python -m techdigest`), que liga o log em arquivo. Uma execução de 20 itens leva
   uns 60 a 110 minutos; nenhum item novo começa depois de 180 minutos.
4. Quando terminar, ou quando falhar, pare a sessão: `systemctl --user stop techdigest-teste.target` e confira com
   `is-active`.

## Depois

- Resumo da execução: `.venv/bin/python scripts/resumo_lotes.py` (do dia; `07/11` para outro dia; `--log <arquivo>`).
  Mostra entregues, pulados pelo QA, filtrados, abandonados, feeds fora da coleta e paradas.
- Status de saída 1 quer dizer que a execução parou: trava ocupada, freio da máquina (memória, temperatura, GPU), erro
  inesperado, falhas seguidas de entrega ou todos os feeds fora. Nesses casos chega um aviso curto no chat do Telegram;
  o que não foi entregue volta na próxima execução. Se a causa foi o Ollama subido à mão, comece de novo pelo passo 1.
- Item reprovado pelo QA em 2 execuções é abandonado (`reprovacoes` no banco).

## Onde ficam os registros

| O quê | Onde |
|---|---|
| Log da execução | `data/logs/techdigest.log` (rotativo, 2 MB x 7) |
| Registro de cada execução | `data/execucoes/<data-hora>/`: `amostra.json`, `relatorio_<data-hora>.json` e um JSON por episódio (30 dias) |
| Áudio e texto entregues | `data/audio/<slug>.mp3` |
| Banco de notícias vistas | `data/digest.db` (não editar à mão) |
| Log do Ollama e trava do modelo | `~/.local/state/techdigest/` |

Chaves em vigor: `AGRUPAMENTO_ATIVO=false` e `DISPUTA_FONTE_UNICA=false`. Ligar qualquer uma depende do dono
(`docs/roteiro-fase4.md`).

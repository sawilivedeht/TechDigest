# Frente 8: JSON incompleto e schema

Arquivo no Projeto: `claude/frentes/08-schema.md` · no repositório: `docs/melhorias/08-schema.md`

| | |
|---|---|
| Branch | `melhoria/schema` |
| Worktree | `/home/sytw/Projetos/techdigest-schema` |
| Onda | 1 (medição, só leitura) e 3 (experimento) |
| Depende de | a medição decide se o experimento acontece; o experimento espera a frente 6 integrada (`config.py`) |
| Conflita com | frente 6 no `config.py` |

## Objetivo

Saber, com números, quantas chamadas ao modelo são refeitas por JSON incompleto e, se valer, testar o JSON Schema no
`format` do Ollama.

## Por que

- As chamadas ao Ollama pedem `format="json"` (`OllamaProvider._pedido`, em `src/techdigest/ai/llm.py`). O `SCHEMA` do mesmo
  arquivo só serve para listar as 8 chaves do episódio (`REQUIRED_KEYS`).
- Desde 30/10, o `Summarizer._chamar_inteiro` refaz uma vez a chamada da geração ou de uma correção que volta com JSON sem
  todas as chaves (`JSONIncompleto`). O log registra `JSON incompleto (...): nova tentativa da mesma chamada.` e o relatório
  conta por item em `json_incompleto_refeito`.
- Cada chamada refeita é uma chamada a mais ao modelo; a da geração leva uns 95 s nas medidas de 14/10.

## Etapa 1: medição (só leitura, onda 1)

- Somar `json_incompleto_refeito` nos relatórios de `/home/sytw/Projetos/techdigest/data/execucoes/*/relatorio_*.json` (a
  produção dos últimos 30 dias) e nos das simulações, se houver.
- Contar as linhas `JSON incompleto` no log da produção e nos rotacionados, com as chaves que faltaram (a mensagem as
  traz), para saber que chamada falha mais.
- Resultado: refeitas por execução e por item, que chamada e o tempo estimado. O script fica fora do git, em
  `/home/sytw/Projetos/techdigest/data/agrupamento/medicao_json_incompleto_20261107/`.

Decisão do dono: se for raro (menos de uma por execução, por exemplo), a frente fecha com o número registrado aqui. Se for
frequente, etapa 2.

## Etapa 2: experimento (onda 3, com rodadas)

- Uma chave nova (por exemplo `OLLAMA_FORMATO=json|schema`, padrão `json`) que passa no `format` o JSON Schema da chamada: o
  do episódio e os das correções (título, resumo, roteiro, revisão).
- A/B com o `scripts/testar_episodio.py` na mesma amostra, 2 ou 3 repetições de cada lado: refeitas, aprovação no QA, tempo
  por item e o `scripts/checar_fidelidade.py`.
- O caminho OpenAI não muda.
- A medir: a decodificação com gramática pode mudar o texto e a velocidade. E não resolve a resposta cortada pela janela.

## Aceite separado

- Etapa 1: os números neste arquivo e a decisão do dono.
- Etapa 2: a suíte inteira, com a chave desligada mudando nada; o A/B com os números; a decisão do dono de ligar ou não.

## Prompt inicial para o Claude Code

```text
Frente 8 (JSON incompleto e schema) das melhorias de 07/11. Você está na worktree /home/sytw/Projetos/techdigest-schema,
branch melhoria/schema. Leia docs/plano-melhorias.md, docs/melhorias/08-schema.md e docs/regras-de-sessao.md.
Agora só a etapa 1, só leitura e sem mudar código: some o json_incompleto_refeito nos relatórios de
/home/sytw/Projetos/techdigest/data/execucoes/ e conte as linhas "JSON incompleto" no log da produção
(/home/sytw/Projetos/techdigest/data/logs/techdigest.log e os rotacionados .1 a .7), com as chaves que faltaram. O script
fica em /home/sytw/Projetos/techdigest/data/agrupamento/medicao_json_incompleto_20261107/, fora do git.
Me mostre os números (por execução, por item e por chamada) e o tempo estimado que essas chamadas custam, e espere a
decisão. Nada de mudar código nesta etapa e nada de chamar o modelo.
```

## Estado

- 07/11/2026: não começada.
- 10/11/2026: **fechada** na etapa 1. Decisão do dono de 10/11: fechar com os números abaixo; a etapa 2 (o JSON Schema no
  `format`) não acontece.
  - Branch `melhoria/schema`, levada por avanço rápido à `testes` em `3e1045e`; este commit é só deste arquivo. A `.venv`
    foi refeita pelo lock (`uv sync --locked --extra dev`; o `--check` dá `Would make no changes`); a antiga ficou em
    `.venv.pip-20261110`, ignorada pelo git. 753 testes passam e o `ruff check .` não dá aviso.
  - Motivo: nenhuma chamada refeita por JSON incompleto em lugar nenhum. Na produção, 0 em 109 itens desde que a nova
    tentativa chegou lá (merge de 05/11), e nenhuma resposta sem chaves nos 491 itens do log inteiro (05/10 a 07/11). O
    único caso registrado é o C3.48 da regressão de 29/10, numa rodada, antes da nova tentativa. É bem menos que uma por
    execução: o custo projetado é de uns 2 s por execução de 20 itens, no pior caso.
  - Pasta da medição (fora do git): `/home/sytw/Projetos/techdigest/data/agrupamento/medicao_json_incompleto_20261107/`,
    com `medir.py` (só leitura, sem modelo: `python3 -I medir.py --json <arquivo>`), `saida_20261110.txt` (a saída
    inteira) e `resultado_20261110.json`.
  - Pendências: nenhuma. A worktree, a branch e a `.venv.pip-20261110` ficam até a frente 0 dizer.

### Medição de 10/11/2026

Fontes, só lidas:

- Produção: os relatórios `/home/sytw/Projetos/techdigest/data/execucoes/*/relatorio_*.json` (10, de 05/11 e 07/11: o
  registro de cada execução entrou com o merge de 05/11) e o log `/home/sytw/Projetos/techdigest/data/logs/techdigest.log`,
  de 05/10 18:39 a 07/11 01:01, com 53 inícios (por dia: 05/10 10, 06/10 8, 07/10 18, 11/10 4, 21/10 2, 26/10 1, 05/11 4,
  07/11 6). Os rotacionados `.1` a `.7` não existem: o log tem 1,6 MB e a rotação é aos 2 MB.
- Simulações: as 6 da worktree `techdigest-fase4` (`data/simulacoes/*/execucoes/` e `*/logs/`), de 25/10 a 04/11. A pasta
  principal não tem nenhuma.
- Rodadas dos scripts: os 36 relatórios de `/home/sytw/Projetos/techdigest/data/agrupamento/`, de 11/10 a 03/11.
- Contraprova por grep em todos os `data/` (pasta principal, `techdigest-fase4` e `techdigest-testes`): "JSON incompleto",
  "sem as chaves" e um `json_incompleto_refeito` diferente de zero só aparecem no C3.48, em cópias de código e em
  documentos.

O que se conta: o `json_incompleto_refeito` de cada episódio dos relatórios; nos logs, as linhas `JSON incompleto (...)`
(a nova tentativa, desde 30/10) e as `sem as chaves` (a mesma resposta antes de 30/10, quando ela derrubava o item), com a
chamada em que apareceram (análise de lados, geração ou qual correção), pela ordem das linhas de cada item.

**Por execução, a partir de 30/10** (a nova tentativa entrou na branch em 30/10 e na produção com o merge de 05/11):

| Grupo | Execução | Itens | Chamadas ao modelo | `json_incompleto_refeito` | Linhas "JSON incompleto" | Como terminou |
|---|---|---|---|---|---|---|
| Produção | 05/11 06:40 | 0 | 0 | 0 | 0 | interrompida antes de carregar o modelo: log do Ollama de outra subida |
| Produção | 05/11 06:41 | 0 | 0 | 0 | 0 | idem |
| Produção | 05/11 06:42 | 0 | 0 | 0 | 0 | interrompida: o Ollama não estava rodando |
| Produção | 05/11 06:44 | 89 | 197 | 0 | 0 | nenhuma entrega em 181 min (edge-tts com 403): 88 falharam, 1 reprovado |
| Produção | 07/11 00:55 | 0 | 0 | 0 | 0 | interrompida: o Ollama não estava rodando |
| Produção | 07/11 00:56 | 0 | 0 | 0 | 0 | interrompida: log do Ollama de outra subida |
| Produção | 07/11 00:57:16 | 0 | 0 | 0 | 0 | interrompida: log do Ollama sem a linha `inference compute` |
| Produção | 07/11 00:57:56 | 0 | 0 | 0 | 0 | idem |
| Produção | 07/11 00:58 | 0 | 0 | 0 | 0 | idem |
| Produção | 07/11 01:01 | 20 | 45 | 0 | 0 | 20 entregues em 59 min, todos aprovados |
| Simulação | 04/11 22:33 (`merge_20261104`) | 23 | 49 | 0 | 0 | 20 entregues em 61 min, 3 reprovados |
| Rodada | 03/11 19:50 (`validacao_20261103/coleta_4`) | 22 | — | 0 | — | 21 aprovados, 1 reprovado |
| Rodada | 03/11 20:37 (`validacao_20261103/complementar`) | 4 | — | 0 | — | 4 aprovados |

Nas rodadas, a saída gravada não traz a linha de métricas de cada chamada (por isso o "—"); o `resultado.md` da validação
de 03/11 já dizia "Nenhuma chamada refeita por JSON incompleto".

**Por grupo**, em todas as execuções lidas:

| Grupo | Período | Execuções | Itens | Itens com a nova tentativa (desde 30/10) | Chamadas refeitas | Respostas sem chaves que derrubaram o item |
|---|---|---|---|---|---|---|
| Produção | log de 05/10 a 07/11; relatórios de 05/11 e 07/11 | 53 inícios no log (29 com chamada ao modelo); 10 relatórios | 491 | 109 | 0 | 0 |
| Simulações | 25/10 a 04/11 | 6 (5 antes de 30/10) | 128 | 23 | 0 | 0 |
| Rodadas | 11/10 a 03/11 | 36 relatórios (34 antes de 30/10) | 266 | 26 | 0 | 1 (o C3.48) |
| Total | | | 885 | 158 | 0 | 1 |

- Na produção, os itens são as linhas `Resumindo:` do log: 382 de 05 a 26/10 (a mesma contagem da medida de 30/10, em
  `correcoes_20261030/resultado_medida.md`) e 109 em 05/11 e 07/11. Nas simulações, os 128 episódios dos relatórios são as
  128 linhas `Resumindo:` dos logs delas; nas rodadas, os 266 episódios dos relatórios.
- **Relatórios e logs batem.** Os 2 relatórios da produção com episódios têm 89 + 20 = 109 episódios, os mesmos 109 itens
  do log naquelas datas, e os dois lados dão 0. A simulação de 04/11 dá 23 e 23, também com 0. O C3.48 está no relatório
  (`regressao_20261029/coleta_3/relatorio_20261029-233342.json`, episódio 5) e na saída de texto da mesma rodada: é um
  evento só, citado em 4 arquivos.
- **O C3.48** ("Reddit traz o feed 'Para Você'", regressão de 29/10, coleta 3): a geração fechou o JSON depois de
  `titulo_reescrito` e `resumo_didatico` e deixou de fora as outras 6 chaves (`fontes_citadas`, `houve_divergencia`,
  `personagens`, `pontos_chave`, `por_que_importa`, `roteiro_podcast`). A chamada levou 21 s. É o caso que fez a nova
  tentativa entrar em 30/10.
- **Por chamada:** sem nenhum evento desde 30/10, não há o que dividir entre a geração e as correções; o único caso (C3.48)
  foi na geração.
- Fora da contagem: na produção, 108 gerações para 109 itens. O item que falta ("'Devolveram esperança ao mundo'...", 05/11
  09:32) falhou na geração com `RuntimeError: Ollama respondeu HTTP 500: prediction aborted, token repeat limit reached`,
  que não é JSON incompleto e não passa pela nova tentativa.

**Tempo por chamada**, desde 30/10: o `total=` da linha de métricas do Ollama (gemma4:26b), em segundos. A análise de
lados tem a sua própria nova tentativa e não passa pelo `_chamar_inteiro`; está aqui para comparação.

| Chamada | Produção: n | mediana | média | máx | Simulação: n | mediana | média | máx |
|---|---|---|---|---|---|---|---|---|
| Análise de lados | 114 | 20,4 | 20,9 | 34,3 | 23 | 22,2 | 22,5 | 41,4 |
| Geração | 108 | 88,2 | 86,4 | 106,7 | 23 | 88,2 | 86,9 | 101,5 |
| Revisão (completa) | 4 | 65,5 | 65,4 | 78,8 | 2 | 72,3 | 72,3 | 76,1 |
| Revisão do roteiro | 14 | 50,8 | 49,4 | 59,5 | 1 | 49,7 | 49,7 | 49,7 |
| Correção do resumo | 1 | 20,0 | 20,0 | 20,0 | 0 | — | — | — |
| Correção do título | 1 | 5,1 | 5,1 | 5,1 | 0 | — | — | — |

**Tempo das chamadas refeitas:** medido, 0 s. Um evento custaria a chamada que voltou incompleta: de uns 21 s (um JSON
fechado cedo, como o C3.48) a uns 88 s (uma geração inteira); numa correção, de 5 s (título) a uns 65 s (revisão). Com a
taxa observada, 1 caso em 885 itens (e 0 nos 158 com a nova tentativa), dá uns 0,1 s por item, uns 2 s por execução de
20 itens se cada caso custasse uma geração inteira.

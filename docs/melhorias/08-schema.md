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

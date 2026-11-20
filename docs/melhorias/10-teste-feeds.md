# Frente 10: teste de feeds

No repositório: `docs/melhorias/10-teste-feeds.md`

| | |
|---|---|
| Branch | `melhoria/teste-feeds`, nascida da `master` em `8a250b6` |
| Worktree | `/home/sytw/Projetos/techdigest-teste-feeds`, com o link `data/agrupamento` para a pasta principal e o `.env` da produção copiado pelo dono |
| Onda | fora das ondas (20/11/2026) |
| Integração | direta: rebase sobre a `master`, a suíte, o `ruff check .` e o pyright; o dono faz o avanço rápido |
| Fora do escopo | `config/feeds.txt`, `pipeline.py` e `ai/`: a troca de feeds é um commit à parte, com o `FEEDS_DO_REPOSITORIO` de `tests/test_feeds.py`, depois do ok do dono |

## Objetivo

Aprovar ou reprovar os feeds candidatos ao `config/feeds.txt` (`config/feeds_candidatos.txt`: categoria, subcategoria,
nome, idioma e URL) testando cada um pelo caminho que o pipeline usa de verdade.

- Etapa 1, sem o modelo: `scripts/testar_feeds.py`, com as funções do pacote (a coleta, o filtro, a extração, a forma
  falada do veículo e a leitura dos números). Os critérios estão no começo do script. Saída em
  `data/agrupamento/feeds_<AAAAMMDD>/`: `etapa1.csv` e `etapa1.md`.
- Etapa 2, com o modelo e só com o ok do dono: a simulação sem áudio, com o `RSS_FEEDS` do lote no ambiente, em lotes de
  até 10 feeds, só para os APROVADO e ETAPA 2 da etapa 1; `scripts/testar_feeds.py --simulacao <pasta>` lê o registro de
  cada execução e escreve o `etapa2.md`.

## Decisões do dono

- 20/11/2026, plano aprovado com estas correções:
  1. A worktree tem o link `data/agrupamento`, como as outras, e o `.env` da produção, que o dono copia antes da etapa 1:
     a etapa 1 usa os limites reais, e o `etapa1.md` mostra os valores usados.
  2. Na coluna "nome" dos candidatos, nomes latinos no lugar dos ideogramas (ifanr, GeekPark, QbitAI, TMTPost, IThome,
     sspai, China News Service): é o que `qa._palavras_do_nome` enxerga e o que o episódio consegue dizer. O título do
     feed em ideogramas continua dando AJUSTE.
  3. Critério 9, só aviso: a sobreposição com o Google Notícias. Com `AGRUPAMENTO_ATIVO=false` (conferido nos
     registros da produção: nenhum relatório tem `etapa3`, e todos os episódios são `fonte_unica`), o pipeline marca
     como visto só o link do feed e confere só ele: a mesma matéria pelo Google Notícias e pelo feed direto vira dois
     episódios. O script mede, nos `amostra.json` da produção, as matérias vindas do Google Notícias com a URL resolvida
     num host do candidato.
  4. Na etapa 2, as linhas "Feed OK" do log casam pelo título do feed que a etapa 1 anotou, não pela ordem do lote, e os
     filtrados pelos hosts dos links que a etapa 1 viu em cada feed. Problema de veículo por título genérico ou em
     ideogramas não conta contra o feed: vai para a pendência do nome fixo.
  5. A simulação roda da worktree, com o `.env` copiado; a pasta principal fica só para leitura.
  6. Integração direta, sem a `testes`.
  7. A frente fica registrada no `docs/plano-melhorias.md` (as linhas dela) e no "Commands" do `CLAUDE.md`.
  8. Pendências, além das do pedido (nome fixo por feed, leitura de números de outros idiomas em `ai/numeros.py`, cota
     por categoria, deduplicar também pela URL resolvida): o "3.5%" que `numeros()` lê como 3 e 5% e o "$1,200" que lê
     como 1,2 (valores falsos da fonte afrouxam o QA), e a forma falada vazia de `qa._formas_faladas` para um nome sem
     letras latinas.
- Leituras confirmadas no plano: o host sem "www." é o "domínio" do critério 3 (`tek.sapo.pt`, `pplware.sapo.pt` e
  `eco.sapo.pt` são veículos diferentes) e o mesmo host em dois candidatos é só aviso; a extração reprova com menos de
  60% dos extraídos com texto (3 de 5); o idioma vai para a etapa 2 quando a coluna ou o texto não é pt-BR, e o
  português sem marca que decida conta como pt-BR quando a coluna diz pt-BR; só as expressões com escala levam à etapa
  2, e os formatos de algarismo de outros idiomas ("1.5", "1,200", "12 000") ficam no relatório; o robots.txt do feed
  vale para o User-Agent da coleta e o das matérias para o do trafilatura, que é o que a extração manda.

## Testes

`tests/test_testar_feeds.py`, sem rede: o feed é um RSS escrito no teste e lido pelo feedparser de verdade; a extração e
o robots.txt são falsos. Cada veredito, cada motivo de reprovação (erro HTTP, tempo esgotado duas vezes, sem entradas,
XML quebrado, item sem data, itens antigos, URL e host repetidos, site de partido no feed, nos links e na URL resolvida,
texto curto), cada aviso, a pausa entre as requisições, o título genérico e em ideogramas, "1.5 billion", o chinês, o
português de Portugal, a sobreposição com o Google Notícias numa amostra falsa e a saída do `main`.

## Estado

- 20/11/2026: plano aprovado pelo dono, com as correções acima. Worktree criada da `master` em `8a250b6`, com o link
  `data/agrupamento`; `uv sync --locked --check --extra dev` deu `Would make no changes`; de partida, 869 testes
  passando, `ruff check .` sem avisos e pyright com 0 erros.
- 20/11/2026: etapa 1 escrita (commit desta linha): `config/feeds_candidatos.txt` (61 feeds), `scripts/testar_feeds.py`
  e `tests/test_testar_feeds.py` (42 testes). Suíte: 911 passando (869 mais 42); `ruff check .` sem avisos; pyright com 0
  erros. Prova por mutação, uma de cada vez, com o script restaurado depois (`cmp` igual ao original): a fração de 60%
  trocada por 40%, a segunda tentativa tirada, o host repetido tirado, o pt-PT trocado por pt-BR, o filtro da URL
  resolvida tirado, a palavra genérica contida aceita e a escala chinesa tirada fazem falhar de 1 a 2 testes cada; a
  contagem do link do Google Notícias não resolvido passava nos testes e ganhou uma asserção sobre os hosts lidos, que
  agora falha. A etapa 1 ainda não rodou: espera o `.env` copiado pelo dono.
- 20/11/2026: primeira rodada da etapa 1 (`607eab4`, 13:55 a 14:13, com o `.env` da produção copiado pelo dono: 7 dias,
  15 por feed, 1200 caracteres): APROVADO 12, AJUSTE 6, ETAPA 2 29, REPROVADO 14. Os arquivos estão em
  `data/agrupamento/feeds_20261120/primeira_rodada/`. Conferidos à mão: o texto do Golem.de (ETAPA 2 só pelo idioma,
  "texto em en") é a página de consentimento de cookies, com 1949 caracteres, que passava no critério 5; o Nexo tem os 5
  textos do resumo do feed (o trafilatura falha), com o HTML escapado duas vezes que `rss._texto_puro` deixa como texto
  (`<media:content url=...>`): pendência no coletor.
- 20/11/2026: o dono aprovou (a) e (b) (commit desta linha): (a) o andamento sai na hora (`flush`), o começo de cada
  texto extraído vai para o `etapa1_textos.json`, com a origem e o que o teste fez dele, e a página de consentimento (duas
  ou mais de cookie, consent, privacy, privacidade e javascript nos primeiros 500 caracteres, sem acento nem caixa) não
  conta como texto, qualquer que seja o tamanho; (b) os AJUSTE também vão para a etapa 2. Suíte: 914 passando (911 mais 3);
  `ruff check .` sem avisos; pyright com 0 erros. Prova por mutação: sem a conferência do consentimento, com uma marca só
  bastando, com a origem sempre "trafilatura" e sem gravar o JSON, um teste falha em cada caso; o script restaurado é
  igual ao original (`cmp`). Em seguida, a segunda rodada da etapa 1.

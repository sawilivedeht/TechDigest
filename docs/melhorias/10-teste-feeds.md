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
- 20/11/2026: a etapa 2 no script (commit desta linha), escrita enquanto a segunda rodada da etapa 1 rodava. `--lotes`
  monta os lotes dos APROVADO, AJUSTE e ETAPA 2 do `etapa1.csv` (até 10 feeds, cada categoria em lotes de tamanho igual
  ou quase), grava `loteN.txt` (no formato do `config/feeds.txt`) e `lotes.md`, e mostra o comando do `rodada.py` de cada
  lote, com o `RSS_FEEDS` entre aspas simples e a simulação sem áudio. `--simulacao <pastas>` lê, só para leitura, o log
  (as linhas "Feed OK", casadas pelo título da etapa 1, e os textos curtos), os relatórios (os feeds fora, os filtrados,
  casados pelos hosts dos links da etapa 1, e os episódios) e as amostras de cada simulação, e escreve o `etapa2.md`:
  por feed, coletados, filtrados, gerados, aprovados, reprovados (os de número e de veículo à parte), falhas, os
  problemas de número na primeira versão e as fontes citadas, com o veredito da proposta (2 ou mais gerados, 80% ou mais
  aprovados, nenhuma reprovação por número do formato da fonte, pela pista dos algarismos significativos, conferida à
  mão); `--producao <EXECUCOES_DIR>` acrescenta os mesmos números dos feeds de hoje nas execuções reais. Suíte: 920
  passando (914 mais 6); `ruff check .` sem avisos; pyright com 0 erros. Prova por mutação: sem casar pelo título, o
  filtrado só pelo host do feed, o log rotativo ignorado, sem a pista do formato, 80% trocado por 50%, os lotes de 10 sem
  equilibrar e os AJUSTE fora fazem falhar de 1 a 2 testes cada; o script restaurado é igual ao original (`cmp`).
- 20/11/2026: segunda rodada da etapa 1 (`0c8948a`, 14:39 a 14:57): APROVADO 12, AJUSTE 6, ETAPA 2 27, REPROVADO 16. Só
  dois vereditos mudaram, os dois pela página de consentimento, com os 5 textos nela: o Golem.de e a CGTN (esta em
  inglês, num site em inglês: o idioma não a pegava), de ETAPA 2 para REPROVADO. O começo do primeiro texto de cada um
  dos 45 que seguem foi lido à mão: nenhum outro é página de consentimento; alguns começam com o lixo da página antes da
  matéria ("Siga Startups no Google...", o aviso de anúncios do Notes from Poland, o menu do Hoje Macau). Pendência: o
  filtro de esporte só olha o primeiro segmento do caminho e só em português, e a ANSA traz `/english/news/sports/...`.
  `--lotes`: 45 feeds (12 APROVADO, 6 AJUSTE e 27 ETAPA 2) em 5 lotes (9, 9, 9, 8 e 10), em
  `data/agrupamento/feeds_20261120/lotes.md`.
- 20/11/2026: lote 1 (Brasil, tecnologia, 9 feeds), rodado pelo dono com o `rodada.py` (`1be9dff`, 15:04 a 15:45):
  `FIM` com status 0, 41 min, memória disponível mínima de 16,5 GiB, a sessão parada. 91 coletados, nenhum filtrado e
  nenhum texto curto; 21 gerados, 20 aprovados e entregues. Pela proposta, 8 APROVADO e o Olhar Digital REPROVADO (2 de
  3, 67%): a reprovação é da contagem de palavras do roteiro (Otávio com 203, para um mínimo de 204), uma regra do QA que
  não depende do feed. Os problemas de número estão todos na primeira versão, corrigidos pela revisão, e nenhum vem do
  formato da fonte. Os nomes citados confirmam o AJUSTE: "ConvergenciaDigital", "Startups", "RSS Feed do Site Inovação
  Tecnológica". O relatório ganhou, neste commit, o tipo de cada falha, a taxa entre os julgados pelo QA e o lugar de
  cada problema de número: na comparação com a produção, as falhas dos feeds de hoje são as do Edge-TTS de 05/11
  (`WSServerHandshakeError`), e entre os julgados pelo QA eles aprovam de 75% a 100%. Suíte: 920 passando; `ruff check .`
  sem avisos; pyright com 0 erros.
- 20/11/2026: o dono escolheu a regra (b) para o veredito da etapa 2 (commit desta linha): contam contra o feed só as
  falhas (o texto, como o JanelaExcedida) e as reprovações por número do formato da fonte ou por veículo; o veículo não
  conta quando o nome do feed não bateu na etapa 1 (a correção 4, título genérico ou em ideogramas: pendência do nome
  fixo), e as reprovações pelas regras gerais do QA ficam na tabela sem contar. APROVADO com 2 ou mais gerados, 80% ou
  mais deles sem nada contra o feed e nenhuma reprovação por número do formato da fonte. Suíte: 921 passando (920 mais
  1); `ruff check .` sem avisos; pyright com 0 erros. Prova por mutação: as falhas que não contam, o veículo que conta
  sempre, a regra geral que conta e o formato que não é registrado fazem falhar um teste cada; o script restaurado é
  igual ao original (`cmp`).
- 20/11/2026: lote 2 (Brasil, política e Paraná, 9 feeds), rodado pelo dono (`01ca3bb`): `FIM` com status 0, 43,5 min,
  memória disponível mínima de 16,7 GiB, a sessão parada. 115 coletados, nenhum filtrado, 3 textos curtos; 20 gerados,
  20 aprovados e entregues. Lidos com o lote 1 pela regra (b): APROVADO 17, REPROVADO 1 (de 18). O Olhar Digital passa
  (a reprovação dele era de palavras do roteiro). A Agência Senado fica com 1 gerado: 2 dos 3 textos curtos do lote são
  itens dela só de áudio ("Áudio: Comissões aprovam emendas ao Orçamento de 2027", 617 caracteres; "Áudio: Congresso
  homenageia Embratur...", 721), e o lote chegou aos 20 entregues antes de um quarto item dela; o nome dela no episódio
  já era "Senado Federal" (AJUSTE). Os problemas de número dos dois lotes estão todos na primeira versão, corrigidos pela
  revisão, nenhum do formato da fonte; os nomes citados confirmam os AJUSTE ("República", "Paraná", "Câmara notícias -
  Câmara dos Deputados").

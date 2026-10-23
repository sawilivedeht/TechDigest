# Roteiro da fase 4: o agrupamento no pipeline

O plano da fase 4, as decisões do dono e o estado de cada item. O CLAUDE.md descreve o código como
ele está; este arquivo guarda o que foi decidido e o que falta, e é atualizado a cada etapa.

## Onde as coisas estão

- **Fases 1 a 3:** branch `agrupamento-fase3`, congelada em 14/10/2026 (0f903ef), sem merge. O
  estado dela está no CLAUDE.md ("State of phase 3"). Uma cópia do CLAUDE.md dessa data fica fora
  do git, em `~/Documentos/techdigest-fase3/CLAUDE.md`.
- **Fase 4:** branch `agrupamento-fase4`, criada a partir da `agrupamento-fase3`, na worktree
  `../techdigest-fase4`. A pasta principal fica na `master`, que é o que roda em produção.
- **Amostras e gabaritos,** em `data/agrupamento/` da pasta principal (fora do git; na worktree,
  `data/agrupamento` é um link para lá):
  - amostra antiga, `amostra_20261011-154002.json` (108 candidatos), com os pares rotulados em
    `rotulos_20261011-154558.csv` (18 pares);
  - amostra nova, `amostra_20261012-220330.json` (101 candidatos);
  - os lados esperados da antiga e o gabarito da nova, que o dono mandou na conversa, transcritos em
    `gabaritos_do_dono.md`.

## Ordem do trabalho

1. **Worktree e ambiente.** Feita (a1093d7).
2. **Roteiro e CLAUDE.md.** Feita (28159f7).
3. **Trava do modelo, travas da máquina e simulação.** Feita (4f33eb5).
4. **Validação da fonte única.** Rodada em 17/10/2026, como teste de regressão: 18 de 20
   aprovados, mas o aceite não foi atingido (três disputas inventadas, uma delas aprovada, e um
   fato distorcido num aprovado). Em 19/10, o plano das correções (ver "Depois da validação: o
   plano de 19/10").
5. **Integração do agrupamento** atrás de `AGRUPAMENTO_ATIVO`, com os filtros, o limite de
   tentativas, os excedentes e o registro de cada execução.
6. **Simulação de ponta a ponta.** A que libera o merge roda com `AGRUPAMENTO_ATIVO=false`, que é o
   que vai para produção, e com áudio. A rodada com o agrupamento ligado é uma prévia.
7. **Merge** das fases 1 a 4 na `master`, com `AGRUPAMENTO_ATIVO=false`. A fonte única muda já no
   merge, porque a análise de lados, o recorte por relevância e as regras novas do QA vivem em
   `Summarizer.process`; por isso a validação da etapa 4 vem antes.

Fora do plano até o dono avisar, inclusive depois do merge: o timer do systemd e a unit do
techdigest. A instalação das units e o linger também ficam com ele.

Depois do merge: a terceira amostra e a decisão de ligar o agrupamento (ver as seções abaixo).

## Ambiente da worktree

- **`.venv` própria** (`python -m venv .venv` e `pip install -e '.[dev]'`): a instalação editável
  aponta para uma pasta só, e a `.venv` da pasta principal continua com o código da `master`.
- **`.env`:** o dono cria, copiando o de produção, sem o token e o chat do Telegram. Se `DB_PATH`,
  `LOG_DIR` ou `AUDIO_DIR` estiverem nele, saem do `.env` da worktree: os padrões já apontam para o
  `data/` da worktree, e os scripts gravam os diagnósticos em `<pasta do DB_PATH>/agrupamento`, que
  ali é o link para as amostras. Um `DB_PATH` em outro lugar mandaria os diagnósticos para outra
  pasta.
- **O `data/digest.db` de produção só pode ser lido.** Nenhum teste nem script da fase 4 escreve
  nele. Os testes nem o veem (`tests/conftest.py` desliga o `.env` e põe banco, logs, áudio e log do
  Ollama numa pasta temporária); os scripts o abrem só para leitura; a simulação trabalha numa
  cópia.
- **Ollama:** a unit de usuário `deploy/systemd/ollama.service` e a sessão de teste
  `deploy/systemd/techdigest-teste.target` (o CLAUDE.md explica as duas). Ninguém mais roda
  `ollama serve` à mão: as rodadas da fase 4 usam o Ollama da unit, o mesmo que o pipeline vai usar.
  Instalação, pelo dono, uma vez:

  ```bash
  mkdir -p ~/.config/systemd/user ~/.local/state/techdigest
  cp deploy/systemd/ollama.service deploy/systemd/techdigest-teste.target ~/.config/systemd/user/
  systemctl --user daemon-reload
  ```

  Uso: `systemctl --user start techdigest-teste.target` antes da rodada e `systemctl --user stop
  techdigest-teste.target` depois. O linger só é preciso para rodar sem o dono logado, ou seja,
  quando o timer for ligado.
- **Até o merge, a `master` não conhece a trava do modelo** (etapa 3) nem a unit do Ollama. Quem
  rodar a `master` à mão confere antes que nenhuma rodada da fase 4 está em curso
  (`systemctl --user is-active techdigest-teste.target`), porque as duas disputariam o mesmo modelo.
- **Uma rodada nunca atravessa uma suspensão da máquina** (decisão de 17/10). Até o inibidor entrar
  nas units, as rodadas rodam sob `systemd-inhibit --what=sleep:idle`. Depois ele entra na sessão de
  teste e na unit do techdigest. Proposta para a sessão de teste: uma unit pequena,
  `techdigest-inibir.service`, com `ExecStart=/usr/bin/systemd-inhibit --what=sleep:idle
  --who=TechDigest --why="sessão de teste" --mode=block sleep infinity`, que o target puxa e que cai
  com ele; na unit do techdigest, o `ExecStart` dentro do `systemd-inhibit`. Em 17/10, o
  `systemd-inhibit` funcionou de dentro de uma unit de usuário temporária, sem pedir permissão.
- **Depois do merge, o pipeline só roda com o Ollama da unit.** Ele confere a GPU pelo log dela
  (`OLLAMA_LOG`) e para se o servidor no ar for outro. Enquanto a unit do techdigest não existir, uma
  execução de produção à mão sobe o Ollama pela sessão de teste, como as rodadas.

## Decisões do dono

Em 16/10/2026, ao aprovar o plano:

- **650 contra 480.** O 650 estava no `.env` e é o valor em vigor. Ficam 650 no QA e 480 nos
  prompts, como margem, do mesmo jeito que nas frases do resumo (8 a 9 pedidas, 7 a 10 cobradas).
  O 650 passou para o padrão do `config.py` e os dois números estão no CLAUDE.md.
- **Excedentes:** marcados como vistos junto com a pauta e listados no texto, como as duplicatas.
  Assim não voltam como episódio de fonte única repetido. (Era a ideia do dono, em 11/10, não
  marcá-los.)
- **Tentativas do item reprovado:** duas execuções no total. Só `QAReprovado` conta; erro de rede
  ou do Ollama, não. Na segunda reprovação o item é descartado, e o registro da execução guarda os
  episódios para diagnóstico. A mudança no banco é aditiva, para a `master` antiga ainda funcionar
  com ele se for preciso voltar atrás.
- **Filtros:** esporte e ofertas pela seção da URL e pela categoria do feed, nunca por palavras do
  título. Sites de partido ficam fora por uma lista de domínios, aplicada à URL final, depois de
  resolver o link do Google Notícias.
- **Quando o agrupamento liga:** três condições, na seção própria.
- **Aceite da fonte única:** pelo menos 17 de 20 aprovados, nenhuma disputa inventada e nenhum fato
  sem fonte confirmado nos aprovados, conferindo o que o `checar_fidelidade.py` aponta e os
  episódios lidos. Disputa perdida e tempo vão para o relatório, sem barrar.
- **`.env` da worktree:** o dono cria (ver "Ambiente").
- **Timer:** não liga nesta fase, nem depois do merge, até o dono avisar. A unit do techdigest
  também fica para depois. A do Ollama entrou já na etapa 1, para as rodadas da fase 4 usarem o
  Ollama de produção.
- **Uma trava só:** tudo o que chama o modelo (o pipeline, o `techdigest --simular`,
  `scripts/testar_episodio.py` e `scripts/testar_agrupamento.py --etapa3`) pega a mesma trava, num
  caminho fixo fora das duas pastas, e sai com uma mensagem clara se ela estiver ocupada. Vale
  mesmo com o timer desligado, porque a simulação e os scripts de teste podem rodar ao mesmo tempo.
  O log da simulação fica separado.
- **Áudio:** pode ser desligado nas simulações de trabalho; a simulação que libera o merge roda com
  áudio.
- **Leituras confirmadas:** o roteiro fica em `docs/`; uma trava da máquina que dispara interrompe a
  execução inteira, porque memória, temperatura e GPU são da máquina e não de um item; com o
  agrupamento ligado, `MAX_NEWS` conta episódios por execução e o agrupamento olha todos os
  candidatos coletados; os exemplos do CLAUDE.md tirados das amostras foram trocados por inventados.

Em 17/10/2026, ao ver o fim das etapas 1 a 3:

- **Confirmadas as quatro decisões da etapa 3:** a trava do modelo ocupada sai com status 1; uma
  pasta nova de simulação exige `--banco-origem`; o canal `arquivo` recusa rodar fora da simulação;
  a etapa 3 do `testar_episodio.py` passa pelas travas da máquina.
- **Aprovados:** o aviso de parada (ajuste 8), a ordem das vagas de `MAX_NEWS`, o protocolo da
  terceira amostra e o gabarito dos 20 itens da fonte única.
- **O que faz um lado:** o critério não é de quem é a frase, e sim se o texto traz a resposta do
  ator à questão. No A79, o texto relata o que o comandante dos bombeiros afirmou, e isso responde
  à questão; no A46, nada responde se a Meta tentou interferir ("admitido falhas técnicas"
  descreve a conduta dela), então um lado da Meta é disputa inventada.
- **Três tipos de erro na análise de lados:** disputa inventada (dois lados ou mais onde o
  gabarito tem um), disputa perdida (um lado onde ele tem dois) e questão errada (dois lados, mas
  sobre outra questão: no N13, a da área técnica, que o gabarito de 13/10 põe noutra pauta, a 71 +
  85). Ator secundário ou ressalva ausente contam como detalhe. Planos de governo diferentes sem
  respostas opostas a uma pergunta são informação complementar (N27).
- **A validação da fonte única é um teste de regressão:** as duas amostras já não são cegas, e dos
  cinco itens com disputa só o N92 não está nos gabaritos da fase 3. A medida cega da fonte única
  fica para a terceira amostra, que inclui itens de fonte única com disputa, com o gabarito do dono
  antes da rodada. Prompt e QA não mudam por causa do resultado: ele vem primeiro para o dono.
- **O filtro de esporte, ofertas e sites de partido** vale com o agrupamento ligado ou desligado.

Em 19/10/2026, ao ver o resultado da validação da fonte única:

- **O plano tem oito itens** (ver "Depois da validação: o plano de 19/10"). Só o item 5 muda
  código neste ciclo; a linha de base da `master` entra logo depois dele; os outros voltam como
  medida e proposta.
- **Arredondamento na escala:** o QA aceita "245 milhões" para R$ 245,5 milhões. A comparação é
  pelo valor, qualquer que seja a forma como a fonte o escreve (R$ 245.500.000 também), na escala
  em que o episódio fala, e só com 10 ou mais nessa escala: 3,6 bilhões não vira "três bilhões".
- **Linha de base:** antes de importar a `master`, o script zera `TELEGRAM_TOKEN` e
  `TELEGRAM_CHAT_ID` no ambiente; a trava e as travas da máquina não podem vir do pacote da
  `master`; é uma rodada de cada lado, então diferença de um ou dois episódios é ruído.
- **Medida das conferências da disputa inventada:** conta também o ator principal perdido, nos
  itens com disputa e nos de um lado só, porque as variantes trocam disputa inventada por ator
  perdido, e é essa troca que se decide; uma variante a mais, o verbo de decisão (determinar,
  decidir, suspender, mandar) para quem decidiu, pela regra de que quem toma a decisão responde a
  favor dela. A medida sem o modelo não vê a nova tentativa do item 6: os lados certos derrubados
  são o pior caso.
- **Verbos:** um verbo novo que passa no critério (não apresenta a afirmação como verdade) vai para
  a lista única de `verbos.py`, e afrouxar a regra dos analistas é relaxamento. Listas separadas só
  se aparecer um verbo que sirva a uma regra e não à outra.
- **Orçamento:** os 20 episódios da `master` entram no teste da hipótese; se a `master` também
  inventa nos textos curtos, a hipótese ganha força.
- **Turnos:** os roteiros com menos de 10 turnos (12 de 20 em 17/10) ficam como diagnóstico por
  enquanto. O registro da limitação no item 10 está bom.

Das fases 1 a 3, continuam valendo (o detalhe está no CLAUDE.md e no histórico do git):

- Mesma história é o mesmo acontecimento ou um desdobramento direto dele na janela da coleta; só o
  mesmo tema não vale; na dúvida, não juntar. Nos rótulos, `sobreposicao_parcial` (agenda do dia,
  resumo semanal) conta como negativo.
- No máximo 3 textos por pauta, com prioridade para veículos distintos. Nada de filtro por palavra
  no título: "agenda" aparece em manchete de fato único.
- `AGRUP_LIMIAR` 0,18 e `AGRUP_CHARS_TEXTO` 1500, medidos nas duas amostras.
- Nas rodadas com o modelo: `OLLAMA_NUM_CTX` não muda (o orçamento tem de caber em 8192);
  memória disponível, swap e temperatura são registradas antes de cada chamada; a rodada para com
  menos de 4 GiB de memória disponível ou se o Ollama cair ou descarregar o modelo; com a CPU acima
  de 95 °C, espera baixar de 85 °C; a saída de rodada longa vai para `data/`, não para `/tmp`.
- Ajuste de prompt se valida numa amostra rotulada que não serviu para escrevê-lo, e os exemplos
  dos prompts são inventados, fora das amostras.
- Para mudar as regras: verbo que apresenta a afirmação como verdadeira não entra nos verbos de
  posição; regra que relaxa o QA entra direto, e regra nova que reprova passa antes pelo diagnóstico
  (`checar_fidelidade.py`, depois `refazer_qa.py`) e só então vai para o `qa.py`.
- No gabarito, ressalva ausente e ator secundário ausente contam como detalhe.
- O trabalho segue com plano aprovado antes de editar, branch própria por fase e commit sem push.

## Itens da fase 4

Os números são os da lista que o dono mandou registrar em 13 e 14/10/2026.

1. **Filtro de esporte e de ofertas** antes do agrupamento. Decidido (seção da URL e categoria do
   feed). Na amostra nova são 7 candidatos de esporte (ids 2, 9, 30, 37, 45, 52, 98) e 11 de ofertas
   (8 com "link de afiliado": 4, 18, 19, 33, 34, 40, 48, 56; mais 3 do Canaltech sem a frase: 47,
   87, 99), 18 de 101. Medida em 16/10, sem o modelo e só pela URL final, porque as amostras não
   guardam a categoria do feed (`data/agrupamento/filtros_20261016.txt`; as regras estão em
   `medir_filtros_20261016.py`, na mesma pasta). Regras propostas, à espera do dono: esporte pela
   seção `/esportes/` ou `/esporte/` e pelos sites inteiros de esporte (ge.globo.com, lance.com.br,
   goal.com, cbf.com.br); ofertas pelas seções `/achados/` (Tecnoblog), `/hardware-indica/`
   (Hardware.com.br) e `/ofertas/`. Resultado nas duas amostras: esporte 12 de 12, ofertas 16 de 21,
   nenhum falso positivo. Ficam de fora quatro notícias de preço do Canaltech (seções `/carros/`,
   `/produtos/` e `/smartphone/`) e um texto de afiliado do Hardware.com.br na seção `/games/`: a
   categoria do feed pode pegá-los, e a terceira amostra vai dizer. Na primeira coleta dela (17/10),
   45 de 108 candidatos têm categoria: o Canaltech e o Google Notícias não mandam nenhuma, o
   Tecnoblog manda só etiquetas de assunto (marcas, produtos, serviços) e o Hardware.com.br manda
   "Hardware Indica", a mesma seção que a URL já mostra. A categoria, portanto, não pega as
   notícias de preço do Canaltech, que eram a maior parte do que a URL perdeu. O filtro vale com o
   agrupamento ligado ou desligado. Implementação na etapa 5.
2. **Site de partido como fonte** (junto com o 9). O pt.org.br entrou como veículo "Partido dos
   Trabalhadores" na pauta do Alckmin (ids 29 + 20 da amostra nova), e o episódio atribuiu ao PT,
   como veículo, um relatório que o site não menciona; no áudio, isso soa como posição do partido.
   Decidido: lista de domínios na URL final. Nas duas amostras o pt.org.br é o único site de
   partido, e a regra o pega. A lista completa de domínios fica para o dono revisar na etapa 5. Vale
   com o agrupamento ligado ou desligado.
3. **GPU no pipeline** (junto com o 7, de onde ler o log do Ollama): `gpu.conferir_antes_de_carregar`
   antes da primeira chamada e `gpu.modelo_na_gpu` depois dela. O log é o da unit, `OLLAMA_LOG`
   (etapa 1). As conferências entram no pipeline na etapa 3.
4. **Limite de tentativas** do item reprovado pelo QA, que hoje volta a cada execução até sair do
   prazo de `MAX_IDADE_DIAS`. Decidido (duas execuções). Etapa 5.
5. **Lula/TSE × área técnica do TSE.** Na amostra nova, as pautas Lula/TSE (64 + 13 + 42) e área
   técnica (71 + 85) só ficaram separadas pelo teto de 3 artigos: o par 64 × 71 tem score 0,209,
   acima do limiar. Virou condição para ligar o agrupamento; a rodada fica para depois, com as
   outras que chamam o modelo.
6. **Diagnósticos nos episódios reais.** Cada execução passa a guardar os textos usados e os
   episódios, no formato que `checar_fidelidade.py` e `refazer_qa.py` já leem (etapa 5). A
   validação da regra estrita de atribuição, que ia usar os primeiros dias de uso, passou para a
   terceira amostra.
7. Ver o 3.
8. **Trava de temperatura** no pipeline (na rodada de 14/10 a CPU chegou a 94 °C antes de uma
   chamada): acima de 95 °C antes de uma chamada, espera baixar de 85 °C, por até 15 minutos; depois
   disso, para. Etapa 3.
9. Ver o 2.
10. **Limitações conhecidas,** sem regra; os episódios lidos nas rodadas são a única defesa:
    - nenhuma checagem pega argumento atribuído a um ator sem estar nos textos (no episódio
      Lula/TSE de `episodios_amostra2_v2`, a analista diz que a campanha de Flávio "continuará
      monitorando se as regras... serão aplicadas de forma uniforme");
    - a conferência dos trechos confirma que o trecho está no texto, não que ele traz a resposta do
      ator à questão (o caso do A46: "admitido falhas técnicas" está no texto, mas descreve a
      conduta da Meta, não responde se ela tentou interferir). Registrada em 17/10.
11. **Worktree:** feita, e usada mesmo com o timer desligado.
12. **Excedentes:** decidido (vistos com a pauta e listados no texto). Etapa 5.

## Etapa 3: trava do modelo, travas da máquina e simulação (feita)

- **Trava do modelo** (`trava.py`): um arquivo fixo fora das duas pastas,
  `~/.local/state/techdigest/modelo.lock` (a mesma pasta do log do Ollama), com `flock` sem espera.
  Quem a pega grava nela o comando, o PID, desde quando e a pasta; quem a encontra ocupada mostra
  isso e sai com status 1 (o pipeline registra "Execução não começou: ..."). Substitui a trava
  antiga do pipeline, `data/techdigest.lock`, que valia só para a pasta dele.
- **Travas da máquina** (`ai/maquina.py`), as mesmas para o pipeline e para os scripts: memória
  disponível abaixo de 4 GiB antes de cada chamada; a CPU acima de 95 °C (espera baixar de 85 °C por
  até 15 minutos); a GPU antes da primeira chamada (no pipeline, antes até da coleta) e depois da
  carga; o Ollama fora do ar ou sem o modelo carregado no meio da execução. Cada uma interrompe a
  execução inteira com status 1 e a linha "Execução interrompida: <motivo> (N notícia(s) entregue(s)
  antes; ...)", que o `resumo_lotes.py` mostra na tabela. A etapa 3 do `testar_episodio.py`, que
  antes chamava o modelo sem as conferências de memória e temperatura, passou a usá-las. Ficam
  para avaliar na simulação: um vigia de memória durante a carga do modelo (nas rodadas, por
  enquanto, é um laço em segundo plano que para a sessão de teste com menos de 3 GiB disponíveis)
  e um `MemoryMax` na unit (o modelo mapeado conta como cache de arquivo).
- **Simulação** (`simulacao.py`, `delivery/arquivo.py`):

  ```bash
  .venv/bin/techdigest --simular data/simulacoes/<nome> --banco-origem /home/sytw/Projetos/techdigest/data/digest.db
  .venv/bin/techdigest --simular data/simulacoes/<nome>          # a segunda execução, com o banco da primeira
  .venv/bin/python scripts/resumo_lotes.py DD/MM --log data/simulacoes/<nome>/logs/techdigest.log
  ```

  Coleta, extração, LLM e TTS são reais; a entrega vai para `<pasta>/entregas` (o texto como o
  Telegram o receberia, o episódio em JSON e o mp3, e `entregas.txt` com a ordem); o banco é uma
  cópia, feita com o de origem aberto só para leitura; o log e o áudio ficam na pasta. Uma pasta nova
  pede `--banco-origem`; a de uma simulação anterior continua com o banco dela; qualquer outra é
  recusada. Nenhum caminho do `--simular` chama a API do Telegram: o canal é `arquivo`, o token e o
  chat ficam vazios no ambiente e o `_post` do Telegram recusa rodar numa simulação; um teste roda
  uma simulação inteira num processo novo, com coleta, extração e geração falsas e um
  `requests.post` que reprova o teste se for chamado. O canal `arquivo`, por sua vez, recusa rodar
  fora de uma simulação. O áudio pode ser desligado (`--sem-audio`) nas simulações de trabalho.

## Aviso de parada (ajuste 8): aprovado em 17/10, a implementar na etapa 5

- **Quando:** a execução parou numa trava da máquina; não começou porque a trava do modelo estava
  ocupada; e, se o dono quiser, terminou com erro inesperado.
- **Em produção:** uma mensagem curta no mesmo chat do Telegram, enviada pelo próprio processo antes
  de sair com status 1, sem URL nem token, pelo mesmo caminho que já esconde o token (`_post`). Por
  exemplo: "TechDigest parou às 08:42: memória disponível em 3,1 GiB, abaixo de 4 GiB. Entregues: 7
  de 20; o resto volta na próxima execução." ou "TechDigest não começou às 08:00: o modelo está em
  uso por testar_episodio.py (PID 1234, desde 07:15)." O log ganha uma linha de texto fixo para o
  `resumo_lotes.py` mostrar a parada. Se o próprio aviso falhar, fica o log e o status 1.
- **Quando houver a unit do techdigest:** um `OnFailure=` que manda o mesmo aviso cobre o que o
  processo não consegue avisar sozinho (morto pelo OOM killer ou pelo limite de 4 horas). O
  `OnFailure=` dispara em qualquer falha, inclusive nas saídas com status 1 que o processo já
  avisou: por isso o aviso dele lê `MONITOR_SERVICE_RESULT` e `MONITOR_EXIT_STATUS` e só fala quando
  o resultado não for `exit-code` com status 1 (OOM killer, tempo esgotado, sinal).
- **No `--simular`:** o aviso vai para `<pasta>/AVISO.txt` e para a saída de erro, e nunca para o
  Telegram: as três camadas da etapa 3 (o canal `arquivo`, o token vazio e a recusa do `_post` numa
  simulação) valem também para ele, e o teste de ponta a ponta passa a cobrir o aviso.
- **Nos scripts de teste:** a mensagem na tela e o status 1, como hoje. Eles nunca falam com o
  Telegram.

## Integração: a ordem das vagas de MAX_NEWS (ajuste 7)

Aprovada em 17/10:

- Com o agrupamento ligado, a execução coleta como hoje (os feeds intercalados, o filtro de idade e
  `MAX_POR_FEED`), tira os vistos, aplica os filtros, extrai todos os candidatos em lote, descarta
  os textos curtos, agrupa (etapas 1 a 3) e só então gera.
- Cada pauta final ocupa a posição do primeiro dos seus artigos na lista intercalada (contando
  principal, relacionados, duplicatas e excedentes), e as pautas são geradas nessa ordem até
  `MAX_NEWS` episódios entregues ou até o fim do orçamento de tempo.
- O intercalado do boletim duplo continua valendo: a primeira vaga é da pauta do primeiro artigo
  do primeiro feed, a segunda da do primeiro artigo do segundo feed, e assim por diante. Uma pauta
  que junta artigos de vários feeds ocupa uma vaga só, na posição do artigo dela que vem primeiro
  na lista, e as posições dos outros ficam livres para as pautas seguintes.
- Efeito a medir na prévia com o agrupamento ligado: o boletim cujas histórias saem em mais
  veículos ao mesmo tempo passa a ocupar menos vagas, cada uma com mais artigos, e o outro ganha
  vagas. Uma cota fixa por boletim seria regra nova (o código não conhece boletins, só feeds), para
  decidir depois da prévia.
- O que não couber em `MAX_NEWS` não é marcado como visto e volta na execução seguinte, onde pode
  ganhar artigos novos.

## Terceira amostra (ponto 7): protocolo aprovado em 17/10

Ela não pode depender dos primeiros dias de uso e precisa estar pronta quando se for decidir se o
agrupamento liga.

- **Coletas:** três, com `scripts/testar_agrupamento.py --incluir-vistos --salvar-amostra`, em dias
  diferentes, com pelo menos três dias entre uma e outra, em horários diferentes e com um fim de
  semana no meio. A coleta não chama o modelo, não usa a trava e abre o banco só para leitura: dá
  para fazer com outra rodada em curso. Pode começar já, porque cada coleta leva um ou dois
  minutos e as três ficam prontas antes do merge.
- **Antes da primeira coleta:** o `--salvar-amostra` passou a gravar também a categoria e o feed de
  cada candidato (7aa467c), para medir o filtro pela categoria e o efeito do agrupamento nas vagas
  de cada boletim.
- **Primeira coleta, em 17/10/2026 às 10:56:** `amostra_20261017-105620.json`, 108 candidatos (45
  com categoria), com a saída da coleta em `coleta_20261017-105619.txt`, os pares de maior score em
  `pares_20261017-105620.csv` (11 com score de 0,15 para cima) e a lista para rotular em
  `candidatos_20261017-105620.csv` (id, veículo, título, URL, feed, categorias e tamanho, com
  colunas vazias para o filtro e as notas). As outras duas, quando o dono pedir, com pelo menos três
  dias entre elas.
- **Cada coleta é uma amostra** (`amostra_<data-hora>.json`), como um retrato de uma execução real;
  um artigo que apareça em duas coletas leva o mesmo rótulo nas duas. As três juntas formam a
  terceira amostra, com um gabarito só.
- **Gabarito do dono, antes de qualquer rodada:** para cada coleta, os pares da mesma história
  (com a relação, mesmo acontecimento ou desdobramento) e os textos de vários fatos, num CSV no
  formato de `rotulos_*.csv`, para o `--rotulos` conferir; para cada pauta, a questão em disputa e
  os atores de cada lado, ou "sem disputa", e as ressalvas, inclusive em itens de fonte única com
  disputa, para a medida cega da fonte única; e os candidatos de esporte, ofertas e site de partido.
  Para ajudar, entrego por coleta a lista dos candidatos (id, veículo, título, URL) e o CSV dos pares
  de maior score, como nas amostras anteriores, sem nenhuma saída do modelo.
- **Tamanho:** a meta é chegar a pelo menos 15 pautas de 2 ou mais artigos e 6 pautas com disputa
  pelo gabarito, somando as três; se faltar, uma quarta coleta.
- **Depois do gabarito:** a etapa 3 com `--repeticoes 3`, a análise de lados, a geração e o
  `checar_fidelidade.py` com a regra estrita.

## Quando o agrupamento liga

Três condições, todas cumpridas:

1. Na amostra nova, com o teto acima de 3 artigos (`AGRUP_MAX_ARTIGOS`) e `--repeticoes 3`, a etapa
   3 separa Lula/TSE (64 + 13 + 42) da área técnica do TSE (71 + 85) sem depender do teto.
2. A etapa 3 mantém o acerto na terceira amostra, com o gabarito do dono.
3. A regra estrita de atribuição passa por essa amostra e, se confirmada, entra no QA pelo caminho
   de sempre (diagnóstico, `refazer_qa.py`, `qa.py`).

## Validação da fonte única (etapa 4)

- **Itens:** 20 de fonte única, de tecnologia e de política, tirados das duas amostras: política com
  e sem disputa, tecnologia, texto curto perto dos 1.200 caracteres e texto longo que exercita o
  recorte. Esporte e ofertas ficam de fora, porque o filtro foi adotado.
- **Gabarito:** o resultado esperado de cada item, lido nos textos (um lado só, ou a disputa com os
  atores de cada lado), para medir disputa inventada e disputa perdida. O dono revisa antes da
  rodada. Está em `data/agrupamento/gabarito_fonte_unica_20261016.md`: 11 itens de política e 9 de
  tecnologia; 5 com dois lados, 3 com um lado e ressalva, 12 com um lado; 4 dúvidas para o dono
  (A46, N13, N27 e, já decidido por ele em 14/10, o contraste da N69). Nenhum texto de tecnologia
  das amostras traz disputa entre atores nomeados, então a disputa perdida só se mede na política.
  Os comandos da rodada estão no fim do arquivo.
- **Rodada:** `scripts/testar_episodio.py --amostra <amostra> --pautas "<id>;<id>;..."` na worktree,
  uma vez por amostra; sem `--repetir`, o `--pautas` roda só as pautas pedidas, sem a etapa 3
  (conferido no código).
- **Medidas:** aprovação, correções, tempo, disputa inventada, disputa perdida e o
  `checar_fidelidade.py`; leio todos os episódios que saírem com dois lados. Para comparar, no log
  de produção a `master` pulou de 0 a 4 itens por QA a cada 20 entregues.
- **Aceite:** ver "Decisões do dono". Se a disputa inventada no N27 for o único erro, o episódio vai
  para o dono antes de fechar o aceite.
- **Como rodou (17/10):** as duas amostras em pastas separadas, `fonte_unica_v1_antiga` e
  `fonte_unica_v1_nova` (o `refazer_qa.py` conta só o relatório mais recente de cada pasta, e as
  duas amostras têm um item 92), sob `systemd-inhibit --what=sleep:idle`, com o vigia de memória.
  O script, o vigia, o andamento e o comparador com o gabarito estão em
  `data/agrupamento/rodada_20261017/`. Na leitura, além dos episódios com dois lados e do N27: no
  N13, se o analista da campanha de Flávio (uma frase de material, que a contagem do código não marca
  como fina) inventa argumento para chegar ao mínimo de palavras; nos itens de uma voz só (A46, N84,
  N86), se o episódio apresenta a acusação, a crítica ou a opinião como fato.
- **Resultado (17/10), teste de regressão:** o detalhe por item e a leitura dos episódios estão em
  `data/agrupamento/rodada_20261017/resultado.md`.
  - Aprovação: 18 de 20, em 48 minutos (145 s por item, sem áudio). A máquina não chegou perto de
    nenhuma trava (CPU até 93 °C, memória disponível nunca abaixo de 17,4 GiB). O `refazer_qa.py`
    confirma a situação gravada dos 20.
  - Análise de lados: 3 disputas inventadas, cada uma de uma forma (A46: a Meta, cuja "resposta"
    só descreve a conduta; N69: a estratégia diferente da Sony; N55: "comunidade de programação",
    coletivo sem nome que a lista de termos genéricos não pega). Nenhuma disputa perdida, nenhuma
    questão errada: os cinco itens com disputa saíram com os atores principais nos lados certos.
    O QA reprovou A46 e N55, porque os analistas não apresentam os lados um a um; o N69 passou.
  - Fidelidade: nenhum número inventado sobreviveu, porque o QA pegou quatro e a correção os tirou.
    Há um fato distorcido num aprovado, no N92: "o recolhimento de cerca de 30 mil exemplares",
    quando o texto diz que 30 mil foram impressos e só os não distribuídos são recolhidos. Também
    há argumentos que o texto não traz nos lados com pouco material (A63, A79, A92, N13) e nas
    disputas inventadas.
  - Aceite: o primeiro critério foi cumprido; o segundo e o terceiro, não.

## Depois da validação: o plano de 19/10

1. **Linha de base:** os mesmos 20 itens com o código da `master`, por um script fora do
   repositório, com a trava do modelo e as travas da máquina; o `checar_fidelidade.py` e a mesma
   leitura. Separa o que é regressão do caminho novo do que já sai hoje.
2. **Disputa inventada:** uma conferência em `lados.py` para cada forma (o trecho do ator com verbo
   de posição; o coletivo de pessoas como grupo mesmo com qualificador e a instituição só sem ele;
   o N69, em código e no prompt), medida nas análises gravadas da fase 3 e de 17/10.
3. **Orçamento de palavras:** conferir se a invenção se concentra nos textos curtos e nos lados com
   pouco material; propor um orçamento proporcional ao material (relaxamento); medir pelo
   `refazer_qa.py` o teto de 200 palavras do lado fino como regra do QA.
4. **Prompt:** a acusação, a crítica e a opinião de uma voz só ficam sempre atribuídas e a ressalva
   do próprio veículo se mantém (N84); a Helena não monta escolhas que o texto não faz (N27).
   Exemplos inventados.
5. **Arredondamento na escala.** Feito em 19/10 (ver as decisões dessa data).
6. **Nova tentativa para o ator cujo trecho não passou** (o Lula do A92, trecho parafraseado), como a
   que já existe para o ator sem entrada.
7. **Alternativa,** se as correções não bastarem: a fonte única sem análise de lados, como na
   `master`, e o que isso custa nos cinco itens com disputa.
8. **Até o merge:** a regressão nos mesmos 20 itens depois das correções e a validação cega na
   terceira amostra, com itens de fonte única com e sem disputa.

**Estado em 20/10** (o detalhe, as medidas e as propostas estão em
`data/agrupamento/medidas_20261020/relatorio.md`):

- **Item 5:** feito (8c99dac).
- **Item 1:** os scripts estão em `data/agrupamento/linha_de_base_master/`, com processos separados.
  - A trava fica com um processo da worktree e as travas da máquina num script da `.venv` dela,
    porque o `trava.py` e o `maquina.py` importam do pacote `techdigest` e pegariam o da `master`.
  - Só a resposta "segue", exata, deixa a chamada seguir, e a conferência também verifica que a
    trava continua presa.
  - O teste sem o modelo confirmou que a parada atravessa o `Summarizer.process` da `master`, que
    só captura `Exception`.
  - **Não rodou:** em 20/10 a máquina estava no kernel `7.2.11-arch1-1`, sem o driver da NVIDIA.
- **Item 2:** medido nas 85 análises com questão e `respostas_por_ator` (127 válidas para a regra
  do coletivo), sem a nova tentativa do item 6, então os lados certos derrubados são o pior caso.
  - **O verbo dentro do trecho, como proposto:** pega as 3 disputas inventadas, mas desfaz 31
    disputas certas.
  - **A combinação proposta:** verbo no trecho ou na frase, citação direta, verbo de decisão de
    quem decidiu, os verbos novos (classificar, ressaltar, o infinitivo e o pretérito composto),
    os marcadores ("segundo ele") e o coletivo.
  - **Efeito da combinação:** pega as 3 inventadas com o ator certo e, nos 20 de 17/10, não perde
    nada. Nas 85, perde 3 disputas certas, todas da pauta 71+85.
- **Item 3:** a leitura frase a frase dos 20 de 17/10 marcou 21% das frases.
  - **A hipótese do orçamento se confirma só em parte:** nos itens de um lado, a taxa é a mesma
    nos textos curtos e nos longos (16% e 15%).
  - **O que mais pesa é a estrutura:** 15% com um lado, 27% nas disputas reais e 35% nas
    inventadas.
  - **Nas disputas reais,** o lado com uma ou duas frases inventa mais (54% contra 43%).
  - **O teto de 200 do lado fino como regra** reprovaria 5 dos 60 episódios gravados.
  - Falta a parte da `master`.
- **Item 4:** proposta de seção "Quem diz o quê" no prompt, com exemplos inventados.
- **Item 6:** dispararia em 1 das 85 análises gravadas com a conferência de hoje e em 11 com a do
  item 2.
- **Itens 7 e 8:** no relatório; o 7 depende da linha de base.

**Em 23/10, a linha de base:**

- **A rodada:**
  - **Máquina:** continuava no kernel comum (7.2.11-arch1-1), agora com o `nvidia-open`, a GPU
    respondendo e `library=CUDA` no log.
  - **Resultado:** a `master` aprovou os 20 itens em 38 minutos, com 21 chamadas.
  - **Carga:** o modelo carregou com 27 de 31 camadas na GPU, e a memória disponível ficou sempre
    acima de 17 GiB.
- **A mesma leitura, frase a frase:**
  - **Taxa:** 30% das frases da `master` trazem argumento, opinião ou fato que o texto não traz,
    contra 21% na fase 4.
  - **Por tamanho de texto:** na `master`, 36% nos textos curtos e 27% nos longos, o que reforça a
    hipótese do orçamento.
  - **Nas cinco disputas:** a `master` põe menos argumento na boca dos atores (9 contra 29), mas
    inventa mais no geral (32% contra 27%).
  - **Outros erros:** pende para um lado (A79) e troca as posições (N13). Também cria um debate
    sem disputa (A72).
- **Item 7:** a recomendação é manter a análise de lados na fonte única, com as correções.

## Números medidos

- **Produção, 07/10/2026** (`master`, execução das 08:09): geração de 208 a 291 s a 11-16 tok/s,
  áudio de 28 a 48 s, Telegram de 3 a 30 s (o upload do áudio às vezes falha e é tentado de novo);
  execuções de 20 itens em 74 a 109 minutos.
- **Duas execuções quase sem memória:** às 13:20 de 07/10, com 0,3 GB disponíveis, e às 09:11 de
  11/10, com 0,5 GB e 7,4 tok/s, antes de o `nvidia-open-lts` ser instalado (provavelmente com o
  modelo inteiro na RAM). As travas da máquina não são hipotéticas.
- **Rodadas de 14/10:** análise de lados em 28 s, geração em 95 s, correção em cerca de 40% dos
  itens (uns 25 s em média por item), áudio em uns 35 s e Telegram em uns 10 s: uns 3,2 minutos
  por item e de 65 a 80 minutos para 20 itens, somando a coleta e a primeira carga do modelo. Fica
  abaixo dos 180 minutos de `MAX_RUNTIME_MIN` e das 4 horas da unit.
- **Com o agrupamento:** a extração de uns 100 candidatos leva cerca de 1 minuto e a etapa 3 cerca
  de 2; a geração de uma pauta de 3 fontes, uns 110 s.

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
   plano de 19/10"). Em 23/10, a regressão depois das correções também não atingiu o aceite: 4 de
   20 aprovados, todos os outros por palavras abaixo do mínimo, e uma disputa inventada nova (N27).
   Em 24/10, as decisões do dono entraram (f1e2713 e 31a2060), e a rodada curta de 8 itens também
   não atingiu o aceite: 5 de 8 aprovados, os outros por palavras, porque a conta do bloco não
   fecha, com 9,8 marcas por mil palavras. Na segunda leva do mesmo dia, o plano das falas entrou
   (70ef651), e a segunda rodada curta também não atingiu o aceite: 6 de 8 aprovados, com 6,8 marcas
   por mil palavras. Na terceira leva, a mensagem do que falta em cada fala, o teto pelo material, a
   passiva de decisão, o nome do analista, o "Sim" e "Não" e o número ligado ao que mede entraram
   (bb1fc8b), e a terceira rodada curta também não atingiu o aceite: 3 de 8 aprovados, todos os outros
   por palavras, com 7,9 marcas por mil palavras. Na quarta leva, o mínimo do QA em 60% do alvo, os
   nomes dos analistas pelo código e as aspas na contagem de menções entraram (8d1a2d2), e a
   regressão nos 20, direto, sem outra rodada curta, atingiu o aceite de 23/10: 19 de 20 aprovados,
   nenhuma disputa inventada, 10% de frases marcadas e 16 atribuídos (7 nas disputas), com 7,3 marcas
   por mil palavras (7,4 com a correção da leitura do A14 que o dono fez em 25/10). Em 25/10 o dono
   aceitou o resultado e mandou seguir para o item 5.
5. **Integração do agrupamento** atrás de `AGRUPAMENTO_ATIVO`, com os filtros, o limite de
   tentativas, os excedentes e o registro de cada execução. Plano aprovado em 25/10 (ver "Integração
   do agrupamento: o plano de 25/10"). Implementada em 25/10, desligada por padrão, com
   `AGRUP_MAX_PROVISORIA` em 6; faltam as simulações de trabalho.
6. **Simulação de ponta a ponta.** A que libera o merge roda com `AGRUPAMENTO_ATIVO=false`, que é o
   que vai para produção, e com áudio. A rodada com o agrupamento ligado é uma prévia. Antes do merge
   vem também a validação cega da fonte única na quarta coleta (decisão de 29/10/2026): a terceira
   amostra deixou de ser cega com as correções da análise de lados feitas olhando para ela (ver "O
   gabarito da terceira amostra e a validação cega: as decisões de 29/10").
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

Em 23/10/2026, ao ler o relatório das medidas (`data/agrupamento/medidas_20261020/relatorio.md`):

- **Item 2, aprovado:** a última linha da tabela (verbo no trecho ou na frase, citação direta, verbo
  de decisão de quem decidiu, marcadores e o coletivo), os verbos novos (classificar, ressaltar, o
  infinitivo e o pretérito composto como par de auxiliar e particípio) e a frase do N69 no
  `PROMPT_LADOS`. O "considerar" fica fora. As quatro limitações da conferência vão para o CLAUDE.md.
- **Item 6, aprovado:** a nova tentativa para o ator cujo trecho não vale, na mesma vaga da que já
  existe.
- **Item 4, aprovado, com três ajustes:**
  - nenhum veículo dos exemplos pode existir: o "Diário do Litoral" é um jornal real de Santos, e um
    veículo real é o nome que o modelo pode pôr num episódio em que ele não é fonte;
  - a regra de não acrescentar avaliação, motivo, consequência, previsão ou argumento vale também
    para o "por que importa";
  - a seção soma uns 1.500 caracteres ao `PROMPT_SISTEMA`, que saem do espaço do texto: a regressão
    mostra os caracteres que cada texto recebe, ao lado dos de 17/10.
- **Item 3, aprovado, com o fator de 1,75 e três ajustes:**
  - o número de turnos e as palavras por turno seguem o alvo (10 a 20 turnos de 50 a 90 palavras
    são 500 palavras no mínimo, que não cabem num alvo de 350);
  - os mínimos do QA ficam sempre abaixo do alvo de cada personagem, inclusive com os pisos de 120 e
    180 (no N92, o alvo da Helena seria de uns 150 a 190, e o piso de 180 passaria dele);
  - os máximos não mudam nesta rodada. Quanto cada personagem passa do alvo, e o teto de 200 do lado
    fino, entram na regressão como diagnóstico; a decisão de pôr um teto no QA vem depois.
- **Item 5:** "dois milhões e meio" lido como 2,5 milhões entra já, porque é relaxamento. Ler "três
  vírgula seis bilhões" com a escala passa antes pelo diagnóstico.
- **A regressão:** os mesmos 20 itens, com as duas amostras em pastas separadas, a sessão de teste no
  ar e o `systemd-inhibit`; a leitura frase a frase com o mesmo critério do `leitura_fase4.py`; a
  tabela da linha de base com as três versões lado a lado (17/10, a regressão e a `master`). Prompt e
  QA não mudam por causa do resultado: ele vem primeiro para o dono.
- **O critério de aceite da regressão** (substitui o de 16/10 para esta rodada):
  - pelo menos 17 de 20 aprovados;
  - nenhuma disputa inventada;
  - frases marcadas até 21% no total;
  - argumentos atribuídos até o nível da `master`: 34 no total e 9 nas cinco disputas.

  As subdivisões por tamanho de texto e por tipo vão para o relatório, sem barrar: com uma rodada de
  cada lado, são ruído.
- **Terceira amostra:** a coleta 2 em 23/10; a 3 quando o dono pedir, a partir de 26/10.

Em 24/10/2026, ao ler o resultado da regressão (a fidelidade resolvida, o tamanho reprovando):

- **Tamanho do roteiro: as saídas a e b, com acréscimos.**
  - O número que o bloco diz para cada personagem é o alvo, não o mínimo do QA. O QA continua em 75%
    do alvo, e a diferença fica como margem, como nas frases do resumo.
  - O número de turnos também é um número só, calculado com falas de 70 a 80 palavras.
  - A volta do "expanda as falas" diz com o quê: com o que os textos trazem, sem argumento novo.
  - O "com pouco material, fale menos" do item 4 muda, porque contradiz o "expanda até o alvo". Entra:
    "o alvo do bloco já é menor quando há pouco material; cumpra-o com o que os textos trazem, sem
    argumento novo".
  - O fechamento deixa de pedir que a Helena resuma "o que ficou claro". Ela recapitula os fatos e as
    posições, cada uma atribuída, e o que os textos dizem que segue em aberto. O "fica claro que..."
    é a marca mais comum nos itens de um lado.
- **Análise de lados:**
  - N27: as saídas (a) e (b), juntas: separar a frase também no ";" e recusar a questão que não é de
    sim ou não;
  - A14: a saída (c), a conferência do trecho só com dois lados ou mais com ator nomeado;
  - A72: só medida, sem regra, de quanto da posição de cada lado e ressalva não está no trecho dela.
- **Para a integração do agrupamento:** com vários veículos, o prompt maior tira texto da geração (ver
  o estado de 24/10).
- **Rodada curta antes da regressão:** 8 itens (N86, A63, N92, N13, A79, A104, N27 e N84), lidos frase a
  frase com o mesmo critério e com as marcas separadas por personagem e pelo fechamento.
  - Passa com pelo menos 7 de 8 aprovados e menos de 10 marcas por mil palavras (17/10 teve 12,6, e a
    regressão, 6,9).
  - Junto, sem o modelo: quantos dos 20 episódios da regressão passariam com o mínimo do QA em 60%,
    65% e 70% do alvo, a alternativa de aceitar episódios mais curtos.
  - Prompt e QA não mudam por causa do resultado: ele vem primeiro.
- **Terceira amostra:** a coleta 3 a partir de 26/10, quando o dono pedir.

Em 24/10/2026, segunda leva, ao ler o resultado da rodada curta (o diagnóstico e as três leituras
confirmados):

- **Tamanho: a opção a.** O bloco diz quantas falas cada personagem tem e de que tamanho, numa
  sequência que começa e termina com a Helena; o relatório mostra o plano de cada um dos 8 itens e a
  conferência feita sem o modelo. A revisão recebe o mesmo plano e o mantém: corrige o que o QA apontou
  sem encurtar as falas. As opções b (a Helena com uns 50%) e c (o mínimo do QA mais baixo) ficam de
  fora por enquanto.
- **Contagem de menções, agora:** com o plano, os analistas chegam ao alvo, e a Beatriz do A79 seria
  levada a 350 palavras com 2 frases de material. Antes de mudar, medir nas análises gravadas quantas
  divisões mudam e listar os sobrenomes que passam a contar. O sobrenome sozinho não conta quando outra
  pessoa citada no texto tem o mesmo (Bolsonaro, por exemplo). Só na contagem, não na regra do QA.
- **Fechamento, a opção a:** a Helena só fala do que segue em aberto quando os textos disserem; se não
  disserem, não fala disso. Ela também não tira conclusão que os textos não tiram ("fica claro
  que..."). A regra do QA para a Helena fechar fica só como diagnóstico: contar os episódios que
  terminam com o analista.
- **N27:** o lado único só com Flávio é desequilíbrio numa matéria que compara dois candidatos, e vai
  se repetir sempre que a conferência tirar um dos dois. A regra da questão aberta se amplia: com
  qualquer número de lados, a questão que não é de sim ou não leva ao lado neutro. Antes, medir nas
  análises gravadas, com as da rodada curta; na rodada, contar as falas e as palavras de cada plano no
  N27.
- **Outros pontos:**
  - a pergunta com confirmação no fim ("..., não é?") afirma e se julga pelo texto: o 3.1 do N84 fica
    sem marca porque o texto descreve a mudança, e não por ser pergunta;
  - A72: a medida da posição contra o trecho não diz de quem são as palavras que vão além dele, então
    não separa a paráfrase da atribuição errada. Fica como limitação, sem regra por enquanto;
  - A63: conferir de que lado ficou o Kassio; se o "Sim" o pôs junto de Lula, é lado trocado, conta
    como erro da análise, e o relatório diz por que a conferência não pegou.
- **A rodada:** os itens 1 a 4 com testes e commit, com o CLAUDE.md e o roteiro atualizados. A
  mudança do item 2 que contar sobrenome para a pessoa errada, ou a do item 4 que mudar uma análise
  certa pelo gabarito, fica fora da rodada, e a medida vem para o dono.
  - Depois, os mesmos 8 itens, com o mesmo critério: pelo menos 7 aprovados e menos de 10 marcas por
    mil palavras.
  - O relatório traz também: de cada analista, as palavras, o alvo, as frases do lado dele no recorte
    e as marcas, com o lado fino em destaque, e a mesma conta, sem o modelo, para os analistas de
    17/10 e da regressão (a partir de que proporção entre palavras e material o analista passa a
    inventar); se o plano foi seguido (falas e palavras por personagem); os episódios que terminam
    com o analista.
  - Se a rodada curta passar nos dois critérios, segue a regressão nos 20, com o critério de 23/10,
    as marcas por mil palavras e as mesmas medidas por analista. Se não passar, parar e trazer.
  - Em nenhum caso mudar prompt ou QA por causa do resultado.
  - Se o analista do lado fino inventar para chegar ao alvo, trazer a medida: baixar o piso de 120 é
    decisão do dono.

Em 24/10/2026, terceira leva, ao ler o resultado da segunda rodada curta (a invenção caiu, o fechamento
foi de 12 marcas para 4, o N27 deixou de favorecer um dos planos; as leituras confirmadas, inclusive a de
citar o "fica claro que..." no prompt):

- **1. Tamanho das falas, a opção a:** na revisão por palavras, a mensagem do QA diz o que falta em cada
  fala, com o que os textos trazem. O tamanho em frases fica para depois, se não bastar. O relatório
  mostra quantas palavras cada revisão acrescentou.
- **2. Teto do alvo pelo material:** o alvo de cada analista não passa de 90 palavras por frase do lado;
  com 1 frase, o teto prevalece sobre o piso de 120 e o alvo fica em 90. Só nas pautas com dois lados
  ou mais: com um lado só, o analista explica a história inteira, e o alvo dele não muda. Antes, medir
  sem o modelo quais alvos mudam nos 20 itens e nas análises gravadas.
- **3. Voz passiva na regra dos analistas por lado** (relaxamento): o verbo de decisão na passiva, com o
  ator como agente ("foi determinada por decisão de <ator>"), apresenta o lado, como na conferência V4 da
  análise de lados, com a mesma lista de verbos de decisão nas duas. Antes, medir nos episódios gravados.
- **4. Nome do analista:** o analista não pode ter o nome de uma pessoa citada nos textos, nem o primeiro
  nome dela. Evitar onde o nome é escolhido (código ou prompt) e pôr a regra no QA, conferindo contra os
  atores da análise, como na medida (só o N86, nas quatro rodadas).
- **5. Respostas de sim ou não:** numa disputa de dois lados, as respostas da análise de lados são "Sim"
  e "Não", opostas; com três, fica a conferência de hoje. Das 10 análises que a regra pegaria, 2 são o
  A63 com a resposta do Kassio trocada e 8 têm os lados certos com respostas descritivas, que a nova
  tentativa deve consertar. Diferente da análise inválida (que vira lado neutro se a nova tentativa
  também falhar): se a primeira só falhou nesta regra e a nova tentativa não valer, por qualquer motivo,
  fica a primeira. Na rodada, conferir no A63 se as respostas de Lula e do Kassio batem com a questão:
  a citação de Lula começa com "Não vamos aceitar", e a nova tentativa pode virar um "Não" limpo do lado
  errado, que a regra não pega.
- **6. Número ligado à coisa certa:** nas regras de números do `PROMPT_SISTEMA`, com exemplo inventado:
  "Um número fica com o que o texto diz que ele mede. Se o texto diz que 4 mil ingressos foram vendidos
  e que só os não usados serão devolvidos, não diga que 4 mil ingressos serão devolvidos." (o N92 pôs os
  30 mil exemplares no recolhimento em quatro das cinco rodadas, contando a da master).
- **7. Leitura:** sai. O "Partido dos Trabalhos" do N27 já está marcado como F no R5.
- **A rodada:** os itens 1 a 6 com testes e commit, com o CLAUDE.md e o roteiro atualizados; a parte de
  2 a 5 cuja medida mostrar mudança errada fica fora, e a medida vem para o dono. Depois, os mesmos 8
  itens, com o mesmo critério e o mesmo relatório; se passar, a regressão nos 20, com o critério de
  23/10, as marcas por mil palavras e as medidas por analista. Se não passar, parar e trazer. Em nenhum
  caso mudar prompt ou QA por causa do resultado.

Em 24/10/2026, quarta leva, ao ler o resultado da terceira rodada curta (as duas decisões minhas confirmadas: a Helena
com no máximo 45% do total que sobra quando o teto corta, e a nova tentativa por ator faltando valendo como antes; as
leituras certas, menos o "queimadas causadas pelo El Niño" do A79, que conta como A):

- **1. Mínimo do QA em 60% do alvo:** o mínimo de cada personagem e do total passa de 75% para 60% do alvo, e os mínimos
  antigos (240, 180, 120 e 600) continuam como teto. O plano continua pedindo o alvo inteiro. É relaxamento: os
  analistas de material cheio já passam com 56% (240 de 430), e a regra dá a mesma folga aos outros. O motivo: desde
  23/10, os analistas ficam entre 66% e 73% do alvo, e nem o plano nem a mensagem por fala os fizeram escrever mais.
- **2. Nomes dos analistas pelo código:** sai do prompt a frase sobre o nome (depois dela, todos os analistas viraram
  "Analista de Política", "Analista Jurídico"...). O código dá os nomes, de uma lista fixa de nomes de pessoa, sem os
  nomes e os primeiros nomes dos atores da análise; o bloco diz o nome de cada analista, e o QA confere que o roteiro usa
  esses nomes. Conferir como o TTS escolhe a voz, para que todo nome da lista tenha voz.
- **3. Contagem de menções:** a menção que só aparece dentro de aspas não conta (no A79, a segunda frase do comandante é
  o ministro falando dele; no N13, uma das frases de Lula é a da área técnica sobre o canal "Exército de Lula"). Antes,
  medir e listar as frases que deixam de contar, inclusive as que são fala do próprio ator. Na mesma medida, o sobrenome
  sozinho só vale para nome de pessoa (no N92, "Unificado" contou como sobrenome do "Sindipetro Unificado").
- **4. Número:** a frase do número sai do prompt (não mudou o N92 nem evitou o caso do A104); o número ligado à coisa
  errada fica como limitação conhecida.
- **A regressão:** os itens 1 a 4 com testes e commit, com o CLAUDE.md e o roteiro atualizados; a parte do item 3 cuja
  medida mostrar mudança errada fica fora, e a medida vem para o dono. Depois, direto à regressão nos 20, sem outra
  rodada curta, com o critério de 23/10, as mesmas medidas das rodadas curtas e a leitura frase a frase, acompanhando as
  marcas da Helena fora do fechamento (de 4 para 12 na terceira rodada curta). Não mudar prompt nem QA por causa do
  resultado.

Em 25/10/2026, ao ler o resultado da regressão da quarta leva (as leituras certas, menos a do A14):

- **A regressão passou** nos quatro critérios de 23/10. O "lançou o GPT-5 para corrigir a falha" do A14 (R3) conta como
  A: o texto diz que o GPT-5 foi ajustado para reduzir o problema, não que foi lançado para corrigi-lo. Com isso, 79
  marcas em 785 frases (10%) e 7,4 por mil palavras de roteiro; o resumo, os pontos e o "por que importa" vão de 3,5 para
  3,8 por mil (`data/agrupamento/correcoes_20261024d/leitura_regressao2.py` e as tabelas refeitas).
- **Ficam como diagnóstico para a terceira amostra, sem mudança agora:** os 30 mil do N92 e a revisão que encurtou a
  analista; a Helena fora do fechamento (3,9 por mil); o resumo, os pontos e o "por que importa".
- **O próximo passo é o item 5,** com o plano da seção "Integração do agrupamento: o plano de 25/10", aprovado com três
  decisões e sete ajustes (lá).

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
- **Segunda coleta, em 23/10/2026 (sexta) às 16:20:** `amostra_20261023-162009.json`, 106 candidatos
  (45 com categoria), nenhum em comum com a primeira, com a saída em `coleta_20261023-162009.txt`, os
  pares em `pares_20261023-162009.csv` (8 com score de 0,15 para cima; 4 pautas provisórias de 2
  artigos) e a lista para rotular em `candidatos_20261023-162009.csv`, no formato da primeira. A
  terceira fica para quando o dono pedir, a partir de 26/10.
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

Ponto a estudar antes de ligar, junto com a regra estrita (decisão de 25/10/2026): **a janela dos
outros veículos.** Nas duas pautas da prévia de 25/10 com veículo errado, os relacionados entraram na
geração com 872 a 1.374 caracteres (G1 com 919 e Agência Brasil com 872 no 92+97+63; Gazeta com 1.374
e Valor com 1.258 no 64+13+42), e o prompt de hoje tira de 1.393 a 2.078 caracteres de texto por pauta
em relação ao de 17/10. O 90+79+43 também teve relacionados curtos (1.214 e 1.426) e nenhuma frase com
veículo errado, então a ligação não está provada. Nada muda agora, porque o merge vai com o
agrupamento desligado.

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

**Em 23/10, as correções aprovadas** (ver as decisões dessa data):

- **Commits:** itens 2 e 6 (0f448ff), item 5 (d5affcd), item 4 (b8b74b2) e item 3 (e4a63af), com 430
  testes passando.
- **Item 2 conferido no código:** nas 127 análises gravadas, o código pega as 3 disputas inventadas de
  17/10 e perde as 3 análises da pauta 71+85, sem a nova tentativa, como na medida de 20/10
  (`data/agrupamento/correcoes_20261023/conferir_item2.py`). "Segundo <ator>" como marcador não
  mudaria nada nessas análises e ficou fora, como na regra medida.
- **Efeito no QA dos episódios gravados** (`refazer_qa.py` nos 60, contra o código de antes): os verbos
  novos e o "e meio" não mudam nada; o orçamento só tira o problema de palavras da Beatriz no N55, que
  continua reprovado pela regra dos analistas.
- **Leituras minhas no orçamento, para o dono corrigir:**
  - a parte da Helena é a de antes dentro de 35% a 45%: 45% com um analista, 35% com dois ou três;
  - nenhum personagem passa de 430 palavras de alvo, para a faixa ficar abaixo dos 480 que o prompt
    pedia; com um lado fino, o total fica abaixo do teto;
  - a faixa do bloco é o alvo com 10% para cada lado, e o mínimo do QA, 75% do alvo, nunca acima do
    mínimo de antes: os pisos de 120 e 180 viraram o limite de cima do mínimo, que fica sempre
    abaixo da faixa;
  - as falas têm 50 a 90 palavras a partir de 600 no total e encolhem na proporção até 30 a 54; os
    turnos são os que cabem no total, nunca menos que a estrutura (5, 7 ou 9) nem mais que 20.
- **Item 4:** o "Jornal do Vale" (jornaldovale.com, Goiás), que também existe e estava no mesmo
  exemplo do `PROMPT_SISTEMA`, saiu junto com o "Diário do Litoral", pelo mesmo critério.
- **Terceira amostra, coleta 2:** feita (ver a seção da terceira amostra).
- **Regressão:** em `data/agrupamento/rodada_20261023/` (o detalhe em `resultado.md`; a leitura e
  as medidas em `data/agrupamento/correcoes_20261023/`).

**Em 23/10, a regressão** (16:45 a 17:33, 62 chamadas, memória disponível sempre acima de 17,2 GiB):

- **O aceite de 23/10 não foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 17 de 20 ou mais | 4 |
  | Disputa inventada | nenhuma | 1 (N27) |
  | Frases marcadas | até 21% | 10% |
  | Argumentos atribuídos | até 34, e 9 nas disputas | 16, e 7 nas disputas |

- **Os 16 reprovados caíram só por palavras.** O roteiro saiu com 508 palavras em média, contra 862
  em 17/10 e 968 na `master`.
  - Os turnos quase não mudaram (8 contra 9).
  - As falas encolheram de 96 para 64 palavras: em 17/10 elas já passavam das 90 que o prompt
    pedia, e era isso que fazia os roteiros passarem dos 600.
  - A primeira versão fica abaixo do mínimo em 16 itens, contra 2 em 17/10, e a revisão acrescenta
    26 palavras pela mediana.
  - Hipótese: saiu do `PROMPT_SISTEMA` o "expanda as falas até cumprir o mínimo", o item 4 diz "com
    pouco material, fale menos", e o modelo mira o piso de qualquer faixa.
- **Análise de lados:**
  - as três disputas inventadas de 17/10 sumiram;
  - as cinco disputas certas ficaram;
  - o N27 inventou uma disputa nova (planos de governo, "Qual deve ser a prioridade...?"), pelo
    verbo do outro ator na mesma frase do título, que é a limitação 1;
  - o A14 perdeu a OpenAI: a conferência recusou "admitiu" numa resposta de um lado só, e a nova
    tentativa voltou sem ator.
- **A leitura** (`leitura_regressao.py`, mesma régua): 10% das frases marcadas, contra 21% em 17/10
  e 30% na `master`. São 6,9 marcas por mil palavras de roteiro, contra 12,6 e 18,1: a queda não vem
  só do roteiro mais curto.
- **O item 4 na prática:** o N84 manteve a ressalva do próprio veículo. A análise do Diolinux ainda
  vai para a boca da comunidade no A72, por causa da posição da ressalva na análise de lados.
- **Caracteres recebidos:** iguais aos de 17/10, a não ser no A92, que mudou por outra causa. Na
  fonte única, o teto de 5.000 limita antes da janela. O `PROMPT_SISTEMA` passou de 7.843 para
  9.280 caracteres, e a conta vai pesar nas pautas com vários veículos.
- **Diagnósticos:** só a Helena do N92 passou da faixa; nenhum analista de lado fino passou de 200;
  o `checar_fidelidade.py` só acha ruído.
- **À espera do dono** (propostas em `resultado.md`; nada foi mudado):
  - a falta de palavras: a instrução de expandir de volta, e o bloco com o mínimo de cada
    personagem e um número de turnos só, validados antes numa rodada de uns 8 itens;
  - o N27: recusar a questão que não é de sim ou não, ou separar a frase no ";". Cada uma pega só o
    N27 nas 147 análises gravadas;
  - o A14: a conferência do trecho só com dois lados nomeados ou mais, que é relaxamento.

**Em 24/10, as decisões do dia** (ver as decisões dessa data):

- **Commits:** o tamanho do roteiro (f1e2713) e a análise de lados (31a2060), com 435 testes passando.
- **O bloco, como ficou:** "Alvo de palavras: Helena, 350; analista, 430; total, 780. Roteiro de 10
  turnos, com falas de 70 a 80 palavras."
  - Os turnos são o total dividido por 75, nunca abaixo da estrutura (5, 7 ou 9) nem acima de 20.
  - Quando a estrutura pede mais turnos do que o total comporta, o bloco diz a média ("falas de uns 60
    palavras").
  - A mensagem do QA diz o alvo como número só.
- **A análise de lados, conferida nas 147 análises gravadas** (as 127 de antes e as 20 da regressão):
  - o N27 deixa de ser disputa inventada;
  - a primeira resposta do A14 fica com a OpenAI;
  - duas análises da pauta 1 recuperam o Milei, que o gabarito lista;
  - nada piora.
- **Leituras minhas, para o dono corrigir:**
  - o bloco diz o alvo como número, sem "pelo menos": é o "expanda até o alvo" do `PROMPT_SISTEMA` que
    faz o alvo funcionar como o tamanho a cumprir;
  - quando a estrutura pede mais turnos do que o total comporta com falas de 70, o bloco diz a média
    que sobra, em vez de 70 a 80;
  - o aviso de pouco material do bloco passou a dizer o mesmo que a frase nova do item 4 ("o alvo já
    é menor: cumpra-o com o que as fontes trazem, sem argumento novo"), em vez de "não preencha o
    tempo com argumento";
  - o fechamento novo entrou também em `_REGRAS_DO_ROTEIRO`, porque as duas revisões reescrevem o
    roteiro inteiro;
  - o "sem argumento novo" entrou também no "EXPANDA" das duas revisões;
  - a questão aberta usa a lista de palavras que foi medida (qual, quais, como, quem, o que, por
    que, onde, quando).
- **O custo do prompt para a integração do agrupamento:**
  - o `PROMPT_SISTEMA` passou de 7.843 para 9.329 caracteres (1.437 a mais depois de 23/10, e 1.486
    com as mudanças de 24/10);
  - na fonte única, o teto de 5.000 caracteres do principal limita antes da janela, e nenhum texto
    perdeu espaço;
  - com vários veículos, a janela limita, e a geração perde até 1.486 caracteres de texto;
  - medir isso na prévia com o agrupamento ligado.
- **A72, medida sem regra** (`data/agrupamento/correcoes_20261024/posicao_e_trecho.py`):
  - nos lados, a posição fica longe do trecho (pela mediana, 55% das palavras de conteúdo não estão
    nele), mas não do texto (11%): ela resume o lado com o que o texto diz em outras partes;
  - nas ressalvas, a mediana é 0%, mas 5 das 12 têm metade ou mais da posição fora do trecho, quase
    tudo de outras partes do texto: no A72, nas duas rodadas, a ressalva da comunidade leva a análise
    do Diolinux;
  - é o mecanismo por que o grupo recebe palavras que o texto não põe na boca dele.
- **O mínimo do QA abaixo de 75%, sem o modelo**
  (`data/agrupamento/correcoes_20261024/fracao_do_minimo.py`):
  - nos 20 episódios da regressão, 70%, 65% e 60% do alvo aprovariam 6, 11 e 12, contra 4 em 75%;
  - mesmo em 60%, oito ficam reprovados, por algum personagem abaixo do mínimo dele.

**Em 24/10, a rodada curta** (07:33 a 07:52, 21 chamadas, memória disponível sempre acima de 17,2
GiB; o detalhe em `data/agrupamento/rodada_20261024/resultado.md`):

- **O aceite não foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 7 de 8 ou mais | 5 (A79, A104, N86, N27, N84) |
  | Marcas por mil palavras de roteiro | menos de 10 | 9,8 |

  As marcas passam por uma: com 48, seriam 10,0. Nos mesmos 8 itens, 17/10 teve 14,6 e a regressão,
  4,8.
- **Os três reprovados (A63, N92 e N13) têm pouco material e caíram por palavras.** A conta do bloco
  não fecha:
  - o modelo segue os turnos e o tamanho da fala: 7 dos 8 saíram com o número exato de turnos, e as
    falas pedidas de 70 a 80 saíram com 64 a 81 palavras, para a Helena e para os analistas;
  - a Helena fala em metade dos turnos e fica com 49% das palavras, contra 35% a 45% do alvo. Ela
    chegou a 108% do alvo, e os analistas, a 76%;
  - com material cheio, os analistas precisariam de 86 ou 87 palavras por fala. Com pouco material,
    nem a fala do tamanho pedido leva ao mínimo: a Bia do N92 teve uma fala só;
  - com um analista, os 10 turnos pedidos não terminam com a Helena: o A104 e o N27 terminam com o
    analista, e o N84 fez 11 turnos;
  - a revisão não expande: no A63 e no N13, ela encurtou o roteiro;
  - o mínimo do QA em 70% ou 65% do alvo daria os mesmos 5 aprovados, e em 60%, 6.
- **A leitura** (`data/agrupamento/correcoes_20261024/leitura_curta.py`, mesma régua), em marcas por
  mil palavras do grupo:
  - resumo e pontos, 2,1; Helena fora do fechamento, 2,3; analistas, 11,7; fechamento, 16,2;
  - 16 das 27 marcas dos analistas são do A79. O alvo é o mesmo que na regressão deu 3 marcas, mas
    agora são 14 turnos em vez de 7: cada analista respondeu 4 perguntas, e o lado do comandante tem
    2 frases no texto;
  - no fechamento, o "segue em aberto" sem base no texto deu 3 marcas; o "fica claro" caiu de 4 itens
    para 2; e 4 marcas são do analista que fala depois da Helena.
- **Análise de lados:** o N27 ficou sem disputa, só com o lado de Flávio, porque o trecho de Lula
  perdeu o verbo no ";". As quatro disputas ficaram com os dois lados.
- **À espera do dono** (propostas em `resultado.md`; nada foi mudado):
  - o bloco dizer as falas de cada personagem, quantas e de que tamanho, numa sequência que termina
    com a Helena (a recomendada);
  - só falar do que segue em aberto quando os textos disserem;
  - contar o sobrenome sozinho nas menções, depois de medir.

**Em 24/10, a segunda leva** (as decisões de mesmo nome; medidas em
`data/agrupamento/correcoes_20261024b/`):

- **Item 4, medido antes** (`medir_questao_aberta.py`): das 185 análises gravadas, só as duas do N27
  (23 e 24/10) têm questão aberta, as duas na resposta que valeu, e a da rodada curta também na
  primeira tentativa. As duas passam de "Flávio Bolsonaro" para o lado neutro e continuam certas pelo
  gabarito, que não tem disputa. Nenhuma análise certa muda: entra na rodada.
- **Item 2, medido antes** (`medir_sobrenomes.py`): das 61 análises com dois lados ou mais, mudam 28
  divisões do orçamento e 3 lados finos (o Cueva da pauta 71+85 passa de 1 frase para 3).
  - Os sobrenomes que passam a contar são Amorim, Cueva, Góes, Janones e Marques, todos da pessoa
    certa, frase por frase. Nenhum ficou de fora por outra pessoa com o mesmo sobrenome.
  - A primeira versão barrava Janones e Amorim por engano: em "Lula, Janones e Sidônio", lia "Lula"
    como prenome. Corrigido antes da medida final: só vale a palavra colada ao sobrenome, com espaço
    ou partícula entre elas.
  - No A79, o ministro passa de 2 frases para 4, e a divisão, de 350 e 350 para 430 e 230. Entra na
    rodada.
- **Item 1, o plano sem o modelo** (`planos.py`): nos 20 itens da regressão, todos os planos começam e
  terminam com a Helena, ela nunca fala duas vezes seguidas, cada analista tem de 2 a 5 falas de no
  máximo 90 palavras, e falas × tamanho ficam entre 96% e 105% do alvo. O plano dos 8 itens vai no
  relatório da rodada.
- **O bloco com o plano** cabe: das 155 análises válidas, 3 encolhem as posições (dois lados e uma
  ressalva), e nenhuma é cortada. O `PROMPT_SISTEMA` foi para 9.604 caracteres.
- **A63:** o Kassio ficou num lado separado do de Lula, mas com a resposta "Sim" à pergunta "foi
  intromissão indevida?", que é a de Lula, em 17/10 e em 24/10 (na regressão, as respostas saíram
  certas). Lula ficou com uma citação que começa por "Não". Conta como erro da análise (respostas
  trocadas). A conferência não pegou por duas razões:
  - ela vê se o trecho traz uma resposta, e não qual: o do Kassio passou pelo "disse" de Lula na mesma
    frase (a limitação 1);
  - nada compara a resposta com a posição do lado nem cobra respostas de sim ou não opostas, só que
    sejam diferentes. Das 61 análises com disputa, 10 têm alguma resposta que não é sim nem não
    (`medir_respostas.py`): o A63 em duas e a pauta 86+71 em sete.
  - Uma regra para isso reprovaria: passa antes pelo diagnóstico, e fica para o dono.
- **Limitação registrada (A72):** a medida da posição contra o trecho mostra que a posição vai além
  do trecho em mais da metade das palavras, quase sempre com palavras do texto, mas não diz de quem
  são essas palavras, então não separa a paráfrase da atribuição errada. Sem regra por enquanto.
- **A leitura:** a pergunta com confirmação no fim afirma e se julga pelo texto. O 3.1 do N84 fica sem
  marca porque o texto descreve a mudança.
- **Leituras minhas, para o dono corrigir:**
  - cada analista tem as falas que o alvo pede com no máximo 90 palavras (o máximo de fala do prompt
    de antes), e pelo menos 2; o tamanho vai arredondado a 5 ("uns 85");
  - a Helena fala entre as rodadas e não entre cada analista: com dois analistas, eles falam em
    seguida ("Helena, lado 1, lado 2, Helena"). Com três analistas de 250, a Helena fica com 4 falas de
    uns 100 palavras;
  - o bloco dá o alvo e o plano juntos, e a ordem como lista ("Helena, lado 1, lado 2, ..."); com um
    analista, a lista também vai inteira;
  - o "fica claro que..." aparece no prompt, entre parênteses, como o que não se faz, como na decisão;
    em 24/10 ele tinha saído do prompt para não ser sugerido;
  - o sobrenome conta para nome de pessoa (duas palavras ou mais, todas com maiúscula, a penúltima sem
    partícula); "o ministro" continua não contando; começo de frase e cargo antes do sobrenome não são
    outra pessoa;
  - a questão aberta vai direto ao lado neutro, sem nova tentativa (antes, com dois lados, ela ganhava
    uma), e as ressalvas saem, como em todo lado neutro;
  - o teste da janela de 8192 passou a usar a menor proporção de caracteres por token medida (3,26):
    com a inicial de 3,0, que só vale se a análise de lados falhar, um texto de 5.000 caracteres
    perderia o último parágrafo.

**Em 24/10, a segunda rodada curta** (19:03 a 19:20, 19 chamadas, memória disponível sempre acima de
18,2 GiB; o detalhe em `data/agrupamento/rodada_20261024b/resultado.md`):

- **O aceite não foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 7 de 8 ou mais | 6 (A79, A104, N86, N92, N27, N84) |
  | Marcas por mil palavras de roteiro | menos de 10 | 6,8 |

  A regressão nos 20 não rodou.
- **O plano das falas foi seguido em número e ordem, mas não em tamanho.**
  - O número de falas e a ordem bateram em 6 dos 8. No A79 faltou uma rodada; no N13 o analista falou
    duas vezes seguidas.
  - Nenhum episódio termina com o analista (2 de 8 de manhã).
  - As falas dos analistas saíram com uns 75% do tamanho do plano, e as da Helena, com 89%. O roteiro
    médio caiu de 597 para 517 palavras.
- **Os dois reprovados:**
  - **A63, pela regra dos analistas por lado.** A Beatriz apresenta o Kassio na voz passiva ("foi
    determinada por decisão do presidente do TSE"), e o particípio sozinho não é verbo de posição. O
    texto só traz o Kassio assim. A revisão completa corrigiu as palavras sem encurtar.
  - **N13, por palavras.** O Dr. Ramos fez as 4 falas do plano com 49 palavras em vez de 90, e a
    revisão manteve o plano mas acrescentou só 15 palavras. O episódio não tem marca.
- **A leitura** (`data/agrupamento/correcoes_20261024b/leitura_curta2.py`): 28 marcas.
  - O fechamento caiu de 12 marcas para 4: nenhum "segue em aberto" sem base, e uma questão em aberto
    inventada (N84). O "fica claro" apareceu uma vez, no meio do A104.
  - 6 das 16 marcas dos analistas são da Bia do A79, a do lado do comandante (2 frases de material,
    185 palavras); o Dr. Ramos, do lado do ministro, não tem nenhuma.
- **Por analista** (`analistas.py`, nas quatro rodadas): nas pautas com disputa, a invenção salta
  acima de umas 90 palavras por frase do lado. Desde 23/10, até 50 palavras por frase dão 6,7 marcas
  por mil, de 50 a 90 dão 6,8, e acima de 90, 19,8.
- **Lado fino:** o Dr. Ramos do N92 (1 frase, alvo 120) escreveu 101 palavras com 2 marcas. Desde 23/10,
  5 dos 6 analistas de lado fino (44 a 120 palavras) não têm marca. O piso de 120 é decisão do dono.
- **N27:** foi para o lado neutro. O plano de Flávio ficou com 59 palavras e o de Lula com 94, contra
  umas 70 e 290 no texto; de manhã, com o lado único de Flávio, tinham sido 146 e 99.
- **Outras observações:**
  - no N86, o analista leva o nome do colunista que é a fonte ("Bruno Silva"); em 96 episódios
    gravados, só o N86 tem isso, nas quatro rodadas;
  - no N84, a ressalva do próprio veículo sumiu;
  - no N92, a distorção dos 30 mil voltou.
- **À espera do dono** (propostas em `resultado.md`; nada foi mudado):
  - a mensagem do QA dizer quantas palavras faltam por fala (a recomendada); ou o plano em frases;
  - um teto do alvo do analista pelo material, de 90 palavras por frase do lado;
  - aceitar na regra dos analistas por lado o verbo de decisão na passiva com o ator como agente;
  - o nome do analista igual ao de um ator, e as respostas trocadas, como regras a decidir.

**Em 24/10, a terceira leva** (as decisões de mesmo nome; medidas em
`data/agrupamento/correcoes_20261024c/`):

- **Item 2, medido antes** (`medir_teto.py`, `frases_do_teto.py` e `conferir_teto_no_codigo.py`): das 65
  análises gravadas com dois lados ou mais, 22 mudam de alvo, em quatro pautas; dos 20 itens, 3.
  - A79: o ministro (4 frases) vai de 430 para 360 e o comandante (2 frases), de 230 para 180; o total,
    de 1.040 para 920. N13: a campanha de Flávio (1 frase) vai de 120 para 90. N92: o Kassio (1 frase), de
    120 para 90. Na pauta 86+71, o Flávio (1 frase), de 120 para 90.
  - As frases contadas são da pessoa certa nas pautas da rodada. Numa análise antiga da pauta 79+105, a
    contagem do comandante inclui o "Corpo de Bombeiros Militar" (a instituição) e uma frase colada pelo
    corte do recorte: o teto fica mais folgado (270 em vez de 90 a 180), não mais apertado. É um erro da
    contagem que já existia, não do teto. Entra na rodada.
  - Nos 20 itens, todos os planos continuam fechando a conta (`planos.py`, `saida_planos_todos.txt`).
- **Item 3, medido antes** (`medir_passiva.py`): nos 44 episódios gravados com dois lados ou mais, só uma
  frase passa a apresentar um lado, a da Beatriz no A63 da segunda rodada curta, e o A63 passa a ter a
  correspondência um a um. Nas falas de analista dos 96 episódios, só essa frase tem a passiva de um
  verbo de decisão com agente (`saida_agentes_nos_episodios.txt`). Entra na rodada.
- **Item 4, medido de novo com a regra** (`medir_nomes.py`): os mesmos 4 casos em 96 episódios, todos do
  N86 ("Bruno" três vezes e "Bruno Silva" uma, contra o ator "Bruno Silva"). Entra.
- **Item 5, medido de novo com a regra** (`medir_sim_e_nao.py`): as mesmas 10 análises, agora de 65 com
  disputa (as 4 da segunda rodada curta já tinham "Sim" e "Não"). Entra.
- **O `PROMPT_SISTEMA`** foi para 9.878 caracteres (eram 9.604): o recorte da geração encolhe uns 270
  caracteres.
- **Leituras minhas, para o dono corrigir:**
  - teto: lado com 0 frases conta como 1 (como no peso da divisão), e lado sem contagem não tem teto; o
    que o teto tira sai do total, não vai para o outro lado; a Helena fica com a parte dela do total de
    antes do teto, mas não passa de 45% do total que fica (a faixa de 35% a 45% que já valia; nas análises
    gravadas, isso não muda nenhum alvo); o aviso de "pouco material" do bloco continua olhando só o
    material da pauta. Com o teto, a Helena pode ficar com falas mais longas, porque fala uma vez a mais
    que o analista que mais fala: no A79, 5 de 75 em vez de 6 de 65;
  - mensagem das palavras: só para quem está abaixo do mínimo. Com o número de falas do plano, diz quantas
    palavras acrescentar a cada fala ("acrescente uns 40 palavras a cada fala, com o que os textos
    trazem"); com outro número, quantas faltam para o alvo e "siga o plano"; o analista sem lado não tem
    plano, só as palavras que faltam;
  - passiva: o particípio de determinar, decidir, suspender e mandar, seguido em até 3 palavras de "por",
    "pelo", "pela", "pelos" ou "pelas"; o agente vai até o próximo verbo, conjunção ("e", "mas", "que"...)
    ou ponto e vírgula, então com dois agentes só o primeiro conta. A ativa "suspendeu" continua sem
    contar, e a mensagem do QA continua pedindo o verbo de posição;
  - nome: sem os títulos e cargos do começo ("Dr.", "presidente"), reprova o nome igual ao do ator ou o
    primeiro nome igual ao do ator que começa com maiúscula; o sobrenome sozinho passa ("Dr. Silva" com o
    ator "Bruno Silva"). O problema vai para a revisão completa, que pode trocar o nome; a revisão do
    roteiro continua sem trocar nomes;
  - sim ou não: vale "Sim" e "Não" com ou sem ponto final, e não "Sim, mas..."; o `PROMPT_LADOS` não
    mudou, a regra age pela nova tentativa. A nova só fica se valer e trouxer "Sim" e "Não" em dois lados
    (um lado só ou três não contam como consertar); quando a primeira já tinha "Sim" e "Não" e só faltava
    a entrada de um ator, fica a nova se valer, como antes, mesmo sem eles. A nova tentativa pede, se a
    questão não se responde com sim ou não, que ela seja reescrita sobre o mesmo fato;
  - número: a frase entrou só no `PROMPT_SISTEMA`, como pedido; as revisões continuam com "Todo número e
    todo percentual vêm das fontes, com o valor que elas trazem".

**Em 24/10, a terceira rodada curta** (20:52 a 21:11, 23 chamadas, memória disponível sempre acima de
18,2 GiB; o detalhe em `data/agrupamento/rodada_20261024c/resultado.md`):

- **O aceite não foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 7 de 8 ou mais | 3 (A104, N27, N84) |
  | Marcas por mil palavras de roteiro | menos de 10 | 7,9 |

  A regressão nos 20 não rodou. Os 5 reprovados caíram só por palavras, depois da revisão do roteiro;
  quatro deles ficaram poucas palavras abaixo do mínimo (126 de 135, 132 de 135, 135 de 142, total 275 de
  277). Com o mínimo em 70% do alvo, seriam 6 de 8.
- **O plano:** número de falas e ordem seguidos em 6 de 8; nenhum episódio termina com o analista. Os
  analistas escreveram 69% do alvo (73% na segunda rodada), e o roteiro médio foi de 517 para 492
  palavras.
- **Item 1:** a mensagem por fala chegou à revisão, mas a revisão deu de 0 a 5 palavras ao analista
  apontado nos 5 reprovados, e duas vezes acrescentou à Helena. Só acrescentou mais quando faltava uma
  fala inteira (+34 e +71). Quando o problema era só o total, resolveu (A104 e N84).
- **Item 2:** nenhum analista passou de 90 palavras por frase do lado. Os dois de lado fino (alvo 90)
  escreveram 71 e 58 palavras, sem marca. O analista do lado do comandante no A79 inventou de novo:
  5 marcas em 132 palavras, 66 por frase.
- **Item 3:** nenhum analista precisou da passiva; a correspondência um a um saiu certa nas 4 disputas.
- **Item 4:** o N86 não tem mais o nome do colunista, mas os 12 analistas da rodada saíram com nome de
  função ("Analista", "Analista de Política"...), contra nenhum em 140 até a segunda rodada; em 3
  episódios o papel foi "analista do lado 1". A causa provável é a frase nova do prompt.
- **Item 5:** as 8 análises valeram na primeira tentativa, e as 4 disputas já vieram com "Sim" e "Não",
  nos lados certos (no A63, Lula "Sim" e Kassio "Não"). A nova tentativa não foi acionada.
- **Item 6:** o N92 pôs de novo os 30 mil exemplares no recolhimento (cinco de seis rodadas), e o A104
  ligou 52,2% ao "total de vítimas" em vez dos casos.
- **A leitura** (`data/agrupamento/correcoes_20261024c/leitura_curta3.py`): 31 marcas, com o "queimadas
  causadas pelo El Niño" do A79 marcado como A por decisão do dono. O fechamento foi
  de 4 para 1; a Helena fora do fechamento, de 4 para 12 (avaliações e contrastes que o texto não faz);
  os analistas, de 16 para 12. A ressalva do veículo no N84 voltou.
- **À espera do dono** (propostas em `resultado.md`; nada foi mudado): o tamanho (o plano em frases, ou
  o mínimo em 70%); o nome do analista (a regra escrita pelo que se quer, ou os nomes dados pelo código);
  o lado do comandante no A79; o número ligado à coisa errada, que nenhuma conferência pega.

**Em 24/10, a quarta leva** (as decisões de mesmo nome; medidas em `data/agrupamento/correcoes_20261024d/`):

- **Item 3, as aspas, medido antes** (rascunho em `aspas.py`, medida em `medir_aspas.py`, conferência do código em
  `conferir_no_codigo.py`): das 69 análises gravadas com dois lados ou mais, em 46 alguma frase deixa de contar, mudam 46
  divisões do orçamento e 5 lados finos. Em todas as frases que saem, o nome do ator só aparece dentro das aspas:
  - a fala de outro ator sobre ele: o ministro sobre o comandante (A79 e 79+105), a campanha e o PT sobre a Meta (2+46),
    Lula sobre Nunes Marques, com o nome posto entre colchetes pelo jornalista dentro da citação (64+13+42);
  - o nome citado como título: o canal "Exército do Lula", em frases da área técnica, do TSE, do Cueva e do próprio
    canal (N13, 92+97+63, 64+13+42);
  - **a fala do próprio ator**: Lula falando do "Exército do Lula" e da "Aeronáutica do Lula" (N13 e 64+13+42, três
    frases), e uma frase em que ele é "o presidente" e só o canal tem o nome dele (64+13+42). Elas contavam só pelo nome
    do canal; sem ele, seriam como qualquer frase que nomeia o ator pelo cargo, que não conta. A fala do próprio ator que
    o texto atribui pelo nome continua contando ("“...”, afirmou Lula", no A63, que não muda).
  - Nos 20 itens, mudam o A79 (o comandante passa de 2 frases para 1: lado fino, alvo de 180 para 90, e a Helena de 380
    para 370, pelo limite de 45%) e o N13 (Lula de 5 para 3, alvo de 360 para 270; com só a frase da área técnica fora,
    seriam 4 e o alvo continuaria 360).
  - Nenhuma frase saiu por erro das aspas (aspa sem fechar, apóstrofo): entra.
- **Item 3, o sobrenome de organização** (`medir_sobrenome_de_organizacao.py` e `medir_pessoa.py`): dos 28 atores que
  `lados.sobrenome` aceita nas análises gravadas, 6 são organizações (Agência Brasil, Banco Central, Coligação Brasil
  Pronto Para Mais, Justiça Global, Sindipetro Unificado, Terra de Direitos e Justiça Global), e a regra
  (`lados.nome_de_pessoa`) separa exatamente esses 6 dos 22 nomes de pessoa. Só mudam contagens de análises de um lado
  só, que não pesam no orçamento: no A104, o "Brasil" sozinho contava frases sobre o país como menções da Agência
  Brasil (3 para 1). Entra.
- **Item 2, as vozes:** o TTS dava as vozes pela ordem de declaração (a primeira masculina, a segunda feminina), e não
  pelo nome: a "Bia" analista única falava com a voz do Antonio. Agora cada nome tem a voz da vaga dele.
- **Leituras minhas, para o dono corrigir:**
  - nomes: três vagas, uma por lado, cada uma com a voz do TTS do mesmo gênero: Otávio, Mateus, Caio (voz do Antonio);
    Patrícia, Sofia, Isabela (Thalita); Vinícius, Sérgio, Renato (Gustavo). Não usei Ricardo, Beatriz e Dr. Ramos, os
    exemplos da decisão, porque aparecem nas amostras (Ricardo 23 vezes, entre elas Ricardo Villas Bôas Cueva, citado no
    N13 sem ser ator; Beatriz 10; Ramos 8); os escolhidos aparecem de 0 a 2 vezes. Em cada vaga vale o primeiro nome que
    não é o nome nem o primeiro nome de um ator da análise; com um lado só, a primeira vaga;
  - o QA confere o nome, não o lado (o analista do lado 2 com o nome do lado 1 passa), com o nome escrito como o bloco dá
    ("Dr. Otávio" não vale por "Otávio"); o problema vai para a revisão completa, que pode trocar o nome;
  - o bloco usa o nome no elenco ("Otávio, do lado 1, e Patrícia, do lado 2"), no alvo, no plano e na ordem dos turnos;
  - aspas: contam as duplas retas e curvas e as simples curvas; a curva aberta só continua no parágrafo seguinte quando
    ele abre com aspas; a fala do próprio ator em que o nome só aparece dentro das aspas deixa de contar (a lista acima);
  - nome de pessoa: sem palavra de organização (uma lista fechada) e, nos textos fora das aspas, mais vezes sem artigo
    antes do que com artigo; o "a" conta como artigo mesmo quando é preposição ("direcionado a Nunes Marques"), o que só
    pesa num nome que aparece poucas vezes;
  - o mínimo de 60% vale também para a Helena e para o total, como pedido; o plano continua pedindo o alvo inteiro.

**Em 24/10, a regressão da quarta leva** (23:37 de 24/10 a 00:18 de 25/10, 49 chamadas, memória disponível sempre
acima de 18,1 GiB; o detalhe em `data/agrupamento/rodada_20261024d/resultado.md`, a leitura e as medidas em
`data/agrupamento/correcoes_20261024d/`):

- **O aceite de 23/10 foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 17 de 20 ou mais | 19 (só o N92 reprovou) |
  | Disputa inventada | nenhuma | nenhuma |
  | Frases marcadas | até 21% | 10% |
  | Argumentos atribuídos | até 34, e 9 nas disputas | 16, e 7 nas disputas |

  Marcas por mil palavras de roteiro: 7,3 (12,6 em 17/10, 6,9 em 23/10, 18,1 na `master`). Roteiro médio de 536
  palavras.
- **O N92** caiu na regra dos analistas por lado na primeira versão; a revisão do roteiro consertou, mas encurtou a
  analista do sindicato de 99 para 79 palavras (mínimo de 84), mesmo com o plano.
- **O plano:** número de falas e ordem seguidos nos 20; nenhum termina com o analista. Os analistas escreveram 70% do
  alvo e a Helena 83%: o mínimo de 60% decide (com 75%, os mesmos episódios dariam 7 aprovados).
- **A Helena fora do fechamento:** 16 marcas, 3,9 por mil (2,9 em 23/10, 3,0 em 17/10; 8,4 na terceira rodada curta),
  quase todas enquadramentos na abertura, conclusões ("fica claro que...", "disputa muito equilibrada") e contrastes
  que o texto não faz. O fechamento caiu de 17 para 12; o resumo, os pontos e o "por que importa" subiram de 12 para 17;
  os analistas ficaram em 5,9 por mil (5,8 em 23/10).
- **Nomes:** Otávio e Patrícia nos 20, com as vozes da vaga; a Helena chama o analista pelo nome.
- **Aspas:** no A79, o lado do comandante ficou fino (alvo 90), e a analista dele fez 1 marca em 62 palavras (5 em 132
  na terceira rodada curta).
- **Análise de lados:** as 5 disputas do gabarito e nenhuma outra; a nova tentativa do "Sim" e "Não" não foi
  acionada; no N69, a recusa do trecho da Sony levou ao lado único do gabarito.
- **Limitações que continuam:** os 30 mil do N92 no recolhimento (seis de sete rodadas); a ressalva do veículo no N84
  sumiu de novo.
- **Leituras minhas, para o dono corrigir** (o detalhe em `resultado.md`): o "devido ao El Niño" do A79 também como
  A; os pontos-chave "A necessidade de..." como opinião como fato (O), como no N86 da segunda rodada; a análise do
  veículo atribuída a outro grupo como F, como em 17/10.

## Integração do agrupamento: o plano de 25/10

Aprovado em 25/10/2026, com as leituras confirmadas. Valem as decisões de 16 e 17/10 (`AGRUPAMENTO_ATIVO` desligado por
padrão; mark_seen da pauta inteira de uma vez; os excedentes vistos com a pauta e listados no texto; cada pauta na vaga do
seu primeiro artigo, com o boletim duplo; o filtro com o agrupamento ligado ou desligado; duas execuções por item, só
`QAReprovado` contando, com mudança aditiva no banco).

**O que muda na fonte única com o agrupamento desligado.** Além do filtro e do limite de tentativas, cinco coisas, todas
na simulação final:

1. o filtro depois da extração lê a URL final, então o laço passa a usar a extração que devolve a URL resolvida (o mesmo
   `_extrair` de hoje; conferir nas amostras, item a item e sem o modelo, que o texto é o mesmo);
2. o registro de cada execução (item 6 da fase 4);
3. o aviso de parada (ajuste 8);
4. as vozes registradas: o TTS escreve no log a voz de cada personagem e o episódio a guarda, para a simulação conferir;
5. o nome do analista evita também as pessoas citadas nos textos (decisão 3 abaixo).

O `resumo_lotes.py` ganha as linhas novas. O laço continua sem extração em lote, e o texto entregue com uma fonte só não
muda.

**Excedentes: hoje nunca aparecem.** A etapa 2 forma as provisórias com no máximo `AGRUP_MAX_ARTIGOS` artigos, e a etapa 3
confirma dentro delas com o mesmo teto. Para os excedentes existirem, o teto da provisória fica separado do teto de
textos da geração (3).

**Decisões:**

1. **Aviso de parada também no erro inesperado.** O processo avisa e sai com status 1, como nas travas, para o
   `OnFailure=` da futura unit ficar só com o que o processo não consegue avisar (OOM, tempo, sinal). No Telegram, o tipo
   do erro e quantos itens saíram; o traceback fica no log. Na simulação, o aviso vai para o `AVISO.txt`.
2. **Sites de partido:** um rascunho da lista a partir dos partidos registrados no TSE, com o domínio oficial de cada um,
   para o dono ver. A lista fica num arquivo de configuração, e cada domínio vale também para os subdomínios.
3. **Nome do analista e teto da provisória:** a escolha do nome evita também as pessoas citadas (no elenco, não no QA); o
   teto da pauta provisória fica separado (`AGRUP_MAX_PROVISORIA`, valendo 3 até a condição do teto passar).

**Ajustes:**

1. **Extração:** conferir nas amostras, item a item e sem o modelo, que a extração que devolve a URL resolvida dá o mesmo
   texto que a de hoje.
2. **Prévia:** pelo gabarito de 13/10, a pauta do Muse Wonder é 90+79+43. Na leitura, a atribuição ao veículo errado
   conta à parte (foi o problema de 4 dos 18 aprovados na fase 3).
3. **Condição do teto:** conferir que a etapa 3 com 6 artigos cabe na janela de 8192, sem cortar texto.
4. **Simulação de trabalho com o agrupamento ligado:** se a condição do teto passar, também uma execução com a provisória em
   6, para os excedentes passarem pelo pipeline de ponta a ponta.
5. **Filtro:** o item filtrado depois da extração é extraído de novo a cada execução. Contar quantos são por execução na
   simulação de trabalho; se forem muitos, propor guardá-los numa tabela, sem mexer no significado de `seen`.
6. **Registro:** propor quantos dias de `data/execucoes/` ficam guardados.
7. **Simulação final:** separar uns três episódios para o dono ouvir, com pelo menos um de disputa (as duas vozes de
   analista).

**A ordem:**

1. Este registro.
2. **Sessão de teste,** sem o código novo: a prévia em 9 pautas de várias fontes das duas amostras (antiga: 79+105,
   29+104, 2+46, 92+97+63, 86+71; nova: 64+13+42, 71+85, 26+69, 90+79+43; a 52+30+2 é de esporte e o 20 é site de
   partido), com `testar_episodio.py --pautas`, as medidas das rodadas de fonte única e a leitura frase a frase, sem
   critério de aceite (as amostras já não são cegas); a medida da janela (os caracteres de cada texto com o prompt e o
   bloco de hoje contra os de 17/10); e a condição do teto (`testar_agrupamento.py --etapa3 --repeticoes 3` com o teto em 6
   na amostra nova, e na antiga com `--rotulos`). O resultado vem para o dono.
3. **Depois da sessão,** as partes que não dependem da prévia: o filtro (a lista de partidos ainda como rascunho), o
   limite de tentativas, o registro, o aviso de parada, os nomes e as vozes. O agrupamento atrás de `AGRUPAMENTO_ATIVO`
   espera a leitura da prévia pelo dono.
4. Simulações de trabalho sem áudio (desligada; ligada com uma segunda execução na mesma pasta; ligada com a provisória
   em 6, se a condição passar).
5. Terceira amostra: a coleta 3 quando o dono pedir (a partir de 26/10) e o rascunho do gabarito (pares e pautas para a
   etapa 3, uns 20 itens de fonte única com e sem disputa, os candidatos de esporte, ofertas e site de partido). Nenhum
   prompt nem regra se ajusta olhando para ela antes da rodada.
6. Validação cega na terceira amostra, com o critério que o dono fixar antes.
7. Simulação final, desligada e com áudio.
8. Merge, desligado, sem push.

**Leituras confirmadas:** o filtro com as regras de 16/10 e a categoria do feed por lista fechada (Esporte, Esportes,
Ofertas, Achados, Hardware Indica), sem o título, e o item filtrado sem mark_seen; a contagem das reprovações numa tabela
nova (`reprovacoes`), fora de `seen`, que continua significando "entregue", com a linha "Item abandonado" no log; o
registro em `data/execucoes/<data-hora>/`; com o agrupamento ligado, a mesma matéria por dois feeds vai com a pauta como
duplicata, a chamada da etapa 3 que falha deixa os artigos separados e o link entregue continua o do feed; nenhuma
proposta de mudança se apoia na terceira amostra.

**Em 25/10, a sessão de teste** (08:54 a 09:24, 51 chamadas, memória disponível sempre acima de 17,5 GiB; o detalhe em
`data/agrupamento/previa_20261025/resultado.md`):

- **A condição do teto passa.** Com a provisória em 6, a etapa 2 junta Lula/TSE e a área técnica numa provisória de 5
  artigos (71+64+85+13+42), e nas três repetições a etapa 3 a separa em 71+85 e 64+13+42. A maior chamada teve 2.653 + 273
  tokens: cabe em 8192 sem cortar texto (ajuste 3). Na amostra antiga o teto em 6 não muda nenhuma provisória.
- **A prévia:** 7 de 9 aprovadas; 57 marcas em 411 frases (14%), 9,4 por mil palavras de roteiro (7,4 na regressão de fonte
  única de 24/10), 19 atribuídos (2,1 por episódio, contra 0,8). As 6 disputas saíram com os atores principais nos lados
  certos e nenhuma disputa foi inventada; o 90+79+43 caiu no lado neutro de emergência (veículos fora de todos os lados nas
  duas tentativas), sem disputa como o gabarito.
- **Veículo errado (ajuste 2):** 5 frases, em 2 dos 7 aprovados (92+97+63 e 64+13+42), contra 4 de 18 na fase 3. A regra
  estrita pegou 2, sem falso positivo.
- **A janela:** o prompt de hoje tira de 1.393 a 2.078 caracteres de texto por pauta, em relação ao de 17/10; nenhum
  parágrafo com trecho de evidência ficou de fora.
- **Dois falsos positivos do QA, que valem também para a fonte única:** o "360" do Poder360 lido como número sem fonte
  (86+71) e os pontos do "Hardware.com.br" contados como fim de frase no resumo (26+69, "12 frases" para 8; a contagem é a
  da `master`). Os dois são relaxamento; nada foi mudado.
- **À espera do dono:** a leitura da prévia, que libera o agrupamento atrás de `AGRUPAMENTO_ATIVO`, e os dois falsos
  positivos.

**Em 25/10, as partes que não dependem da prévia** (implementadas depois da sessão, com testes):

- **Filtro** (`processing/filtro.py`, `config/sites_de_partido.txt` como rascunho): nas duas primeiras amostras, o mesmo
  resultado da medida de 16/10. A extração que devolve a URL resolvida dá o mesmo texto que a de hoje nos 209 candidatos
  das duas amostras, item a item (ajuste 1; `data/agrupamento/filtro_20261025/saida_conferir_extracao.txt`).
- **Limite de tentativas:** a tabela `reprovacoes`, aditiva (um teste confere que os comandos da `master` continuam
  funcionando no banco com ela).
- **Registro de cada execução** (`registro.py`): lido pelos dois diagnósticos sem mudança neles; 30 dias guardados, a
  proposta do ajuste 6 (uns 0,6 MB por execução de 20 itens: com duas execuções por dia, uns 36 MB por mês).
- **Aviso de parada**, também no erro inesperado (decisão 1).
- **Nomes e vozes:** a escolha do nome evita as pessoas citadas (decisão 3); a voz de cada personagem no log e no episódio.

**Em 25/10, à noite, as decisões do dono sobre a prévia** ("A prévia libera a integração. Suas leituras estão
certas."):

1. **Lista de partidos** aprovada como está, com os 30 partidos; o pcb.org.br e o pv.org.br ficam, mesmo sem a
   conferência do conteúdo. Lideranças, fundações e federações ficam de fora por enquanto: entram quando aparecerem no
   registro de alguma execução. Sem o "RASCUNHO" no cabeçalho (98d7289).
2. **Os dois falsos positivos do QA,** corrigidos antes das simulações; os dois são relaxamento (98d7289):
   - **Números:** o número que faz parte do nome de um veículo da pauta não conta ("Poder360", "Poder 360", "Brasil
     247"; `numeros.numeros_fora_dos_nomes`, comparando parte a parte, sem acento nem caixa, antes de um slogan). Nos
     158 episódios gravados, só o 86+71 da prévia tinha um ("360", 7 vezes); ele segue reprovado pelas 6 frases do resumo
     e pela analista do lado fino. O `checar_fidelidade.py` não muda: a referência dele já inclui o nome do veículo.
   - **Frases do resumo:** o ".", "!" ou "?" colado a uma letra ou a um algarismo não fecha frase. A contagem continua a
     da `master` com essa exceção (abreviatura e reticências contam como antes). Nos 158 episódios, 17 resumos contam
     menos frases: 11 pelo "Hardware.com.br" e 6 pelo ponto de milhar ("6.901", "1.564", que também contava); nenhum fica
     abaixo de 7, e só o 26+69 da prévia muda de situação (12 frases para 8, reprovado → aprovado; o
     `checar_fidelidade.py` não acha nada nele que o QA deixe passar). Medida:
     `data/agrupamento/correcoes_20261025/medir_falsos_positivos.py` e `saida_falsos_positivos.txt`.
   - **A contagem de menções e os números de frase das leituras não mudam:** os dois usam `qa.frases()`, que já não
     separava dentro de uma palavra (pede espaço depois do sinal) e não foi mexida. A contagem nova e `qa.frases()`
     diferem em 2 dos 158 resumos, por abreviatura: "Matt J. Robb" (o `frases()` acerta) e "cinco G. Smartphones" (o
     `frases()` junta duas frases por engano, tomando o "G." por abreviatura). É uma falha do `frases()` sem relação com a
     mudança; fica registrada, sem correção.
3. **A integração do agrupamento:** implementar, com testes e commit, e atualizar o CLAUDE.md e o roteiro, com:
   - `AGRUP_MAX_PROVISORIA` em 6 por padrão (a condição do teto passou); com o agrupamento desligado, nada muda;
   - **o veículo fora de todos os lados** (o 90+79+43): proposta e medida antes de entrar (8ff8f57). Com um lado só, o
     veículo que ficou de fora entra nele (sem lado com ator nomeado, fica no lado neutro, que já tem todos); com dois
     lados ou mais, o veículo cujo texto não cita ator de nenhum lado (pela contagem de `mencoes`) entra como contexto
     (`Analise.contexto`, `veiculos_de_contexto` no registro), fora dos lados e do bloco, sem invalidar a análise; o que
     cita um ator continua invalidando ("veículo da pauta em nenhum lado, com ator de um lado no texto"), porque a
     resposta o deixou fora do lado desse ator. Medido nas 243 respostas gravadas da análise de lados (a que valeu, as
     primeiras tentativas e as segundas recusadas; 115 de pautas com vários veículos,
     `data/agrupamento/correcoes_20261025/medir_veiculo_fora.py`): só as duas tentativas do 90+79+43 tinham veículo de
     fora, e as duas passam a dar o lado único do Zuckerberg com os três veículos, sem disputa como o gabarito (que diz
     "Meta"); nenhuma outra análise muda, e o caso do contexto não aconteceu em nenhuma;
   - **a janela** fica como ponto a estudar antes de ligar o agrupamento, junto com a regra estrita (ver "Quando o
     agrupamento liga").
4. **As simulações de trabalho,** depois da implementação, cada uma numa cópia do banco: a desligada, contando os itens
   filtrados depois da extração (ajuste 5), e a ligada, com a provisória em 6 e uma segunda execução na mesma pasta. O
   resultado vem antes da terceira amostra. O registro com 30 dias está aprovado; a coleta 3 fica para quando o dono
   pedir, a partir de 26/10.

**A integração, como ficou** (com `AGRUPAMENTO_ATIVO=false` por padrão; o detalhe no CLAUDE.md, "Architecture"):

- **Ligado,** o pipeline tira os entregues, os abandonados e os filtrados pelo link e pela categoria do feed, extrai
  todos os candidatos em lote, aplica o filtro na URL resolvida, descarta os textos curtos e agrupa: provisórias de até
  `AGRUP_MAX_PROVISORIA` (6) artigos, a etapa 3 no pacote (`agrupamento.confirmar_pauta`, a mesma chamada dos dois
  scripts, pelas travas da máquina) e até `AGRUP_MAX_ARTIGOS` (3) textos por pauta final; o resto são excedentes.
- **As vagas (ajuste 7):** cada pauta na posição do primeiro dos seus artigos na lista intercalada, contando principal,
  relacionados, duplicatas e excedentes; geradas nessa ordem até `MAX_NEWS` entregues ou o fim do tempo; o que não cabe
  não é marcado e volta.
- **A entrega:** o texto leva um link por artigo gerado (o do feed) e lista as duplicatas e os excedentes em "Também
  noticiaram"; com uma fonte só, o texto é o de sempre. Depois da entrega, todos os links da pauta (gerados, duplicatas e
  excedentes) entram em `seen` numa transação só (`SeenStore.marcar_vistos`).
- **A reprovação** de uma pauta conta para os textos gerados e as duplicatas, não para os excedentes (que não entraram
  na geração e podem formar outra pauta depois).
- **A mesma matéria por dois links do feed** (o do Google Notícias e o do veículo) é duplicata quando os dois resolvem
  para a mesma URL canônica, mesmo com textos extraídos diferentes (`agrupamento._mesma_materia`); a etapa 3 que falha,
  ou o veredito descartado, deixa os artigos separados, e um erro inesperado no agrupamento deixa cada candidato sozinho
  ("Agrupamento falhou: ..."), sem parar a execução.
- **O registro** guarda também cada provisória e o que a etapa 3 fez dela (`etapa3`) e, por item, as `duplicatas` e os
  `excedentes`; o `resumo_lotes.py` mostra a linha "Agrupamento: N candidato(s) em M pauta(s), K com várias fontes"
  nas observações.
- **Desligado,** o laço é o de um artigo por vez, como antes. A única diferença é a data de cada artigo no registro: a
  coleta passou a preencher `Article.published` com a data do feed, que a etapa 3 mostra ao modelo (nas amostras, a data
  vinha do mesmo lugar).
- **Os scripts** usam o teto novo: `testar_agrupamento.py` e `testar_episodio.py` formam as provisórias com
  `AGRUP_MAX_PROVISORIA`. Na amostra nova, sem o modelo, saem as mesmas 8 provisórias da condição do teto (uma de 5
  artigos).

**Em 25/10, as simulações de trabalho** (18:18 a 20:26, sem áudio, cada uma numa cópia do banco, sob `systemd-inhibit`
e com o vigia de memória, que nunca viu menos de 16,3 GiB disponíveis; o detalhe em
`data/simulacoes/rodada_20261025/resultado.md`):

- **Desligada** (42 min): 20 entregues, 1 reprovado, 2 filtrados antes da extração e **nenhum depois dela** (ajuste 5:
  nada a guardar numa tabela por enquanto), 4 textos curtos.
- **Ligada, primeira execução** (41 min): 108 extraídos em lote em cerca de 1 minuto, 17 curtos, 91 candidatos em 83
  pautas, 5 de várias fontes; a etapa 3 levou 1,5 minuto para 7 provisórias (uma de 4 artigos virou 3 textos e 1
  excedente). Nas 20 vagas coube uma pauta de várias fontes (CBN, Money Times e Estadão, aprovada): as outras estavam
  mais adiante na lista intercalada. As vagas por boletim ficaram iguais às da desligada.
- **Ligada, segunda execução na mesma pasta** (44 min): 73 candidatos em 66 pautas, 5 de várias fontes, 3 geradas (duas
  aprovadas; a do Zanin, com 1 excedente, reprovada, com a reprovação contada para os 3 textos e não para o excedente).
  Nenhum link entregue duas vezes; todos os links das pautas entregues estão em `seen`.
- **Problema que barra o merge: a medida de caracteres por token.** O `Summarizer` usa o mínimo de todas as chamadas da
  execução (desde 5d72d68, na fase 3). Na segunda ligada, a pauta CartaCapital + BBC (tabelas de votos por país) mediu
  2,6 caracteres por token (2,34 com a folga), e daí em diante a geração de todos os itens ficou com uns 1.900
  caracteres para os textos e o bloco: do item 13 ao 23 entraram de 206 a 966 caracteres de texto por item, os de
  fonte única inclusive, e 9 foram aprovados assim; a análise de lados também passou a cortar os textos. A `master`
  corta em 5.000 caracteres fixos e não tem isso. Com o merge, vale também para a fonte única com o agrupamento
  desligado; na desligada não aconteceu só porque nenhum texto longo de números apareceu. A proposta de correção vai
  para o dono antes de qualquer mudança.
- **Outras observações:** o "Entenda por que a votação foi prorrogada" (Folha) ficou fora da pauta do Zanin (score de
  0,10 a 0,12, abaixo do limiar); a história do NYT saiu de novo na segunda execução, por outro veículo (o artigo que
  chega depois forma outra pauta).

## A janela por item: as decisões de 29/10 e a medida

O dono aprovou em 29/10 a medida por item, com cinco requisitos, e mandou medir antes e implementar se a medida
confirmasse o desenho: (1) a parte fixa de cada chamada entra no limite pelo número exato de tokens; (2) a proporção do
texto vale por item, e a folga de 0,9 fica, só no texto; (3) nenhuma chamada é cortada em silêncio (`truncate` e
`shift` desligados, conferidos na sessão de teste); (4) a primeira chamada de cada item começa da proporção típica e,
com erro de janela, é refeita com a proporção medida do item ou, sem medida, com a menor já vista; (5) quando a janela, e
não o teto, corta o texto de um item de fonte única, um aviso no log e no registro. As leituras 1 a 9 de 25/10 foram
confirmadas; na 7, a falha do agrupamento passa a ir também para o registro da execução.

**A sessão de teste de 29/10** (`data/agrupamento/correcoes_20261029/`, `saida_sessao_janela.txt` e
`saida_sessao_shift.txt`; memória disponível sempre acima de 17,3 GiB):

- Ollama 0.40.2, sem `/api/tokenize`. O cliente Python (0.6.3) não manda `truncate` nem `shift`.
- A parte fixa exata (o prompt e o template, com a mensagem do usuário vazia e num_predict 1): `PROMPT_SISTEMA` 2.591
  tokens, `PROMPT_LADOS` 1.573, `PROMPT_REVISOR` 1.124, `PROMPT_ROTEIRO` 1.041, `PROMPT_TITULO` 335, `PROMPT_RESUMO`
  242, `PROMPT_AGRUPADOR` 879; o template sozinho, 18.
- `"truncate": false`: o pedido maior que a janela volta na hora com HTTP 400 e a contagem exata (15.329 de 8.192
  tokens), sem processar nada. `"shift": false`: a resposta parou em 8.189 de 8.192 tokens, com `done_reason`
  "length". O `shift` é opção do servidor do modelo: trocá-lo entre pedidos recarrega o modelo (uns 10 s), e repeti-lo
  não; por isso vai igual em todos os pedidos.

**A medida nas três simulações de 25/10** (`medir_janela.py`, `saida_medir_janela.txt`; resumo em
`resultado_medida.md`):

- A proporção do texto por item (sem a parte fixa) vai de 2,30 (a pauta CartaCapital + BBC, tabelas de votos) a 4,79,
  com mediana 4,31 em 64 itens; o prompt de sistema mede de 3,2 a 3,8.
- Fonte única: dos 60 itens, recebem o teto com a regra de hoje 52 e com a nova os 60. As pautas de várias fontes
  recebem muito mais texto (a do Zanin, de 206, 0 e 0 caracteres para 2.751, 1.375 e 1.046).
- Com a proporção típica (4,31 × 0,9), uma primeira chamada passa da conta (a das tabelas, 7.250 tokens) e nenhuma
  passa da janela.
- A maior saída de cada etapa: lados 953 tokens (o menor espaço que sobrou, 942, foi o da pauta das tabelas, cuja
  resposta saiu inteira: 289 tokens, done=stop), geração 1.797, correção completa 1.377, do roteiro 1.148, do resumo
  219; nenhuma chamada terminou fora de done=stop. Na geração, a reserva (3.000) e a margem (256) somam 3.256 tokens,
  e a maior saída foi 1.797: é o próximo espaço a estudar para a janela dos outros veículos, sem mudança agora.
- A parte fixa na regra de hoje: com a proporção 2,34 o limite descontava 4.129 tokens pelo `PROMPT_SISTEMA` (exato:
  2.591); com 3,3, 2.928.
- **As rodadas de validação desde 17/10 não foram afetadas:** a proporção no início de cada pauta ficou entre 3,22 e
  3,46 (3,0 só antes da primeira medida de cada rodada), e com ela o teto de 5.000 caracteres do principal cabe na
  janela. No 92+97+63 da prévia valia 3,3 (o início da pauta seguinte também foi 3,3, então nenhuma chamada dela mediu
  menos): os 3.828 caracteres de texto vêm do que o bloco de lados e os cabeçalhos ocupam, não de uma proporção de 3,0.

**A implementação** (o detalhe no CLAUDE.md, "The input budget"): `ai/janela.py` (a parte fixa contada uma vez e
guardada em `TOKENS_FIXOS`, pelo hash do modelo e do prompt), `OllamaProvider` por HTTP com `truncate` e `shift`
desligados (`llm._ClienteOllama`; `ps` e `generate` seguem do cliente Python), `JanelaExcedida` com a contagem do
servidor, a proporção por item no `Summarizer` (começa de `PROPORCAO_TIPICA`, 4,3), a nova tentativa depois de um erro de
janela (com a proporção que o erro mediu; sem contagem, a menor da execução, ou 3,0), o aviso da janela na fonte única
(log e registro, com `cortado_pela_janela` em cada corte e `proporcao_do_texto` em cada item) e a falha do agrupamento
no registro (`agrupamento_falhou`). O `resumo_lotes.py` mostra a falha do agrupamento e a contagem dos avisos da janela
nas observações.

**Leitura minha no requisito 4:** o erro de janela traz a contagem exata da entrada (`n_prompt_tokens`), e é dela que a
nova tentativa tira a proporção medida do item; "a menor já vista" fica para o erro que não traz a contagem.

**Para o roteiro, antes de ligar o agrupamento** (pedido de 29/10):

- **O teste de ponta a ponta do "Também noticiaram" e do excedente marcado como visto.** Passou na simulação ligada de
  29/10 (uma pauta com 2 excedentes, aprovada e entregue). Fica a duplicata, que ainda não apareceu. Proposta, se for
  preciso forçar: uma simulação de
  trabalho sem áudio com `AGRUP_MAX_ARTIGOS=2` (toda pauta confirmada de 3 artigos ou mais tem excedente) e `MAX_NEWS`
  alto o bastante para as pautas de várias fontes caberem nas vagas (na ligada 1 de 25/10, só 1 das 5 coube nas 20),
  com a segunda execução na mesma pasta para conferir que o excedente não volta. A duplicata é mais difícil de forçar:
  a de texto aparece sozinha quando dois feeds trazem a mesma matéria; a da URL canônica, quando o Google Notícias e o
  feed do veículo trazem o mesmo link. Se nenhuma aparecer em duas coletas, um teste com uma amostra gravada em que o
  mesmo artigo entra duas vezes, com links diferentes.
- **O explicativo do mesmo fato que a etapa 1 não junta** ("Entenda por que a votação foi prorrogada", da Folha, com
  score de 0,10 a 0,12 contra a pauta do Zanin) e **a história que volta na execução seguinte por outro veículo** (o
  NYT, na segunda ligada): os dois entram na leitura da terceira amostra.
- **A prioridade das pautas de várias fontes nas vagas:** na ligada 1, só 1 das 5 coube nas 20 vagas, porque cada
  pauta fica na posição do seu primeiro artigo na lista intercalada. Uma prioridade seria regra nova, para o dono
  decidir depois da terceira amostra.

**Depois da implementação, a sessão de teste e a simulação de 29/10** (o detalhe em
`data/simulacoes/rodada_20261029/resultado.md`):

- **O texto de tabelas e os itens seguintes da ligada 2, um por um, no mesmo processo:** o de tabelas (proporção 2,44)
  entrou com 4.231 de 5.000 caracteres, com o aviso da janela; os 13 seguintes receberam o teto, o da Black Friday com
  4.986 de 5.000 (em 25/10, 669). Nenhuma chamada cortada: a maior entrada teve 4.621 tokens, sem "truncating" nem
  erro de janela. 13 de 14 aprovados.
- **A simulação ligada, com as duas execuções na mesma pasta, numa cópia nova do banco:** 20 e 20 entregues (46 e 42
  min), 3 e 3 pautas de várias fontes geradas. O "Também noticiaram" e o excedente marcado como visto passaram de ponta a
  ponta (Agência Brasil + GOV.BR + O Globo, com 2 excedentes, que não voltaram na segunda execução); nenhum texto de
  fonte única cortado pela janela; as pautas de várias fontes entraram com [3.465, 1.788, 1.606] e [3.846, 2.797]
  caracteres. No log do Ollama da sessão inteira, 148 entradas, a maior com 4.985 tokens, nenhuma cortada. Uma pauta
  tem um site do governo (GOV.BR) como veículo, que o filtro não tira.

**A terceira amostra, em 29/10:** a coleta 3 (`amostra_20261029-070905.json`, 105 candidatos; 5 em comum com a coleta 2,
com o mesmo rótulo) e o rascunho do gabarito das três coletas, para o dono revisar, em
`data/agrupamento/terceira_amostra/` (`especificacao_do_rascunho.md`; por coleta, `rascunho_<carimbo>.md` e
`rotulos_rascunho_<carimbo>.csv`, no formato do `--rotulos`). Feito por três workers de leitura, um por coleta; os CSVs
e os trechos citados foram conferidos por script (ids, relações, todo par do CSV de pares rotulado, os artigos
repetidos). Pelo rascunho, a meta do protocolo não fecha: 9 pautas de 2 ou mais artigos nas três coletas (2, 1 e 6; uma
de esporte), contra 15, e 3 com disputa (todas na coleta 3), contra 6; 8 itens de fonte única com disputa. Se o
gabarito do dono confirmar, falta uma quarta coleta.

## O gabarito da terceira amostra e a validação cega: as decisões de 29/10

Em 29/10/2026, ao ler o rascunho do gabarito (a janela e as duas leituras do relatório da janela certas):

- **Regras para o gabarito:**
  1. Listas e guias de compra ("10 X", "5 apps", "conheça 5 modelos") e sumários de revista são textos de vários fatos
     (coleta 1: 5, 6, 11 e 24; coleta 2: 4, 24, 79, 105 e 43). Opinião ou análise de um tema só não é.
  2. Um veículo citado que afirma o fato que o ator nega é lado: o 83 da coleta 1 (Aftonbladet "Sim", TV4 "Não") e o 53
     da coleta 3 (UOL "Sim", Ricardo Nunes "Não") têm disputa.
  3. Uma decisão anterior que a nova suspende, sem ninguém que a defenda no texto, é sequência dos fatos: o 77 da coleta
     1 fica sem disputa, com lado único do MP Eleitoral e do TRE/AL.
- **Item a item:** na coleta 3, a carta (A) e a fuga (B) são duas pautas, a C fica à parte, o 100 fica na B e o 49 na A;
  na B, a disputa do visto conta só se o 50 estiver entre os textos da geração (sem ele, lado único da PF); na A, Trump
  fica fora dos lados, a bancada do PL entra no "Sim" como secundária e Marinho fica no "Não"; o 23 tem disputa; o 38 é
  oferta. Na coleta 1, o 36 × 73 leva a relação do 11 × 23 da amostra de 12/10, e o lado do 74 é só Kutaragi. Na coleta
  2, o 5 tem disputa (Meta "Não", News/Media Alliance "Sim"); o 11, o 26 e o 25 são notícia; o 16 fica no lado neutro. O
  resto como no rascunho.
- **A validação cega da fonte única:** os 24 itens de fonte única das três coletas, com a sessão de teste e a leitura
  frase a frase de sempre. O aceite é o de 23/10, proporcional a 24 itens: pelo menos 21 aprovados, nenhuma disputa
  inventada, frases marcadas até 21%, argumentos atribuídos até 1,7 por episódio no total e 1,8 nos itens com disputa.
  Vêm também a disputa perdida, a questão errada e as marcas por mil palavras ao lado das de 24/10. Prompt e QA não mudam
  por causa do resultado.
- **Sem o modelo:** `testar_agrupamento.py --rotulos` nas etapas 1 e 2 das três coletas; a etapa 3 fica para quando a
  quarta coleta estiver rotulada.
- **Para decidir antes de ligar o agrupamento:**
  - **Sites de quem é parte da história** (governo, MPF, sindicato): se entram como veículo, como "Também noticiaram" ou
    como ator. Hoje a `master` já os trata como veículo na fonte única (o 77 da coleta 1 é do MPF; a pauta D da coleta 3
    tem o GOV.BR e o site do Governo Federal; na simulação ligada de 29/10, o GOV.BR entrou como veículo).
  - **Texto patrocinado com cupom** (o 38 da coleta 3: um texto sobre a falha no PHP que termina oferecendo a Hostinger
    com cupom), que o filtro do código não pega.
  - **A quarta coleta**, a partir de 01/11, quando o dono pedir: faltam 6 pautas de várias fontes e 3 com disputa para a
    meta.

**O gabarito final, em 29/10** (`data/agrupamento/terceira_amostra/`): por coleta, `gabarito_<carimbo>.md` e
`rotulos_<carimbo>.csv`, a partir dos rascunhos, que ficam como estavam. Cada dúvida do rascunho leva a decisão no começo
(seção 6). Os 91 trechos citados estão, literalmente, no texto do artigo indicado (conferido por script).

- **Nos pares, mudou um rótulo:** o 36 × 73 da coleta 1, de `sobreposicao_parcial` para `desdobramento`. O 11 × 23 de
  12/10 está entre os pares que "deveriam ter sido avaliados" no gabarito do dono, juntos; o 73 (13/10) testa o Myna
  antes do lançamento e o 36 (15/10) é o lançamento do Ubuntu 26.10. Com isso, a coleta 1 ganha uma pauta de 2 artigos
  (sem disputa, lado único da Canonical, ou relato dos fatos), ambos do Diolinux.
- **Nos lados e nas listas:** os textos de vários fatos da regra 1; o 83 e o 53 com disputa; o 77 e o 74 com um lado
  só; a pauta B com as duas respostas, conforme o 50 esteja na geração; a bancada do PL no "Sim" da A e Trump fora; os
  guias de compra (6, 11 e 24 da coleta 1; 105 da coleta 2) fora das ofertas, porque não trazem preço, cupom nem
  afiliado; o 70 da coleta 1 é tecnologia; o 89 da coleta 1 e o 11, o 26 e o 25 da coleta 2 são notícia; o 38 da coleta 3
  é oferta.
- **A contagem para a meta:** 10 pautas de 2 ou mais artigos (3, 1 e 6), 9 sem a de esporte, e 2 com disputa (A e C),
  mais a B quando o 50 está na geração. Entre os 24 itens de fonte única da medida cega, 8 têm disputa (55 e 83; 63, 62,
  5 e 55; 23 e 53).

**As etapas 1 e 2, sem o modelo** (`data/agrupamento/etapas12_20261029/`: a saída do `--rotulos` por coleta, e
`contar.py` com `saida_contar.txt`, que conta os pares de cada pauta do gabarito):

| Coleta | Pauta (artigos) | Pares juntos | O limiar deixa passar | Forma-se |
|---|---|---|---|---|
| 1 | Datafolha (3) | 3 | 0 | inteira |
| 1 | Ubuntu 26.10 (2) | 1 | 1 (36 × 73, score 0,09) | não |
| 1 | Copa do Brasil Feminina, esporte (2) | 1 | 0 | inteira |
| 2 | Combos da Vivo (2) | 1 | 0 | inteira |
| 3 | A, a carta de Flávio (8) | 28 | 24 | em parte: 44 + 71 + 93 e 30 + 78, em duas pautas; 1, 2 e 49 sozinhos |
| 3 | B, a fuga de Flávio (4) | 6 | 6 (o 64 × 65 tem 0,18 arredondado, abaixo do limiar) | não |
| 3 | C, a relação Brasil-EUA (2) | 1 | 1 (16 × 85, score 0,12) | não |
| 3 | D, a violência política (5) | 10 | 0 | inteira |
| 3 | E, o Uber Moto (2) | 1 | 0 | inteira |
| 3 | F, o MacBook Pro (2) | 1 | 0 | inteira |

O limiar junta 7 pares que o gabarito separa, todos `mesmo_tema`: na coleta 1, os dois guias de TV do Tecnoblog (6 × 24,
textos de vários fatos) e os três textos de IA (29 × 41, 29 × 56, 41 × 56); na coleta 2, 12 × 32, 13 × 49 e 19 × 33. É o
trabalho da etapa 3, que fica para quando a quarta coleta estiver rotulada.

**A validação cega da fonte única, em 29/10** (de 17:26 a 18:25, 59 minutos para 24 itens, sob `systemd-inhibit` e com
o vigia de memória, nunca abaixo de 14,9 GiB; código de `b263ac1`; o detalhe em
`data/agrupamento/validacao_20261029/resultado.md`). A leitura foi feita por um leitor por coleta (Opus, só leitura, com
a régua e as marcas de 24/10 como calibração, sem o gabarito), com marcas de cada coleta conferidas pelo lead contra o
texto recebido.

- **O aceite de 23/10, proporcional, não foi atingido:**

  | Critério | Meta | Resultado |
  |---|---|---|
  | Aprovados | 21 de 24 ou mais | 19 |
  | Disputa inventada | nenhuma | 3 (C2.16, C2.87, C3.52), as três reprovadas pelo QA |
  | Frases marcadas | até 21% | 8% (76 em 962) |
  | Argumentos atribuídos | até 1,7 por episódio, e 1,8 nos itens com disputa | 0,79, e 1,25 |

- **Disputa perdida em 5 dos 8 itens com disputa no gabarito.** Em três (C1.55, C1.83, C2.63), a primeira resposta do
  modelo trazia a disputa certa e a conferência do trecho (`lados.traz_a_resposta`) tirou um lado: o substantivo
  "alegação", "rejeitou" e "proibiu" fora dos verbos de decisão (e "o ministro" sem o nome), e "divulgada pelo jornal".
  Nos outros dois, o modelo errou: no C3.23 ficou com Lula, e no C3.53 pôs o UOL como ressalva de grupo (a regra 2 de
  29/10 é posterior ao prompt). Só 3 disputas saíram certas (C2.62, C2.5, C2.55).
- **Questão errada:** 1, leve (C2.55: os lados certos, a questão é a conclusão antitruste de 2025, não a decisão nova).
- **Disputas inventadas:** a de planos de governo (C2.16, o caso do N27), a fala de Bolsonaro da pandemia como lado
  (C2.87) e a fonte anônima da Eurogamer contra o "não discutimos assuntos pessoais" (C3.52). Três das cinco reprovações
  são esses itens: o lado que o texto não tem fica sem material para o alvo de palavras. As outras duas: um número por
  extenso que não bate (C1.1) e a ressalva do UOL sem a frase da Helena (C3.53).
- **Ressalvas:** nenhuma das 8 do gabarito apareceu (detalhe, pelas regras de 14/10).
- **A leitura:** 5,5 marcas por mil palavras de roteiro, contra 7,4 na regressão de 24/10 (4,9 contra 8,7 nos itens com
  disputa; 5,8 contra 7,0 nos de um lado); roteiro médio de 572 palavras. Os leitores são outros, o que limita a
  comparação.
- **Prompt e QA não mudaram por causa do resultado.** O que fazer com a conferência do trecho e com as disputas
  inventadas fica com o dono.

Em 29/10/2026, ao ler a validação cega (a fidelidade generalizou, com 5,5 marcas por mil e 8% das frases; o que falhou
foi a análise de lados; as leituras 1 a 4 do relatório certas):

- **Gabarito:** o C2.16 passa a disputa ("O próximo governo deve retomar as privatizações?", Flávio Bolsonaro "Sim",
  Lula "Não"). A regra do N27 vale para planos diferentes sem respostas opostas; aqui elas são opostas. Com isso, o
  aceite continua não atingido: 19 de 24 aprovados, 2 disputas inventadas (C2.87, C3.52), 8% de frases marcadas,
  0,79 atribuídos por episódio e 1,22 nos 9 com disputa; das 9 disputas do gabarito, 4 certas e 5 perdidas
  (`data/agrupamento/validacao_20261029/resultado.md`, `saida_tabela.txt`).
- **Correções, medidas antes sem o modelo nas análises gravadas desde 17/10, com a medida entregue junto da
  implementação** (a que reabrir uma disputa inventada fica de fora):
  1. conferência do trecho (`lados.traz_a_resposta`), relaxamentos: os verbos de decisão que faltam (rejeitar,
     proibir, acolher, negar um pedido e os da mesma família que a medida mostrar); o substantivo de posição com o ator
     ("a alegação de X", "a versão de X"); o ator pelo cargo ("o ministro"), com o nome no mesmo parágrafo e o cargo na
     análise; o veículo citado que não é da pauta, com verbo de relato ("divulgada pelo jornal X", "de acordo com o X"),
     que pela regra 2 de 29/10 é ator;
  2. fonte anônima não é lado: o ator sem nome ("uma fonte", "fontes", "pessoas próximas", "interlocutores") é grupo e
     vai para a ressalva;
  3. recusa de comentar não é resposta ("não comentamos", "não discutimos", "não se pronunciou");
  4. o prompt da análise de lados, com exemplos inventados: o veículo citado que afirma o fato que o ator nega é ator; a
     fala que o texto situa antes do fato novo, como contexto, não é lado (o C2.87); fonte anônima e recusa de comentar;
  5. QA, relaxamento direto, com teste: o número por extenso composto vale pelo número inteiro (9.544).
- **As rodadas depois das correções:** os 24 da validação e os 20 de 16/10, com a mesma leitura e as mesmas medidas. Os
  24 passam a ser regressão, porque as correções foram feitas olhando para eles; o aceite é o mesmo, com o C2.16 como
  disputa. Nos 20, o critério de 23/10. Nada muda por causa do resultado.
- **A nova validação cega, que libera o merge, é a da quarta coleta:** a partir de 01/11, quando o dono pedir, com o
  rascunho do gabarito para ele, como nas três primeiras. Motivo: a terceira amostra deixou de ser cega com estas
  correções, feitas olhando para os itens dela.
- **Para estudar antes de ligar o agrupamento, o primeiro problema:** a etapa 1 pelos títulos não forma a fuga (B) nem
  a pauta C e só junta parte da carta (A) da coleta 3: na cobertura pós-eleição, os títulos variam demais. Sem mudança
  agora.

**A medida, em 29/10** (`data/agrupamento/correcoes_20261029b/`, o resumo em `resultado_medida.md`): as 236 análises
gravadas desde 17/10 (as rodadas de fonte única de 17 a 24/10, a prévia de 25/10, as cinco execuções das simulações de 25
e 29/10, a sessão da janela e a validação), reaplicadas com as respostas gravadas do modelo (`replay.py`: um `chamar` que
devolve a primeira resposta, a final e a nova tentativa recusada, na ordem). Cada mudança sozinha, todas juntas e todas
menos uma (`variantes.py`, `medir.py`):

- **Com todas, mudam 4 das 236:** o C1.55 sai com a campanha de Flávio no "Sim" e Cueva e Magu Haddad no "Não" (precisa
  do substantivo, do cargo e do verbo novo juntos); o C1.83 com o Aftonbladet no "Sim" (o veículo citado); o C2.63 com a
  Justiça do Trabalho no "Sim" ("proibiu"); e o C3.52 fica com um lado só, de Kari Perez (a fonte anônima). São as 3
  disputas perdidas pela conferência e a disputa inventada da fonte anônima. **Nenhuma disputa inventada reaberta;
  nenhuma outra análise muda.** O A46, o N55 e o N69 ficam com o lado único em todas as rodadas. O C2.87 não muda: a fala
  de Bolsonaro tem verbo de posição, e o que a separa do fato novo é o tempo, que só o prompt trata.
- **A família dos verbos de decisão:** entre os 18 trechos recusados das respostas gravadas, só "rejeitou" e "proibiu".
  "Negar" já é verbo de posição; entra o particípio, para a passiva. A passiva nova aparece em 2 episódios (o N92, no
  resumo), onde o QA não procura a apresentação dos lados: nada muda no QA.
- **A recusa de comentar:** com a fonte anônima, não muda o resultado; sozinha, tira a Kari Perez do C3.52 e deixa a
  disputa com Asha Sharma. Entra, porque não reabre nada.
- **O veículo citado:** "segundo o X" e "de acordo com o X" valem nos textos para qualquer ator, e o código não separa
  um veículo de outra organização (o UOL nem está entre os veículos das amostras). A regra aceita o relato para o ator
  que não é nome de pessoa nem veículo da pauta, ou que vem logo depois do tipo de veículo ("o jornal Aftonbladet").
- **O número por extenso:** o C1.1 dizia "nove mil, quinhentas e quarenta e quatro"; a vírgula depois de "mil" partia o
  número. Com a vírgula aceita depois da escala, antes de uma parcela menor, muda 1 dos 236 episódios gravados, o C1.1,
  cujos dois problemas de número somem.
- **A conferência da implementação:** a reaplicação com o código antigo (`b263ac1`) e com o novo, em processos
  separados (`resumos.py`, e `numeros_dump.py` para os números), dá as mesmas 4 mudanças da medida e só o C1.1 nos
  números, nos 236 episódios.
- **A revisão do diff antes do commit** (Claude Opus, só leitura; o Agy, escolhido quando o Claude estava em 99% da
  janela, não conseguiu ler arquivos no modo sem interface): 9 achados, todos corrigidos e com teste. Os 2 altos deixavam
  passar o trecho que só descreve quem é acusado ou perdeu: o ator em qualquer ponto das seis palavras depois do
  substantivo ou do marcador ("a acusação de improbidade contra a Construtora Alfa", "de acordo com o Ministério
  Público, a Construtora Alfa...", o ordinal "no segundo semestre", "A Gazeta revelou que a Construtora...") e os
  particípios novos sem agente ("teve o pedido negado"). Agora o nome tem de vir logo depois do marcador ou logo antes do
  verbo ativo, e o particípio novo só vale com o ator como agente. Os médios: a recusa com "limitou-se a dizer", com
  "questionou a prefeitura, que não respondeu", com "não respondeu" sozinho, "não vai se manifestar" e "recusou-se a
  comentar", e na frase quando o trecho não a traz; o cargo seguido do nome de outra pessoa e o sobrenome de outra
  pessoa. Os baixos: "dez mil, vinte mil" lido como um número só, e um teste que passava sem a mudança. A medida com o
  código corrigido é a mesma.
- **Achados fora do pedido, sem mudança:** "Para o cientista político Maurício Santoro, ..." e "Para Brownlee, ..."
  ("Para X," não é marcador), "acredita" e "explicou" (não são verbos de posição), "Segundo o órgão" (o ator por um
  substantivo genérico) e "A conclusão foi que..." (a Assessoria do TSE no N71+85).

**As rodadas depois das correções, de 22:55 de 29/10 a 00:30 de 30/10** (código de fae6910; 95 minutos para 44 itens,
sob `systemd-inhibit` e com o vigia de memória, nunca abaixo de 15,6 GiB; o detalhe em
`data/agrupamento/regressao_20261029/resultado.md`). A leitura foi de um worker Opus por pasta, com a régua e as marcas
de 24/10 como calibração, e marcas de cada leitor conferidas pelo lead contra o texto. Nada mudou por causa do resultado.

- **Os 24 da terceira amostra, como regressão: o aceite não foi atingido.**

  | Critério | Meta | Validação cega | Regressão |
  |---|---|---|---|
  | Aprovados | 21 de 24 ou mais | 19 | 19 (o C3.48 sem episódio) |
  | Disputa inventada | nenhuma | 2 (C2.87, C3.52) | 2 (C1.77, C2.87) |
  | Frases marcadas | até 21% | 8% | 9% |
  | Atribuídos por episódio | até 1,7, e 1,8 nas disputas | 0,79 e 1,22 | 1,17 e 1,89 |

  Disputas do gabarito: 6 de 9 certas (eram 4), 3 perdidas (C2.63, C3.23, C3.53), nenhuma questão errada. O C1.55 e o
  C1.83 saíram com a disputa e o C3.52 sem a inventada, como na medida. O C2.87 não mudou com o prompt, nem o UOL do C3.53
  virou lado. O C1.77 saiu com a disputa inventada da 33ª Zona Eleitoral, pelo "questionou" do MP Eleitoral no mesmo
  trecho (o limite conhecido: o verbo de outro ator na frase também vale). O C2.63 perdeu de novo: o modelo pôs o MPT,
  com o trecho da decisão da Justiça do Trabalho, e a conferência o recusou. O C3.48 falhou na geração: o modelo fechou o
  JSON depois do resumo, e não há nova tentativa nesse caso. Os atribuídos nas disputas subiram com os lados recuperados
  (7 no C2.62, 4 no C1.55). 6,3 marcas por mil palavras de roteiro (5,5 na validação).
- **Os 20 de 16/10: o critério de 23/10 foi atingido**, com 17 de 20 aprovados (19 em 24/10), nenhuma disputa
  inventada, 11% de frases marcadas (10%) e 22 atribuídos, 3 nas disputas (16 e 7). As 5 disputas do gabarito certas. As
  3 reprovações, por palavras, são de itens com disputa (A92, A79, N92). 7,7 marcas por mil palavras (7,4).
- **O limite da comparação:** os leitores são outros nas três leituras (o lead em 24/10, três workers na validação,
  cinco workers agora).

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

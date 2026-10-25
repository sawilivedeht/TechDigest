"""Os nomes dos analistas, que o código dá (decisão de 24/10/2026): o bloco LADOS DA PAUTA diz o nome de cada um, o QA
confere que o roteiro os usa (`qa.problemas_dos_nomes`) e o TTS dá a cada nome a voz da vaga dele (`tts.atribuir_vozes`).

Até então o modelo escolhia os nomes. Ele repetia o nome de uma pessoa citada nos textos (o N86 chamou o analista de
"Bruno Silva", o colunista que é a fonte), e, quando o prompt pediu que não fizesse isso, passou a dar nomes de função
("Analista de Política", "Analista Jurídico") a todos.

Os nomes vão por vaga: a vaga i é a do analista do lado i (com um lado só, a primeira), e cada vaga tem a sua voz no TTS,
do gênero dos nomes dela. Em cada vaga vale o primeiro nome que não é o nome nem o primeiro nome de um ator da análise
(ver `mesmo_nome`). Os nomes quase não aparecem nas amostras da fase 4, para não coincidir com o de uma pessoa citada
que não é ator.

Não importa nada do projeto: `lados.py` e `qa.py` o usam.
"""
import re
import unicodedata

# Por vaga, os nomes, na ordem de preferência. A voz de cada vaga está em `tts.VOZES_DIVERSIDADE`, na mesma posição.
VAGAS = (
    ("Otávio", "Mateus", "Caio"),          # voz masculina
    ("Patrícia", "Sofia", "Isabela"),      # voz feminina
    ("Vinícius", "Sérgio", "Renato"),      # voz masculina
)
# Títulos e cargos que vêm antes de um nome ("Dr. Ramos", "presidente Lula"), sem acento: não contam na comparação.
TITULOS = frozenset({
    "dr", "dra", "doutor", "doutora", "prof", "profa", "professor", "professora", "sr", "sra", "senhor", "senhora",
    "presidente", "presidenta", "ministro", "ministra", "senador", "senadora", "deputado", "deputada", "governador",
    "governadora", "prefeito", "prefeita", "general", "coronel", "comandante", "juiz", "juiza", "padre", "pastor", "papa",
})


def _dobrar(palavra: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", palavra) if not unicodedata.combining(c)).lower()


def nome_sem_titulos(nome) -> list[tuple[str, str]]:
    """As palavras de um nome, como estão escritas e sem acento nem caixa, sem os títulos e cargos do começo (TITULOS)."""
    palavras = [(p, _dobrar(p)) for p in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", str(nome)))]
    while palavras and palavras[0][1] in TITULOS:
        palavras.pop(0)
    return palavras


def mesmo_nome(nome, ator) -> str:
    """Se o nome é o do ator ("o nome") ou tem o primeiro nome dele ("o primeiro nome"); vazio se não.

    Sem os títulos e cargos do começo, é o nome do ator quando as palavras são as mesmas (sem acento nem caixa), e é o
    primeiro nome quando a primeira palavra é a mesma e a do ator começa com maiúscula: com o ator "Bruno Silva",
    "Bruno" e "Bruno Costa" têm o primeiro nome, e "Dr. Silva" não tem nada.
    """
    meu, dele = nome_sem_titulos(nome), nome_sem_titulos(ator)
    if not meu or not dele:
        return ""
    if [p for _, p in meu] == [p for _, p in dele]:
        return "o nome"
    if dele[0][0][:1].isupper() and meu[0][1] == dele[0][1]:
        return "o primeiro nome"
    return ""


def nomes_dos_analistas(lados) -> list[str]:
    """O nome do analista de cada lado, na ordem dos lados (com um lado só, ou nenhum, um analista).

    Em cada vaga, o primeiro nome que não coincide com nenhum ator dos lados (ver `mesmo_nome`); se todos coincidirem, o
    último da vaga.
    """
    atores = [ator for lado in lados for ator in lado.atores]
    nomes = []
    for vaga in VAGAS[:max(len(lados), 1)]:
        nomes.append(next((n for n in vaga if not any(mesmo_nome(n, ator) for ator in atores)), vaga[-1]))
    return nomes


def vaga(nome) -> int | None:
    """A vaga de um nome da lista (0, 1 ou 2), pela comparação sem acento nem caixa; None se não é da lista."""
    dobrado = _dobrar(str(nome).strip())
    return next((i for i, nomes in enumerate(VAGAS) if any(_dobrar(n) == dobrado for n in nomes)), None)

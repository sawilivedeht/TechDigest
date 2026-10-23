"""O orçamento de palavras do episódio, proporcional ao material que a geração recebe (item 3 de 19/10/2026).

O alvo total é FATOR vezes as palavras dos textos que a geração recebe (os recortes), com piso
PISO_TOTAL e teto no alvo de antes para o tamanho do elenco (ALVO_DE_ANTES por personagem). A
Helena fica com uma parte do total (`parte_da_helena`); os analistas dividem o resto na proporção
das frases dos textos com os atores do lado de cada um (`Lado.mencoes`), cada um com MIN_ANALISTA
palavras ou mais, e nenhum personagem passa de MAX_ALVO. Com pouco material, as falas encolhem e o
número de turnos acompanha o total. O alvo vai ao bloco LADOS DA PAUTA como faixa; o QA cobra uma
fração dele como mínimo (ver `qa.limites_de_cada_personagem`). Os máximos do QA não mudam.

Não importa nada de `lados.py` nem de `qa.py`, que o usam: dos lados, só lê `mencoes`.
"""
import math
from dataclasses import dataclass

FATOR = 1.75                  # palavras de roteiro por palavra de texto recebido (a calibrar na regressão)
PISO_TOTAL = 300
# O alvo de antes, por personagem, pelo número de analistas: o centro de 360-420, 320-400 e 260-310.
ALVO_DE_ANTES = {1: 390, 2: 360, 3: 285}
MENOR_PARTE_DA_HELENA, MAIOR_PARTE_DA_HELENA = 0.35, 0.45
MIN_ANALISTA = 120            # o alvo de cada analista, no mínimo (o que se pedia ao de lado fino)
MAX_ALVO = 430                # o alvo de cada personagem, no máximo: a faixa fica abaixo dos 480 que o prompt pedia
FAIXA = 0.10                  # o alvo vai ao prompt como faixa: 10% para baixo e para cima
FRACAO_DO_MINIMO = 0.75       # o QA cobra esta fração do alvo como mínimo (nunca acima do mínimo de antes)
PALAVRAS_POR_FALA = (50, 90)  # com material cheio
TOTAL_DAS_FALAS_CHEIAS = 600  # abaixo deste total, as falas encolhem na proporção...
MENOR_ESCALA_DAS_FALAS = 0.6  # ...até 60% (30 a 54 palavras)
MAX_TURNOS = 20


def _dezena(valor: float) -> int:
    """A dezena mais próxima, com a metade para cima (165 vira 170, e não 160 como no `round` do Python)."""
    return int(math.floor(valor / 10 + 0.5) * 10)


def faixa(alvo: int) -> tuple[int, int]:
    """A faixa que o prompt pede em volta de um alvo, em dezenas."""
    return _dezena(alvo * (1 - FAIXA)), _dezena(alvo * (1 + FAIXA))


def minimo_do_qa(alvo: int, minimo_de_antes: int) -> int:
    """O mínimo que o QA cobra de um alvo: FRACAO_DO_MINIMO dele, nunca acima do mínimo de antes.

    Fica sempre abaixo da faixa que o prompt pede, inclusive para quem antes tinha um piso (o
    analista de lado fino, 120; a Helena com debate, 180).
    """
    return min(int(alvo * FRACAO_DO_MINIMO), minimo_de_antes)


def parte_da_helena(analistas: int) -> float:
    """A parte do total que fica com a Helena: a de antes (um por personagem), entre 35% e 45%."""
    return min(max(1 / (analistas + 1), MENOR_PARTE_DA_HELENA), MAIOR_PARTE_DA_HELENA)


def _repartir(parte: float, pesos: list[float], minimo: float) -> list[float]:
    """Divide `parte` na proporção dos pesos, com `minimo` para cada um: quem ficaria abaixo leva o mínimo e sai da conta."""
    alvos: list[float | None] = [None] * len(pesos)
    livres, resto = set(range(len(pesos))), parte
    while livres:
        soma = sum(pesos[i] for i in livres)
        baixos = [i for i in livres if resto * pesos[i] / soma < minimo]
        if not baixos:
            break
        for i in baixos:
            alvos[i], resto = minimo, resto - minimo
            livres.discard(i)
    soma = sum(pesos[i] for i in livres)
    for i in livres:
        alvos[i] = resto * pesos[i] / soma
    return alvos


@dataclass(frozen=True)
class Orcamento:
    """O alvo de palavras de cada personagem, do total e dos turnos de um episódio."""
    helena: int
    analistas: tuple[int, ...]      # um por lado, na ordem dos lados
    palavras_do_texto: int | None   # as palavras que a geração recebe; None = sem medida (o alvo de antes)
    reduzido: bool = False          # o material é pouco e o total ficou abaixo do alvo de antes

    @property
    def total(self) -> int:
        return self.helena + sum(self.analistas)

    @property
    def por_fala(self) -> tuple[int, int]:
        """Quantas palavras cada fala tem: 50 a 90 com material cheio, e menos com pouco."""
        escala = min(max(self.total / TOTAL_DAS_FALAS_CHEIAS, MENOR_ESCALA_DAS_FALAS), 1.0)
        return round(PALAVRAS_POR_FALA[0] * escala), round(PALAVRAS_POR_FALA[1] * escala)

    @property
    def turnos(self) -> tuple[int, int]:
        """Quantos turnos cabem no total com falas do tamanho pedido; pelo menos os da estrutura.

        A estrutura é a Helena abrindo, fechando e passando a palavra a cada analista duas vezes.
        """
        menor_fala, maior_fala = self.por_fala
        baixo, alto = faixa(self.total)
        estrutura = 2 * len(self.analistas) + 3
        primeiro = min(max(math.ceil(baixo / maior_fala), estrutura), MAX_TURNOS)
        return primeiro, min(max(alto // menor_fala, primeiro), MAX_TURNOS)


def orcamento(lados, palavras_do_texto: int | None = None) -> Orcamento:
    """O orçamento do episódio, pelos lados da pauta e pelas palavras dos textos que a geração recebe.

    Sem as palavras, o total é o alvo de antes para o tamanho do elenco. Com um lado só, o analista
    leva tudo o que não é da Helena; com dois ou mais, os analistas dividem pela proporção das
    menções de cada lado (lado sem contagem conta como os outros; com zero, como uma).
    """
    n = max(len(lados), 1)
    teto = (n + 1) * ALVO_DE_ANTES[min(n, 3)]
    total = teto if palavras_do_texto is None else min(max(FATOR * palavras_do_texto, PISO_TOTAL), teto)
    helena = _dezena(min(total * parte_da_helena(n), MAX_ALVO))
    if n == 1:   # o analista leva o resto do total arredondado
        analistas = [_dezena(total) - helena]
    else:
        contadas = [lado.mencoes for lado in lados]
        pesos = [max(m, 1) if m is not None else None for m in contadas]
        media = sum(p for p in pesos if p is not None) / max(sum(p is not None for p in pesos), 1) or 1
        analistas = _repartir(total - helena, [p if p is not None else media for p in pesos], MIN_ANALISTA)
    return Orcamento(helena, tuple(min(_dezena(a), MAX_ALVO) for a in analistas), palavras_do_texto, reduzido=total < teto)


def palavras(textos) -> int:
    """As palavras dos textos que a geração recebe (o recorte de cada um, sem o título)."""
    return sum(len(str(t["texto"]).split()) for t in textos)

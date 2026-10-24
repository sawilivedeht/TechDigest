"""O orçamento de palavras do episódio, proporcional ao material que a geração recebe (item 3 de 19/10/2026).

O alvo total é FATOR vezes as palavras dos textos que a geração recebe (os recortes), com piso
PISO_TOTAL e teto no alvo de antes para o tamanho do elenco (ALVO_DE_ANTES por personagem). A
Helena fica com uma parte do total (`parte_da_helena`); os analistas dividem o resto na proporção
das frases dos textos com os atores do lado de cada um (`Lado.mencoes`), cada um com MIN_ANALISTA
palavras ou mais, e nenhum personagem passa de MAX_ALVO. O alvo de cada personagem e o do total vão
ao bloco LADOS DA PAUTA como um número só, com o plano das falas (`Plano`, decisão de 24/10/2026):
quantas falas cada personagem tem, de que tamanho e em que ordem, começando e terminando com a
Helena. O plano fecha a conta do alvo: a Helena fala entre as rodadas dos analistas, e cada um tem
as falas que o alvo dele pede. O QA cobra uma fração do alvo como mínimo (ver
`qa.limites_de_cada_personagem`), e a diferença fica como margem, como nas frases do resumo. Os
máximos do QA não mudam.

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
MAX_ALVO = 430                # o alvo de cada personagem, no máximo: abaixo dos 480 que o prompt pedia
FRACAO_DO_MINIMO = 0.75       # o QA cobra esta fração do alvo como mínimo (nunca acima do mínimo de antes)
MAX_FALA_DO_ANALISTA = 90     # palavras: cada analista tem as falas que o alvo dele pede com no máximo este tamanho
MIN_FALAS_DO_ANALISTA = 2     # a Helena passa a palavra a cada analista pelo menos duas vezes


def _metade_para_cima(valor: float) -> int:
    """O inteiro mais próximo, com a metade para cima (o `round` do Python leva 4,5 a 4)."""
    return int(math.floor(valor + 0.5))


def _dezena(valor: float) -> int:
    """A dezena mais próxima, com a metade para cima (165 vira 170, e não 160)."""
    return _metade_para_cima(valor / 10) * 10


def _cinco(valor: float) -> int:
    """O múltiplo de 5 mais próximo, com a metade para cima: o tamanho de fala que o bloco diz ("uns 85 palavras")."""
    return _metade_para_cima(valor / 5) * 5


def minimo_do_qa(alvo: int, minimo_de_antes: int) -> int:
    """O mínimo que o QA cobra de um alvo: FRACAO_DO_MINIMO dele, nunca acima do mínimo de antes.

    Fica sempre abaixo do alvo que o bloco pede, inclusive para quem antes tinha um piso (o
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
class Plano:
    """As falas do episódio: quantas cada personagem tem, de que tamanho e em que ordem."""
    falas: tuple[int, ...]      # por personagem: a Helena primeiro, depois o analista de cada lado, na ordem dos lados
    tamanhos: tuple[int, ...]   # o tamanho de cada fala de cada personagem, em palavras, arredondado a 5
    ordem: tuple[int, ...]      # a sequência dos turnos: 0 é a Helena, i é o analista do lado i

    @property
    def turnos(self) -> int:
        return len(self.ordem)


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
    def plano(self) -> Plano:
        """O plano das falas, que fecha a conta do alvo de cada personagem.

        Cada analista tem as falas que o alvo dele pede com no máximo MAX_FALA_DO_ANALISTA palavras,
        e pelo menos MIN_FALAS_DO_ANALISTA. A Helena abre e fecha e fala entre as rodadas: em cada
        rodada, falam na ordem dos lados os analistas que ainda têm fala. Ela tem, então, uma fala a
        mais que o analista que mais fala, e o alvo dela se divide por elas. Com um analista de 430 e
        a Helena com 350: Helena, 6 falas de uns 60; analista, 5 de uns 85; 11 turnos.
        """
        falas = [max(MIN_FALAS_DO_ANALISTA, math.ceil(alvo / MAX_FALA_DO_ANALISTA)) for alvo in self.analistas]
        ordem = [0]
        for rodada in range(max(falas)):
            ordem += [i for i, n in enumerate(falas, 1) if n > rodada] + [0]
        da_helena = max(falas) + 1
        tamanhos = [_cinco(self.helena / da_helena)] + [_cinco(alvo / n) for alvo, n in zip(self.analistas, falas)]
        return Plano((da_helena, *falas), tuple(tamanhos), tuple(ordem))

    @property
    def turnos(self) -> int:
        """O número de turnos do plano."""
        return self.plano.turnos


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

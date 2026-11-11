"""O artigo da coleta (`Article`) e, depois dele, os tipos do episódio que o modelo escreve (o contrato de
`ai/llm.SCHEMA`) e do item que o pipeline entrega.

Os tipos do episódio são só anotações para o verificador de tipos: nada aqui valida em tempo de execução. Onde o JSON
do modelo vira episódio, o código usa `typing.cast(Episodio, ...)`, que não confere nada: o `llm.parse_json` só garante
que as 8 chaves existem, não o tipo de cada valor. Quem trata o episódio malformado (um valor de outro tipo, um turno
sem `fala`) é o QA: `summarizer._qa` transforma o KeyError, o TypeError e o AttributeError de `qa.problemas_com_campo`
num problema de estrutura. Por isso o código defensivo do QA continua como está.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import NotRequired, TypedDict
import logging
logger = logging.getLogger("techdigest.models")

@dataclass
class Article:
    title: str
    url: str
    summary: str = ""
    source: str = ""
    published: datetime | None = None
    feed: str = ""                       # a URL do feed de onde o artigo veio (o da primeira aparição no intercalado)
    categorias: tuple[str, ...] = ()     # as categorias da entrada no feed (<category>), como o feed as escreve


class Personagem(TypedDict):
    """Um item de `personagens`: o nome, que o roteiro usa, e o papel (a especialidade, sem vínculo com um ator)."""
    nome: str
    papel: str


class Turno(TypedDict):
    """Um item de `roteiro_podcast`: quem fala e o que fala."""
    personagem: str
    fala: str


class Episodio(TypedDict):
    """As 8 chaves do episódio, as de `llm.SCHEMA` e `llm.REQUIRED_KEYS` (o `tests/test_models.py` confere)."""
    titulo_reescrito: str
    resumo_didatico: str
    pontos_chave: list[str]
    por_que_importa: str
    personagens: list[Personagem]
    roteiro_podcast: list[Turno]
    houve_divergencia: bool
    fontes_citadas: list[str]


class ItemEntregue(Episodio):
    """O episódio com o que o pipeline acrescenta antes da entrega (`pipeline._Lote.gerar_e_entregar`), no mesmo dict.

    `url` e `source` são o link do feed do artigo principal e o veículo dele, e `vozes` a voz de cada personagem: os
    três sempre postos. Numa pauta de várias fontes vêm também `outras_fontes` (url e source de cada relacionado
    gerado) e `tambem_noticiaram` (url, source e titulo das duplicatas e dos excedentes), só quando há o que listar.
    """
    url: str
    source: str
    vozes: dict[str, str]
    outras_fontes: NotRequired[list[dict[str, str]]]
    tambem_noticiaram: NotRequired[list[dict[str, str]]]

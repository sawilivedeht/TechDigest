"""Os tipos do episódio (`techdigest.models`) amarrados ao contrato de saída do modelo (`llm.SCHEMA`, `llm.REQUIRED_KEYS`).

O formato do episódio está no SCHEMA, no texto dos prompts e nestes tipos: os testes falham quando os tipos e o SCHEMA
se separam (uma chave a mais ou a menos, ou de outro tipo).
"""
import typing

from techdigest.ai.llm import REQUIRED_KEYS, SCHEMA
from techdigest.models import Episodio, ItemEntregue, Personagem, Turno

_TIPO_DO_SCHEMA = {"string": str, "boolean": bool, "array": list}


def _confere(tipo, esquema: dict) -> None:
    """Cada chave do TypedDict é uma do objeto do JSON Schema, obrigatória e do mesmo tipo, e nenhuma falta."""
    dicas = typing.get_type_hints(tipo)
    assert set(dicas) == set(esquema["properties"])
    assert tipo.__required_keys__ == frozenset(esquema["required"])
    assert tipo.__optional_keys__ == frozenset()
    for chave, propriedade in esquema["properties"].items():
        dica = dicas[chave]
        assert (typing.get_origin(dica) or dica) is _TIPO_DO_SCHEMA[propriedade["type"]], chave


def test_episodio_tem_as_8_chaves_do_schema():
    assert Episodio.__required_keys__ == REQUIRED_KEYS
    _confere(Episodio, SCHEMA)


def test_itens_das_listas_do_episodio():
    dicas = typing.get_type_hints(Episodio)
    for chave, tipo in (("personagens", Personagem), ("roteiro_podcast", Turno)):
        assert typing.get_args(dicas[chave]) == (tipo,)
        _confere(tipo, SCHEMA["properties"][chave]["items"])
    for chave in ("pontos_chave", "fontes_citadas"):
        assert SCHEMA["properties"][chave]["items"] == {"type": "string"}
        assert typing.get_args(dicas[chave]) == (str,)


def test_item_entregue_e_o_episodio_com_as_chaves_do_pipeline():
    assert ItemEntregue.__required_keys__ == REQUIRED_KEYS | {"url", "source", "vozes"}
    assert ItemEntregue.__optional_keys__ == {"outras_fontes", "tambem_noticiaram"}

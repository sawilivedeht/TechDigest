"""A parte fixa de cada chamada em tokens exatos (ai/janela.py): contada uma vez, guardada pelo hash do modelo e do
prompt, e None para o provider que não conta. O conftest dá a cada teste um arquivo e uma memória vazios."""
import json
import logging

from techdigest.ai import janela


class Contador:
    def __init__(self, model="modelo", tokens=2591, erro=None):
        self.model, self.tokens, self.erro, self.contagens = model, tokens, erro, []

    def contar_tokens_fixos(self, system):
        self.contagens.append(system)
        if self.erro:
            raise self.erro
        return self.tokens


def test_a_parte_fixa_e_contada_uma_vez_e_guardada_pelo_hash_do_modelo_e_do_prompt():
    contador = Contador()
    assert janela.tokens_fixos(contador, "sistema") == 2591
    assert janela.tokens_fixos(contador, "sistema") == 2591
    assert contador.contagens == ["sistema"]
    guardadas = json.loads(open(janela.settings.tokens_fixos, encoding="utf-8").read())
    assert guardadas[janela.chave("modelo", "sistema")]["tokens"] == 2591

    janela._memoria.clear()                              # outro processo: lê o arquivo, sem contar de novo
    assert janela.tokens_fixos(Contador(tokens=9), "sistema") == 2591
    outro_modelo = Contador(model="outro", tokens=2700)  # outro modelo, outra contagem
    assert janela.tokens_fixos(outro_modelo, "sistema") == 2700 and outro_modelo.contagens == ["sistema"]
    assert janela.tokens_fixos(contador, "outro prompt") == 2591 and contador.contagens == ["sistema", "outro prompt"]


def test_sem_contagem_a_parte_fixa_e_none(caplog):
    class SemContagem:
        model = "openai"
    assert janela.tokens_fixos(SemContagem(), "sistema") is None
    with caplog.at_level(logging.WARNING, logger="techdigest.ai.janela"):
        assert janela.tokens_fixos(Contador(erro=ConnectionError("fora do ar")), "sistema") is None
    assert "Parte fixa não contada (ConnectionError: fora do ar)" in caplog.text

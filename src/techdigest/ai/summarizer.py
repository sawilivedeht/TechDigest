"""Summarizer — geração + revisão com QA determinístico."""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from techdigest.ai.lados import MAX_BLOCO, Analise, analisar_lados, bloco_dos_lados
from techdigest.ai.llm import get_provider
from techdigest.ai.prompt import PROMPT_REVISOR, PROMPT_SISTEMA
from techdigest.ai.qa import problemas, veiculos_distintos
from techdigest.config import Settings

logger = logging.getLogger("techdigest.ai.summarizer")

settings = Settings()

TETO_PRINCIPAL = 5000           # caracteres do texto do artigo principal (o corte de sempre)
TETO_RELACIONADO = 3000         # caracteres do trecho de cada relacionado
MAX_RELACIONADOS = 2            # relacionados que entram na entrada (principal + 2)
MIN_TRECHO = 400                # relacionado que ficaria com menos que isto sai da entrada
MARGEM_TOKENS = 256             # folga da janela de contexto, além da reserva de saída
CHARS_POR_TOKEN_INICIAL = 3.0   # antes da primeira medida: conservador (o medido fica perto de 4)
FOLGA_DA_MEDIDA = 0.9           # vale 90% da menor proporção medida

LEMBRETE = (
    "\nLEMBRETE: só o JSON das 8 chaves. Roteiro com 600-1300 palavras "
    "no total, 240-480 por personagem, 14-24 turnos."
)
_BRASILIA = timezone(timedelta(hours=-3))  # sem horário de verão desde 2019


class QAReprovado(ValueError):
    """Episódio ainda viola as regras editoriais depois da passada de revisão."""


@dataclass
class Entrada:
    """A mensagem montada para o LLM e o que entrou nela."""
    texto: str
    fontes: list[str]                                   # veículo de cada texto incluído, o principal primeiro
    cortes: list[dict] = field(default_factory=list)    # por artigo recebido: fonte, caracteres do texto e quantos entraram
    textos: list[dict] = field(default_factory=list)    # por texto incluído: fonte, titulo e o trecho que entrou


def _limpar(texto: str) -> str:
    """Remove caracteres de controle e whitespace degenerado de extrações sujas."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _qa(result: dict, veiculos: list[str], lados: list) -> list[str]:
    """Roda o QA sem deixar um JSON malformado derrubar o fluxo (vira problema, não exceção)."""
    try:
        return problemas(result, veiculos, lados)
    except (KeyError, TypeError, AttributeError) as e:
        return [f"estrutura inválida para o QA ({type(e).__name__}: {e})"]


def _cortar_em_paragrafo(texto: str, limite: int) -> str:
    """Os primeiros `limite` caracteres, terminando em fim de parágrafo.

    Se o corte no parágrafo jogar fora mais da metade do espaço (um parágrafo enorme), vale o fim
    de frase; em último caso, o fim de palavra.
    """
    if len(texto) <= limite:
        return texto
    trecho = texto[:limite]
    fim = trecho.rfind("\n")
    if fim >= limite // 2:
        return trecho[:fim].rstrip()
    fim = max(trecho.rfind(sinal) for sinal in (". ", "! ", "? "))
    if fim >= limite // 2:
        return trecho[:fim + 1]
    return trecho.rsplit(None, 1)[0] if " " in trecho else trecho


def _repartir(desejados: list[int], orcamento: int) -> list[int]:
    """Divide `orcamento` caracteres entre os textos; o primeiro é o principal.

    Se tudo cabe, cada um leva o que pede. Senão o principal fica com metade e os relacionados
    dividem a outra metade; quem pede menos que a sua cota devolve a sobra, que vai para os outros.
    """
    if sum(desejados) <= orcamento:
        return list(desejados)
    n = len(desejados)
    cotas = [float(orcamento)] if n == 1 else [orcamento / 2] + [orcamento / 2 / (n - 1)] * (n - 1)
    concedidos = [0.0] * n
    abertos = set(range(n))
    while abertos:
        satisfeitos = [i for i in abertos if desejados[i] <= cotas[i]]
        if not satisfeitos:
            break
        sobra = 0.0
        for i in satisfeitos:
            concedidos[i] = desejados[i]
            sobra += cotas[i] - desejados[i]
            abertos.discard(i)
        em_aberto = sum(cotas[i] for i in abertos)
        for i in abertos:
            cotas[i] += sobra * cotas[i] / em_aberto
    for i in abertos:
        concedidos[i] = cotas[i]
    return [int(c) for c in concedidos]


def _aviso(artigos: list[dict]) -> str:
    """Aviso do editor-chefe para a entrada com relacionados: só fala do que entrou no texto.

    Conta os textos e os veículos e pede a ordem cronológica; os lados da história vêm no bloco LADOS DA PAUTA.
    """
    veiculos = veiculos_distintos(a["source"] for a in artigos)
    if len(veiculos) > 1:
        aviso = (
            f"\nAVISO DO EDITOR-CHEFE: há {len(artigos)} textos de {len(veiculos)} veículos sobre este "
            f"assunto ({', '.join(sorted(veiculos))}). Cite cada veículo pelo nome."
        )
    else:
        aviso = (
            f"\nAVISO DO EDITOR-CHEFE: há {len(artigos)} textos do mesmo veículo sobre este assunto "
            f"({veiculos[0]}). Cite-o como uma fonte só."
        )
    if any(a.get("relacao") == "desdobramento" for a in artigos[1:]):
        aviso += " Os textos relatam momentos diferentes da mesma história: narre os fatos em ordem cronológica"
        if all(a.get("data") for a in artigos):
            ordem = sorted(artigos, key=lambda a: a["data"])
            aviso += " (" + "; ".join(f"{a['source']}, {a['data'].astimezone(_BRASILIA):%d/%m %H:%M}" for a in ordem) + ")"
        aviso += "."
    return aviso


def montar_entrada(principal: dict, relacionados: list[dict] | None = None, limite: int | None = None,
                   lados: list | None = None) -> Entrada:
    """Monta a mensagem do episódio dentro de `limite` caracteres (None = sem limite).

    Cada artigo é um dict com "source", "title" e "text"; os relacionados podem trazer também
    "relacao" e "data" (com fuso), que só o aviso usa. Entram o principal e até MAX_RELACIONADOS
    relacionados, cada texto com o teto de sempre (TETO_PRINCIPAL, TETO_RELACIONADO).

    Cabeçalhos, aviso e lembrete nunca são cortados: o orçamento dos textos é o que sobra do
    limite depois deles. Se os textos não cabem, são repartidos (ver `_repartir`) e cortados em
    fim de parágrafo. Relacionado que ficaria com menos de MIN_TRECHO caracteres sai da entrada, e
    o aviso conta e nomeia só os que entraram.

    `lados` é o resultado da análise de lados: com ele, o bloco LADOS DA PAUTA entra antes do
    lembrete. O espaço do bloco (MAX_BLOCO) é reservado sempre, com ou sem `lados`, para que os
    trechos sejam os mesmos na chamada sem o bloco (a que alimenta a análise de lados) e na
    chamada com ele (a do episódio).
    """
    recebidos = [principal, *(relacionados or [])]
    artigos = recebidos[:1 + MAX_RELACIONADOS]
    textos = [_limpar(a["text"])[:TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO] for i, a in enumerate(artigos)]

    while True:
        cabecalhos = [
            f"ARTIGO PRINCIPAL\nFonte: {principal['source']}\nTítulo: {_limpar(principal['title'])}\nTexto:\n"
        ] + [
            f"\nARTIGO RELACIONADO [{i}]\nFonte: {rel['source']}\nTítulo: {_limpar(rel['title'])}\nTrecho:\n"
            for i, rel in enumerate(artigos[1:], 1)
        ]
        avisos = [_aviso(artigos)] if len(artigos) > 1 else []
        if limite is None:
            concedidos = [len(t) for t in textos]
            break
        fixos = (sum(map(len, cabecalhos)) + sum(map(len, avisos)) + MAX_BLOCO + len(LEMBRETE)
                 + len(cabecalhos) + len(avisos) + 1)   # com as quebras do join
        concedidos = _repartir([len(t) for t in textos], max(limite - fixos, 0))
        apertados = [i for i in range(1, len(artigos)) if concedidos[i] < min(MIN_TRECHO, len(textos[i]))]
        if not apertados:
            break
        del artigos[apertados[-1]], textos[apertados[-1]]  # sai o último da fila e a conta recomeça

    if concedidos[0] < min(MIN_TRECHO, len(textos[0])):
        logger.error(
            "Orçamento da entrada pequeno demais (%s caracteres): o artigo principal vai com %d caracteres "
            "mesmo assim e a mensagem passa do limite.", limite, min(MIN_TRECHO, len(textos[0])),
        )
        concedidos[0] = min(MIN_TRECHO, len(textos[0]))
    trechos = [_cortar_em_paragrafo(texto, cabe) for texto, cabe in zip(textos, concedidos)]

    finais = avisos + ([bloco_dos_lados(lados)] if lados else []) + [LEMBRETE]
    incluido = {id(a): len(t) for a, t in zip(artigos, trechos)}
    return Entrada(
        texto="\n".join([c + t for c, t in zip(cabecalhos, trechos)] + finais),
        fontes=[a["source"] for a in artigos],
        cortes=[{"fonte": a["source"], "texto": len(_limpar(a["text"])), "incluido": incluido.get(id(a), 0)} for a in recebidos],
        textos=[{"fonte": a["source"], "titulo": _limpar(a["title"]), "texto": t} for a, t in zip(artigos, trechos)],
    )


class Summarizer:
    """Gera (e se preciso, revisa) o JSON editorial completo de uma notícia."""

    def __init__(self, provider=None):
        self.provider = provider or get_provider(settings)
        self.chars_por_token = CHARS_POR_TOKEN_INICIAL  # passa a valer a medida do provider depois da 1ª chamada
        self._medidas = 0
        self.ultimo_diagnostico: dict = {}  # da última chamada a process: entradas montadas e problemas de QA

    def _limite_da_entrada(self, system: str, extra: int = 0) -> int:
        """Quantos caracteres a entrada pode ter numa chamada com este prompt de sistema.

        No Ollama é a janela (num_ctx) menos a reserva de saída e uma margem, convertida para
        caracteres pela proporção medida, menos o prompt de sistema. A reserva é o menor entre
        OLLAMA_NUM_PREDICT e LLM_RESERVA_SAIDA, porque num_predict pode ser maior que a própria
        janela. No caminho OpenAI vale LLM_MAX_PROMPT_CHARS. `extra` é o que mais vai na mensagem
        além da entrada (na revisão: os problemas e o episódio original).
        """
        if settings.llm_provider != "ollama":
            return settings.llm_max_prompt_chars - extra
        reserva = min(settings.ollama_num_predict, settings.llm_reserva_saida)
        tokens = settings.ollama_num_ctx - reserva - MARGEM_TOKENS
        return int(tokens * self.chars_por_token) - len(system) - extra

    def _chamar(self, system: str, user: str, **opcoes) -> dict:
        """Chama o provider e aproveita os tokens que ele contou para medir caracteres por token."""
        result = self.provider.chat_json(system, user, **opcoes)
        tokens = (getattr(self.provider, "ultimo_uso", None) or {}).get("prompt", 0)
        if tokens > 0:
            medida = (len(system) + len(user)) / tokens * FOLGA_DA_MEDIDA
            self.chars_por_token = medida if self._medidas == 0 else min(self.chars_por_token, medida)
            self._medidas += 1
        return result

    def _montar_entrada(self, principal: dict, relacionados: list[dict] | None = None) -> str:
        return montar_entrada(principal, relacionados, self._limite_da_entrada(PROMPT_SISTEMA)).texto

    def preparar(self, principal: dict, relacionados: list[dict] | None = None) -> tuple[Entrada, Analise]:
        """Roda a análise de lados da pauta e monta a entrada do episódio, já com o bloco de lados.

        O limite é calculado uma vez, antes da análise: assim os trechos que o LLM lê para contar
        os lados são os mesmos que vão para a geração.
        """
        limite = self._limite_da_entrada(PROMPT_SISTEMA)
        previa = montar_entrada(principal, relacionados, limite)
        logger.info(
            "Resumindo: %r (fonte: %s, %d caracteres de texto, %d relacionado(s))",
            str(principal["title"])[:80], principal["source"],
            len(principal["text"]), len(previa.fontes) - 1,
        )
        analise = analisar_lados(self._chamar, previa.textos)
        return montar_entrada(principal, relacionados, limite, analise.lados), analise

    def process(self, principal: dict, relacionados: list[dict] | None = None) -> dict:
        """Devolve um episódio que passou no QA; do contrário levanta QAReprovado (item é pulado)."""
        entrada, analise = self.preparar(principal, relacionados)
        self.ultimo_diagnostico = {
            "entrada": entrada, "lados": analise, "problemas": None, "revisao": None, "problemas_da_revisao": None,
        }
        logger.debug("Início da entrada enviada ao LLM: %r", entrada.texto[:600])

        result = self._chamar(PROMPT_SISTEMA, entrada.texto)

        probs = _qa(result, entrada.fontes, analise.lados)
        self.ultimo_diagnostico["problemas"] = probs
        if not probs:
            return result

        logger.warning("QA reprovou a 1ª versão: %s — acionando revisão", probs)
        # A revisão recebe o artigo-fonte: sem ele, "expandir" o roteiro vira invenção de fatos.
        # Ela leva também o episódio original, então a fonte é remontada no espaço que sobra.
        antes = "ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\n"
        depois = (
            "\n\nPROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs)
            + "\n\nEPISÓDIO ORIGINAL:\n" + json.dumps(result, ensure_ascii=False)
        )
        fonte = montar_entrada(
            principal, relacionados, self._limite_da_entrada(PROMPT_REVISOR, extra=len(antes) + len(depois)), analise.lados,
        )
        self.ultimo_diagnostico["revisao"] = fonte
        try:
            corrigido = self._chamar(PROMPT_REVISOR, antes + fonte.texto + depois)
        except Exception as e:
            raise QAReprovado(
                f"revisão falhou ({type(e).__name__}: {str(e)[:200]}); "
                f"1ª versão reprovada: {probs}"
            ) from e

        probs2 = _qa(corrigido, entrada.fontes, analise.lados)
        self.ultimo_diagnostico["problemas_da_revisao"] = probs2
        if not probs2:
            logger.info("Revisão aprovada pelo QA.")
            return corrigido

        raise QAReprovado(f"revisão ainda reprovada pelo QA: {probs2}")

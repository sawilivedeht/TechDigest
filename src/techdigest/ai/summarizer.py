"""Summarizer — geração, QA determinístico e uma correção: do título, do resumo, do roteiro ou do episódio inteiro."""
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from techdigest.ai.lados import (
    MAX_SAIDA_LADOS, Analise, analisar_lados, bloco_dos_lados, com_mencoes, reserva_do_bloco, trechos_de_evidencia,
)
from techdigest.ai.janela import tokens_fixos
from techdigest.ai.llm import JanelaExcedida, get_provider
from techdigest.ai.orcamento import Orcamento, orcamento, palavras
from techdigest.ai.prompt import PROMPT_LADOS, PROMPT_RESUMO, PROMPT_REVISOR, PROMPT_ROTEIRO, PROMPT_SISTEMA, PROMPT_TITULO
from techdigest.ai.qa import ELENCO, ESTRUTURA, PAPEL, RESUMO, ROTEIRO, TITULO, Problema, problemas_com_campo, veiculos_distintos
from techdigest.ai.recorte import recortar
from techdigest.config import Settings

logger = logging.getLogger("techdigest.ai.summarizer")

settings = Settings()

TETO_PRINCIPAL = 5000           # caracteres do recorte do artigo principal, no máximo
TETO_RELACIONADO = 3000         # caracteres do recorte de cada relacionado, no máximo
MAX_RELACIONADOS = 2            # relacionados que entram na entrada (principal + 2)
MIN_TRECHO = 400                # relacionado que ficaria com menos que isto sai da entrada
MARGEM_TOKENS = 256             # folga da janela de contexto, além da reserva de saída
# A janela (decisão do dono de 29/10/2026; ver `Summarizer._limite_da_entrada`). A proporção é a do texto: os caracteres
# da mensagem do usuário por token, sem a parte fixa (o prompt de sistema e o template), que entra em tokens exatos.
PROPORCAO_TIPICA = 4.3          # com que a 1ª chamada de cada item começa: a mediana de 64 itens das simulações de 25/10
                                # (gemma4:26b; de 2,30, numa pauta de tabelas de votos, a 4,79)
FOLGA_DA_MEDIDA = 0.9           # o limite usa 90% da proporção do texto (a típica ou a medida do item)
CHARS_POR_TOKEN_DO_PROMPT = 3.0 # a conversão do prompt de sistema quando o provider não conta a parte fixa (os prompts
                                # medem de 3,2 a 3,8 caracteres por token)
PROPORCAO_SEM_MEDIDA = 3.0      # a do item depois de um erro de janela que não disse quantos tokens a entrada tinha,
                                # quando a execução ainda não mediu nenhuma

LEMBRETE = (
    "\nLEMBRETE: só o JSON das 8 chaves. Roteiro no alvo de palavras de cada personagem e do total, "
    "no plano das falas que o bloco LADOS DA PAUTA indica: quantas falas cada um tem, de que tamanho e em que ordem."
)
LEMBRETE_DO_ROTEIRO = (
    "\nLEMBRETE: só o JSON com a chave roteiro_podcast. Roteiro no alvo de palavras de cada personagem e do "
    "total, no plano das falas que o bloco LADOS DA PAUTA indica: quantas falas cada um tem, de que tamanho e em "
    "que ordem. Corrigir os problemas não encurta as falas."
)
FONTE_ANTES = "ARTIGO-FONTE (use somente fatos deste texto; não invente informações):\n"
MAX_SAIDA_RESUMO = 700          # tokens: a correção do resumo devolve só o resumo
MAX_SAIDA_TITULO = 200          # tokens: a correção do título devolve só o título
TENTATIVAS_DO_TITULO = 2        # a correção do título pode ser tentada de novo, com os títulos já reprovados
# Os tipos de correção depois de um QA reprovado e como cada um aparece nas mensagens.
CORRECOES = {
    "titulo": "correção do título", "resumo": "correção do resumo", "roteiro": "revisão do roteiro", "completa": "revisão",
}
_BRASILIA = timezone(timedelta(hours=-3))  # sem horário de verão desde 2019


class QAReprovado(ValueError):
    """Episódio ainda viola as regras editoriais depois da passada de revisão."""


@dataclass
class Entrada:
    """A mensagem montada para o LLM e o que entrou nela."""
    texto: str
    fontes: list[str]                                   # veículo de cada texto incluído, o principal primeiro
    cortes: list[dict] = field(default_factory=list)    # por artigo recebido: fonte, caracteres do texto e quantos entraram
    textos: list[dict] = field(default_factory=list)    # por texto incluído: fonte, titulo e o recorte que entrou
    artigos: str = ""                                   # os artigos e o aviso, sem o bloco de lados nem o lembrete
    # Por artigo que a análise de lados leu: fonte, quantos parágrafos o texto tem, os que entraram (paragrafo, motivo,
    # caracteres) e os que têm trecho de evidência e ficaram de fora.
    recortes: list[dict] = field(default_factory=list)
    orcamento: Orcamento | None = None                  # o alvo de palavras que o bloco de lados pede (ver `ai/orcamento.py`)
    # Os textos que a janela, e não o teto, cortou: a posição entre os recebidos, a fonte, quanto o teto deixaria entrar
    # ("teto": o texto inteiro, se é menor), quanto a janela deixou ("cabe", 0 para o relacionado que saiu da entrada) e
    # quanto entrou, cortado em fim de parágrafo ("entrou").
    pela_janela: list[dict] = field(default_factory=list)


def _limpar(texto: str) -> str:
    """Remove caracteres de controle e whitespace degenerado de extrações sujas."""
    texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _qa(result: dict, veiculos: list[str], lados: list, ressalvas: list, textos: list[str],
        orc: Orcamento | None = None) -> list[Problema]:
    """Roda o QA sem deixar um JSON malformado derrubar o fluxo (vira problema, não exceção)."""
    try:
        return problemas_com_campo(result, veiculos, lados, ressalvas, textos, orc)
    except (KeyError, TypeError, AttributeError) as e:
        return [Problema(ESTRUTURA, f"estrutura inválida para o QA ({type(e).__name__}: {e})")]


def tipo_de_correcao(problemas: list[Problema]) -> str:
    """Que correção os problemas pedem: "titulo", "resumo", "roteiro" ou "completa".

    Com todos os problemas no título, só o título é reescrito; com todos no resumo_didatico, só o
    resumo; com todos no roteiro_podcast ou no papel de um personagem, a revisão do roteiro, que
    devolve o roteiro e os personagens. Problema em outro campo, ou em mais de um desses grupos,
    pede a revisão do episódio inteiro.
    """
    campos = {p.campo for p in problemas}
    if campos == {TITULO}:
        return "titulo"
    if campos == {RESUMO}:
        return "resumo"
    if campos <= {ROTEIRO, PAPEL}:
        return "roteiro"
    return "completa"


def _com_os_papeis(personagens: list[dict], devolvidos) -> list[dict]:
    """Os personagens do episódio com o papel que a revisão devolveu para o mesmo nome: os nomes não mudam."""
    papeis = {
        str(p.get("nome")): p["papel"] for p in devolvidos or []
        if isinstance(p, dict) and isinstance(p.get("papel"), str) and p["papel"].strip()
    } if isinstance(devolvidos, list) else {}
    return [{**p, "papel": papeis[p["nome"]]} if p.get("nome") in papeis else p for p in personagens]


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


def textos_da_pauta(principal: dict, relacionados: list[dict] | None = None) -> list[dict]:
    """Os textos inteiros que a análise de lados lê: o principal e até MAX_RELACIONADOS relacionados, os mesmos da geração."""
    artigos = [principal, *(relacionados or [])][:1 + MAX_RELACIONADOS]
    return [{"fonte": a["source"], "titulo": _limpar(a["title"]), "texto": _limpar(a["text"])} for a in artigos]


def montar_entrada(principal: dict, relacionados: list[dict] | None = None, limite: int | None = None,
                   lados: list | None = None, questao: str = "", ressalvas=(), lembrete: str = LEMBRETE,
                   reserva: int | None = None, orc: Orcamento | None = None) -> Entrada:
    """Monta a mensagem do episódio dentro de `limite` caracteres (None = sem limite).

    Cada artigo é um dict com "source", "title" e "text"; os relacionados podem trazer também
    "relacao" e "data" (com fuso), que só o aviso usa. Entram o principal e até MAX_RELACIONADOS
    relacionados, cada um com o seu teto (TETO_PRINCIPAL, TETO_RELACIONADO).

    Cabeçalhos, aviso, bloco de lados e lembrete nunca são cortados: o orçamento dos textos é o
    que sobra do limite depois deles. Se os textos não cabem, o espaço é repartido (ver
    `_repartir`). Relacionado que ficaria com menos de MIN_TRECHO caracteres sai da entrada, e o
    aviso conta e nomeia só os que entraram.

    De cada texto entra um recorte por relevância (ver `recorte.recortar`): o lide, os parágrafos
    com os trechos de evidência dos lados e das ressalvas e o resto, em ordem, até o espaço dele.
    `Entrada.recortes` diz que parágrafos entraram, por quê, e quais ficaram de fora tendo trecho.

    `lados`, `questao` e `ressalvas` são o resultado da análise de lados: com eles, o bloco LADOS
    DA PAUTA entra antes do lembrete, e o orçamento guarda para ele o tamanho que ele tem.
    `reserva` troca esse tamanho por outro: é o que `Summarizer.preparar` usa antes de saber quais
    lados são finos. `orc` é o orçamento de palavras que o bloco pede (ver `ai/orcamento.py`); sem
    ele, o bloco pede o alvo de antes. `lembrete` fecha a mensagem: o do episódio pede as 8 chaves,
    e a revisão do roteiro passa o dela.
    """
    recebidos = [principal, *(relacionados or [])]
    lidos = recebidos[:1 + MAX_RELACIONADOS]
    artigos = list(lidos)
    completos = {id(a): _limpar(a["text"]) for a in lidos}
    titulos = {id(a): _limpar(a["title"]) for a in lidos}
    # Os nomes dos analistas evitam as pessoas citadas nos textos: os mesmos textos que o QA recebe (ver `process`).
    pauta = [f"{a['title']}\n{a['text']}" for a in recebidos]
    bloco = bloco_dos_lados(lados, questao, ressalvas, orc, pauta) if lados else ""
    evidencias = trechos_de_evidencia(lados or [], ressalvas)

    while True:
        desejados = [min(len(completos[id(a)]), TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) for i, a in enumerate(artigos)]
        cabecalhos = [
            f"ARTIGO PRINCIPAL\nFonte: {principal['source']}\nTítulo: {titulos[id(principal)]}\nTexto:\n"
        ] + [
            f"\nARTIGO RELACIONADO [{i}]\nFonte: {rel['source']}\nTítulo: {titulos[id(rel)]}\nTrecho:\n"
            for i, rel in enumerate(artigos[1:], 1)
        ]
        avisos = [_aviso(artigos)] if len(artigos) > 1 else []
        if limite is None:
            concedidos = list(desejados)
            break
        fixos = (sum(map(len, cabecalhos)) + sum(map(len, avisos)) + (len(bloco) if reserva is None else reserva)
                 + len(lembrete) + len(cabecalhos) + len(avisos) + 1)   # com as quebras do join
        concedidos = _repartir(desejados, max(limite - fixos, 0))
        apertados = [i for i in range(1, len(artigos)) if concedidos[i] < min(MIN_TRECHO, desejados[i])]
        if not apertados:
            break
        del artigos[apertados[-1]]  # sai o último da fila e a conta recomeça

    if concedidos[0] < min(MIN_TRECHO, desejados[0]):
        logger.error(
            "Orçamento da entrada pequeno demais (%s caracteres): o artigo principal vai com %d caracteres "
            "mesmo assim e a mensagem passa do limite.", limite, min(MIN_TRECHO, desejados[0]),
        )
        concedidos[0] = min(MIN_TRECHO, desejados[0])
    cabe = {id(a): concedido for a, concedido in zip(artigos, concedidos)}
    tetos = {id(a): min(len(completos[id(a)]), TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) for i, a in enumerate(lidos)}
    feitos = {id(a): recortar(completos[id(a)], cabe.get(id(a), 0), evidencias, titulos[id(a)]) for a in lidos}
    pela_janela = [{"indice": i, "fonte": a["source"], "teto": tetos[id(a)], "cabe": cabe.get(id(a), 0),
                    "entrou": len(feitos[id(a)].texto) if id(a) in cabe else 0}
                   for i, a in enumerate(lidos) if cabe.get(id(a), 0) < tetos[id(a)]]
    trechos = [feitos[id(a)].texto for a in artigos]
    for a in lidos:
        if feitos[id(a)].fora:
            logger.warning(
                "Parágrafo(s) com trecho de evidência fora da entrada (%s): %s.", a["source"],
                "; ".join(f"§{f['paragrafo']}, {f['motivo']}, {f['caracteres']} caracteres" for f in feitos[id(a)].fora),
            )

    partes = [c + t for c, t in zip(cabecalhos, trechos)] + avisos
    finais = ([bloco] if lados else []) + [lembrete]
    return Entrada(
        texto="\n".join(partes + finais),
        artigos="\n".join(partes),
        fontes=[a["source"] for a in artigos],
        cortes=[{"fonte": a["source"], "texto": len(_limpar(a["text"])), "incluido": len(feitos[id(a)].texto) if id(a) in feitos else 0}
                for a in recebidos],
        textos=[{"fonte": a["source"], "titulo": titulos[id(a)], "texto": t} for a, t in zip(artigos, trechos)],
        recortes=[{"fonte": a["source"], "paragrafos": feitos[id(a)].total, "entraram": feitos[id(a)].entraram, "fora": feitos[id(a)].fora}
                  for a in lidos],
        orcamento=orc,
        pela_janela=pela_janela,
    )


def aviso_da_janela(entrada: Entrada, relacionados: list[dict] | None = None) -> str:
    """O aviso de quando a janela, e não o teto, cortou o texto de um item de fonte única (decisão de 29/10/2026); vazio
    se não cortou ou se o item tem várias fontes (nelas a janela é que reparte o espaço entre os textos)."""
    if relacionados or not entrada.pela_janela:
        return ""
    corte = entrada.pela_janela[0]
    return (f"o texto de {corte['fonte']} entrou na geração com {corte['entrou']} de {corte['teto']} caracteres: a janela, e "
            f"não o teto, cortou o texto (fonte única)")


class Summarizer:
    """Gera (e se preciso, revisa) o JSON editorial completo de uma notícia."""

    def __init__(self, provider=None):
        self.provider = provider or get_provider(settings)
        self.proporcao_do_item: float | None = None   # a menor medida das chamadas do item; reinicia a cada item
        self.menor_proporcao: float | None = None     # a menor medida da execução: só para o erro de janela sem contagem
        self._fixos: dict[str, int] = {}              # a parte fixa de cada prompt de sistema, em tokens
        self.ultimo_diagnostico: dict = {}  # da última chamada a process: entradas montadas e problemas de QA

    def _fixos_de(self, system: str) -> int:
        """Os tokens da parte fixa de uma chamada com este prompt de sistema: exatos (ver `ai/janela.py`) ou, se o
        provider não os conta, o prompt convertido por CHARS_POR_TOKEN_DO_PROMPT."""
        if system not in self._fixos:
            exato = tokens_fixos(self.provider, system)
            self._fixos[system] = exato if exato is not None else math.ceil(len(system) / CHARS_POR_TOKEN_DO_PROMPT)
        return self._fixos[system]

    def proporcao(self) -> float:
        """A proporção do texto com que o limite é calculado: a medida do item ou, antes da 1ª chamada dele, a típica."""
        return self.proporcao_do_item or PROPORCAO_TIPICA

    def _limite_da_entrada(self, system: str, extra: int = 0, saida: int | None = None) -> int:
        """Quantos caracteres a mensagem do usuário pode ter numa chamada com este prompt de sistema.

        No Ollama é a janela (num_ctx) menos a reserva de saída, uma margem e a parte fixa da chamada (o prompt de
        sistema e o template, em tokens exatos: ver `_fixos_de`), convertida para caracteres por 90% da proporção do
        texto do item (`proporcao`; decisão de 29/10/2026). A proporção vale por item: os textos de um item nunca
        mudam o limite de outro. A reserva é o menor entre OLLAMA_NUM_PREDICT e LLM_RESERVA_SAIDA, porque num_predict
        pode ser maior que a própria janela; a chamada que limita a própria saída (`saida`, em tokens) reserva só
        isso. No caminho OpenAI vale LLM_MAX_PROMPT_CHARS. `extra` é o que mais vai na mensagem além da entrada (na
        revisão: os problemas e o episódio original).
        """
        if settings.llm_provider != "ollama":
            return settings.llm_max_prompt_chars - extra
        reserva = min(settings.ollama_num_predict, settings.llm_reserva_saida) if saida is None else saida
        tokens = settings.ollama_num_ctx - reserva - MARGEM_TOKENS - self._fixos_de(system)
        return int(tokens * self.proporcao() * FOLGA_DA_MEDIDA) - extra

    def _medir(self, system: str, user: str, tokens: int | None) -> None:
        """Mede a proporção do texto numa chamada do item: os caracteres da mensagem do usuário pelos tokens dela, sem a
        parte fixa. Vale a menor medida do item; a chamada sem contagem não muda nada."""
        if not tokens:
            return
        do_texto = tokens - self._fixos_de(system)
        if do_texto <= 0 or not user:
            return
        medida = len(user) / do_texto
        self.proporcao_do_item = medida if self.proporcao_do_item is None else min(self.proporcao_do_item, medida)
        self.menor_proporcao = medida if self.menor_proporcao is None else min(self.menor_proporcao, medida)

    def _chamar(self, system: str, user: str, **opcoes) -> dict:
        """Chama o provider e aproveita os tokens que ele contou para medir a proporção do texto do item.

        O pedido que passa da janela volta com erro (`JanelaExcedida`, com a contagem do servidor): a chamada não é
        cortada, a medida fica com o item e quem montou a mensagem a refaz (ver `_na_janela`).
        """
        self._fixos_de(system)   # contada antes da 1ª chamada com este prompt: o prefixo dela nunca está em cache
        try:
            result = self.provider.chat_json(system, user, **opcoes)
        except JanelaExcedida as e:
            antes = self.proporcao()
            if e.tokens:
                self._medir(system, user, e.tokens)
            else:   # o erro não disse quantos tokens: a menor proporção da execução, ou PROPORCAO_SEM_MEDIDA
                self.proporcao_do_item = min(antes, self.menor_proporcao or PROPORCAO_SEM_MEDIDA)
            if self.proporcao() >= antes:   # a nova tentativa sairia igual: encolhe de qualquer jeito
                self.proporcao_do_item = antes * 0.8
            raise
        self._medir(system, user, (getattr(self.provider, "ultimo_uso", None) or {}).get("prompt", 0))
        return result

    def _na_janela(self, fazer, o_que: str):
        """Faz uma etapa que monta a mensagem pelo limite e chama o modelo. Se a chamada passa da janela, a etapa é
        refeita uma vez, com o limite da proporção que o erro mediu; um segundo erro de janela sobe."""
        try:
            return fazer()
        except JanelaExcedida as e:
            logger.warning("Janela: %s passou da janela (%s de %s tokens); refeita com a proporção %.2f do item.",
                           o_que, e.tokens if e.tokens is not None else "?", e.janela if e.janela is not None else "?", self.proporcao())
            return fazer()

    def _montar_entrada(self, principal: dict, relacionados: list[dict] | None = None) -> str:
        return montar_entrada(principal, relacionados, self._limite_da_entrada(PROMPT_SISTEMA)).texto

    def preparar(self, principal: dict, relacionados: list[dict] | None = None) -> tuple[Entrada, Analise]:
        """Roda a análise de lados da pauta e monta a entrada do episódio, já com o bloco de lados.

        A análise lê os textos inteiros, no espaço da chamada dela. A entrada do episódio leva de
        cada texto o recorte por relevância, com os parágrafos dos trechos de evidência. O lado
        fino e o orçamento de palavras (ver `ai/orcamento.py`) saem desse recorte: antes de contar,
        o bloco é reservado no tamanho maior que poderia ter, e a mesma reserva vale para a entrada
        final, que por isso leva o mesmo recorte. O orçamento fica em `Entrada.orcamento`.
        """
        self.proporcao_do_item = None   # a 1ª chamada do item começa da proporção típica
        completos = textos_da_pauta(principal, relacionados)
        logger.info(
            "Resumindo: %r (fonte: %s, %d caracteres de texto, %d relacionado(s))",
            str(principal["title"])[:80], principal["source"],
            len(principal["text"]), len(completos) - 1,
        )
        analise = self._na_janela(
            lambda: analisar_lados(self._chamar, completos, self._limite_da_entrada(PROMPT_LADOS, saida=MAX_SAIDA_LADOS)),
            "a análise de lados",
        )
        return self._montar_geracao(principal, relacionados, analise), analise

    def _montar_geracao(self, principal: dict, relacionados: list[dict] | None, analise: Analise) -> Entrada:
        """A entrada da geração, no limite de agora: o recorte de cada texto, o lado fino e o orçamento de palavras."""
        limite = self._limite_da_entrada(PROMPT_SISTEMA)
        reserva = reserva_do_bloco(analise.lados, analise.questao, analise.ressalvas)
        previa = montar_entrada(principal, relacionados, limite, analise.lados, analise.questao, analise.ressalvas, reserva=reserva)
        analise.lados = com_mencoes(analise.lados, previa.textos)
        orc = orcamento(analise.lados, palavras(previa.textos))
        return montar_entrada(principal, relacionados, limite, analise.lados, analise.questao, analise.ressalvas,
                              reserva=reserva, orc=orc)

    def _corrigir_titulo(self, analise: Analise, result: dict, reprovados: list[dict]) -> dict:
        """Reescreve só o título, a partir do resumo: a chamada leva os atores dos lados e não leva os textos.

        `reprovados` são os títulos que o QA já recusou neste episódio, cada um com os seus motivos.
        """
        atores = [ator for lado in analise.lados for ator in lado.atores]
        usuario = (
            "RESUMO:\n" + str(result[RESUMO])
            + "\n\nATORES: " + (", ".join(atores) or "nenhum ator nomeado")
            + "\n\nTÍTULOS JÁ REPROVADOS:\n"
            + "\n".join(f'- "{r["titulo"]}": {"; ".join(r["motivos"])}' for r in reprovados)
        )
        resposta = self._chamar(PROMPT_TITULO, usuario, chaves=(TITULO,), max_saida=MAX_SAIDA_TITULO)
        return {**result, TITULO: resposta[TITULO]}

    def _corrigir_resumo(self, entrada: Entrada, analise: Analise, result: dict, probs: list[str]) -> tuple[dict, Entrada]:
        """Reescreve só o resumo, com os mesmos recortes que foram para a geração e sem o episódio inteiro."""
        usuario = (
            FONTE_ANTES + entrada.artigos
            + "\n\nhouve_divergencia: " + ("true" if len(analise.lados) >= 2 else "false")
            + "\n\nPROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs)
            + "\n\nRESUMO ORIGINAL:\n" + str(result["resumo_didatico"])
        )
        resposta = self._chamar(PROMPT_RESUMO, usuario, chaves=(RESUMO,), max_saida=MAX_SAIDA_RESUMO)
        return {**result, RESUMO: resposta[RESUMO]}, entrada

    def _revisar_roteiro(self, principal: dict, relacionados: list[dict] | None, analise: Analise, result: dict,
                         probs: list[str], orc: Orcamento | None = None) -> tuple[dict, Entrada]:
        """Reescreve o roteiro: a chamada leva os textos, os lados, os personagens e o roteiro original.

        Os textos vão no recorte por relevância, refeito para o espaço desta chamada. Devolve o
        roteiro e os personagens; dos personagens só o papel pode mudar (ver `_com_os_papeis`).
        """
        depois = (
            "\n\nPERSONAGENS (os mesmos, com estes nomes):\n" + json.dumps(result["personagens"], ensure_ascii=False)
            + "\n\nPROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs)
            + "\n\nROTEIRO ORIGINAL:\n" + json.dumps(result[ROTEIRO], ensure_ascii=False)
        )
        def montar_e_chamar() -> tuple[dict, Entrada]:
            fonte = montar_entrada(
                principal, relacionados, self._limite_da_entrada(PROMPT_ROTEIRO, extra=len(FONTE_ANTES) + len(depois)),
                analise.lados, analise.questao, analise.ressalvas, lembrete=LEMBRETE_DO_ROTEIRO, orc=orc,
            )
            return self._chamar(PROMPT_ROTEIRO, FONTE_ANTES + fonte.texto + depois, chaves=(ROTEIRO,)), fonte

        resposta, fonte = self._na_janela(montar_e_chamar, "a revisão do roteiro")
        personagens = _com_os_papeis(result[ELENCO], resposta.get(ELENCO))
        return {**result, ELENCO: personagens, ROTEIRO: resposta[ROTEIRO]}, fonte

    def _revisar(self, principal: dict, relacionados: list[dict] | None, analise: Analise, result: dict,
                 probs: list[str], orc: Orcamento | None = None) -> tuple[dict, Entrada]:
        """A revisão completa: leva o artigo-fonte e o episódio original, e devolve o episódio inteiro.

        Sem o artigo-fonte, "expandir" o roteiro vira invenção de fatos. Como o episódio original
        vai junto, a fonte é remontada no espaço que sobra, com o recorte por relevância.
        """
        depois = (
            "\n\nPROBLEMAS DETECTADOS:\n- " + "\n- ".join(probs)
            + "\n\nEPISÓDIO ORIGINAL:\n" + json.dumps(result, ensure_ascii=False)
        )
        def montar_e_chamar() -> tuple[dict, Entrada]:
            fonte = montar_entrada(
                principal, relacionados, self._limite_da_entrada(PROMPT_REVISOR, extra=len(FONTE_ANTES) + len(depois)),
                analise.lados, analise.questao, analise.ressalvas, orc=orc,
            )
            return self._chamar(PROMPT_REVISOR, FONTE_ANTES + fonte.texto + depois), fonte

        return self._na_janela(montar_e_chamar, "a revisão")

    def process(self, principal: dict, relacionados: list[dict] | None = None) -> dict:
        """Devolve um episódio que passou no QA; do contrário levanta QAReprovado (item é pulado).

        O episódio reprovado ganha uma correção só, do tipo que os problemas pedem (ver
        `tipo_de_correcao`), e passa pelo QA de novo. A do título é a única que pode ser repetida:
        se o título novo ainda reprova, uma segunda chamada leva os dois títulos recusados.
        """
        entrada, analise = self.preparar(principal, relacionados)
        pauta = [f"{artigo['title']}\n{artigo['text']}" for artigo in (principal, *(relacionados or []))]
        diagnostico = self.ultimo_diagnostico = {
            "entrada": entrada, "lados": analise, "orcamento": entrada.orcamento, "episodio": None, "primeira_versao": None,
            "problemas": None, "correcao": None, "revisao": None, "problemas_da_revisao": None, "titulos_reprovados": [],
            "aviso_da_janela": "", "proporcao_do_item": self.proporcao_do_item,
        }
        logger.debug("Início da entrada enviada ao LLM: %r", entrada.texto[:600])

        def qa(episodio: dict) -> list[Problema]:
            return _qa(episodio, entrada.fontes, analise.lados, analise.ressalvas, pauta, entrada.orcamento)

        try:
            result = self._chamar(PROMPT_SISTEMA, entrada.texto)
        except JanelaExcedida as e:
            logger.warning("Janela: a geração passou da janela (%s de %s tokens); refeita com a proporção %.2f do item.",
                           e.tokens if e.tokens is not None else "?", e.janela if e.janela is not None else "?", self.proporcao())
            entrada = diagnostico["entrada"] = self._montar_geracao(principal, relacionados, analise)
            diagnostico["orcamento"] = entrada.orcamento
            result = self._chamar(PROMPT_SISTEMA, entrada.texto)
        diagnostico["aviso_da_janela"] = aviso_da_janela(entrada, relacionados)
        if diagnostico["aviso_da_janela"]:
            logger.warning("Janela: %s", diagnostico["aviso_da_janela"])
        diagnostico["proporcao_do_item"] = self.proporcao_do_item
        diagnostico["primeira_versao"] = diagnostico["episodio"] = result
        problemas = qa(result)
        probs = diagnostico["problemas"] = [p.texto for p in problemas]
        if not probs:
            return result

        tipo = diagnostico["correcao"] = tipo_de_correcao(problemas)
        logger.warning("QA reprovou a 1ª versão: %s — acionando %s", probs, CORRECOES[tipo])
        reprovados = diagnostico["titulos_reprovados"]
        try:
            if tipo == "titulo":
                reprovados.append({"titulo": str(result[TITULO]), "motivos": probs})
                corrigido, fonte = self._corrigir_titulo(analise, result, reprovados), None
            elif tipo == "resumo":
                corrigido, fonte = self._corrigir_resumo(entrada, analise, result, probs)
            elif tipo == "roteiro":
                corrigido, fonte = self._revisar_roteiro(principal, relacionados, analise, result, probs, entrada.orcamento)
            else:
                corrigido, fonte = self._revisar(principal, relacionados, analise, result, probs, entrada.orcamento)
        except JanelaExcedida:   # erro do item, não reprovação: não conta para o limite de tentativas
            raise
        except Exception as e:
            raise QAReprovado(
                f"{CORRECOES[tipo]} falhou ({type(e).__name__}: {str(e)[:200]}); "
                f"1ª versão reprovada: {probs}"
            ) from e
        diagnostico["revisao"], diagnostico["episodio"] = fonte, corrigido

        problemas2 = qa(corrigido)
        while tipo == "titulo" and problemas2 and len(reprovados) < TENTATIVAS_DO_TITULO and {p.campo for p in problemas2} == {TITULO}:
            reprovados.append({"titulo": str(corrigido[TITULO]), "motivos": [p.texto for p in problemas2]})
            logger.warning("Título corrigido ainda reprovado (%s): nova tentativa, com os títulos já recusados", reprovados[-1]["motivos"])
            try:
                corrigido = diagnostico["episodio"] = self._corrigir_titulo(analise, result, reprovados)
            except Exception as e:
                raise QAReprovado(
                    f"{CORRECOES[tipo]} falhou ({type(e).__name__}: {str(e)[:200]}); 1ª versão reprovada: {probs}"
                ) from e
            problemas2 = qa(corrigido)
        probs2 = diagnostico["problemas_da_revisao"] = [p.texto for p in problemas2]
        if not probs2:
            logger.info("%s aprovada pelo QA.", CORRECOES[tipo].capitalize())
            return corrigido

        raise QAReprovado(f"{CORRECOES[tipo]} ainda reprovada pelo QA: {probs2}")

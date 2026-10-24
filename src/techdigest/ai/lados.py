"""Análise de lados: a questão em disputa na pauta, quem responde a ela de cada lado, que veículo relata cada um
e as ressalvas de grupos sem nome.

Roda em toda pauta, inclusive nas de um veículo só, antes da geração e sobre os textos inteiros. O
número de lados define o elenco (um analista por lado) e o valor de houve_divergencia; quem confere
isso no episódio é `qa.problemas_dos_analistas`. Os trechos de evidência que ela devolve dizem
quais parágrafos de cada texto vão para a geração (ver `recorte.recortar`).
"""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace

from techdigest.ai.orcamento import Orcamento, orcamento
from techdigest.ai.prompt import PROMPT_LADOS
from techdigest.ai.qa import (
    QUANTIFICADORES, ator_citado, atores_exclusivos, frases, mesmo_ator, mesmo_veiculo, palavras_do_ator, termo_do_grupo,
    veiculos_distintos,
)
from techdigest.ai.recorte import cortar_em_paragrafo, literal, localizar_trecho, procurado
from techdigest.ai.verbos import verbos_de_decisao, verbos_de_posicao

logger = logging.getLogger("techdigest.ai.lados")

CHAVES_LADOS = ("lados",)
MAX_LADOS = 3
MAX_RESSALVAS = 2           # acima disso ficam as primeiras, com aviso no log
TEMPERATURA_LADOS = 0.1     # baixa, para a contagem dos lados variar pouco entre execuções
MAX_SAIDA_LADOS = 1200      # tokens: a resposta é um JSON curto, com um trecho literal por ator
MAX_BLOCO = 1600            # caracteres do bloco de lados na entrada do episódio, no máximo
MAX_POSICAO = 220           # caracteres da frase de cada lado no bloco
MIN_POSICAO = 60
MAX_QUESTAO = 160           # caracteres da questão no bloco
MAX_RESPOSTA = 60           # caracteres da resposta de cada lado no bloco
MAX_ANTERIOR = 2000         # caracteres da resposta recusada que voltam ao LLM na nova tentativa
MIN_TRECHO = 20             # caracteres: trecho de evidência menor que isto não comprova nada
MAX_MENCOES_DO_LADO_FINO = 1   # frases dos textos em que os atores de um lado fino aparecem, no máximo
# A posição do lado neutro: quando nenhum lado tem ator nomeado ou quando as duas tentativas da análise não valem.
POSICAO_DE_EMERGENCIA = "relato dos fatos, sem lados definidos"
# Termos que não fazem um ator, sem acento: coletivo sem nome ("economistas"), designação vaga sem
# qualificador ("o governo", "a empresa", "a campanha") e os quantificadores que os acompanham ("alguns analistas").
# É genérico o ator que só tem palavras daqui: "governo federal" e "campanha de Lula" valem.
# O ator genérico passa a grupo, e a posição que só grupos sustentam vira ressalva.
TERMOS_GENERICOS = frozenset({
    "economista", "economistas", "especialista", "especialistas", "analista", "analistas", "critico", "criticos",
    "observador", "observadores", "pesquisador", "pesquisadores", "estudioso", "estudiosos", "cientista", "cientistas",
    "jurista", "juristas", "tecnico", "tecnicos", "comentarista", "comentaristas", "autoridade", "autoridades",
    "fonte", "fontes", "opositor", "opositores", "adversario", "adversarios", "aliado", "aliados",
    "apoiador", "apoiadores", "parlamentar", "parlamentares", "politico", "politicos",
    "governo", "governos", "empresa", "empresas", "companhia", "companhias", "entidade", "entidades",
    "organizacao", "organizacoes", "instituicao", "instituicoes", "orgao", "orgaos",
    # instituições: só são grupo sem qualificador ("a campanha", não "a campanha de Lula")
    "ministerio", "ministerios", "campanha", "campanhas", "prefeitura", "prefeituras", "secretaria", "secretarias",
    "tribunal", "tribunais", "corte", "cortes", "partido", "partidos", "sindicato", "sindicatos", "coligacao",
    "coligacoes", "plataforma", "plataformas", "rede", "redes",
}) | QUANTIFICADORES
# Coletivos de pessoas, sem acento: o ator cuja palavra principal é um deles é grupo mesmo com qualificador
# ("comunidade de programação", "usuários do Reddit"), a não ser que ela venha com maiúscula, como nome
# próprio ("Comunidade Europeia"). Ver `ator_generico`.
COLETIVOS_DE_PESSOAS = frozenset({
    "comunidade", "comunidades", "especialista", "especialistas", "usuario", "usuarios", "critico", "criticos",
    "economista", "economistas", "analista", "analistas", "observador", "observadores", "pesquisador", "pesquisadores",
    "estudioso", "estudiosos", "cientista", "cientistas", "jurista", "juristas", "tecnico", "tecnicos", "comentarista",
    "comentaristas", "opositor", "opositores", "adversario", "adversarios", "aliado", "aliados", "apoiador", "apoiadores",
    "parlamentares", "politicos", "consumidor", "consumidores", "eleitor", "eleitores", "internauta", "internautas",
    "desenvolvedor", "desenvolvedores", "programador", "programadores", "morador", "moradores", "fa", "fas", "jogador",
    "jogadores", "leitor", "leitores", "cidadaos", "trabalhadores", "servidores", "profissionais", "investidores",
    "empresarios", "militantes", "ativistas", "autoridades", "fontes", "membros", "integrantes", "ministros", "setores",
})
# Marcadores de que a frase atribui o que diz a alguém já nomeado, sem verbo de posição (sem acento).
_MARCADOR_DE_ATRIBUICAO = re.compile(
    r"\b(?:segundo (?:ele|ela|eles|elas)|de acordo com (?:ele|ela|eles|elas)|na (?:avaliacao|visao|opiniao) (?:dele|dela|deles|delas))\b"
)
# O que a nova tentativa lembra ao LLM, depois do erro da primeira.
LEMBRETE_DA_CORRECAO = (
    "Responda de novo, com o JSON completo. Uma questão só; cada lado é uma resposta diferente a ela; agrupe os "
    "atores pela resposta que dão à questão, nunca um lado por ator; sem disputa, a questão fica vazia e há um lado só; "
    'coletivo sem nome vai em "grupos", nunca em "atores"; com questão, "respostas_por_ator" traz a resposta de cada '
    "ator e um trecho copiado ao pé da letra do texto; a ressalva traz o grupo e o trecho dela."
)
# O que a nova tentativa pede quando um ator está num lado e não tem entrada em "respostas_por_ator", ou tem uma
# cujo trecho não está no texto ou não traz a resposta dele.
LEMBRETE_DAS_RESPOSTAS = (
    "Responda de novo, com o JSON completo, e traga a entrada de cada um desses atores: a resposta dele à questão e, "
    "copiada ao pé da letra do texto de um veículo, a frase em que o texto traz essa resposta (o que ele afirma, "
    "decide ou declara). Ator cuja resposta o texto não traz sai do lado. Não mude o resto da resposta."
)


@dataclass(frozen=True)
class Lado:
    """Uma resposta à questão da pauta ou, sem disputa, o fato central da história.

    Só conta como lado a posição que tem ator nomeado. No lado neutro, `posicao` é
    POSICAO_DE_EMERGENCIA e `atores` vem vazio.
    """
    posicao: str
    atores: tuple[str, ...]
    veiculos: tuple[str, ...]   # com a grafia da pauta
    resposta: str = ""          # a resposta do lado à questão; vazia quando a pauta tem um lado só
    trechos: tuple[str, ...] = ()   # os trechos dos textos que comprovam a resposta dos atores (só com questão)
    mencoes: int | None = None      # em quantas frases dos textos da geração os atores aparecem (None = não contado)

    @property
    def fino(self) -> bool:
        """Lado cujos atores aparecem em no máximo uma frase dos textos: há pouco material para sustentá-lo."""
        return self.mencoes is not None and self.mencoes <= MAX_MENCOES_DO_LADO_FINO


@dataclass(frozen=True)
class Evidencia:
    """A resposta de um ator à questão e o trecho que a comprova, como o LLM os listou."""
    ator: str
    resposta: str
    trecho: str                 # o trecho que vale: o do LLM ou, se ele era quase literal, o do veículo
    veiculo: str
    comprovada: bool            # o trecho está no texto inteiro desse veículo, ao pé da letra ou quase
    trecho_do_llm: str = ""     # o que o LLM escreveu, quando difere do texto e foi aceito como quase literal
    diferencas: int = 0         # quantas palavras o trecho do LLM difere do texto do veículo
    prova: str = ""             # o que mostra que o trecho traz a resposta do ator (ver `traz_a_resposta`); vazio se nada mostra

    @property
    def vale(self) -> bool:
        """O trecho está no texto e traz a resposta do ator: só assim a entrada põe o ator num lado."""
        return self.comprovada and bool(self.prova)


@dataclass(frozen=True)
class Recusado:
    """Um ator que está num lado e tem entrada em "respostas_por_ator", mas nenhum trecho que valha."""
    ator: str
    trecho: str
    motivo: str


@dataclass(frozen=True)
class Ressalva:
    """Uma posição que só um grupo sem nome sustenta ("economistas alertam que...").

    Não é lado e não ganha analista: entra no episódio como pergunta atribuída da Helena.
    """
    grupos: tuple[str, ...]
    posicao: str
    veiculos: tuple[str, ...]   # com a grafia da pauta
    trecho: str = ""            # o trecho de um texto desses veículos que traz a posição do grupo, como está no veículo


@dataclass
class Analise:
    """Os lados e as ressalvas que valem para a pauta e o que o LLM respondeu."""
    lados: list[Lado]
    questao: str = ""                                    # a pergunta em disputa; só fica com 2 lados ou mais
    motivo: str = ""
    ressalvas: list[Ressalva] = field(default_factory=list)
    respostas: list[Evidencia] = field(default_factory=list)   # a resposta e o trecho de cada ator (só com questão)
    problemas: list[str] = field(default_factory=list)   # por que a resposta não valeu (e a pauta ficou com o lado neutro)
    ajustes: list[str] = field(default_factory=list)     # o que o código mudou na resposta (ator que passou a grupo...)
    descartadas: list[tuple[Ressalva, str]] = field(default_factory=list)   # as ressalvas que não entram no episódio, com o motivo
    faltam: list[str] = field(default_factory=list)      # atores que estão num lado e não têm entrada em respostas_por_ator
    recusados: list[Recusado] = field(default_factory=list)   # atores que estão num lado e cujo trecho não vale
    cortes: list[dict] = field(default_factory=list)     # se os textos não couberam inteiros na chamada: fonte, texto e lido
    resposta: dict | None = None
    primeira: "Analise | None" = None                    # a primeira tentativa, quando houve outra e a outra ficou valendo
    segunda: "Analise | None" = None                     # a segunda tentativa, quando ela não valeu e a primeira ficou


def entrada_dos_lados(textos) -> str:
    """O que o LLM recebe: cada texto com veículo e título. `textos` são dicts com fonte, titulo e texto."""
    partes = [
        f"TEXTO {i}\nVeículo: {t['fonte']}\nTítulo: {t['titulo']}\nTexto:\n{t['texto']}" for i, t in enumerate(textos, 1)
    ]
    partes.append(f"VEÍCULOS DA PAUTA: {', '.join(veiculos_distintos(t['fonte'] for t in textos))}")
    return "\n\n".join(partes)


def textos_que_cabem(textos, limite: int | None) -> tuple[list[dict], list[dict]]:
    """Os textos como a análise vai lê-los: inteiros, a não ser que a entrada passe de `limite` caracteres.

    Quando passa, cada texto perde na proporção do seu tamanho, com o corte em fim de parágrafo. O
    segundo valor diz o que foi cortado (fonte, caracteres do texto e quantos foram lidos), e vem
    vazio quando nada foi.
    """
    if limite is None or len(entrada_dos_lados(textos)) <= limite:
        return list(textos), []
    fixos = len(entrada_dos_lados([{**t, "texto": ""} for t in textos]))
    total = sum(len(t["texto"]) for t in textos)
    lidos = [{**t, "texto": cortar_em_paragrafo(t["texto"], len(t["texto"]) * max(limite - fixos, 0) // total)} for t in textos]
    return lidos, [{"fonte": t["fonte"], "texto": len(t["texto"]), "lido": len(lido["texto"])} for t, lido in zip(textos, lidos)]


def _sem_repetir(itens) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in itens if item.strip()))


def _linha(texto) -> str:
    """O texto numa linha só, sem espaços repetidos; o que não é texto vira vazio."""
    return " ".join(texto.split()) if isinstance(texto, str) else ""


def _mesma_resposta(a: str, b: str) -> bool:
    """Se duas respostas à questão são a mesma, sem contar caixa, acento nem pontuação."""
    def palavras(texto):
        sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        return re.findall(r"\w+", sem_acentos.lower())
    return palavras(a) == palavras(b)


def ator_generico(nome) -> bool:
    """Se o nome não chega a ser um ator.

    Não chega quando só tem termos de TERMOS_GENERICOS (sem contar artigo nem partícula), ou quando
    a palavra principal (a primeira que não é artigo, partícula nem quantificador) é um coletivo de
    pessoas (COLETIVOS_DE_PESSOAS) escrito em minúscula: "comunidade de programação" é grupo, mesmo
    com o qualificador, e "Comunidade Europeia" é ator.
    """
    principal = next((p for p in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFC", str(nome)))
                      if termo_do_grupo(p)), "")
    if termo_do_grupo(principal) in COLETIVOS_DE_PESSOAS and not principal[:1].isupper():
        return True
    return palavras_do_ator(nome) <= TERMOS_GENERICOS


def _lista_de_nomes(valor) -> bool:
    return valor is None or (isinstance(valor, list) and all(isinstance(item, str) for item in valor))


def _problemas_dos_campos(lados: list, da_pauta: list[str]) -> list[str]:
    probs = []
    for i, lado in enumerate(lados, 1):
        if not isinstance(lado, dict):
            probs.append(f"lado {i} não é um objeto")
            continue
        posicao, citados = lado.get("posicao"), lado.get("veiculos")
        if not (isinstance(posicao, str) and posicao.strip()):
            probs.append(f"lado {i} sem posição")
        probs += [
            f'lado {i} com "{campo}" fora do formato (é uma lista de nomes)'
            for campo in ("atores", "grupos") if not _lista_de_nomes(lado.get(campo))
        ]
        if not (isinstance(citados, list) and citados and all(isinstance(v, str) for v in citados)):
            probs.append(f"lado {i} sem veículo")
        elif fora := [v for v in citados if not any(mesmo_veiculo(v, p) for p in da_pauta)]:
            probs.append(f"lado {i} com veículo fora da pauta ({', '.join(fora)})")
    return probs


@dataclass
class _Rascunho:
    """Um lado da resposta enquanto é conferido: os atores ainda podem sair ou mudar de lado."""
    numero: int
    posicao: str
    atores: list[str]           # só os nomeados
    grupos: tuple[str, ...]
    veiculos: tuple[str, ...]
    resposta: str
    trecho: str = ""            # o trecho da ressalva (lado que veio só com grupos)
    veio_com_ator: bool = False   # tinha ator nomeado na resposta: se perder todos, é descartado e não vira ressalva
    trechos: list[str] = field(default_factory=list)


def _rascunhos(lados: list[dict], da_pauta: list[str]) -> tuple[list[_Rascunho], list[str]]:
    """Os lados de uma resposta já conferida, com o ator genérico passado de "atores" para "grupos"."""
    rascunhos, ajustes = [], []
    for i, lado in enumerate(lados, 1):
        atores = _sem_repetir(lado.get("atores") or [])
        genericos = tuple(a for a in atores if ator_generico(a))
        if genericos:
            ajustes.append(f"ator genérico do lado {i} passou a grupo ({', '.join(genericos)})")
        nomeados = [a for a in atores if a not in genericos]
        rascunhos.append(_Rascunho(
            numero=i, posicao=_linha(lado["posicao"]), atores=nomeados,
            grupos=tuple(g for g in _sem_repetir([*(lado.get("grupos") or []), *genericos]) if termo_do_grupo(g)),
            veiculos=tuple(v for v in da_pauta if any(mesmo_veiculo(v, citado) for citado in lado["veiculos"])),
            resposta=_linha(lado.get("resposta")), trecho=_linha(lado.get("trecho")), veio_com_ator=bool(nomeados),
        ))
    return rascunhos, ajustes


def _no_texto(trecho: str, textos, veiculos) -> tuple[str, int] | None:
    """Onde o trecho está, no título ou no texto inteiro de um dos veículos: o trecho que vale e as diferenças.

    Vale o trecho de pelo menos MIN_TRECHO caracteres, ao pé da letra (espaços, aspas e maiúsculas
    não contam, nem as reticências e as aspas em volta) ou quase (ver `recorte.localizar_trecho`):
    a cópia literal em qualquer texto vem antes da quase literal. Achado quase literal, vale o
    trecho como está no veículo. None se não está em nenhum texto desses veículos.
    """
    alvo = procurado(trecho)
    if len(alvo) < MIN_TRECHO:
        return None
    dos_veiculos = [f"{t['titulo']}\n{t['texto']}" for t in textos if any(mesmo_veiculo(t["fonte"], v) for v in veiculos)]
    if any(alvo in literal(texto) for texto in dos_veiculos):
        return trecho, 0
    return next(filter(None, (localizar_trecho(trecho, texto) for texto in dos_veiculos)), None)


def _linhas_do_veiculo(textos, veiculo: str) -> list[str]:
    """O título e os parágrafos dos textos desse veículo, na ordem."""
    return [linha for t in textos if mesmo_veiculo(t["fonte"], veiculo) for linha in (t["titulo"], *t["texto"].splitlines())]


def frase_do_trecho(trecho: str, textos, veiculo: str) -> str:
    """A frase (ou as frases) do texto do veículo em que o trecho está, pela comparação de `recorte.literal`.

    Vazio se o trecho não está, ao pé da letra, num parágrafo do título ou do texto desse veículo.
    """
    alvo = procurado(trecho)
    for linha in _linhas_do_veiculo(textos, veiculo) if alvo else ():
        paragrafo = literal(linha)
        inicio = paragrafo.find(alvo)
        if inicio < 0:
            continue
        fim, pos, envolvem = inicio + len(alvo), 0, []
        for frase in frases(paragrafo):
            i = paragrafo.find(frase, pos)
            if i < 0:
                continue
            pos = i + len(frase)
            if i < fim and pos > inicio:
                envolvem.append(frase)
        return " ".join(envolvem) or paragrafo
    return ""


def _citacao_direta(trecho: str, textos, veiculo: str) -> bool:
    """Se o trecho está dentro de uma citação no texto do veículo: entre aspas ou numa fala marcada com travessão.

    As aspas curvas abertas num parágrafo e não fechadas continuam abertas no seguinte, como se
    escreve uma citação longa. Quem disse a citação não é conferido.
    """
    alvo, aberta = procurado(trecho), False
    for linha in _linhas_do_veiculo(textos, veiculo) if alvo else ():
        plano = literal(linha)
        # as aspas como estão no texto, para separar a curva de abrir da de fechar (o resto é como em `literal`)
        curvo = " ".join(re.sub("[„‟«]", "“", re.sub("»", "”", unicodedata.normalize("NFC", linha))).split()).casefold()
        i = plano.find(alvo)
        if i >= 0:
            antes = curvo[:i]
            curvas, retas = aberta, 0
            for c in antes:
                if c in "“”":
                    curvas = c == "“"
                retas += c == '"'
            travessao = plano.lstrip().startswith(("—", "–", "- ")) or antes.rstrip().endswith(("—", "–")) or alvo.startswith(("—", "–"))
            return curvas or retas % 2 == 1 or travessao
        for c in curvo:
            if c in "“”":
                aberta = c == "“"
    return False


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)).lower()


def traz_a_resposta(ator: str, trecho: str, textos, veiculo: str) -> str:
    """O que mostra que o trecho traz a resposta do ator à questão, e não só o descreve; vazio se nada mostra.

    Vale, nesta ordem: um verbo de posição (`verbos.py`) no trecho; ou na frase do texto em que o
    trecho está; o trecho ser citação direta; a frase nomear o ator e ter um verbo de decisão
    (quem decide responde a favor da decisão); ou um marcador de atribuição na frase ("segundo
    ele", "na avaliação dela"). O trecho que descreve a conduta do ator ("admitido falhas técnicas")
    não traz a resposta dele. A conferência não vê de quem é o verbo da frase nem quem disse a
    citação: o verbo de outro ator na mesma frase também vale.
    """
    if verbos := verbos_de_posicao(trecho):
        return f"verbo de posição no trecho ({verbos[0]})"
    frase = frase_do_trecho(trecho, textos, veiculo)
    if verbos := verbos_de_posicao(frase):
        return f"verbo de posição na frase ({verbos[0]})"
    if _citacao_direta(trecho, textos, veiculo):
        return "citação direta"
    if ator_citado(ator, frase) and (verbos := verbos_de_decisao(frase)):
        return f"verbo de decisão de quem decidiu ({verbos[0]})"
    if marcador := _MARCADOR_DE_ATRIBUICAO.search(_sem_acento(frase)):
        return f"marcador de atribuição ({marcador.group()})"
    return ""


def _evidencias(entradas: list, textos) -> list[Evidencia]:
    """As respostas por ator da resposta do LLM, cada uma com o resultado da conferência do trecho.

    O trecho tem de estar no texto do veículo (ver `_no_texto`) e trazer a resposta do ator (ver
    `traz_a_resposta`). `textos` são os textos inteiros da pauta, mesmo quando a chamada leu um corte deles.
    """
    evidencias = []
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        ator, resposta, trecho, veiculo = (_linha(entrada.get(chave)) for chave in ("ator", "resposta", "trecho", "veiculo"))
        if not ator:
            continue
        achado = _no_texto(trecho, textos, [veiculo] if veiculo else [])
        if achado is None:
            evidencias.append(Evidencia(ator, resposta, trecho, veiculo, False))
            continue
        prova = traz_a_resposta(ator, achado[0], textos, veiculo)
        if achado[0] != trecho:   # achado palavra por palavra: vale o trecho como está no veículo
            evidencias.append(Evidencia(ator, resposta, achado[0], veiculo, True, trecho_do_llm=trecho, diferencas=achado[1], prova=prova))
        else:
            evidencias.append(Evidencia(ator, resposta, trecho, veiculo, True, prova=prova))
    return evidencias


def _responde(resposta_do_ator: str, resposta_do_lado: str) -> bool:
    """Se a resposta do ator é a do lado: iguais, ou uma começa com a outra ("Sim" e "Sim, é desinformação")."""
    def palavras(texto):
        sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        return re.findall(r"\w+", sem_acentos.lower())
    a, b = sorted((palavras(resposta_do_ator), palavras(resposta_do_lado)), key=len)
    return bool(a) and b[:len(a)] == a


def _conferir_atores(rascunhos: list[_Rascunho], evidencias: list[Evidencia]) -> tuple[list[str], list[str], list[Recusado]]:
    """Deixa em cada lado só os atores cuja resposta, comprovada por um trecho, é a do lado.

    Um ator pode ter mais de uma entrada, uma por trecho. O ator sem resposta listada sai, e o
    ator sem trecho que valha (que esteja no texto e traga a resposta dele, ver `Evidencia.vale`)
    também. O ator que está num lado de resposta diferente da dele vai para o lado da resposta
    dele, se existir, ou sai. Cada lado fica com os trechos que valem dos atores que ficaram nele.
    Devolve o que mudou, os atores que saíram por não terem entrada na lista e os que saíram
    porque nenhum trecho deles valeu, com o trecho e o motivo.
    """
    def evidencias_de(ator: str) -> list[Evidencia]:
        iguais = [e for e in evidencias if palavras_do_ator(e.ator) == palavras_do_ator(ator)]
        return iguais or [e for e in evidencias if mesmo_ator(e.ator, ator)]

    ajustes, faltam, recusados, ficam = [], [], [], {r.numero: [] for r in rascunhos}   # por lado: (ator, trechos)
    for r in rascunhos:
        for ator in r.atores:
            listadas = evidencias_de(ator)
            comprovadas = [e for e in listadas if e.vale]
            if not listadas:
                ajustes.append(f"ator do lado {r.numero} saiu: não está em respostas_por_ator ({ator})")
                faltam.append(ator)
                continue
            if not comprovadas:
                no_texto = next((e for e in listadas if e.comprovada), None)
                if no_texto is None:
                    motivo = f"o trecho não está no texto de {listadas[0].veiculo or 'nenhum veículo'}"
                else:
                    motivo = "o trecho não traz a resposta dele (sem verbo de posição, citação direta, decisão dele nem marcador de atribuição)"
                ajustes.append(f"ator do lado {r.numero} saiu: {motivo} ({ator})")
                recusados.append(Recusado(ator, (no_texto or listadas[0]).trecho, motivo))
                continue
            if any(_responde(e.resposta, r.resposta) for e in comprovadas):
                ficam[r.numero].append((ator, [e.trecho for e in comprovadas]))   # todo trecho comprovado dele conta para o lado
                continue
            dele = comprovadas[0].resposta
            destino = next((o for o in rascunhos if o is not r and _responde(dele, o.resposta)), None)
            if destino is None:
                ajustes.append(f"ator do lado {r.numero} saiu: nenhum lado tem a resposta dele ({ator}: {dele})")
                continue
            ficam[destino.numero].append((ator, [e.trecho for e in comprovadas]))
            ajustes.append(f"ator passou do lado {r.numero} para o lado {destino.numero}, o da resposta dele ({ator}: {dele})")
    for r in rascunhos:
        r.atores, r.trechos = [], []
        for ator, trechos in ficam[r.numero]:
            if not any(mesmo_ator(ator, outro) for outro in r.atores):
                r.atores.append(ator)
                for trecho in trechos:
                    if trecho not in r.trechos:
                        r.trechos.append(trecho)
    return ajustes, faltam, recusados


def _separar(rascunhos: list[_Rascunho], textos) -> tuple[dict[int, Lado], list[Ressalva], list[tuple[Ressalva, str]], list[str]]:
    """Separa os lados conferidos: os que têm ator nomeado, pelo número, as ressalvas e as ressalvas descartadas.

    No lado que tem ator nomeado, os grupos saem, porque concordam com ele. O lado que veio com
    ator nomeado e perdeu todos é descartado: nunca vira ressalva. O lado que veio só com grupos é
    uma ressalva. Se um grupo dela é ator de um lado (pela comparação de nomes de
    `qa.mesmo_ator`), ela sai, e o trecho dela, se estiver no texto, passa para esse lado, com os
    seus veículos. Nos outros casos a ressalva só fica se o trecho estiver num texto dos seus
    veículos (ver `_no_texto`), e vale o trecho como está no veículo; senão é descartada, com o
    motivo. O último valor diz o que foi mudado.
    """
    da_pauta = veiculos_distintos(t["fonte"] for t in textos)
    nomeados, ressalvas, descartadas, ajustes = {}, [], [], []
    for r in rascunhos:
        if r.atores:
            nomeados[r.numero] = Lado(r.posicao, tuple(r.atores), r.veiculos, r.resposta, tuple(r.trechos))
        elif r.veio_com_ator:
            ajustes.append(f"lado {r.numero} saiu: ficou sem ator nomeado")
    for r in rascunhos:
        if r.atores or r.veio_com_ator:
            continue
        achado = _no_texto(r.trecho, textos, r.veiculos)
        trecho = achado[0] if achado else r.trecho
        dono = next(((numero, grupo) for numero, lado in nomeados.items() for grupo in r.grupos
                     if any(mesmo_ator(grupo, ator) for ator in lado.atores)), None)
        if dono:
            numero, grupo = dono
            if achado:
                lado = nomeados[numero]
                nomeados[numero] = replace(
                    lado, trechos=lado.trechos + (() if trecho in lado.trechos else (trecho,)),
                    veiculos=tuple(v for v in da_pauta if v in lado.veiculos or v in r.veiculos),
                )
            ajustes.append(
                f"ressalva do lado {r.numero} saiu: o grupo dela é ator do lado {numero} ({grupo}); "
                + ("o trecho passou para esse lado" if achado else "o trecho não está no texto e não passou")
            )
        elif achado:
            if trecho != r.trecho:
                ajustes.append(f"trecho da ressalva do lado {r.numero} aceito como quase literal ({achado[1]} palavra(s) "
                               f"diferente(s)): vale o do veículo")
            ressalvas.append(Ressalva(r.grupos, r.posicao, r.veiculos, trecho))
        else:
            motivo = f"o trecho não está no texto de {', '.join(r.veiculos)}" if r.trecho else "sem trecho de evidência"
            descartadas.append((Ressalva(r.grupos, r.posicao, r.veiculos, r.trecho), motivo))
            ajustes.append(f"ressalva do lado {r.numero} saiu: {motivo} ({', '.join(r.grupos)})")
    return nomeados, ressalvas, descartadas, ajustes


def trechos_de_evidencia(lados, ressalvas=()) -> list[tuple[str, str]]:
    """Os trechos de evidência da pauta, cada um com o motivo que leva o parágrafo dele à geração.

    Vêm na ordem de prioridade: um trecho de cada lado e de cada ressalva por vez, para que nenhum
    lado fique sem o seu quando o espaço é curto.
    """
    filas = [[(f"trecho do lado {i}", trecho) for trecho in lado.trechos] for i, lado in enumerate(lados, 1)]
    filas += [[(f"trecho da ressalva {i}", ressalva.trecho)] for i, ressalva in enumerate(ressalvas, 1) if ressalva.trecho]
    return [fila[k] for k in range(max(map(len, filas), default=0)) for fila in filas if k < len(fila)]


def mencoes(atores, textos) -> int:
    """Em quantas frases dos textos (o título e as frases do texto de cada um) aparece algum dos atores.

    Conta o nome, pela regra de `qa.ator_citado`: "o ministro" não vale por "Waldez Góes". É a
    medida de quanto material as fontes trazem sobre quem sustenta um lado.
    """
    return sum(
        any(ator_citado(ator, frase) for ator in atores)
        for texto in textos for frase in (texto["titulo"], *frases(texto["texto"]))
    )


def com_mencoes(lados, textos) -> list[Lado]:
    """Os lados com a contagem das frases de `textos` em que os atores de cada um aparecem (ver `mencoes`).

    `textos` são os que a geração recebe: é neles que se vê se um lado é fino. O lado sem atores não é contado.
    """
    return [replace(lado, mencoes=mencoes(lado.atores, textos)) if lado.atores else lado for lado in lados]


def lados_finos(lados) -> list[bool]:
    """Para cada lado, se ele é fino. Só há lado fino em pauta de 2 lados ou mais."""
    return [len(lados) >= 2 and lado.fino for lado in lados]


def _problemas_das_respostas(ficam: dict[int, Lado]) -> list[str]:
    """Com questão, cada lado tem a sua resposta, diferente das dos outros."""
    probs = [f"lado {i} sem resposta à questão" for i, lado in ficam.items() if not lado.resposta]
    respondidos = [(i, lado.resposta) for i, lado in ficam.items() if lado.resposta]
    probs += [
        f"lados {i} e {j} com a mesma resposta à questão ({a})"
        for n, (i, a) in enumerate(respondidos) for j, b in respondidos[n + 1:] if _mesma_resposta(a, b)
    ]
    return probs


def lado_unico(veiculos) -> list[Lado]:
    """O lado neutro: um lado só, sem atores, com todos os veículos da pauta e a posição de emergência."""
    return [Lado(posicao=POSICAO_DE_EMERGENCIA, atores=(), veiculos=tuple(veiculos_distintos(veiculos)))]


def analise_da_resposta(resposta, textos) -> Analise:
    """A análise que vale para a pauta, a partir da resposta do LLM (função pura).

    `textos` são os textos inteiros da pauta (fonte, titulo e texto): é neles que os trechos de
    evidência são conferidos. Cada lado da resposta tem posição e pelo menos um veículo, todos da
    pauta (pela comparação tolerante de `qa.mesmo_veiculo`), e todo veículo da pauta está em algum
    lado da resposta. Só conta como lado o que tem ator nomeado: o ator genérico (`ator_generico`)
    passa a grupo, e a posição que só grupos sustentam é uma ressalva, que fica se o trecho dela
    estiver no texto (ver `_separar`). Ficam no máximo MAX_RESSALVAS ressalvas, as primeiras. O
    lado sem ator nem grupo não vale; se ele é o único da resposta, a pauta fica com o lado neutro.

    Com questão, a resposta traz também "respostas_por_ator": a resposta de cada ator e um trecho
    literal de um texto da pauta que a comprova. O ator sem trecho que valha (no texto e com a
    resposta dele, ver `traz_a_resposta`) sai e fica em `recusados`, e o ator que está num lado de
    resposta diferente da dele vai para o lado certo, ou sai (ver `_conferir_atores`); o que não
    tem entrada na lista fica em `faltam`. O lado que perde todos os atores nomeados é descartado.
    Sem questão, os atores ficam como vieram.

    Dos lados com ator nomeado, vale até 3, cada um com um ator que nenhum outro tem. A questão só
    fica com 2 lados ou mais, e aí cada lado tem a sua resposta, diferente das outras; com um lado
    só, a questão sai. Sem nenhum lado com ator nomeado, a pauta fica com o lado neutro e as
    ressalvas são descartadas. Os lados saem sem a contagem das menções (ver `com_mencoes`).

    Resposta que não cumpre isso vira o lado neutro, sem ressalvas, com o motivo em `problemas`.
    """
    da_pauta = veiculos_distintos(t["fonte"] for t in textos)

    def invalida(*probs: str) -> Analise:
        return Analise(lado_unico(da_pauta), problemas=list(probs), resposta=resposta)

    lados = resposta.get("lados") if isinstance(resposta, dict) else None
    if not isinstance(lados, list):
        return invalida("resposta sem a lista de lados")
    if not lados:
        return invalida(f"resposta com 0 lados (vale de 1 a {MAX_LADOS})")
    if probs := _problemas_dos_campos(lados, da_pauta):
        return invalida(*probs)
    questao = _linha(resposta.get("questao"))
    motivo = _linha(resposta.get("motivo"))
    rascunhos, ajustes = _rascunhos(lados, da_pauta)
    vazios = [r.numero for r in rascunhos if not r.atores and not r.grupos]
    if vazios and len(rascunhos) == 1:   # um lado só, sem ninguém que o sustente: é o relato dos fatos
        ajustes.append("lado único sem ator nem grupo: a pauta fica com o lado neutro")
        return Analise(lado_unico(da_pauta), motivo=motivo, ajustes=ajustes, resposta=resposta)
    if vazios:
        return invalida(*(f"lado {i} sem ator nem grupo (a ressalva tem de nomear o grupo que a sustenta)" for i in vazios))
    sem_lado = [v for v in da_pauta if not any(v in r.veiculos for r in rascunhos)]
    respostas, faltam, recusados = [], [], []
    if questao:
        entradas = resposta.get("respostas_por_ator")
        if not (isinstance(entradas, list) and entradas):
            return invalida('resposta com questão e sem "respostas_por_ator" (cada ator tem a sua resposta e um trecho literal)')
        respostas = _evidencias(entradas, textos)
        ajustes += [
            f"trecho de {e.ator} aceito como quase literal ({e.diferencas} palavra(s) diferente(s) do texto de {e.veiculo}): "
            f"vale o do veículo" for e in respostas if e.trecho_do_llm
        ]
        mudou, faltam, recusados = _conferir_atores(rascunhos, respostas)
        ajustes += mudou
    nomeados, ressalvas, descartadas, mudou = _separar(rascunhos, textos)
    ajustes += mudou
    if len(nomeados) > MAX_LADOS:
        return invalida(f"resposta com {len(nomeados)} lados (vale de 1 a {MAX_LADOS})")
    probs = []
    if len(nomeados) > 1:
        if not questao:
            return invalida(f"questão vazia com {len(nomeados)} lados (questão vazia exige exatamente 1 lado)")
        probs = _problemas_das_respostas(nomeados)
        probs += [
            f"lado {i} sem ator que não esteja em outro lado"
            for i, proprios in zip(nomeados, atores_exclusivos(list(nomeados.values()))) if not proprios
        ]
        validos = list(nomeados.values())
    else:   # sem disputa entre atores nomeados, a questão sai
        questao = ""
        validos = [replace(lado, resposta="") for lado in nomeados.values()]
    if sem_lado:
        probs.append(f"veículo da pauta em nenhum lado ({', '.join(sem_lado)})")
    if probs:
        return invalida(*probs)
    if not validos:   # sem lado com ator nomeado não há a quem a ressalva se oponha: fica só o relato dos fatos
        validos = lado_unico(da_pauta)
        descartadas += [(ressalva, "nenhum lado tem ator nomeado") for ressalva in ressalvas]
        ressalvas = []
        ajustes.append("nenhum lado com ator nomeado: a pauta fica com o lado neutro, sem ressalvas")
    elif len(ressalvas) > MAX_RESSALVAS:
        ajustes.append(f"{len(ressalvas) - MAX_RESSALVAS} ressalva(s) a mais: ficam as {MAX_RESSALVAS} primeiras")
        descartadas += [(ressalva, f"a pauta já tem {MAX_RESSALVAS} ressalvas") for ressalva in ressalvas[MAX_RESSALVAS:]]
        ressalvas = ressalvas[:MAX_RESSALVAS]
    return Analise(
        validos, questao, motivo, ressalvas=ressalvas, respostas=respostas, ajustes=ajustes,
        descartadas=descartadas, faltam=faltam, recusados=recusados, resposta=resposta,
    )


def _anterior(analise: Analise) -> list[str]:
    """A resposta anterior, como volta ao LLM na nova tentativa (cortada em MAX_ANTERIOR caracteres)."""
    if analise.resposta is None:
        return []
    return [f"Resposta anterior: {json.dumps(analise.resposta, ensure_ascii=False)[:MAX_ANTERIOR]}"]


def pedido_de_correcao(recusada: Analise) -> str:
    """O que a nova tentativa acrescenta à entrada: o erro da resposta recusada, a própria resposta e o lembrete."""
    return "\n".join([
        f"CORREÇÃO: a sua resposta anterior não valeu: {'; '.join(recusada.problemas)}.", *_anterior(recusada), LEMBRETE_DA_CORRECAO,
    ])


def pedido_das_respostas(incompleta: Analise) -> str:
    """O que a nova tentativa acrescenta à entrada quando um ator de um lado não tem entrada em "respostas_por_ator"
    ou tem uma cujo trecho não vale: cada ator recusado vai com o trecho e o motivo."""
    linhas = []
    if incompleta.faltam:
        linhas.append(f'CORREÇÃO: na sua resposta anterior, estes atores estão num lado e não têm entrada em '
                      f'"respostas_por_ator": {"; ".join(incompleta.faltam)}.')
    if incompleta.recusados:
        linhas.append(f"{'Além disso' if linhas else 'CORREÇÃO'}: na sua resposta anterior, o trecho destes atores não "
                      f"comprova a resposta deles:")
        linhas += [f'- {r.ator}: "{r.trecho}" ({r.motivo}).' for r in incompleta.recusados]
    return "\n".join([*linhas, *_anterior(incompleta), LEMBRETE_DAS_RESPOSTAS])


def _tentar(chamar, entrada: str, textos) -> Analise:
    try:
        resposta = chamar(
            PROMPT_LADOS, entrada, chaves=CHAVES_LADOS, temperatura=TEMPERATURA_LADOS, max_saida=MAX_SAIDA_LADOS,
        )
    except Exception as e:  # resposta vazia, cortada, sem a chave, servidor fora do ar...
        return Analise(lado_unico(t["fonte"] for t in textos), problemas=[f"a chamada falhou ({type(e).__name__}: {str(e)[:200]})"])
    return analise_da_resposta(resposta, textos)


def analisar_lados(chamar, textos, limite: int | None = None) -> Analise:
    """Pergunta ao LLM a questão e os lados da pauta.

    `textos` são os textos inteiros da pauta, e é neles que os trechos são conferidos. Eles só são
    cortados se a entrada passar de `limite` caracteres (o espaço da chamada), com aviso no log e o
    corte em `Analise.cortes`.

    Há no máximo uma nova tentativa. Chamada que falha ou resposta inválida ganham uma, com o erro
    anexado à entrada; se ela também não valer, a pauta segue com o lado único de emergência, com
    aviso no log. A resposta válida em que um ator está num lado sem entrada em
    "respostas_por_ator", ou com entrada cujo trecho não vale, também ganha uma, que pede a entrada
    de cada um, com o trecho recusado e o motivo: se a nova resposta valer, é ela que fica (e o
    ator que continuar sem entrada ou sem trecho que valha sai); se não valer, fica a primeira, sem o ator.
    `chamar(system, user, **opções)` é o chat_json do provider (ou o `_chamar` do Summarizer).
    """
    def entrada(pedido: str = "") -> tuple[str, list[dict]]:
        lidos, cortes = textos_que_cabem(textos, limite if limite is None or not pedido else limite - len(pedido) - 2)
        if cortes:
            logger.warning(
                "Análise de lados: os textos não cabem inteiros na chamada e foram cortados (%s).",
                "; ".join(f"{c['fonte']}: {c['lido']} de {c['texto']} caracteres" for c in cortes),
            )
        return entrada_dos_lados(lidos) + (f"\n\n{pedido}" if pedido else ""), cortes

    mensagem, cortes = entrada()
    analise = replace(_tentar(chamar, mensagem, textos), cortes=cortes)
    if analise.problemas:
        logger.warning("Análise de lados: a resposta não valeu (%s). Nova tentativa, com o erro anexado.", "; ".join(analise.problemas))
        mensagem, cortes = entrada(pedido_de_correcao(analise))
        analise = replace(_tentar(chamar, mensagem, textos), cortes=cortes, primeira=analise)
    elif analise.faltam or analise.recusados:
        if analise.faltam:
            logger.warning('Análise de lados: ator sem entrada em "respostas_por_ator" (%s). Nova tentativa, pedindo a entrada.',
                           "; ".join(analise.faltam))
        if analise.recusados:
            logger.warning("Análise de lados: ator com trecho que não vale (%s). Nova tentativa, pedindo o trecho.",
                           "; ".join(f"{r.ator}: {r.motivo}" for r in analise.recusados))
        mensagem, cortes = entrada(pedido_das_respostas(analise))
        nova = replace(_tentar(chamar, mensagem, textos), cortes=cortes)
        if nova.problemas:
            logger.warning("Análise de lados: a nova tentativa não valeu (%s). Fica a primeira resposta, sem o ator.",
                           "; ".join(nova.problemas))
            analise = replace(analise, segunda=nova)
        else:
            analise = replace(nova, primeira=analise)
    if analise.ajustes:
        logger.info("Análise de lados: ajustes na resposta (%s).", "; ".join(analise.ajustes))
    if analise.descartadas:
        logger.warning("Análise de lados: %d ressalva(s) descartada(s): %s.", len(analise.descartadas),
                       "; ".join(dict.fromkeys(motivo for _, motivo in analise.descartadas)))
    if analise.problemas:
        logger.warning(
            "Análise de lados inválida nas duas tentativas (%s): a pauta segue com um lado só, sem lados definidos.",
            "; ".join(analise.problemas),
        )
    else:
        logger.info(
            "Lados da pauta: %d (%s)%s%s", len(analise.lados),
            " × ".join(", ".join(lado.atores) or "sem atores" for lado in analise.lados),
            f" · questão: {analise.questao}" if analise.questao else "",
            f" · ressalvas: {'; '.join(', '.join(r.grupos) for r in analise.ressalvas)}" if analise.ressalvas else "",
        )
    return analise


def _encurtar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1].rsplit(None, 1)[0].rstrip(",;:") + "…"


def _frase(texto: str) -> str:
    return texto if texto.endswith((".", "!", "?", "…")) else texto + "."


def _alvo_do_elenco(orc: Orcamento) -> str:
    """O alvo de palavras de cada personagem e do total, os turnos e o tamanho das falas, como o bloco os diz.

    Cada alvo é um número só: o QA cobra uma fração dele, e a diferença fica como margem.
    """
    if len(orc.analistas) == 1:
        analistas = f"analista, {orc.analistas[0]}"
    else:
        analistas = "; ".join(f"analista do lado {i}, {alvo}" for i, alvo in enumerate(orc.analistas, 1))
    menor, maior = orc.por_fala
    falas = f"de {menor} a {maior}" if menor != maior else f"de uns {menor}"
    texto = (f" Alvo de palavras: Helena, {orc.helena}; {analistas}; total, {orc.total}. Roteiro de {orc.turnos} turnos, "
             f"com falas {falas} palavras.")
    if orc.reduzido:
        texto += " Os textos trazem pouco material, e o alvo já é menor: cumpra-o com o que as fontes trazem, sem argumento novo."
    return texto


def _linhas_do_bloco(lados, questao: str, ressalvas, finos: list[bool], teto: int, orc: Orcamento) -> list[str]:
    """As linhas do bloco: o cabeçalho (com a questão), uma por lado, uma por ressalva e o elenco, com o alvo de palavras.

    `finos` diz quais lados são finos, `teto`, quantos caracteres a frase de posição de cada um
    pode ter, e `orc`, o orçamento de palavras do episódio (ver `ai/orcamento.py`).
    """
    n = len(lados)
    if n > 1:
        elenco = (
            f'ELENCO: Helena e exatamente {n} analistas, um por lado; "houve_divergencia": true. Helena apresenta a '
            f"questão uma vez, na abertura, com palavras naturais, e não atribui as posições aos atores; cada analista "
            f"sustenta a posição do seu lado, numa frase que nomeia um ator do lado, cita um veículo do lado e usa um "
            f'verbo de posição, como em "segundo <veículo>, <ator> afirma que...".'
        )
    elif ressalvas:
        elenco = (
            "ELENCO: Helena e exatamente 1 analista, que explica a posição e responde às ressalvas com o que as fontes "
            'dizem, sem tomar partido; "houve_divergencia": false.'
        )
    else:
        elenco = 'ELENCO: Helena e exatamente 1 analista, que explica o tema com ela, sem advogar; "houve_divergencia": false.'
    if ressalvas:
        elenco += (
            " Ressalva não é lado nem ganha analista: Helena traz cada uma como pergunta atribuída, sem avaliá-la nem "
            "reformulá-la, numa frase com o veículo, o grupo e um verbo de posição, seguida de uma pergunta aberta, como "
            'em "Segundo <veículo>, <grupo> alertam que... Como você vê isso?".'
        )
    if any(finos):
        elenco += " Lado fino tem pouco material nas fontes: o analista dele não amplia além do que as fontes trazem."
    elenco += _alvo_do_elenco(orc)
    cabecalho = f"\nLADOS DA PAUTA: {n} lado{'s' if n > 1 else ''}."
    if questao:
        cabecalho += f"\nQUESTÃO: {_encurtar(questao, MAX_QUESTAO)}"

    def lado_descrito(i: int, lado: Lado) -> str:
        resposta = f" (resposta: {_encurtar(lado.resposta, MAX_RESPOSTA).rstrip('.')}" if lado.resposta else ""
        resposta += ("; lado fino)" if finos[i - 1] else ")") if resposta else (" (lado fino)" if finos[i - 1] else "")
        atores = f" Atores: {', '.join(lado.atores)}." if lado.atores else ""
        return f"Lado {i}{resposta}: {_frase(_encurtar(lado.posicao, teto))}{atores} Veículos: {', '.join(lado.veiculos)}."

    def ressalva_descrita(i: int, ressalva: Ressalva) -> str:
        grupos = f" Grupos: {', '.join(ressalva.grupos)}." if ressalva.grupos else ""
        return f"Ressalva {i}: {_frase(_encurtar(ressalva.posicao, teto))}{grupos} Veículos: {', '.join(ressalva.veiculos)}."

    return [
        cabecalho,
        *(lado_descrito(i, lado) for i, lado in enumerate(lados, 1)),
        *(ressalva_descrita(i, ressalva) for i, ressalva in enumerate(ressalvas, 1)),
        elenco,
    ]


def bloco_dos_lados(lados, questao: str = "", ressalvas=(), orc: Orcamento | None = None) -> str:
    """O bloco LADOS DA PAUTA da entrada do episódio: a questão, os lados, as ressalvas, o elenco exato e o alvo de palavras.

    O alvo vem de `orc`; sem ele, é o de antes para o tamanho do elenco (ver `orcamento.orcamento`).
    Nunca passa de MAX_BLOCO caracteres: se for preciso, as frases de posição encolhem. O orçamento
    da entrada reserva para ele o tamanho que ele tem (ver `reserva_do_bloco`).
    """
    finos = lados_finos(lados)
    orc = orc or orcamento(lados)
    teto = MAX_POSICAO
    linhas = _linhas_do_bloco(lados, questao, ressalvas, finos, teto, orc)
    while len("\n".join(linhas)) > MAX_BLOCO and teto > MIN_POSICAO:
        teto -= 20
        linhas = _linhas_do_bloco(lados, questao, ressalvas, finos, teto, orc)
    bloco = "\n".join(linhas)
    if len(bloco) > MAX_BLOCO:   # listas de atores longas demais: o que fica de fora é o fim da última linha
        logger.warning("Bloco de lados com %d caracteres: cortado em %d.", len(bloco), MAX_BLOCO)
        cabecalho, *descritos, elenco = linhas
        bloco = "\n".join([cabecalho, elenco, *descritos])[:MAX_BLOCO - 1] + "…"
    return bloco


def reserva_do_bloco(lados, questao: str = "", ressalvas=()) -> int:
    """Quantos caracteres guardar para o bloco antes de saber quais lados são finos e qual é o orçamento.

    O lado fino só é contado depois do recorte dos textos, e o orçamento de palavras vem das
    palavras do recorte, que depende do espaço que o bloco ocupa. Por isso a reserva é o tamanho do
    bloco com todos os lados finos (em pauta de 2 lados ou mais) e o orçamento com os números mais
    compridos e o aviso de pouco material, sem encolher as posições e até MAX_BLOCO: o bloco de
    verdade nunca passa disso.
    """
    todos = [len(lados) >= 2] * len(lados)
    maior = Orcamento(9990, (9990,) * max(len(lados), 1), 0, reduzido=True)
    return min(MAX_BLOCO, len("\n".join(_linhas_do_bloco(lados, questao, ressalvas, todos, MAX_POSICAO, maior))))

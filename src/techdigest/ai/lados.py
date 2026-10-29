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

from techdigest.ai.elenco import VAGAS, nomes_dos_analistas
from techdigest.ai.llm import JanelaExcedida
from techdigest.ai.orcamento import MAX_ALVO, Orcamento, orcamento
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
# A questão que não é de sim ou não: começa por pronome ou advérbio interrogativo ("Qual deve ser a prioridade...?").
# A questão em disputa é respondida de formas opostas; com qualquer número de lados, a questão aberta leva ao lado
# neutro: planos ou prioridades diferentes não são disputa, e um lado só com um dos atores desequilibraria a pauta.
_QUESTAO_ABERTA = re.compile(r"^\s*(?:qual|quais|como|quem|o que|por que|porque|onde|quando)\b", re.IGNORECASE)
# A contagem de menções aceita o sobrenome sozinho de quem é nome de pessoa (ver `sobrenome` e `mencoes`).
_PARTICULAS_DO_NOME = frozenset({"da", "de", "do", "das", "dos", "e", "van", "von", "der", "del", "di", "du"})
_PALAVRA = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
# Palavras com maiúscula que, antes de um sobrenome, não são o prenome de outra pessoa (sem acento, em minúsculas):
# as que começam frase e os cargos ("Segundo Góes", "Para Góes", "Ministro Góes").
_ANTES_DO_SOBRENOME = frozenset({
    "a", "o", "as", "os", "um", "uma", "e", "mas", "ja", "ainda", "tambem", "segundo", "conforme", "para", "por", "pelo",
    "pela", "com", "sem", "sobre", "entre", "contra", "ate", "desde", "apos", "antes", "depois", "durante", "quando", "se",
    "como", "em", "no", "na", "nos", "nas", "ao", "aos", "do", "da", "dos", "das", "de", "ontem", "hoje", "agora", "entao",
    "ele", "ela", "isso", "esse", "essa", "este", "esta", "so", "nem", "ou", "que", "porque", "embora", "enquanto",
    "presidente", "presidenta", "ministro", "ministra", "senador", "senadora", "deputado", "deputada", "governador",
    "governadora", "prefeito", "prefeita", "vereador", "vereadora", "candidato", "candidata", "juiz", "juiza",
    "desembargador", "desembargadora", "general", "coronel", "comandante", "secretario", "secretaria", "diretor",
    "diretora", "doutor", "doutora", "dr", "dra", "sr", "sra", "professor", "professora", "padre", "pastor", "papa",
    "dom", "ex", "governo", "gestao", "campanha", "familia",
})
# Palavras que fazem do nome uma organização, sem acento: o sobrenome sozinho só conta para nome de pessoa (ver `nome_de_pessoa`).
_PALAVRAS_DE_ORGANIZACAO = frozenset({
    "agencia", "banco", "justica", "sindicato", "coligacao", "associacao", "federacao", "confederacao", "instituto",
    "fundacao", "conselho", "comissao", "comite", "ministerio", "secretaria", "prefeitura", "tribunal", "corte", "partido",
    "governo", "camara", "assembleia", "senado", "congresso", "uniao", "universidade", "policia", "forca", "forcas", "corpo",
    "central", "rede", "frente", "movimento", "observatorio", "centro", "ordem", "igreja", "grupo", "empresa", "companhia",
    "organizacao", "instituicao", "orgao", "campanha", "plataforma",
})
# O artigo, ou a contração com artigo, logo antes do nome: "o Sindipetro Unificado", "segundo a Agência Brasil".
_ARTIGO_ANTES = re.compile(
    r"(?<![^\W\d_])(?:o|a|os|as|do|da|dos|das|no|na|nos|nas|pelo|pela|pelos|pelas|ao|aos|à|às|um|uma|num|numa)\s*$",
    re.IGNORECASE,
)
# As aspas da contagem de menções (ver `fora_das_aspas`): a reta simples não entra, porque também é apóstrofo.
_ABRE_DUPLAS, _FECHA_DUPLAS = "“«„", "”»"
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
# Numa disputa de dois lados, as respostas dos lados são "Sim" e "Não", opostas (decisão de 24/10/2026): o que a nova
# tentativa pede quando não são.
REGRA_DO_SIM_E_NAO = (
    'A resposta de cada lado é "Sim" ou "Não" à questão, e a de cada ator em "respostas_por_ator" é a do lado dele: '
    '"Sim" se o trecho dele afirma o que a questão pergunta, "Não" se o trecho dele nega. Se a questão não se responde '
    'com "Sim" ou "Não", reescreva-a como pergunta de sim ou não sobre o mesmo fato.'
)
LEMBRETE_DO_SIM_E_NAO = f"Responda de novo, com o JSON completo. {REGRA_DO_SIM_E_NAO} Não mude o resto da resposta."
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
    sem_sim_e_nao: str = ""                              # numa disputa de dois lados, por que as respostas não são "Sim" e "Não"
    contexto: list[str] = field(default_factory=list)   # veículos da pauta sem lado, que entram como contexto (2 lados ou mais)
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


def _partes(frase: str) -> list[str]:
    """A frase separada também no ponto e vírgula, que junta duas orações de atores diferentes num título."""
    return [parte for parte in re.split(r"(?<=;)\s+", frase) if parte]


def frase_do_trecho(trecho: str, textos, veiculo: str) -> str:
    """A frase (ou as frases) do texto do veículo em que o trecho está, pela comparação de `recorte.literal`.

    A frase é separada também no ponto e vírgula: no título "Cooperativa quer fechar a feira;
    associação defende a praça", o trecho da cooperativa fica com a parte dela, sem o verbo da associação.
    Vazio se o trecho não está, ao pé da letra, num parágrafo do título ou do texto desse veículo.
    """
    alvo = procurado(trecho)
    for linha in _linhas_do_veiculo(textos, veiculo) if alvo else ():
        paragrafo = literal(linha)
        inicio = paragrafo.find(alvo)
        if inicio < 0:
            continue
        fim, pos, envolvem = inicio + len(alvo), 0, []
        for frase in (parte for frase in frases(paragrafo) for parte in _partes(frase)):
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


def _conferir_atores(rascunhos: list[_Rascunho], evidencias: list[Evidencia],
                     exigir_resposta: bool = True) -> tuple[list[str], list[str], list[Recusado]]:
    """Deixa em cada lado só os atores cuja resposta, comprovada por um trecho, é a do lado.

    Um ator pode ter mais de uma entrada, uma por trecho. O ator sem resposta listada sai, e o
    ator sem trecho que valha também: o trecho tem de estar no texto e, com `exigir_resposta`,
    trazer a resposta dele (ver `Evidencia.vale`). Sem `exigir_resposta` (a resposta tem um lado
    só com ator nomeado, e não há disputa a inventar), basta o trecho estar no texto. O ator que
    está num lado de resposta diferente da dele vai para o lado da resposta dele, se existir, ou
    sai. Cada lado fica com os trechos que valem dos atores que ficaram nele. Devolve o que mudou,
    os atores que saíram por não terem entrada na lista e os que saíram porque nenhum trecho deles
    valeu, com o trecho e o motivo.
    """
    def evidencias_de(ator: str) -> list[Evidencia]:
        iguais = [e for e in evidencias if palavras_do_ator(e.ator) == palavras_do_ator(ator)]
        return iguais or [e for e in evidencias if mesmo_ator(e.ator, ator)]

    ajustes, faltam, recusados, ficam = [], [], [], {r.numero: [] for r in rascunhos}   # por lado: (ator, trechos)
    for r in rascunhos:
        for ator in r.atores:
            listadas = evidencias_de(ator)
            comprovadas = [e for e in listadas if (e.vale if exigir_resposta else e.comprovada)]
            if comprovadas and not exigir_resposta and not any(e.vale for e in comprovadas):
                ajustes.append(f"trecho de {ator} vale sem trazer a resposta: com um lado só com ator nomeado, não há "
                               f"disputa a conferir")
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


def sobrenome(ator) -> str:
    """O sobrenome de um ator que é nome de pessoa: a última palavra, quando todas as palavras do nome começam com
    maiúscula (fora as partículas) e a penúltima não é partícula; vazio nos outros casos.

    "Waldez Góes" dá "Góes"; "Lula", "campanha de Lula" e "Corpo de Bombeiros do Amazonas" não dão nada.
    """
    palavras = str(ator).split()
    if len(palavras) < 2 or palavras[-2].lower() in _PARTICULAS_DO_NOME:
        return ""
    if not all(p[:1].isupper() for p in palavras if p.lower() not in _PARTICULAS_DO_NOME):
        return ""
    ultimo = palavras[-1]
    return ultimo if len(ultimo) >= 3 and ultimo.isalpha() else ""


def _frases_dos_textos(textos) -> list[str]:
    return [frase for texto in textos for frase in (texto["titulo"], *frases(texto["texto"]))]


def fora_das_aspas(texto: str) -> str:
    """O texto com o que está entre aspas, e as próprias aspas, trocado por espaços: o mesmo tamanho, para as posições valerem.

    Contam as aspas duplas retas, as curvas duplas (“ ”, « », „) e as curvas simples (‘ ’). A reta dupla abre e fecha
    dentro do parágrafo. A curva dupla aberta e não fechada continua aberta no parágrafo seguinte quando ele abre com
    aspas, como se escreve uma citação longa (o "“" que abre o parágrafo continuado não é aspa nova); senão, fecha no fim
    do parágrafo. A curva simples só fecha se houver uma aberta: sem ela, o "’" é apóstrofo ("Sant’Ana").
    """
    linhas, saida, duplas = texto.split("\n"), [], 0
    for n, linha in enumerate(linhas):
        reta, simples, nova = False, 0, []
        recuo = len(linha) - len(linha.lstrip())
        continua = duplas > 0 and linha[recuo:recuo + 1] in _ABRE_DUPLAS
        for i, c in enumerate(linha):
            dentro = reta or duplas or simples
            if c == '"':
                reta = not reta
            elif c in _ABRE_DUPLAS:
                duplas += 0 if (continua and i == recuo) else 1
            elif c in _FECHA_DUPLAS:
                duplas = max(duplas - 1, 0)
            elif c == "‘":
                simples += 1
            elif c == "’" and simples:
                simples -= 1
            else:
                nova.append(" " if dentro and not c.isspace() else c)
                continue
            nova.append(" ")
        saida.append("".join(nova))
        if (linhas[n + 1].lstrip()[:1] if n + 1 < len(linhas) else "") not in _ABRE_DUPLAS:
            duplas = 0
    return "\n".join(saida)


def _frases_fora_das_aspas(textos) -> list[str]:
    """As frases de `_frases_dos_textos`, na mesma ordem, cada uma sem o que está entre aspas (ver `fora_das_aspas`).

    A frase que não se acha no texto (não deveria acontecer) fica como está.
    """
    saida = []
    for texto in textos:
        saida.append(fora_das_aspas(str(texto["titulo"])))
        original = str(texto["texto"])
        mascarado, pos = fora_das_aspas(original), 0
        for frase in frases(original):
            achado = re.compile(r"\s+".join(map(re.escape, frase.split()))).search(original, pos) if frase.split() else None
            if achado is None:
                saida.append(frase)
                continue
            saida.append(mascarado[achado.start():achado.end()])
            pos = achado.end()
    return saida


def nome_de_pessoa(ator, textos) -> bool:
    """Se o ator é nome de pessoa, para o sobrenome sozinho contar: o nome não tem palavra de organização
    (`_PALAVRAS_DE_ORGANIZACAO`: "Agência Brasil", "Justiça Global") e, nos textos, fora das aspas, vem mais vezes sem
    artigo antes do que com artigo ("o Sindipetro Unificado"; "o ministro Waldez Góes" não conta, porque o artigo vai com
    o cargo). Para o nome que não aparece inteiro nos textos, vale só a palavra de organização.
    """
    if any(_sem_acento(p) in _PALAVRAS_DE_ORGANIZACAO for p in _PALAVRA.findall(str(ator))):
        return False
    com = sem = 0
    padrao = re.compile(rf"(?<![^\W\d_]){re.escape(str(ator))}(?![^\W\d_])")
    for texto in textos:
        for parte in (texto["titulo"], texto["texto"]):
            fora = fora_das_aspas(str(parte))
            for achado in padrao.finditer(fora):
                if _ARTIGO_ANTES.search(fora[:achado.start()]):
                    com += 1
                else:
                    sem += 1
    return com < sem or com == sem == 0


def outro_com_o_sobrenome(ator, textos, alheios=()) -> str:
    """Quem mais tem o sobrenome do ator: um ator de outro lado ou uma pessoa citada nos textos; vazio se ninguém.

    A pessoa citada é o sobrenome logo depois de uma palavra com maiúscula, só com espaço ou partícula entre as
    duas, que não é do nome do ator nem começo de frase ou cargo (`_ANTES_DO_SOBRENOME`): "Jair Bolsonaro" para
    "Flávio Bolsonaro", "Lula da Silva" para "Bruno Silva". Volta "Jair Bolsonaro", "Lula Silva"... Em "Lula,
    Janones e Sidônio", a vírgula separa duas pessoas, e "Lula" não é prenome de Janones.
    """
    alvo = sobrenome(ator)
    if not alvo:
        return ""
    for outro in alheios:
        if not mesmo_ator(outro, ator) and alvo in str(outro).split():
            return str(outro)
    proprias = set(str(ator).split())
    particulas = "|".join(sorted(_PARTICULAS_DO_NOME))
    colado = re.compile(rf"(?<![^\W\d_])([^\W\d_]+(?:-[^\W\d_]+)*)\s+(?:(?:{particulas})\s+)*{re.escape(alvo)}(?![^\W\d_])")
    for frase in _frases_dos_textos(textos):
        for achado in colado.finditer(frase):
            antes = achado.group(1)
            if antes[:1].isupper() and antes not in proprias and _sem_acento(antes) not in _ANTES_DO_SOBRENOME:
                return f"{antes} {alvo}"
    return ""


def sobrenomes_que_contam(atores, textos, alheios=()) -> list[str]:
    """Os sobrenomes dos atores que contam sozinhos na contagem de menções: os de nome de pessoa (ver `nome_de_pessoa`)
    que ninguém mais tem (ver `outro_com_o_sobrenome`)."""
    return [sobrenome(ator) for ator in atores
            if sobrenome(ator) and nome_de_pessoa(ator, textos) and not outro_com_o_sobrenome(ator, textos, alheios)]


def mencoes(atores, textos, alheios=()) -> int:
    """Em quantas frases dos textos (o título e as frases do texto de cada um) aparece algum dos atores, fora das aspas.

    Conta o nome, pela regra de `qa.ator_citado`, e o sobrenome sozinho de quem é nome de pessoa ("Góes" por
    "Waldez Góes"; ver `nome_de_pessoa`), a não ser que outra pessoa citada nos textos ou um ator de outro lado
    (`alheios`) tenha o mesmo sobrenome (ver `outro_com_o_sobrenome`). O cargo não conta: "o ministro" não vale por
    "Waldez Góes". A menção que só aparece dentro de aspas também não conta (ver `fora_das_aspas`; decisão de
    24/10/2026): a fala de outro ator sobre ele ("“Seria prudente que o comandante...”, declarou" o ministro) e o nome
    citado como título (o canal “Exército de Lula”). A fala do próprio ator conta quando o texto o nomeia fora das
    aspas ("“...”, afirmou Lula"). É a medida de quanto material as fontes trazem sobre quem sustenta um lado. O
    sobrenome sozinho vale só aqui, e não na regra do QA.
    """
    padroes = [re.compile(rf"(?<![^\W\d_]){re.escape(s)}(?![^\W\d_])") for s in sobrenomes_que_contam(atores, textos, alheios)]
    return sum(
        any(ator_citado(ator, frase) for ator in atores) or any(p.search(frase) for p in padroes)
        for frase in _frases_fora_das_aspas(textos)
    )


def com_mencoes(lados, textos) -> list[Lado]:
    """Os lados com a contagem das frases de `textos` em que os atores de cada um aparecem (ver `mencoes`).

    `textos` são os que a geração recebe: é neles que se vê se um lado é fino. O lado sem atores não é contado.
    """
    return [
        replace(lado, mencoes=mencoes(lado.atores, textos, [a for outro in lados if outro is not lado for a in outro.atores]))
        if lado.atores else lado
        for lado in lados
    ]


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


def sim_e_nao(lados) -> bool:
    """Se as respostas dos lados são "Sim" e "Não", uma de cada (sem contar caixa, acento nem ponto final)."""
    return sorted(_sem_acento(lado.resposta).strip().rstrip(".!").strip() for lado in lados) == ["nao", "sim"]


def _veiculos_sem_lado(sem_lado: list[str], validos: list[Lado], textos, da_pauta: list[str]) -> tuple[list[Lado], list[str], list[str], list[str]]:
    """O veículo da pauta que a resposta não pôs em nenhum lado nem ressalva (decisão de 25/10/2026).

    Com um lado só, ele entra nesse lado, que é a pauta inteira; sem lado com ator nomeado, fica no lado neutro, que
    já tem todos os veículos. Com dois lados ou mais, o veículo cujo texto não cita ator de nenhum lado (ver
    `mencoes`) entra como contexto: fica na pauta, sem lado, e não invalida a análise; o que cita um ator continua
    invalidando, porque a resposta o deixou fora do lado desse ator. Devolve os lados, os veículos de contexto, os
    ajustes e os veículos que invalidam a resposta.
    """
    if not validos:
        return validos, [], [f"veículo da pauta em nenhum lado da resposta: fica no lado neutro ({', '.join(sem_lado)})"], []
    if len(validos) == 1:
        lado = validos[0]
        veiculos = tuple(v for v in da_pauta if v in lado.veiculos or v in sem_lado)
        return [replace(lado, veiculos=veiculos)], [], [f"veículo da pauta em nenhum lado da resposta: entra no lado único ({', '.join(sem_lado)})"], []
    atores = [a for lado in validos for a in lado.atores]
    contexto, invalidam = [], []
    for veiculo in sem_lado:
        dele = [t for t in textos if mesmo_veiculo(t["fonte"], veiculo)]
        (invalidam if mencoes(atores, dele) else contexto).append(veiculo)
    ajustes = [f"veículo da pauta em nenhum lado, sem ator de nenhum lado no texto: entra como contexto ({', '.join(contexto)})"] if contexto else []
    return validos, contexto, ajustes, invalidam


def lado_unico(veiculos) -> list[Lado]:
    """O lado neutro: um lado só, sem atores, com todos os veículos da pauta e a posição de emergência."""
    return [Lado(posicao=POSICAO_DE_EMERGENCIA, atores=(), veiculos=tuple(veiculos_distintos(veiculos)))]


def analise_da_resposta(resposta, textos) -> Analise:
    """A análise que vale para a pauta, a partir da resposta do LLM (função pura).

    `textos` são os textos inteiros da pauta (fonte, titulo e texto): é neles que os trechos de
    evidência são conferidos. Cada lado da resposta tem posição e pelo menos um veículo, todos da
    pauta (pela comparação tolerante de `qa.mesmo_veiculo`); o veículo da pauta que não está em
    nenhum lado da resposta entra no lado único ou como contexto (ver `_veiculos_sem_lado`). Só conta como lado o que tem ator nomeado: o ator genérico (`ator_generico`)
    passa a grupo, e a posição que só grupos sustentam é uma ressalva, que fica se o trecho dela
    estiver no texto (ver `_separar`). Ficam no máximo MAX_RESSALVAS ressalvas, as primeiras. O
    lado sem ator nem grupo não vale; se ele é o único da resposta, a pauta fica com o lado neutro.

    Com questão, a resposta traz também "respostas_por_ator": a resposta de cada ator e um trecho
    literal de um texto da pauta que a comprova. O ator sem trecho que valha sai e fica em
    `recusados`: o trecho tem de estar no texto e, quando a resposta tem dois lados ou mais com ator
    nomeado, trazer a resposta dele (ver `traz_a_resposta`). O ator que está num lado de resposta
    diferente da dele vai para o lado certo, ou sai (ver `_conferir_atores`); o que não tem entrada
    na lista fica em `faltam`. O lado que perde todos os atores nomeados é descartado. Sem questão,
    os atores ficam como vieram.

    A questão que não é de sim ou não (começa com "qual", "como", "quem"...) leva ao lado neutro, sem
    ressalvas, com qualquer número de lados: planos ou prioridades diferentes não são disputa, e um
    lado só com um dos atores, quando a conferência tira o outro, desequilibra a pauta. Dos lados com
    ator nomeado, vale até 3, cada um com um ator que nenhum outro tem. A questão só fica com 2 lados
    ou mais, e cada lado tem a sua resposta, diferente das outras; com um lado só, a questão sai. Sem
    nenhum lado com ator nomeado, a pauta fica com o lado neutro e as ressalvas são descartadas. Os
    lados saem sem a contagem das menções (ver `com_mencoes`).

    Resposta que não cumpre isso vira o lado neutro, sem ressalvas, com o motivo em `problemas`. Numa
    disputa de dois lados, as respostas dos lados são "Sim" e "Não" (ver `sim_e_nao`); quando não são,
    a análise vale, com o motivo em `sem_sim_e_nao`, e quem decide a nova tentativa é `analisar_lados`.
    Com três lados, basta que as respostas sejam diferentes.
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
    if questao and _QUESTAO_ABERTA.search(questao):   # com qualquer número de lados: planos ou prioridades não são disputa
        _, ressalvas, descartadas, _ = _separar(rascunhos, textos)
        ajustes.append(f'questão que não é de sim ou não ("{questao}"): a pauta fica com o lado neutro, sem ressalvas')
        descartadas += [(ressalva, "a questão não é de sim ou não") for ressalva in ressalvas]
        return Analise(lado_unico(da_pauta), motivo=motivo, ajustes=ajustes, descartadas=descartadas, resposta=resposta)
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
        com_disputa = sum(1 for r in rascunhos if r.atores) >= 2   # antes da conferência: lados com ator nomeado
        mudou, faltam, recusados = _conferir_atores(rascunhos, respostas, exigir_resposta=com_disputa)
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
    contexto = []
    if sem_lado:
        validos, contexto, mudou, sem_lugar = _veiculos_sem_lado(sem_lado, validos, textos, da_pauta)
        ajustes += mudou
        if sem_lugar:
            probs.append(f"veículo da pauta em nenhum lado, com ator de um lado no texto ({', '.join(sem_lugar)})")
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
    sem_sim_e_nao = ""
    if len(validos) == 2 and questao and not sim_e_nao(validos):
        sem_sim_e_nao = (f'as respostas dos lados são "{validos[0].resposta}" e "{validos[1].resposta}": numa disputa de dois '
                         f'lados, são "Sim" e "Não", opostas')
    return Analise(
        validos, questao, motivo, ressalvas=ressalvas, respostas=respostas, ajustes=ajustes,
        descartadas=descartadas, faltam=faltam, recusados=recusados, sem_sim_e_nao=sem_sim_e_nao, contexto=contexto,
        resposta=resposta,
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
    ou tem uma cujo trecho não vale (cada ator recusado vai com o trecho e o motivo), ou quando, numa disputa de dois
    lados, as respostas dos lados não são "Sim" e "Não"."""
    linhas = []
    if incompleta.faltam:
        linhas.append(f'CORREÇÃO: na sua resposta anterior, estes atores estão num lado e não têm entrada em '
                      f'"respostas_por_ator": {"; ".join(incompleta.faltam)}.')
    if incompleta.recusados:
        linhas.append(f"{'Além disso' if linhas else 'CORREÇÃO'}: na sua resposta anterior, o trecho destes atores não "
                      f"comprova a resposta deles:")
        linhas += [f'- {r.ator}: "{r.trecho}" ({r.motivo}).' for r in incompleta.recusados]
    if incompleta.sem_sim_e_nao:
        linhas.append(f"{'Além disso' if linhas else 'CORREÇÃO'}: na sua resposta anterior, {incompleta.sem_sim_e_nao}.")
    if incompleta.faltam or incompleta.recusados:
        lembrete = LEMBRETE_DAS_RESPOSTAS + (f" {REGRA_DO_SIM_E_NAO}" if incompleta.sem_sim_e_nao else "")
    else:
        lembrete = LEMBRETE_DO_SIM_E_NAO
    return "\n".join([*linhas, *_anterior(incompleta), lembrete])


def _tentar(chamar, entrada: str, textos) -> Analise:
    try:
        resposta = chamar(
            PROMPT_LADOS, entrada, chaves=CHAVES_LADOS, temperatura=TEMPERATURA_LADOS, max_saida=MAX_SAIDA_LADOS,
        )
    except JanelaExcedida:   # na 1ª tentativa, quem refaz é o Summarizer, com a proporção medida (ver `analisar_lados`)
        raise
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
    A resposta válida de dois lados cujas respostas não são "Sim" e "Não" (`Analise.sem_sim_e_nao`)
    também ganha uma, que pede as duas, na mesma tentativa do pedido das entradas se for o caso: a
    nova só fica se valer e trouxer "Sim" e "Não" em dois lados; senão, por qualquer motivo, fica a
    primeira (a regra não derruba a análise).
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

    def segunda(pedido: str) -> Analise:
        """A nova tentativa. O erro de janela dela (o pedido traz a resposta recusada, com menos caracteres por token
        que o texto) vale como a chamada que falha: não derruba a primeira resposta, se ela valeu."""
        mensagem, cortes = entrada(pedido)
        try:
            return replace(_tentar(chamar, mensagem, textos), cortes=cortes)
        except JanelaExcedida as e:
            return Analise(lado_unico(t["fonte"] for t in textos), problemas=[f"a chamada passou da janela ({e})"], cortes=cortes)

    mensagem, cortes = entrada()
    analise = replace(_tentar(chamar, mensagem, textos), cortes=cortes)
    if analise.problemas:
        logger.warning("Análise de lados: a resposta não valeu (%s). Nova tentativa, com o erro anexado.", "; ".join(analise.problemas))
        analise = replace(segunda(pedido_de_correcao(analise)), primeira=analise)
    elif analise.faltam or analise.recusados or analise.sem_sim_e_nao:
        if analise.faltam:
            logger.warning('Análise de lados: ator sem entrada em "respostas_por_ator" (%s). Nova tentativa, pedindo a entrada.',
                           "; ".join(analise.faltam))
        if analise.recusados:
            logger.warning("Análise de lados: ator com trecho que não vale (%s). Nova tentativa, pedindo o trecho.",
                           "; ".join(f"{r.ator}: {r.motivo}" for r in analise.recusados))
        if analise.sem_sim_e_nao:
            logger.warning('Análise de lados: %s. Nova tentativa, pedindo "Sim" e "Não".', analise.sem_sim_e_nao)
        nova = segunda(pedido_das_respostas(analise))
        sem_disputa_de_sim_e_nao = analise.sem_sim_e_nao and (len(nova.lados) != 2 or bool(nova.sem_sim_e_nao))
        if nova.problemas:
            logger.warning("Análise de lados: a nova tentativa não valeu (%s). Fica a primeira resposta%s.",
                           "; ".join(nova.problemas), ", sem o ator" if analise.faltam or analise.recusados else "")
            analise = replace(analise, segunda=nova)
        elif sem_disputa_de_sim_e_nao:
            logger.warning('Análise de lados: a nova tentativa não trouxe "Sim" e "Não" em dois lados (%s). Fica a primeira resposta%s.',
                           nova.sem_sim_e_nao or f"{len(nova.lados)} lado(s)", ", sem o ator" if analise.faltam or analise.recusados else "")
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


def _alvo_do_elenco(orc: Orcamento, analistas: list[str]) -> str:
    """O alvo de palavras de cada personagem e do total e o plano das falas, como o bloco os diz, com o nome de cada um.

    Cada alvo é um número só: o QA cobra uma fração dele, e a diferença fica como margem. O plano diz
    quantas falas cada personagem tem, de que tamanho e em que ordem (ver `orcamento.Orcamento.plano`).
    `analistas` são os nomes dos analistas, um por lado (ver `elenco.nomes_dos_analistas`).
    """
    um = len(orc.analistas) == 1
    nomes = ["Helena", *analistas[:len(orc.analistas)]]
    com_lado = ["Helena"] + (nomes[1:] if um else [f"{nome} (lado {i})" for i, nome in enumerate(nomes[1:], 1)])
    plano = orc.plano
    alvos = "; ".join(f"{nome}, {alvo}" for nome, alvo in zip(com_lado, (orc.helena, *orc.analistas)))
    falas = "; ".join(
        f"{nome}, {n} falas de uns {tamanho}" + (" palavras" if k == 0 else "")
        for k, (nome, n, tamanho) in enumerate(zip(nomes, plano.falas, plano.tamanhos))
    )
    texto = (f" Alvo de palavras: {alvos}; total, {orc.total}. Plano das falas: {falas}. Ordem dos {plano.turnos} turnos: "
             f"{', '.join(nomes[i] for i in plano.ordem)}.")
    if orc.reduzido:
        texto += " Os textos trazem pouco material, e o alvo já é menor: cumpra-o com o que as fontes trazem, sem argumento novo."
    return texto


def _linhas_do_bloco(lados, questao: str, ressalvas, finos: list[bool], teto: int, orc: Orcamento,
                     analistas: list[str]) -> list[str]:
    """As linhas do bloco: o cabeçalho (com a questão), uma por lado, uma por ressalva e o elenco, com o nome de cada
    analista e o alvo de palavras.

    `finos` diz quais lados são finos, `teto`, quantos caracteres a frase de posição de cada um
    pode ter, `orc`, o orçamento de palavras do episódio (ver `ai/orcamento.py`), e `analistas`, os nomes dos
    analistas, um por lado (ver `elenco.nomes_dos_analistas`).
    """
    n = len(lados)
    if n > 1:
        por_lado = [f"{nome}, do lado {i}" for i, nome in enumerate(analistas[:n], 1)]
        elenco = (
            f'ELENCO: Helena e exatamente {n} analistas, um por lado: {", ".join(por_lado[:-1])}, e {por_lado[-1]}; '
            f'"houve_divergencia": true. Helena apresenta a '
            f"questão uma vez, na abertura, com palavras naturais, e não atribui as posições aos atores; cada analista "
            f"sustenta a posição do seu lado, numa frase que nomeia um ator do lado, cita um veículo do lado e usa um "
            f'verbo de posição, como em "segundo <veículo>, <ator> afirma que...".'
        )
    elif ressalvas:
        elenco = (
            f"ELENCO: Helena e exatamente 1 analista, {analistas[0]}, que explica a posição e responde às ressalvas com o "
            'que as fontes dizem, sem tomar partido; "houve_divergencia": false.'
        )
    else:
        elenco = (f"ELENCO: Helena e exatamente 1 analista, {analistas[0]}, que explica o tema com ela, sem advogar; "
                  '"houve_divergencia": false.')
    if ressalvas:
        elenco += (
            " Ressalva não é lado nem ganha analista: Helena traz cada uma como pergunta atribuída, sem avaliá-la nem "
            "reformulá-la, numa frase com o veículo, o grupo e um verbo de posição, seguida de uma pergunta aberta, como "
            'em "Segundo <veículo>, <grupo> alertam que... Como você vê isso?".'
        )
    if any(finos):
        elenco += " Lado fino tem pouco material nas fontes: o analista dele não amplia além do que as fontes trazem."
    elenco += _alvo_do_elenco(orc, analistas)
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


def bloco_dos_lados(lados, questao: str = "", ressalvas=(), orc: Orcamento | None = None, textos=()) -> str:
    """O bloco LADOS DA PAUTA da entrada do episódio: a questão, os lados, as ressalvas, o elenco exato, com o nome de cada
    analista (ver `elenco.nomes_dos_analistas`, que evita os atores e as pessoas citadas nos `textos` da pauta), e o alvo
    de palavras.

    O alvo vem de `orc`; sem ele, é o de antes para o tamanho do elenco (ver `orcamento.orcamento`).
    Nunca passa de MAX_BLOCO caracteres: se for preciso, as frases de posição encolhem. O orçamento
    da entrada reserva para ele o tamanho que ele tem (ver `reserva_do_bloco`).
    """
    finos = lados_finos(lados)
    orc = orc or orcamento(lados)
    analistas = nomes_dos_analistas(lados, textos)
    teto = MAX_POSICAO
    linhas = _linhas_do_bloco(lados, questao, ressalvas, finos, teto, orc, analistas)
    while len("\n".join(linhas)) > MAX_BLOCO and teto > MIN_POSICAO:
        teto -= 20
        linhas = _linhas_do_bloco(lados, questao, ressalvas, finos, teto, orc, analistas)
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
    compridos, o plano mais longo (cada analista no alvo máximo), o nome mais comprido de cada vaga e o
    aviso de pouco material, sem encolher as posições e até MAX_BLOCO: o bloco de verdade nunca passa disso.
    """
    todos = [len(lados) >= 2] * len(lados)
    maior = Orcamento(9990, (MAX_ALVO,) * max(len(lados), 1), 0, reduzido=True)
    compridos = [max(vaga, key=len) for vaga in VAGAS]
    return min(MAX_BLOCO, len("\n".join(_linhas_do_bloco(lados, questao, ressalvas, todos, MAX_POSICAO, maior, compridos))))

"""Análise de lados: a questão em disputa na pauta, quem responde a ela de cada lado, que veículo relata cada um
e as ressalvas de grupos sem nome.

Roda em toda pauta, inclusive nas de um veículo só, antes da geração e sobre os mesmos trechos que
vão para o episódio. O número de lados define o elenco (um analista por lado) e o valor de
houve_divergencia; quem confere isso no episódio é `qa.problemas_dos_analistas`.
"""
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace

from techdigest.ai.prompt import PROMPT_LADOS
from techdigest.ai.qa import (
    MIN_LADO_FINO, QUANTIFICADORES, atores_exclusivos, mesmo_ator, mesmo_veiculo, palavras_do_ator, termo_do_grupo,
    veiculos_distintos,
)

logger = logging.getLogger("techdigest.ai.lados")

CHAVES_LADOS = ("lados",)
MAX_LADOS = 3
MAX_RESSALVAS = 2           # acima disso ficam as primeiras, com aviso no log
TEMPERATURA_LADOS = 0.1     # baixa, para a contagem dos lados variar pouco entre execuções
MAX_SAIDA_LADOS = 1200      # tokens: a resposta é um JSON curto, com um trecho literal por ator
MAX_BLOCO = 1600            # caracteres do bloco de lados na entrada do episódio; o orçamento reserva sempre isto
MAX_POSICAO = 220           # caracteres da frase de cada lado no bloco
MIN_POSICAO = 60
MAX_QUESTAO = 160           # caracteres da questão no bloco
MAX_RESPOSTA = 60           # caracteres da resposta de cada lado no bloco
MAX_ANTERIOR = 2000         # caracteres da resposta recusada que voltam ao LLM na nova tentativa
MIN_TRECHO = 20             # caracteres: trecho de evidência menor que isto não comprova nada
FOLGA_DO_LADO_FINO = 80     # palavras: o alvo do analista de lado fino vai do mínimo dele até o mínimo mais isto
# A posição do lado neutro: quando nenhum lado tem ator nomeado ou quando as duas tentativas da análise não valem.
POSICAO_DE_EMERGENCIA = "relato dos fatos, sem lados definidos"
# Alvo de palavras por personagem conforme o número de analistas: com Helena, o total cabe em 600-1300.
ALVO_POR_PERSONAGEM = {1: "360 a 420", 2: "320 a 400", 3: "260 a 310"}
# Termos que não fazem um ator, sem acento: coletivo sem nome ("economistas"), designação vaga sem
# qualificador ("o governo", "a empresa") e os quantificadores que os acompanham ("alguns analistas").
# É genérico o ator que só tem palavras daqui: "governo federal" e "governo do Amazonas" valem.
# O ator genérico passa a grupo, e a posição que só grupos sustentam vira ressalva.
TERMOS_GENERICOS = frozenset({
    "economista", "economistas", "especialista", "especialistas", "analista", "analistas", "critico", "criticos",
    "observador", "observadores", "pesquisador", "pesquisadores", "estudioso", "estudiosos", "cientista", "cientistas",
    "jurista", "juristas", "tecnico", "tecnicos", "comentarista", "comentaristas", "autoridade", "autoridades",
    "fonte", "fontes", "opositor", "opositores", "adversario", "adversarios", "aliado", "aliados",
    "apoiador", "apoiadores", "parlamentar", "parlamentares", "politico", "politicos",
    "governo", "governos", "empresa", "empresas", "companhia", "companhias", "entidade", "entidades",
    "organizacao", "organizacoes", "instituicao", "instituicoes", "orgao", "orgaos",
}) | QUANTIFICADORES
# O que a nova tentativa lembra ao LLM, depois do erro da primeira.
LEMBRETE_DA_CORRECAO = (
    "Responda de novo, com o JSON completo. Uma questão só; cada lado é uma resposta diferente a ela; agrupe os "
    "atores pela resposta que dão à questão, nunca um lado por ator; sem disputa, a questão fica vazia e há um lado só; "
    'coletivo sem nome vai em "grupos", nunca em "atores"; com questão, "respostas_por_ator" traz a resposta de cada '
    "ator e um trecho copiado ao pé da letra do texto."
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

    @property
    def fino(self) -> bool:
        """Lado com um só trecho de evidência: há pouco material nas fontes para sustentá-lo."""
        return len(set(self.trechos)) == 1


@dataclass(frozen=True)
class Evidencia:
    """A resposta de um ator à questão e o trecho que a comprova, como o LLM os listou."""
    ator: str
    resposta: str
    trecho: str
    veiculo: str
    comprovada: bool            # o trecho existe no texto desse veículo que a análise recebeu


@dataclass(frozen=True)
class Ressalva:
    """Uma posição que só um grupo sem nome sustenta ("economistas alertam que...").

    Não é lado e não ganha analista: entra no episódio como pergunta atribuída da Helena.
    """
    grupos: tuple[str, ...]     # vazio quando o LLM não nomeou nem ator nem grupo
    posicao: str
    veiculos: tuple[str, ...]   # com a grafia da pauta


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
    descartadas: list[Ressalva] = field(default_factory=list)   # as ressalvas além de MAX_RESSALVAS
    resposta: dict | None = None
    primeira: "Analise | None" = None                    # a primeira tentativa, quando ela não valeu e houve outra


def entrada_dos_lados(textos) -> str:
    """O que o LLM recebe: cada trecho com veículo e título. `textos` são os de `Entrada.textos`."""
    partes = [
        f"TEXTO {i}\nVeículo: {t['fonte']}\nTítulo: {t['titulo']}\nTexto:\n{t['texto']}" for i, t in enumerate(textos, 1)
    ]
    partes.append(f"VEÍCULOS DA PAUTA: {', '.join(veiculos_distintos(t['fonte'] for t in textos))}")
    return "\n\n".join(partes)


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
    """Se o nome não chega a ser um ator: só tem termos de TERMOS_GENERICOS (sem contar artigo nem partícula)."""
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
    trechos: list[str] = field(default_factory=list)


def _rascunhos(lados: list[dict], da_pauta: list[str]) -> tuple[list[_Rascunho], list[str]]:
    """Os lados de uma resposta já conferida, com o ator genérico passado de "atores" para "grupos"."""
    rascunhos, ajustes = [], []
    for i, lado in enumerate(lados, 1):
        atores = _sem_repetir(lado.get("atores") or [])
        genericos = tuple(a for a in atores if ator_generico(a))
        if genericos:
            ajustes.append(f"ator genérico do lado {i} passou a grupo ({', '.join(genericos)})")
        rascunhos.append(_Rascunho(
            numero=i, posicao=_linha(lado["posicao"]), atores=[a for a in atores if a not in genericos],
            grupos=tuple(g for g in _sem_repetir([*(lado.get("grupos") or []), *genericos]) if termo_do_grupo(g)),
            veiculos=tuple(v for v in da_pauta if any(mesmo_veiculo(v, citado) for citado in lado["veiculos"])),
            resposta=_linha(lado.get("resposta")),
        ))
    return rascunhos, ajustes


def _literal(texto: str) -> str:
    """O texto para a comparação de trechos: espaços e aspas normalizados, sem contar maiúsculas."""
    texto = unicodedata.normalize("NFC", str(texto))
    texto = re.sub("[“”„‟«»]", '"', re.sub("[‘’‚‛]", "'", texto))
    return " ".join(texto.split()).casefold()


def _evidencias(entradas: list, textos, da_pauta: list[str]) -> list[Evidencia]:
    """As respostas por ator da resposta do LLM, cada uma com o resultado da conferência do trecho.

    O trecho comprova a resposta quando tem pelo menos MIN_TRECHO caracteres e está, ao pé da
    letra, no título ou no texto que a análise recebeu daquele veículo (o trecho já cortado pelo
    orçamento). Reticências e aspas em volta do trecho não contam.
    """
    evidencias = []
    for entrada in entradas:
        if not isinstance(entrada, dict):
            continue
        ator, resposta, trecho, veiculo = (_linha(entrada.get(chave)) for chave in ("ator", "resposta", "trecho", "veiculo"))
        if not ator:
            continue
        do_veiculo = _literal("\n".join(f"{t['titulo']}\n{t['texto']}" for t in textos if veiculo and mesmo_veiculo(t["fonte"], veiculo)))
        procurado = _literal(trecho).strip("\"'. …")
        evidencias.append(Evidencia(ator, resposta, trecho, veiculo, len(procurado) >= MIN_TRECHO and procurado in do_veiculo))
    return evidencias


def _responde(resposta_do_ator: str, resposta_do_lado: str) -> bool:
    """Se a resposta do ator é a do lado: iguais, ou uma começa com a outra ("Sim" e "Sim, é desinformação")."""
    def palavras(texto):
        sem_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
        return re.findall(r"\w+", sem_acentos.lower())
    a, b = sorted((palavras(resposta_do_ator), palavras(resposta_do_lado)), key=len)
    return bool(a) and b[:len(a)] == a


def _conferir_atores(rascunhos: list[_Rascunho], evidencias: list[Evidencia]) -> list[str]:
    """Deixa em cada lado só os atores cuja resposta, comprovada por um trecho, é a do lado.

    Um ator pode ter mais de uma entrada, uma por trecho. O ator sem resposta listada ou sem
    trecho comprovado sai. O ator que está num lado de resposta diferente da dele vai para o lado
    da resposta dele, se existir, ou sai. Cada lado fica com os trechos comprovados dos atores que
    ficaram nele. Devolve o que mudou.
    """
    def evidencias_de(ator: str) -> list[Evidencia]:
        iguais = [e for e in evidencias if palavras_do_ator(e.ator) == palavras_do_ator(ator)]
        return iguais or [e for e in evidencias if mesmo_ator(e.ator, ator)]

    ajustes, ficam = [], {r.numero: [] for r in rascunhos}   # por lado: (ator, trechos)
    for r in rascunhos:
        for ator in r.atores:
            listadas = evidencias_de(ator)
            comprovadas = [e for e in listadas if e.comprovada]
            if not listadas:
                ajustes.append(f"ator do lado {r.numero} saiu: não está em respostas_por_ator ({ator})")
                continue
            if not comprovadas:
                ajustes.append(f"ator do lado {r.numero} saiu: o trecho não está no texto de {listadas[0].veiculo or 'nenhum veículo'} ({ator})")
                continue
            do_lado = [e.trecho for e in comprovadas if _responde(e.resposta, r.resposta)]
            if do_lado:
                ficam[r.numero].append((ator, do_lado))
                continue
            dele = comprovadas[0].resposta
            destino = next((o for o in rascunhos if o is not r and _responde(dele, o.resposta)), None)
            if destino is None:
                ajustes.append(f"ator do lado {r.numero} saiu: nenhum lado tem a resposta dele ({ator}: {dele})")
                continue
            ficam[destino.numero].append((ator, [e.trecho for e in comprovadas if _responde(e.resposta, destino.resposta)]))
            ajustes.append(f"ator passou do lado {r.numero} para o lado {destino.numero}, o da resposta dele ({ator}: {dele})")
    for r in rascunhos:
        r.atores, r.trechos = [], []
        for ator, trechos in ficam[r.numero]:
            if not any(mesmo_ator(ator, outro) for outro in r.atores):
                r.atores.append(ator)
                for trecho in trechos:
                    if trecho not in r.trechos:
                        r.trechos.append(trecho)
    return ajustes


def _separar(rascunhos: list[_Rascunho]) -> tuple[dict[int, Lado], list[Ressalva], list[str]]:
    """Separa os lados conferidos: os que têm ator nomeado, pelo número, e as ressalvas.

    O lado que fica sem ator nomeado (só com grupos, ou sem nada) vira ressalva; no lado que tem
    ator nomeado, os grupos saem, porque concordam com ele. O terceiro valor diz o que foi mudado.
    """
    nomeados, ressalvas, ajustes = {}, [], []
    for r in rascunhos:
        if r.atores:
            nomeados[r.numero] = Lado(r.posicao, tuple(r.atores), r.veiculos, r.resposta, tuple(r.trechos))
            continue
        if not r.grupos:
            ajustes.append(f"lado {r.numero}, sem ator nem grupo, virou ressalva")
        ressalvas.append(Ressalva(r.grupos, r.posicao, r.veiculos))
    return nomeados, ressalvas, ajustes


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

    `textos` são os trechos que a análise recebeu (os de `Entrada.textos`: fonte, titulo e texto).
    Cada lado da resposta tem posição e pelo menos um veículo, todos da pauta (pela comparação
    tolerante de `qa.mesmo_veiculo`). Só conta como lado o que tem ator nomeado: o ator genérico
    (`ator_generico`) passa a grupo, e a posição que só grupos sustentam vira ressalva (ver
    `_separar`). Ficam no máximo MAX_RESSALVAS ressalvas, as primeiras.

    Com questão, a resposta traz também "respostas_por_ator": a resposta de cada ator e um trecho
    literal de um texto da pauta que a comprova. O ator sem trecho comprovado sai, e o ator que
    está num lado de resposta diferente da dele vai para o lado certo, ou sai (ver
    `_conferir_atores`). Sem questão, os atores ficam como vieram.

    Dos lados com ator nomeado, vale até 3, cada um com um ator que nenhum outro tem. A questão só
    fica com 2 lados ou mais, e aí cada lado tem a sua resposta, diferente das outras; com um lado
    só, a questão sai. Sem nenhum lado com ator nomeado, a pauta fica com o lado neutro e mantém
    as ressalvas. Todo veículo da pauta tem de estar em algum lado ou ressalva.

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
    rascunhos, ajustes = _rascunhos(lados, da_pauta)
    respostas = []
    if questao:
        entradas = resposta.get("respostas_por_ator")
        if not (isinstance(entradas, list) and entradas):
            return invalida('resposta com questão e sem "respostas_por_ator" (cada ator tem a sua resposta e um trecho literal)')
        respostas = _evidencias(entradas, textos, da_pauta)
        ajustes += _conferir_atores(rascunhos, respostas)
    nomeados, ressalvas, mudou = _separar(rascunhos)
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
    sem_lado = [v for v in da_pauta if not any(v in item.veiculos for item in (*validos, *ressalvas))]
    if sem_lado:
        probs.append(f"veículo da pauta em nenhum lado ({', '.join(sem_lado)})")
    if probs:
        return invalida(*probs)
    if not validos:
        ajustes.append("nenhum lado com ator nomeado: a pauta fica com o lado neutro")
        validos = lado_unico(da_pauta)
    descartadas = ressalvas[MAX_RESSALVAS:]
    if descartadas:
        ajustes.append(f"{len(descartadas)} ressalva(s) a mais: ficam as {MAX_RESSALVAS} primeiras")
    return Analise(
        validos, questao, _linha(resposta.get("motivo")), ressalvas=ressalvas[:MAX_RESSALVAS], respostas=respostas,
        ajustes=ajustes, descartadas=descartadas, resposta=resposta,
    )


def pedido_de_correcao(recusada: Analise) -> str:
    """O que a nova tentativa acrescenta à entrada: o erro da resposta recusada, a própria resposta e o lembrete."""
    partes = [f"CORREÇÃO: a sua resposta anterior não valeu: {'; '.join(recusada.problemas)}."]
    if recusada.resposta is not None:
        partes.append(f"Resposta anterior: {json.dumps(recusada.resposta, ensure_ascii=False)[:MAX_ANTERIOR]}")
    partes.append(LEMBRETE_DA_CORRECAO)
    return "\n".join(partes)


def _tentar(chamar, entrada: str, textos) -> Analise:
    try:
        resposta = chamar(
            PROMPT_LADOS, entrada, chaves=CHAVES_LADOS, temperatura=TEMPERATURA_LADOS, max_saida=MAX_SAIDA_LADOS,
        )
    except Exception as e:  # resposta vazia, cortada, sem a chave, servidor fora do ar...
        return Analise(lado_unico(t["fonte"] for t in textos), problemas=[f"a chamada falhou ({type(e).__name__}: {str(e)[:200]})"])
    return analise_da_resposta(resposta, textos)


def analisar_lados(chamar, textos) -> Analise:
    """Pergunta ao LLM a questão e os lados da pauta.

    Chamada que falha ou resposta inválida ganham uma nova tentativa, com o erro anexado à entrada.
    Se ela também não valer, a pauta segue com o lado único de emergência, com aviso no log.
    `chamar(system, user, **opções)` é o chat_json do provider (ou o `_chamar` do Summarizer).
    """
    entrada = entrada_dos_lados(textos)
    analise = _tentar(chamar, entrada, textos)
    if analise.problemas:
        logger.warning("Análise de lados: a resposta não valeu (%s). Nova tentativa, com o erro anexado.", "; ".join(analise.problemas))
        analise = replace(_tentar(chamar, f"{entrada}\n\n{pedido_de_correcao(analise)}", textos), primeira=analise)
    if analise.ajustes:
        logger.info("Análise de lados: ajustes na resposta (%s).", "; ".join(analise.ajustes))
    if analise.descartadas:
        logger.warning(
            "Análise de lados: %d ressalva(s) a mais na pauta; ficam as %d primeiras.", len(analise.descartadas), MAX_RESSALVAS,
        )
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
            f" · ressalvas: {'; '.join(', '.join(r.grupos) or 'sem grupo' for r in analise.ressalvas)}" if analise.ressalvas else "",
        )
    return analise


def _encurtar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite - 1].rsplit(None, 1)[0].rstrip(",;:") + "…"


def _frase(texto: str) -> str:
    return texto if texto.endswith((".", "!", "?", "…")) else texto + "."


def bloco_dos_lados(lados, questao: str = "", ressalvas=()) -> str:
    """O bloco LADOS DA PAUTA da entrada do episódio: a questão, os lados, as ressalvas, o elenco exato e o alvo de palavras.

    Nunca passa de MAX_BLOCO caracteres, que é o que o orçamento da entrada reserva para ele: se
    for preciso, as frases de posição encolhem.
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
    finos = lados_finos(lados)
    if any(finos):
        elenco += (
            f" Lado fino tem pouco material nas fontes: o analista dele fala de {MIN_LADO_FINO} a "
            f"{MIN_LADO_FINO + FOLGA_DO_LADO_FINO} palavras e não amplia além do que as fontes trazem."
        )
    elenco += f" Alvo: {ALVO_POR_PERSONAGEM[n]} palavras por personagem{', fora o de lado fino' if any(finos) else ''}."
    cabecalho = f"\nLADOS DA PAUTA: {n} lado{'s' if n > 1 else ''}."
    if questao:
        cabecalho += f"\nQUESTÃO: {_encurtar(questao, MAX_QUESTAO)}"

    def lado_descrito(i: int, lado: Lado, teto: int) -> str:
        resposta = f" (resposta: {_encurtar(lado.resposta, MAX_RESPOSTA).rstrip('.')}" if lado.resposta else ""
        resposta += ("; lado fino)" if finos[i - 1] else ")") if resposta else (" (lado fino)" if finos[i - 1] else "")
        atores = f" Atores: {', '.join(lado.atores)}." if lado.atores else ""
        return f"Lado {i}{resposta}: {_frase(_encurtar(lado.posicao, teto))}{atores} Veículos: {', '.join(lado.veiculos)}."

    def ressalva_descrita(i: int, ressalva: Ressalva, teto: int) -> str:
        grupos = f" Grupos: {', '.join(ressalva.grupos)}." if ressalva.grupos else ""
        return f"Ressalva {i}: {_frase(_encurtar(ressalva.posicao, teto))}{grupos} Veículos: {', '.join(ressalva.veiculos)}."

    def montar(teto: int) -> str:
        return "\n".join([
            cabecalho,
            *(lado_descrito(i, lado, teto) for i, lado in enumerate(lados, 1)),
            *(ressalva_descrita(i, ressalva, teto) for i, ressalva in enumerate(ressalvas, 1)),
            elenco,
        ])

    teto = MAX_POSICAO
    bloco = montar(teto)
    while len(bloco) > MAX_BLOCO and teto > MIN_POSICAO:
        teto -= 20
        bloco = montar(teto)
    if len(bloco) > MAX_BLOCO:   # listas de atores longas demais: o que fica de fora é o fim da última linha
        logger.warning("Bloco de lados com %d caracteres: cortado em %d.", len(bloco), MAX_BLOCO)
        linhas = bloco[len(cabecalho) + 1:].split("\n")[:-1]
        bloco = "\n".join([cabecalho, elenco, *linhas])[:MAX_BLOCO - 1] + "…"
    return bloco

"""Checagem de fidelidade dos episódios gerados por testar_episodio.py (sem LLM e sem rede).

Compara cada episódio com os textos da pauta que o gerou e lista o que não tem fonte:

- números, percentuais e nomes próprios do título, do resumo_didatico, dos pontos_chave e das
  falas que não aparecem em nenhum texto da pauta (número por extenso vale pelo algarismo);
- atribuições vagas ("especialistas afirmam", "segundo as análises") a um grupo que a pauta não cita;
- veículos da pauta fora de fontes_citadas;
- com houve_divergencia true: menos de dois analistas, e falas em que Helena parece tomar posição;
- e, só como diagnóstico, as frases que atribuem algo a um veículo ("segundo o G1...", "o G1 relata
  que..."), com a fração das palavras da frase que está no texto do veículo citado e a maior fração
  num outro veículo da pauta; nos episódios com disputa, a frase que apresenta cada lado.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/checar_fidelidade.py                          # o relatorio_*.json mais recente
    python scripts/checar_fidelidade.py --relatorio <arquivo>

Lê o relatório e os episódios de data/agrupamento/episodios/ e a amostra que o relatório aponta, e
grava data/agrupamento/fidelidade_<data-hora>.txt. As regras comparam texto, não sentido: o que
elas não veem está em COMO_LER, que abre o relatório gravado.
"""
import argparse
import datetime
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from techdigest.ai import qa
from techdigest.ai.atribuicoes import GRUPOS as _GRUPOS
from techdigest.ai.atribuicoes import atribuicoes_a_grupos as atribuicoes_vagas
from techdigest.ai.numeros import _ESCALAS as _escalas
from techdigest.ai.numeros import _PARCELAS as _parcelas
from techdigest.ai.numeros import Numero, formatar, numeros
from techdigest.ai.numeros import Token as _Token
from techdigest.ai.numeros import dobrar as _plano
from techdigest.ai.numeros import junto as _junto
from techdigest.ai.numeros import tokens as _tokens
from techdigest.ai.lados import Lado
from techdigest.ai.recorte import paragrafos
from techdigest.ai.verbos import FORMAS_DE_POSICAO
from techdigest.ai.summarizer import _limpar
from techdigest.config import Settings

settings = Settings()

COMO_LER = """Como ler
  Fato sem fonte: número, percentual, nome próprio ou atribuição vaga do título, do resumo_didatico,
  dos pontos_chave ou de uma fala que não aparece em nenhum texto da pauta (veículo, título e texto
  completo de cada artigo). Cada fato conta uma vez por episódio, mesmo que se repita.
  Valem como iguais: número por extenso e algarismo ("duzentos e noventa" = 290, "3 milhões" =
  3.000.000); nome e sigla ("Tribunal Superior Eleitoral" = TSE); maiúsculas, minúsculas e acentos.
  Percentual só casa com percentual. Nome próprio é conferido palavra por palavra. Atribuição vaga
  tem fonte quando a pauta cita o mesmo grupo (analistas e análises, especialistas, estudos...).
  Arredondado: o número não está na pauta, mas ela traz um mais preciso a até 10% dele ("trinta por
  cento" para 30,7%). Fica à parte, com os dois valores, e não entra na conta dos sem fonte.
  Fora da conta: nome e papel dos personagens, os programas (TechDigest, PulsoBR), contagem de
  quem fala ("dois lados", "dois pilares") e substantivos institucionais genéricos (Estado,
  Judiciário, Governo, Justiça).
  O que a checagem não vê: o sentido (um número certo usado para dizer outra coisa passa), nome
  que só aparece em começo de frase, "um" e "uma" sozinhos, ordinais e frações além de "terço".
  Posição de Helena: lista de expressões de juízo fora de citação; é indício para leitura, não prova.
  Atribuição a veículo (só diagnóstico, só com dois veículos ou mais): frase do resumo ou de uma fala
  com "segundo", "de acordo com" ou "conforme" antes do nome do veículo, ou com um verbo de relato
  depois dele ("o G1 relata que..."). Contam as palavras de 4 letras ou mais, comparadas pela raiz
  sem acento (sem plural, gênero e terminação de verbo: "derrubou" = "derrubada"), menos as palavras
  sem conteúdo, os números por extenso, os verbos de posição, os nomes dos veículos, dos atores e dos
  personagens e as palavras que estão em todos os textos da pauta, que não distinguem um veículo do outro. Mostra a fração delas no texto completo do
  veículo citado e a maior fração num outro veículo. Compara palavras, não sentido: a frase pode usar
  as palavras do veículo para dizer outra coisa."""

HELENA = "helena"
PROGRAMAS = {"techdigest", "pulsobr"}
TRATAMENTOS = {"dr", "dra", "sr", "sra", "prof", "profa"}
# Substantivos institucionais que se escrevem com maiúscula sem ser nome de ninguém: não pedem fonte.
GENERICOS = {"estado", "judiciario", "legislativo", "executivo", "governo", "justica", "uniao", "constituicao",
             "republica", "internet"}
TOLERANCIA_DO_ARREDONDAMENTO = 0.10   # "trinta por cento" para 30,7%: mais redondo e a até 10% do número da pauta

_FIM_DE_FRASE = re.compile(r"(?<!\bDr)(?<!\bDra)(?<!\bSr)(?<!\bSra)[.!?…]+[\"'”’)]*\s+")

_RETORICA = re.compile(r"\s+(?:lados|campos|pilares|frentes|visoes|caminhos|aspectos|eixos|polos|extremos)\b")

_CONECTORES = {"de", "da", "do", "das", "dos"}
_FUNCIONAIS = _CONECTORES | {"o", "a", "os", "as", "um", "uma", "e", "em", "no", "na", "nos", "nas", "por",
                             "para", "com", "ao", "aos"}
_ABREVIATURAS = TRATAMENTOS | {"s", "st", "sta", "av", "dep", "sen", "min", "gen", "cel"}


# Juízo de valor na boca de Helena (texto sem acento). Só conta fora de citação e de fala atribuída.
_JUIZOS = re.compile(
    r"\b(?:absurd[oa]s?|inaceitave(?:l|is)|lamentave(?:l|is)|vergonhos[oa]s?|escandalos[oa]s?|"
    r"irresponsave(?:l|is)|abusiv[oa]s?|autoritari[oa]s?|arbitrari[oa]s?|tendencios[oa]s?|injust[oa]s?|"
    r"covardes?|atropel\w+|pass(?:a|ou|ar|ando) por cima|manobras?|claramente|obviamente|evidentemente|"
    r"felizmente|infelizmente|(?:tem|tinha) (?:toda a |toda )?razao|com razao|"
    r"(?:esta|estao|estava) (?:cert|errad|corret|equivocad)[oa]s?|eu acho|eu acredito|na minha opiniao|"
    r"a meu ver|me parece|concordo|discordo)\b")
_ATRIBUI = re.compile(
    r"\b(?:segundo|conforme|de acordo com|na visao d[eoa]s?|"
    r"(?:classific|afirm|aleg|acus|critic|reclam|consider|apont|denunci|sustent|argument|mencion|relat|report|"
    r"destac|question|qualific|declar|avali)(?:a|am|ou|aram|ando|ava|avam)|"
    r"cham(?:a|ou|am|aram) de|diz|dizem|disse|disseram|defende|defendem|defendeu|rebate|rebateu|"
    r"acusacao|acusacoes|alegacao|alegacoes)\b")
_ASPAS = "\"'“”‘’"


# ── Texto ─────────────────────────────────────────────────────────────────────────────────

def _frase(texto: str, posicao: int) -> str:
    """A frase de `texto` em que está a posição dada."""
    comeco = 0
    for m in _FIM_DE_FRASE.finditer(texto):
        if m.end() > posicao:
            return texto[comeco:m.end()].strip()
        comeco = m.end()
    return texto[comeco:].strip()


# ── Números ───────────────────────────────────────────────────────────────────────────────

# A leitura dos números vem de techdigest.ai.numeros (`numeros`, `formatar`): o QA usa a mesma leitura.


def _algarismos_significativos(valor: float) -> int:
    return len(Decimal(repr(valor)).normalize().as_tuple().digits)


# ── Nomes próprios ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Nome:
    trecho: str                  # como está escrito: "Tribunal Superior Eleitoral"
    palavras: tuple[str, ...]    # as palavras com maiúscula, sem acento e em minúsculas
    inicio: int
    fim: int


def _inicia_frase(tokens: list[_Token], i: int, texto: str) -> bool:
    if i == 0:
        return True
    anterior = tokens[i - 1]
    meio = texto[anterior.fim:tokens[i].inicio]
    if "\n" in meio:
        return True
    if not re.search(r"[.!?…:]", meio):
        return False
    abreviado = anterior.norm in _ABREVIATURAS or (len(anterior.texto) == 1 and anterior.texto.isupper())
    return not (meio.startswith(".") and abreviado)


def maiusculas_no_meio(texto: str) -> set[str]:
    """Palavras escritas com maiúscula fora do começo de frase: é o que confirma um nome próprio."""
    tokens = _tokens(texto)
    return {t.norm for i, t in enumerate(tokens) if t.maiuscula and not _inicia_frase(tokens, i, texto)}


def nomes_proprios(texto: str, confirmados: frozenset[str] | set[str] = frozenset()) -> list[Nome]:
    """Sequências de palavras com maiúscula ("Flávio Bolsonaro", "Terra de Direitos", "TSE").

    A primeira palavra de uma frase tem maiúscula de qualquer jeito: só conta se for sigla, se tiver
    maiúscula interna ("WhatsApp") ou se estiver em `confirmados` (as palavras que o episódio
    escreve com maiúscula no meio de alguma frase).
    """
    tokens = _tokens(texto)
    achados, i = [], 0
    while i < len(tokens):
        if not tokens[i].maiuscula:
            i += 1
            continue
        sequencia, j = [i], i + 1
        while j < len(tokens) and texto[tokens[j - 1].fim:tokens[j].inicio].strip(" \t") in ("", "-"):
            if tokens[j].maiuscula:
                sequencia.append(j)
            elif not (tokens[j].norm in _CONECTORES and j + 1 < len(tokens) and tokens[j + 1].maiuscula
                      and _junto(texto, tokens[j - 1], tokens[j]) and _junto(texto, tokens[j], tokens[j + 1])):
                break
            j += 1
        primeiro = tokens[sequencia[0]]
        forte = (primeiro.norm in confirmados or (len(primeiro.texto) > 1 and primeiro.texto.isupper())
                 or primeiro.texto[1:] != primeiro.texto[1:].lower())
        if _inicia_frase(tokens, sequencia[0], texto) and not forte:
            sequencia = sequencia[1:]
        palavras = tuple(tokens[k].norm for k in sequencia if tokens[k].norm not in _FUNCIONAIS)
        if palavras:
            inicio, fim = tokens[sequencia[0]].inicio, tokens[sequencia[-1]].fim
            achados.append(Nome(texto[inicio:fim], palavras, inicio, fim))
        i = j
    return achados


# ── Atribuição vaga ───────────────────────────────────────────────────────────────────────

# As atribuições vagas vêm de techdigest.ai.atribuicoes (`atribuicoes_vagas`): o QA usa a mesma regra para reprovar.


# ── A pauta como referência ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Fonte:
    """Um artigo da pauta."""
    veiculo: str
    titulo: str
    texto: str                    # texto extraído completo
    enviado: int | None = None    # caracteres do texto que entraram na mensagem do LLM (None = todos)
    id: int | None = None
    recorte: str | None = None    # o que entrou, quando não é só o começo do texto (None = os primeiros `enviado` caracteres)

    @property
    def completo(self) -> str:
        return f"{self.veiculo}\n{self.titulo}\n{self.texto}"

    @property
    def lido(self) -> str:
        corpo = self.texto[:self.enviado] if self.recorte is None else self.recorte
        return f"{self.veiculo}\n{self.titulo}\n{corpo}"


def recorte_enviado(texto: str, corte: dict | None) -> str | None:
    """O que entrou do texto na geração, pelos parágrafos que o relatório lista (o recorte por relevância).

    Devolve None quando o relatório não traz os parágrafos: é um relatório antigo, em que entrava
    o começo do texto, ou uma fonte que ficou fora da entrada.
    """
    entraram = (corte or {}).get("paragrafos_que_entraram")
    if not entraram:
        return None
    por_numero = {p.numero: p for p in paragrafos(texto)}
    return "\n".join(
        texto[por_numero[e["paragrafo"]].inicio:por_numero[e["paragrafo"]].inicio + e["caracteres"]]
        for e in entraram if e["paragrafo"] in por_numero
    )


@dataclass(frozen=True)
class Referencia:
    """O que um conjunto de textos sustenta: palavras, siglas, números e percentuais."""
    palavras: frozenset[str]
    siglas_escritas: frozenset[str]     # palavras todas em maiúsculas: "TSE", "ANPD"
    siglas_dos_nomes: frozenset[str]    # iniciais dos nomes de várias palavras: "tse" de "Tribunal Superior Eleitoral"
    valores: frozenset[float]
    percentuais: frozenset[float]
    plano: str     # os textos sem acento, para procurar os grupos das atribuições vagas

    def tem_numero(self, n: Numero) -> bool:
        return n.valor in (self.percentuais if n.percentual else self.valores)

    def origem_do_arredondamento(self, n: Numero) -> float | None:
        """O número dos textos de que `n` parece ser o arredondamento: `n` é mais redondo e fica perto dele."""
        candidatos = [
            v for v in (self.percentuais if n.percentual else self.valores)
            if v and v != n.valor and abs(v - n.valor) / abs(v) <= TOLERANCIA_DO_ARREDONDAMENTO
            and _algarismos_significativos(n.valor) < _algarismos_significativos(v)
        ]
        return min(candidatos, key=lambda v: abs(v - n.valor), default=None)

    def palavras_sem_fonte(self, nome: Nome, livres: set[str] | frozenset[str] = frozenset()) -> tuple[str, ...]:
        """As palavras do nome que os textos não trazem; vazio se o nome (ou a sigla dele) aparece."""
        faltando = tuple(p for p in nome.palavras if p not in self.palavras and p not in livres)
        if faltando and len(nome.palavras) > 1 and "".join(p[0] for p in nome.palavras) in self.siglas_escritas:
            return ()                                    # "Tribunal Superior Eleitoral" com "TSE" na pauta
        if faltando and len(nome.palavras) == 1 and nome.palavras[0] in self.siglas_dos_nomes:
            return ()                                    # "TSE" com "Tribunal Superior Eleitoral" na pauta
        return faltando

    def tem_grupo(self, grupo: str) -> bool:
        return re.search(rf"\b{_GRUPOS[grupo]}", self.plano) is not None


def referencia(textos) -> Referencia:
    palavras, escritas, dos_nomes, valores, percentuais, planos = set(), set(), set(), set(), set(), []
    for texto in textos:
        texto = unicodedata.normalize("NFC", texto)
        tokens = _tokens(texto)
        palavras.update(t.norm for t in tokens)
        escritas.update(t.norm for t in tokens if len(t.texto) > 1 and t.texto.isupper())
        for nome in nomes_proprios(texto, maiusculas_no_meio(texto)):
            if len(nome.palavras) > 1:
                dos_nomes.add("".join(p[0] for p in nome.palavras))
        for n in numeros(texto):
            valores.add(n.valor)
            if n.percentual:
                percentuais.add(n.valor)
        planos.append(_plano(texto))
    return Referencia(frozenset(palavras), frozenset(escritas), frozenset(dos_nomes), frozenset(valores),
                      frozenset(percentuais), "\n".join(planos))


def onde_aparece(n: Numero, fontes: list[Fonte], margem: int = 70) -> tuple[str, str] | None:
    """O veículo e o trecho da pauta em que o número aparece (a primeira ocorrência), ou None."""
    for fonte in fontes:
        texto = unicodedata.normalize("NFC", fonte.completo)
        for m in numeros(texto):
            if m.valor == n.valor and (m.percentual or not n.percentual):
                trecho = " ".join(texto[max(m.inicio - margem, 0):m.fim + margem].split())
                return fonte.veiculo, f"…{trecho}…"
    return None


# ── A checagem ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Achado:
    tipo: str       # "número", "percentual", "nome próprio", "atribuição vaga", "analistas" ou "posição de Helena"
    chave: object   # identifica o fato dentro do episódio: repetições contam uma vez
    rotulo: str     # como está escrito no episódio
    local: str      # "título", "resumo_didatico", "ponto-chave 2", "fala 5 [Helena]"
    frase: str      # a frase em que aparece


@dataclass
class Resultado:
    sem_fonte: list[Achado] = field(default_factory=list)       # não aparece em nenhum texto da pauta
    arredondados: list[Achado] = field(default_factory=list)    # números que a pauta traz com mais precisão
    so_no_corte: list[Achado] = field(default_factory=list)     # aparece, mas só no trecho que o LLM não recebeu
    conferidos: dict[str, int] = field(default_factory=dict)    # quantos fatos diferentes de cada tipo foram examinados
    fontes_faltando: list[str] = field(default_factory=list)    # veículos da pauta fora de fontes_citadas
    divergencia: list[Achado] = field(default_factory=list)     # só com houve_divergencia true


def distintos(achados: list[Achado]) -> dict[str, int]:
    """Quantos fatos diferentes há em cada tipo (o mesmo fato em duas falas conta uma vez)."""
    contagem: dict[str, set] = {}
    for a in achados:
        contagem.setdefault(a.tipo, set()).add(a.chave)
    return {tipo: len(chaves) for tipo, chaves in contagem.items()}


def campos(episodio: dict) -> list[tuple[str, str]]:
    """Os textos conferidos, com o nome de cada lugar: título, resumo, pontos-chave e falas."""
    def texto(valor) -> str:
        return unicodedata.normalize("NFC", valor) if isinstance(valor, str) else ""

    itens = [("título", texto(episodio.get("titulo_reescrito"))), ("resumo_didatico", texto(episodio.get("resumo_didatico")))]
    pontos = episodio.get("pontos_chave")
    itens += [(f"ponto-chave {i}", texto(p)) for i, p in enumerate(pontos if isinstance(pontos, list) else [], 1)]
    itens += [(f"fala {i} [{t.get('personagem')}]", texto(t.get("fala"))) for i, t in enumerate(_roteiro(episodio), 1)]
    return itens


def _roteiro(episodio: dict) -> list[dict]:
    roteiro = episodio.get("roteiro_podcast")
    return [t for t in roteiro if isinstance(t, dict)] if isinstance(roteiro, list) else []


def _palavras_livres(episodio: dict) -> set[str]:
    """Palavras que não pedem fonte: os personagens (nome e papel são criação do episódio), os programas e os genéricos."""
    personagens = episodio.get("personagens")
    personagens = [p for p in personagens if isinstance(p, dict)] if isinstance(personagens, list) else []
    nomes = [p.get("nome", "") for p in personagens] + [t.get("personagem", "") for t in _roteiro(episodio)]
    livres = {t.norm for nome in nomes for t in _tokens(str(nome))}
    livres |= {t.norm for p in personagens for t in _tokens(str(p.get("papel", ""))) if t.maiuscula}
    return livres | PROGRAMAS | TRATAMENTOS | GENERICOS | {HELENA}


def conferir_divergencia(episodio: dict) -> list[Achado]:
    """Com houve_divergencia true: pede dois analistas e lista onde Helena parece tomar posição."""
    if episodio.get("houve_divergencia") is not True:
        return []
    roteiro = _roteiro(episodio)
    analistas = list(dict.fromkeys(str(t.get("personagem")) for t in roteiro if _plano(str(t.get("personagem"))).strip() != HELENA))
    achados = []
    if len(analistas) < 2:
        achados.append(Achado(
            "analistas", "analistas", f"{len(analistas)} analista(s): {', '.join(analistas) or 'nenhum'}", "elenco",
            "houve_divergencia é true, mas o debate pede ao menos um analista por lado.",
        ))
    for i, turno in enumerate(roteiro, 1):
        if _plano(str(turno.get("personagem"))).strip() != HELENA:
            continue
        fala = unicodedata.normalize("NFC", str(turno.get("fala", "")))
        for m in _JUIZOS.finditer(_plano(fala)):
            frase = _frase(fala, m.start())
            antes = fala[fala.find(frase):m.start()] if frase in fala else ""
            em_citacao = sum(antes.count(aspa) for aspa in _ASPAS) % 2 == 1
            if not em_citacao and not _ATRIBUI.search(_plano(frase)):
                achados.append(Achado("posição de Helena", (i, m.group()), fala[m.start():m.end()], f"fala {i} [Helena]", frase))
    return achados


def conferir(episodio: dict, fontes: list[Fonte]) -> Resultado:
    """Confere um episódio contra os artigos da pauta."""
    lida, completa = referencia(f.lido for f in fontes), referencia(f.completo for f in fontes)
    livres = _palavras_livres(episodio)
    textos = campos(episodio)
    confirmados = set().union(*(maiusculas_no_meio(texto) for _, texto in textos))
    r = Resultado()
    vistos: dict[str, set] = {"número": set(), "percentual": set(), "nome próprio": set(), "atribuição vaga": set()}

    for local, texto in textos:
        for n in numeros(texto):
            por_extenso = not n.trecho[0].isdigit()
            if por_extenso and _RETORICA.match(_plano(texto[n.fim:])):
                continue                                 # "dois lados", "dois pilares": contagem de quem fala, não dado
            tipo = "percentual" if n.percentual else "número"
            vistos[tipo].add((n.valor, n.percentual))
            if lida.tem_numero(n):
                continue
            escrito = f"{n.trecho} (= {formatar(n.valor, n.percentual)})" if por_extenso else n.trecho
            origem = completa.origem_do_arredondamento(n)
            if completa.tem_numero(n):
                destino = r.so_no_corte
            elif origem is not None:
                destino, escrito = r.arredondados, f"{escrito} · na pauta: {formatar(origem, n.percentual)}"
            else:
                destino = r.sem_fonte
            destino.append(Achado(tipo, (n.valor, n.percentual), escrito, local, _frase(texto, n.inicio)))
        for nome in nomes_proprios(texto, confirmados):
            vistos["nome próprio"].add(tuple(p for p in nome.palavras if p not in livres))
            falta = lida.palavras_sem_fonte(nome, livres)
            if falta:
                falta_no_completo = completa.palavras_sem_fonte(nome, livres)
                destino, chave = (r.sem_fonte, falta_no_completo) if falta_no_completo else (r.so_no_corte, falta)
                destino.append(Achado("nome próprio", chave, nome.trecho, local, _frase(texto, nome.inicio)))
        for grupo, expressao, posicao in atribuicoes_vagas(texto):
            vistos["atribuição vaga"].add(grupo)
            if not lida.tem_grupo(grupo):
                destino = r.so_no_corte if completa.tem_grupo(grupo) else r.sem_fonte
                destino.append(Achado("atribuição vaga", grupo, expressao, local, _frase(texto, posicao)))

    citadas = episodio.get("fontes_citadas") if isinstance(episodio.get("fontes_citadas"), list) else []
    r.fontes_faltando = [v for v in qa.veiculos_distintos(f.veiculo for f in fontes)
                         if not any(qa.mesmo_veiculo(v, citada) for citada in citadas)]
    r.divergencia = conferir_divergencia(episodio)
    r.conferidos = {tipo: len(chaves - {()}) for tipo, chaves in vistos.items()}
    return r


# ── Relatório ─────────────────────────────────────────────────────────────────────────────

# ── Atribuição a veículo (só diagnóstico) ─────────────────────────────────────────────────

MIN_LETRAS = 4            # palavra mais curta que isto não conta
MIN_RAIZ = 3              # a raiz nunca fica mais curta que isto
# Terminações de verbo e de derivação que a raiz tira, da mais longa para a mais curta (sem acento).
_TERMINACOES = ("amento", "imento", "mente", "acao", "icao", "ando", "endo", "indo", "aram", "eram", "iram", "avam",
                "ado", "ada", "ido", "ida", "ava", "iam", "ou", "iu", "ar", "er", "ir", "am", "em")
_numeros_por_extenso = set(_parcelas) | set(_escalas)
# Antes do nome do veículo, numa janela de até JANELA palavras: "segundo o G1", "de acordo com a Folha".
_MARCADORES = (["segundo"], ["conforme"], ["de", "acordo", "com"])
JANELA = 4
# Depois do nome do veículo: "o G1 relata que...", "a Folha mostrou".
_VERBOS_DE_RELATO = {raiz + fim for raiz in ("relat", "inform", "mostr", "destac", "apont", "registr", "notici", "acrescent",
                                             "detalh", "revel", "explic", "public", "lembr", "report", "descrev")
                     for fim in ("a", "am", "ou", "aram")} | {"diz", "dizem", "disse", "traz", "trouxe", "afirma", "afirmou"}
# Palavras de 4 letras ou mais que não dizem de que fato a frase fala (sem acento).
_SEM_CONTEUDO = {
    "para", "pelo", "pela", "pelos", "pelas", "como", "mais", "menos", "sobre", "entre", "tambem", "ainda", "porque", "quando",
    "onde", "isso", "isto", "esse", "essa", "esses", "essas", "este", "esta", "estes", "estas", "aquele", "aquela", "aqueles",
    "aquelas", "aquilo", "seus", "suas", "dele", "dela", "deles", "delas", "eles", "elas", "muito", "muita", "muitos", "muitas",
    "pode", "podem", "poderia", "seria", "sera", "seja", "sejam", "foram", "sido", "estar", "estao", "estava", "estavam", "tinha",
    "tinham", "teve", "tendo", "temos", "sendo", "apenas", "desde", "apos", "contra", "outro", "outra", "outros", "outras",
    "mesmo", "mesma", "mesmos", "mesmas", "todo", "toda", "todos", "todas", "cada", "qual", "quais", "assim", "entao", "depois",
    "antes", "durante", "nesta", "neste", "nessa", "nesse", "nestas", "nestes", "nessas", "nesses", "dessa", "desse", "dessas",
    "desses", "deste", "desta", "destes", "destas", "pois", "porem", "embora", "enquanto", "fazer", "feito", "aqui", "agora",
    "hoje", "ontem", "segundo", "acordo", "conforme", "alem", "disso", "tanto", "quanto", "qualquer", "algum", "alguma",
    "alguns", "algumas", "nada", "nenhum", "nenhuma", "tudo", "vezes", "coisa", "ponto", "parte", "forma", "caso", "maneira",
    "modo", "lado", "lados", "veiculo", "texto", "reportagem", "informacoes", "dados", "afirma", "afirmou",
    "cento", "porcento", "virgula",
} | _VERBOS_DE_RELATO | {qa._palavras_do_nome(forma)[0] for forma in FORMAS_DE_POSICAO if qa._palavras_do_nome(forma)} \
  | set(_numeros_por_extenso)


def raiz(palavra: str) -> str:
    """A raiz de uma palavra sem acento e em minúsculas: sem plural, gênero e terminação de verbo ou de derivação.

    "derrubou", "derrubado" e "derrubada" dão "derrub"; "publicou" e "publicações", "public";
    "subindo" e "subiram", "sub". Derivações maiores ("Canadá" e "canadense") ficam diferentes.
    """
    if palavra.endswith(("oes", "aes")):
        palavra = palavra[:-3] + "ao"
    elif palavra.endswith(("res", "zes")):
        palavra = palavra[:-2]
    elif palavra.endswith("s") and len(palavra) > MIN_LETRAS:
        palavra = palavra[:-1]
    for fim in _TERMINACOES:
        if palavra.endswith(fim) and len(palavra) - len(fim) >= MIN_RAIZ:
            return palavra[:-len(fim)]
    return palavra[:-1] if palavra.endswith(("a", "o", "e")) and len(palavra) > MIN_LETRAS else palavra


def _raizes(texto) -> set[str]:
    """As raízes das palavras de conteúdo do texto (sem acento, com MIN_LETRAS ou mais): ver `raiz`."""
    return {raiz(p) for p in qa._palavras_do_nome(texto) if len(p) >= MIN_LETRAS and p not in _SEM_CONTEUDO}


def veiculos_atribuidos(frase: str, veiculos) -> list[str]:
    """Os veículos a que a frase atribui algo: "segundo o G1", "de acordo com a Folha", "o G1 relata que..."."""
    palavras = qa._palavras_do_nome(frase)
    achados = []
    for veiculo in veiculos:
        for forma in qa._formas_faladas(veiculo):
            for k in range(len(palavras) - len(forma) + 1):
                if palavras[k:k + len(forma)] != forma:
                    continue
                antes, depois = palavras[max(k - JANELA, 0):k], palavras[k + len(forma):]
                marcado = any(antes[i:i + len(m)] == m for m in _MARCADORES for i in range(len(antes) - len(m) + 1))
                if marcado or (depois and depois[0] in _VERBOS_DE_RELATO):
                    achados.append(veiculo)
                    break
            if veiculo in achados:
                break
    return achados


@dataclass(frozen=True)
class Medida:
    """Quanto das palavras de uma frase atribuída a um veículo está no texto dele e no de outro veículo."""
    contadas: int                   # palavras que contam (ver COMO_LER)
    no_citado: float | None         # a fração delas no texto completo do veículo citado
    outro: str                      # o veículo da pauta, fora o citado, com a maior fração
    no_outro: float | None
    fora_do_citado: tuple[str, ...]  # as palavras que o veículo citado não tem


def medir(frase: str, veiculo: str, fontes: list[Fonte], fora: set[str]) -> Medida:
    """A fração das palavras da frase no texto do veículo citado e a maior num outro veículo da pauta.

    `fora` são as raízes que não contam: nomes de veículos, atores e personagens e as palavras de
    todos os textos da pauta.
    """
    contam = {p for p in qa._palavras_do_nome(frase) if len(p) >= MIN_LETRAS and p not in _SEM_CONTEUDO and raiz(p) not in fora}
    raizes = {raiz(p) for p in contam}
    if not raizes:
        return Medida(0, None, "", None, ())
    por_veiculo = {}
    for v in qa.veiculos_distintos(f.veiculo for f in fontes):
        por_veiculo[v] = set().union(*(_raizes(f.completo) for f in fontes if qa.mesmo_veiculo(f.veiculo, v)))
    citado = next((v for v in por_veiculo if qa.mesmo_veiculo(v, veiculo)), veiculo)
    no_citado = len(raizes & por_veiculo.get(citado, set())) / len(raizes)
    outros = {v: len(raizes & r) / len(raizes) for v, r in por_veiculo.items() if v != citado}
    outro = max(outros, key=outros.get, default="")
    faltam = tuple(sorted(p for p in contam if raiz(p) not in por_veiculo.get(citado, set())))
    return Medida(len(raizes), no_citado, outro, outros.get(outro), faltam)


def _fora_da_conta(episodio: dict, fontes: list[Fonte], atores) -> set[str]:
    """As raízes que não distinguem um veículo do outro: nomes de veículos, atores e personagens e o que todos os textos têm."""
    nomes = [f.veiculo for f in fontes] + list(atores)
    personagens = episodio.get("personagens") if isinstance(episodio.get("personagens"), list) else []
    nomes += [str(p.get("nome", "")) for p in personagens if isinstance(p, dict)] + [str(t.get("personagem", "")) for t in _roteiro(episodio)]
    fora = {raiz(p) for nome in nomes for p in qa._palavras_do_nome(nome)}
    todos = [_raizes(f.completo) for f in fontes]
    return fora | (set.intersection(*todos) if todos else set())


@dataclass(frozen=True)
class Atribuicao:
    local: str          # "resumo_didatico" ou "fala 3 [Bia]"
    frase: str
    veiculo: str
    medida: Medida


def atribuicoes_a_veiculos(episodio: dict, fontes: list[Fonte], atores=()) -> list[Atribuicao]:
    """As frases do resumo e das falas que atribuem algo a um veículo, cada uma com a medida (ver `medir`).

    Só com dois veículos ou mais na pauta: com um só, não há outro veículo para comparar.
    """
    veiculos = qa.veiculos_distintos(f.veiculo for f in fontes)
    if len(veiculos) < 2:
        return []
    fora = _fora_da_conta(episodio, fontes, atores)
    lugares = [("resumo_didatico", episodio.get("resumo_didatico"))]
    lugares += [(f"fala {i} [{t.get('personagem')}]", t.get("fala")) for i, t in enumerate(_roteiro(episodio), 1)]
    achadas = []
    for local, texto in lugares:
        for frase in qa.frases(texto if isinstance(texto, str) else ""):
            achadas += [Atribuicao(local, frase, v, medir(frase, v, fontes, fora)) for v in veiculos_atribuidos(frase, veiculos)]
    return achadas


@dataclass(frozen=True)
class Apresentacao:
    """A frase de um analista que apresenta um lado, com o veículo do lado que ela cita e a medida."""
    lado: int           # a partir de 1
    atores: tuple[str, ...]
    personagem: str
    frase: str
    veiculo: str
    medida: Medida


def apresentacoes_dos_lados(episodio: dict, fontes: list[Fonte], lados: list[Lado]) -> list[Apresentacao]:
    """Nos episódios com 2 lados ou mais, a frase que apresenta cada lado (pela regra do QA) e a medida dela.

    Vale a frase do analista que a correspondência um a um do QA dá ao lado; sem correspondência,
    a de qualquer analista.
    """
    if len(lados) < 2:
        return []
    try:
        achadas = qa.frases_que_apresentam(episodio, lados)
        do_lado = {i: nome for nome, i in qa.lado_de_cada_analista(episodio, lados).items()}
    except (KeyError, TypeError, AttributeError):
        return []
    fora = _fora_da_conta(episodio, fontes, [a for lado in lados for a in lado.atores])
    feitas = []
    for i, (lado, frases) in enumerate(zip(lados, achadas)):
        dele = [(p, f) for p, f in frases if p == do_lado.get(i)] or frases
        for personagem, frase in dele:
            for v in lado.veiculos:
                if qa.veiculo_citado(v, frase):
                    feitas.append(Apresentacao(i + 1, lado.atores, personagem, frase, v, medir(frase, v, fontes, fora)))
    return feitas


def _medida_em_texto(m: Medida) -> str:
    if m.no_citado is None:
        return "nenhuma palavra que distinga os veículos"
    outro = f"; maior em outro veículo: {m.outro} {m.no_outro:.0%}" if m.outro else ""
    return f"{m.no_citado:.0%} de {m.contadas} palavra(s) no citado{outro}"


@dataclass
class Caso:
    """Um episódio do relatório de testar_episodio.py, com a pauta e o resultado da checagem."""
    numero: int
    nome: str
    situacao: str
    episodio: dict
    fontes: list[Fonte]
    resultado: Resultado
    atribuicoes: list[Atribuicao] = field(default_factory=list)
    apresentacoes: list[Apresentacao] = field(default_factory=list)


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _resumo_da_contagem(achados: list[Achado]) -> str:
    por_tipo = distintos(achados)
    partes = [_plural(por_tipo.get("número", 0), "número", "números"),
              _plural(por_tipo.get("percentual", 0), "percentual", "percentuais"),
              _plural(por_tipo.get("nome próprio", 0), "nome próprio", "nomes próprios"),
              _plural(por_tipo.get("atribuição vaga", 0), "atribuição vaga", "atribuições vagas")]
    return f"{sum(por_tipo.values())} ({', '.join(partes)})"


def _listar(achados: list[Achado], textos: dict[str, str]) -> list[str]:
    """Os achados agrupados pelo lugar em que aparecem, cada lugar com o seu texto inteiro."""
    linhas = []
    for local in dict.fromkeys(a.local for a in achados):
        linhas += ["", f"  {local}", f"    \"{textos.get(local, '')}\""]
        for a in (a for a in achados if a.local == local):
            linhas.append(f"    - {a.tipo}: {a.rotulo} · na frase: \"{a.frase}\"")
    return linhas


def montar_relatorio(origem: str, casos: list[Caso], gerado_em: str) -> str:
    linhas = [f"Checagem de fidelidade · {origem}", f"Gerada em {gerado_em} · {len(casos)} episódio(s)", "", COMO_LER]
    for caso in casos:
        ep, r, textos = caso.episodio, caso.resultado, dict(campos(caso.episodio))
        linhas += ["", f"== Episódio {caso.numero} · {caso.nome} · {caso.situacao} ==", f"  título: {textos['título']}", "  pauta:"]
        for f in caso.fontes:
            enviados = len(f.texto) if f.enviado is None else min(f.enviado, len(f.texto))
            linhas.append(f"    [id {f.id}] {f.veiculo} — {f.titulo} ({len(f.texto)} caracteres, {enviados} enviados ao LLM)")
        linhas.append("  números do título:")
        for n in numeros(textos["título"]):
            onde = onde_aparece(n, caso.fontes)
            linhas.append(f"    {n.trecho} · " + (f"na pauta ({onde[0]}): \"{onde[1]}\"" if onde else "NÃO aparece na pauta"))
        if not numeros(textos["título"]):
            linhas.append("    o título não traz números")
        c = r.conferidos
        linhas.append(f"  fatos conferidos: {c.get('número', 0) + c.get('percentual', 0)} números e percentuais, "
                      f"{c.get('nome próprio', 0)} nomes próprios, {c.get('atribuição vaga', 0)} atribuições vagas")
        linhas.append(f"  fatos sem fonte: {_resumo_da_contagem(r.sem_fonte)}")
        linhas.append(f"  números arredondados: {sum(distintos(r.arredondados).values())}")
        linhas.append(f"  fatos com fonte só no trecho que o LLM não recebeu: {_resumo_da_contagem(r.so_no_corte)}")
        linhas.append("  fontes_citadas: " + (f"FALTAM {', '.join(r.fontes_faltando)}" if r.fontes_faltando
                                               else "todos os veículos da pauta estão citados"))
        if ep.get("houve_divergencia") is not True:
            linhas.append("  divergência: houve_divergencia não é true; a regra do debate não se aplica")
        elif not r.divergencia:
            linhas.append("  divergência: houve_divergencia é true; dois ou mais analistas e nenhum indício de posição de Helena")
        else:
            linhas.append(f"  divergência: houve_divergencia é true; {_plural(len(r.divergencia), 'problema', 'problemas')}")
            linhas += [f"    - {a.tipo} ({a.local}): {a.rotulo} · \"{a.frase}\"" for a in r.divergencia]
        if len(qa.veiculos_distintos(f.veiculo for f in caso.fontes)) >= 2:
            linhas.append(f"  atribuições a veículo (diagnóstico): {len(caso.atribuicoes)} frase(s)")
            for a in caso.atribuicoes:
                m = a.medida
                fora = f" · fora do citado: {', '.join(m.fora_do_citado)}" if m.fora_do_citado else ""
                alerta = "  <- OUTRO VEÍCULO TEM MAIS" if m.no_outro is not None and m.no_citado is not None and m.no_outro > m.no_citado else ""
                linhas.append(f"    {a.local} -> {a.veiculo}: {_medida_em_texto(m)}{alerta} · \"{a.frase}\"{fora}")
        if caso.apresentacoes:
            linhas.append("  frase que apresenta cada lado (diagnóstico):")
            for a in caso.apresentacoes:
                linhas.append(f"    lado {a.lado} ({', '.join(a.atores)}) · {a.personagem} · {a.veiculo}: {_medida_em_texto(a.medida)} · \"{a.frase}\"")
        if r.sem_fonte:
            linhas += ["", "  -- Sem fonte --"] + _listar(r.sem_fonte, textos)
        if r.arredondados:
            linhas += ["", "  -- Arredondados (a pauta traz o número mais preciso) --"] + _listar(r.arredondados, textos)
        if r.so_no_corte:
            linhas += ["", "  -- Com fonte só depois do corte (o LLM não recebeu esse trecho) --"] + _listar(r.so_no_corte, textos)

    linhas += ["", "== Resumo =="]
    for caso in casos:
        r = caso.resultado
        linhas.append(
            f"  episódio {caso.numero} ({caso.nome}): {sum(distintos(r.sem_fonte).values())} fato(s) sem fonte · "
            f"{sum(distintos(r.arredondados).values())} arredondado(s) · "
            f"{sum(distintos(r.so_no_corte).values())} só depois do corte · "
            f"{len(r.fontes_faltando)} veículo(s) fora de fontes_citadas · {len(r.divergencia)} problema(s) de divergência · "
            f"{sum(a.medida.no_outro is not None and a.medida.no_citado is not None and a.medida.no_outro > a.medida.no_citado for a in caso.atribuicoes)}"
            f" de {len(caso.atribuicoes)} atribuição(ões) com mais palavras em outro veículo"
        )
    return "\n".join(linhas) + "\n"


# ── Leitura dos arquivos ──────────────────────────────────────────────────────────────────

def _pasta() -> Path:
    return Path(settings.db_path).parent / "agrupamento"


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Confere os episódios de testar_episodio.py contra os textos da pauta.")
    p.add_argument("--relatorio", metavar="ARQUIVO",
                   help="relatorio_<data-hora>.json de testar_episodio.py (padrão: o mais recente)")
    return p.parse_args()


def _carregar(caminho: Path) -> list[Caso]:
    """Os episódios do relatório, cada um com os artigos da pauta tirados da amostra."""
    relatorio = json.loads(caminho.read_text(encoding="utf-8"))
    amostra = Path(relatorio["amostra"])
    if not amostra.exists():
        amostra = Path(__file__).resolve().parents[1] / relatorio["amostra"]
    candidatos = {c["id"]: c for c in json.loads(amostra.read_text(encoding="utf-8"))["candidatos"]}

    casos = []
    for item in relatorio["episodios"]:
        if not item.get("arquivo"):
            print(f"Episódio {item.get('episodio')} sem arquivo gravado ({item.get('situacao')}): fora da checagem.")
            continue
        cortes = item.get("cortes_na_geracao") or []
        fontes = []
        for k, artigo in enumerate(item["artigos"]):
            texto = _limpar(candidatos[artigo["id"]]["texto"])
            corte = cortes[k] if k < len(cortes) and cortes[k].get("texto") == len(texto) else None
            fontes.append(Fonte(artigo["veiculo"], artigo["titulo"], texto, corte["incluido"] if corte else None, artigo["id"],
                                recorte_enviado(texto, corte)))
        episodio = json.loads(Path(item["arquivo"]).read_text(encoding="utf-8"))
        lados = [Lado(lado["posicao"], tuple(lado["atores"]), tuple(lado["veiculos"]), lado.get("resposta", ""))
                 for lado in (item.get("lados") or {}).get("lados", [])]
        atores = [a for lado in lados for a in lado.atores]
        casos.append(Caso(item["episodio"], item["caso"], item["situacao"], episodio, fontes, conferir(episodio, fontes),
                          atribuicoes_a_veiculos(episodio, fontes, atores), apresentacoes_dos_lados(episodio, fontes, lados)))
    return casos


def main() -> None:
    args = _argumentos()
    caminho = Path(args.relatorio) if args.relatorio else max((_pasta() / "episodios").glob("relatorio_*.json"), default=None)
    if caminho is None or not caminho.exists():
        sys.exit("Nenhum relatorio_<data-hora>.json em data/agrupamento/episodios/: rode antes scripts/testar_episodio.py.")
    agora = datetime.datetime.now()
    texto = montar_relatorio(str(caminho), _carregar(caminho), f"{agora:%d/%m/%Y %H:%M:%S}")
    destino = _pasta() / f"fidelidade_{agora:%Y%m%d-%H%M%S}.txt"
    destino.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Relatório: {destino}")


if __name__ == "__main__":
    main()

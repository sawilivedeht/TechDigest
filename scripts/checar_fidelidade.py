"""Checagem de fidelidade dos episódios gerados por testar_episodio.py (sem LLM e sem rede).

Compara cada episódio com os textos da pauta que o gerou e lista o que não tem fonte:

- números, percentuais e nomes próprios do título, do resumo_didatico, dos pontos_chave e das
  falas que não aparecem em nenhum texto da pauta (número por extenso vale pelo algarismo);
- atribuições vagas ("especialistas afirmam", "segundo as análises") a um grupo que a pauta não cita;
- veículos da pauta fora de fontes_citadas;
- com houve_divergencia true: menos de dois analistas, e falas em que Helena parece tomar posição.

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
from techdigest.ai.numeros import Numero, formatar, numeros
from techdigest.ai.numeros import Token as _Token
from techdigest.ai.numeros import dobrar as _plano
from techdigest.ai.numeros import junto as _junto
from techdigest.ai.numeros import tokens as _tokens
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
  Posição de Helena: lista de expressões de juízo fora de citação; é indício para leitura, não prova."""

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

    @property
    def completo(self) -> str:
        return f"{self.veiculo}\n{self.titulo}\n{self.texto}"

    @property
    def lido(self) -> str:
        return f"{self.veiculo}\n{self.titulo}\n{self.texto[:self.enviado]}"


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

@dataclass
class Caso:
    """Um episódio do relatório de testar_episodio.py, com a pauta e o resultado da checagem."""
    numero: int
    nome: str
    situacao: str
    episodio: dict
    fontes: list[Fonte]
    resultado: Resultado


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
            f"{len(r.fontes_faltando)} veículo(s) fora de fontes_citadas · {len(r.divergencia)} problema(s) de divergência"
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
            fontes.append(Fonte(artigo["veiculo"], artigo["titulo"], texto, corte["incluido"] if corte else None, artigo["id"]))
        episodio = json.loads(Path(item["arquivo"]).read_text(encoding="utf-8"))
        casos.append(Caso(item["episodio"], item["caso"], item["situacao"], episodio, fontes, conferir(episodio, fontes)))
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

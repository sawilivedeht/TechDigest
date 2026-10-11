"""Diagnóstico do agrupamento de notícias (etapas 1 e 2 e, a pedido, a etapa 3 com o LLM).

Coleta os feeds, extrai os textos em lote, pontua todos os pares (título e texto) e mostra as
pautas que seriam formadas. Não envia nada ao Telegram, não chama mark_seen e não escreve no
digest.db: o banco é aberto em modo somente leitura. O LLM só é chamado com --etapa3.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/testar_agrupamento.py                    # só os itens ainda não entregues
    python scripts/testar_agrupamento.py --incluir-vistos   # inclui os já entregues (mais amostras)
    python scripts/testar_agrupamento.py --limiar 0.25 --peso-titulo 0.5 --max-candidatos 60
    python scripts/testar_agrupamento.py --incluir-vistos --salvar-amostra   # guarda os candidatos extraídos
    python scripts/testar_agrupamento.py --amostra data/agrupamento/amostra_<data-hora>.json   # sem rede
    python scripts/testar_agrupamento.py --amostra <amostra> --rotulos <rotulos.csv>           # confere com os rótulos
    python scripts/testar_agrupamento.py --amostra <amostra> --rotulos <rotulos.csv> --etapa3 --repeticoes 3

Grava data/agrupamento/pares_<data-hora>.csv com os pares de maior score. A coluna mesmo_fato
fica vazia, para marcar à mão e calibrar os limiares. Cada coleta traz notícias diferentes: para
repetir a mesma comparação com outros limiares, grave uma amostra e rode de novo com --amostra.

Com --etapa3, o LLM do projeto confirma cada pauta provisória de 2 ou mais artigos (uma chamada por
pauta) e o resultado vai para data/agrupamento/etapa3_<data-hora>.csv. Com --rotulos, o resultado é
comparado com um CSV de pares rotulados (colunas id_a, id_b e relacao, com os ids da amostra).
"""
import argparse
import calendar
import csv
import datetime
import json
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from techdigest.ai.llm import get_provider
from techdigest.ai.prompt import PROMPT_AGRUPADOR
from techdigest.collectors import rss
from techdigest.config import Settings
from techdigest.processing import agrupamento as ag
from techdigest.processing.extractor import _eh_google, extrair_em_lote
from techdigest.storage.dedup import SeenStore

settings = Settings()

CSV_SCORE_MIN = 0.15   # pares abaixo disso não vão para o CSV
CSV_MAX_PARES = 100
QUASE_PAUTAS = 10      # pares logo abaixo do limiar mostrados no console
COLUNAS = ("par", "veiculo_a", "titulo_a", "url_a", "veiculo_b", "titulo_b", "url_b",
           "sim_trigramas", "sim_entidades", "sim_texto", "score", "termos_comuns", "duplicata", "mesmo_fato")

TEMPERATURA_ETAPA3 = 0.1   # baixa, para o veredito variar pouco entre execuções
MAX_SAIDA_ETAPA3 = 512     # tokens: a resposta é um JSON curto
# Como cada rótulo entra na conta: quais pares a pauta deve manter juntos e quais deve separar.
ROTULOS_JUNTOS = ("mesmo_acontecimento", "desdobramento")
ROTULOS_SEPARADOS = ("mesmo_tema", "diferente", "sobreposicao_parcial")
COLUNAS_ETAPA3 = ("repeticao", "par", "id_a", "id_b", "veiculo_a", "titulo_a", "veiculo_b", "titulo_b",
                  "rotulo", "esperado", "veredito", "relacao", "acerto", "motivo")


class VistosSomenteLeitura(SeenStore):
    """SeenStore sobre uma conexão somente leitura.

    O construtor original executa CREATE TABLE e cria o arquivo se ele não existir. Aqui a
    conexão é aberta com mode=ro: qualquer escrita, inclusive um mark_seen, falha no SQLite.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)


@dataclass
class Chamada:
    """Uma consulta ao LLM sobre uma pauta provisória, e o que saiu dela."""
    repeticao: int
    provisoria: ag.Pauta
    segundos: float
    tokens: dict           # {"prompt": n, "saida": n}; vazio se a chamada caiu antes da resposta
    motivo: str            # a frase do LLM
    erro: str              # falha da chamada ou problemas do veredito; "" = veredito aproveitado
    finais: list[ag.Pauta]


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Diagnóstico do agrupamento de notícias, sem efeitos colaterais.")
    p.add_argument("--limiar", type=float, default=settings.agrup_limiar,
                   help="score mínimo para unir dois artigos (padrão: AGRUP_LIMIAR = %(default)s)")
    p.add_argument("--peso-titulo", type=float, default=settings.agrup_peso_titulo,
                   help="peso do título no score; o texto fica com o resto (padrão: AGRUP_PESO_TITULO = %(default)s)")
    p.add_argument("--max-candidatos", type=int, default=0,
                   help="manda à extração só os N primeiros itens (padrão: todos)")
    p.add_argument("--incluir-vistos", action="store_true",
                   help="inclui os itens já entregues, para ter mais amostras")
    amostra = p.add_mutually_exclusive_group()
    amostra.add_argument("--salvar-amostra", action="store_true",
                         help="grava os candidatos extraídos em data/agrupamento/amostra_<data-hora>.json")
    amostra.add_argument("--amostra", metavar="ARQUIVO",
                         help="usa os candidatos de uma amostra gravada, sem coletar, extrair nem acessar a rede")
    p.add_argument("--etapa3", action="store_true",
                   help="confirma cada pauta provisória com o LLM do projeto (exige --amostra)")
    p.add_argument("--rotulos", metavar="ARQUIVO",
                   help="compara o resultado com um CSV de pares rotulados (exige --amostra)")
    p.add_argument("--repeticoes", type=int, default=1, metavar="N",
                   help="repete a etapa 3 N vezes, para ver se o veredito muda (padrão: %(default)s)")
    args = p.parse_args()
    if args.amostra and (args.incluir_vistos or args.max_candidatos):
        p.error("--amostra já traz os candidatos: não combina com --incluir-vistos nem com --max-candidatos")
    if (args.etapa3 or args.rotulos) and not args.amostra:
        p.error("--etapa3 e --rotulos exigem --amostra: os rótulos e a comparação valem para uma amostra fixa")
    if args.repeticoes < 1 or (args.repeticoes > 1 and not args.etapa3):
        p.error("--repeticoes é um número a partir de 1 e só vale com --etapa3")
    return args


def _log_no_console() -> None:
    """Mostra o log do coletor e os avisos do extrator, do LLM e do agrupamento junto com o relatório.

    Não chama setup_logging() de propósito: assim nada vai para data/logs/techdigest.log, o
    arquivo que scripts/resumo_lotes.py lê.
    """
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("  %(message)s"))
    raiz = logging.getLogger("techdigest")
    raiz.addHandler(console)
    raiz.setLevel(logging.INFO)
    raiz.propagate = False
    logging.getLogger("techdigest.processing.extractor").setLevel(logging.WARNING)  # sem uma linha por link resolvido
    logging.getLogger("techdigest.ai.llm").setLevel(logging.WARNING)  # tempo e tokens de cada chamada saem no relatório


def _cronometrar(funcao, *args):
    inicio = time.perf_counter()
    resultado = funcao(*args)
    return resultado, time.perf_counter() - inicio


def _linha(rotulo: str, valor: int, obs: str = "", segundos: float | None = None) -> None:
    tempo = f"  [{segundos:.1f} s]" if segundos is not None else ""
    print(f"{rotulo + ' ':.<26} {valor:>5}  {obs}{tempo}".rstrip(), flush=True)


def _curto(texto: str, limite: int = 95) -> str:
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


def _rotulo(c: ag.Candidato) -> str:
    return f"{c.veiculo} — {_curto(c.titulo)}"


def _pasta() -> Path:
    pasta = Path(settings.db_path).parent / "agrupamento"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _coletar() -> tuple[list, dict[str, list]]:
    """Chama o collect_rss e devolve também as entradas de cada feed que ele baixou.

    O collect_rss entrega os artigos sem a data de publicação e com a descrição já sem as tags.
    Para não baixar os feeds duas vezes, o _baixar_feed do coletor é observado durante a chamada:
    a data e a descrição saem das mesmas entradas que viraram artigos.
    """
    feeds: dict[str, list] = {}
    original = rss._baixar_feed

    def baixar_e_guardar(feed_url: str):
        parsed = original(feed_url)
        feeds[feed_url] = parsed.entries
        return parsed

    rss._baixar_feed = baixar_e_guardar
    try:
        return rss.collect_rss(), feeds
    finally:
        rss._baixar_feed = original


def _datas_de_publicacao(feeds: dict[str, list]) -> dict[str, datetime.datetime]:
    """Data de cada link (published, senão updated), em UTC: o mesmo critério do filtro de idade do coletor."""
    datas: dict[str, datetime.datetime] = {}
    for entradas in feeds.values():
        for entrada in entradas:
            t = entrada.get("published_parsed") or entrada.get("updated_parsed")
            if t and entrada.get("link"):
                datas.setdefault(
                    entrada["link"], datetime.datetime.fromtimestamp(calendar.timegm(t), tz=datetime.timezone.utc)
                )
    return datas


def _separar_vistos(artigos: list) -> tuple[list, int]:
    """Devolve (itens ainda não entregues, quantos já foram), consultando o SeenStore sem escrever."""
    try:
        vistos = VistosSomenteLeitura(settings.db_path)
    except sqlite3.OperationalError as e:
        print(f"  digest.db não pôde ser aberto ({e}): todos os itens contam como novos")
        return artigos, 0
    try:
        novos = [a for a in artigos if vistos.is_new(a.url)]
    except sqlite3.OperationalError as e:
        print(f"  digest.db não pôde ser lido ({e}): todos os itens contam como novos")
        return artigos, 0
    finally:
        vistos.conn.close()
    return novos, len(artigos) - len(novos)


def _sem_repetir(itens: list, chave) -> list:
    unicos = {}
    for item in itens:
        unicos.setdefault(chave(item), item)
    return list(unicos.values())


def _coletar_candidatos(args: argparse.Namespace) -> tuple[list[ag.Candidato], dict[str, list]]:
    """Coleta, filtra e extrai. Devolve os candidatos e as entradas dos feeds baixados."""
    (artigos, feeds), segundos = _cronometrar(_coletar)
    _linha("coletados", len(artigos), segundos=segundos)

    novos, ja_vistos = _separar_vistos(artigos)
    if args.incluir_vistos:
        _linha("já vistos", ja_vistos, "mantidos (--incluir-vistos)")
    else:
        _linha("já vistos", ja_vistos, "ignorados (--incluir-vistos mantém)")
        artigos = novos

    unicos = _sem_repetir(artigos, lambda a: a.url)
    _linha("duplicados (link)", len(artigos) - len(unicos), "o collect_rss já descarta links repetidos entre feeds")
    artigos = unicos
    if args.max_candidatos and len(artigos) > args.max_candidatos:
        _linha("fora do --max-candidatos", len(artigos) - args.max_candidatos)
        artigos = artigos[:args.max_candidatos]

    print(f"  extraindo {len(artigos)} itens: até {settings.extracao_workers} em paralelo, "
          f"{settings.extracao_workers_gnews} no Google Notícias...", flush=True)
    extracoes, segundos = _cronometrar(extrair_em_lote, [(a.url, a.summary) for a in artigos])
    extraidos = sum(e.extraido for e in extracoes)
    _linha("extraídos", extraidos, f"sem extração (ficam com o resumo do feed): {len(artigos) - extraidos}", segundos)

    itens = list(zip(artigos, extracoes))
    unicos = _sem_repetir(itens, lambda item: ag.url_canonica(item[1].url_resolvida or item[0].url))
    _linha("duplicados (URL)", len(itens) - len(unicos), "mesma URL canônica do veículo por feeds diferentes")
    com_texto = [(a, e) for a, e in unicos if len(e.texto) >= settings.min_texto_chars]
    _linha("descartados", len(unicos) - len(com_texto), f"texto com menos de {settings.min_texto_chars} caracteres")

    publicacao = _datas_de_publicacao(feeds)
    candidatos = []
    for artigo, extracao in com_texto:
        titulo, veiculo = ag.separar_veiculo(artigo.title, artigo.source)
        candidatos.append(ag.Candidato(
            titulo=titulo, veiculo=veiculo, url=artigo.url,
            url_veiculo=extracao.url_resolvida or artigo.url, texto=extracao.texto,
            data=publicacao.get(artigo.url),
        ))
    return candidatos, feeds


def _gravar_amostra(candidatos: list[ag.Candidato], incluir_vistos: bool, carimbo: str) -> Path:
    """Guarda os candidatos já extraídos, para repetir a comparação sem coletar de novo.

    O id é a posição do candidato na execução, a partir de 1; `url` é o link do feed.
    """
    conteudo = {
        "criada_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "incluir_vistos": incluir_vistos,
        "candidatos": [
            {"id": n, "veiculo": c.veiculo, "titulo": c.titulo, "url": c.url, "url_resolvida": c.url_veiculo,
             "data": c.data.isoformat() if c.data else None, "texto": c.texto}
            for n, c in enumerate(candidatos, 1)
        ],
    }
    caminho = _pasta() / f"amostra_{carimbo}.json"
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
    return caminho


def _carregar_amostra(caminho: str) -> tuple[list[ag.Candidato], dict[ag.Candidato, int]]:
    """Candidatos de uma amostra gravada com --salvar-amostra, na mesma ordem, e o id de cada um. Sem rede."""
    try:
        conteudo = json.loads(Path(caminho).read_text(encoding="utf-8"))
        ids = {
            ag.Candidato(titulo=c["titulo"], veiculo=c["veiculo"], url=c["url"], url_veiculo=c["url_resolvida"],
                         texto=c["texto"], data=datetime.datetime.fromisoformat(c["data"]) if c["data"] else None): c["id"]
            for c in conteudo["candidatos"]
        }
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"Amostra ilegível ({type(e).__name__}: {e}): {caminho}")
    _linha("amostra", len(ids), f"{caminho} (criada em {conteudo.get('criada_em', '?')})")
    return list(ids), ids


def _mostrar_pautas(pautas: list[ag.Pauta], args: argparse.Namespace) -> None:
    com_varios = [p for p in pautas if p.relacionados]
    print(f"\n== Pautas provisórias com 2 ou mais artigos: {len(com_varios)} "
          f"(limiar {args.limiar:.2f} · peso do título {args.peso_titulo:.2f} · "
          f"até {settings.agrup_max_artigos} artigos) ==")
    for n, pauta in enumerate(com_varios, 1):
        numero = {c: i for i, c in enumerate(pauta.artigos, 1)}
        print(f"\nPauta {n} · {len(pauta.artigos)} artigos · {len(pauta.veiculos)} veículo(s) distinto(s)")
        for c, i in numero.items():
            print(f"  [{i}] {_rotulo(c)}{'  (principal)' if i == 1 else ''}")
            print(f"      {c.url_veiculo}")
        for par in pauta.pares:
            i, j = sorted((numero[par.a], numero[par.b]))
            print(f"  [{i}]×[{j}] score {par.score:.2f} = título {par.sim_titulo:.2f} "
                  f"(trigramas {par.sim_trigramas:.2f}, entidades {par.sim_entidades:.2f}) · texto {par.sim_texto:.2f}")
            print(f"      entidades em comum: {', '.join(par.entidades_comuns) or '-'}")
            print(f"      termos em comum: {', '.join(par.termos_comuns) or '-'}")
        for d in pauta.duplicatas:
            print(f"  republicação, não conta como fonte: {_rotulo(d)}")


def _mostrar_pares(titulo: str, pares: list[ag.ParPontuado]) -> None:
    print(f"\n== {titulo} ==")
    if not pares:
        print("  nenhum")
    for par in pares:
        print(f"  {par.score:.2f} (título {par.sim_titulo:.2f} · texto {par.sim_texto:.2f})  {_rotulo(par.a)}")
        print(f"{'':35}{_rotulo(par.b)}")
        print(f"{'':35}termos em comum: {', '.join(par.termos_comuns) or '-'}")


def _descricoes_do_google(feeds: dict[str, list] | None) -> None:
    """Relata se as descrições do Google Notícias listam outras coberturas do mesmo fato.

    O collect_rss guarda a descrição já sem as tags; o HTML vem das entradas observadas durante
    a coleta. Nada disso entra no agrupamento ainda.
    """
    print("\n== Descrições dos itens do Google Notícias ==")
    if feeds is None:
        print("  não examinadas: com --amostra não há coleta")
        return
    do_google = [entradas for feed, entradas in feeds.items() if _eh_google(feed)]
    itens = com_lista = com_varios_links = 0
    for entradas in do_google:
        for entrada in entradas:
            descricao = entrada.get("summary", "")
            itens += 1
            com_lista += bool(re.search(r"<li\b", descricao))
            com_varios_links += len(re.findall(r"<a\b", descricao)) > 1
    if not itens:
        print("  nenhum item do Google Notícias para examinar")
        return
    print(f"  {len(do_google)} feed(s), {itens} itens: {com_lista} com lista (<li>), "
          f"{com_varios_links} com mais de um link")
    if com_lista or com_varios_links:
        print("  Há descrições que listam outras coberturas do mesmo fato (ainda não usadas no agrupamento).")
    else:
        print("  Nenhuma descrição lista outras coberturas: cada uma traz só o link e o veículo do próprio item.")


def _gravar_csv(pares: list[ag.ParPontuado], carimbo: str) -> tuple[Path, int]:
    escolhidos = [p for p in pares if p.score >= CSV_SCORE_MIN][:CSV_MAX_PARES]
    caminho = _pasta() / f"pares_{carimbo}.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        saida = csv.writer(arquivo)
        saida.writerow(COLUNAS)
        for n, p in enumerate(escolhidos, 1):
            saida.writerow([
                n, p.a.veiculo, p.a.titulo, p.a.url_veiculo, p.b.veiculo, p.b.titulo, p.b.url_veiculo,
                f"{p.sim_trigramas:.4f}", f"{p.sim_entidades:.4f}", f"{p.sim_texto:.4f}", f"{p.score:.4f}",
                "; ".join(p.termos_comuns), "sim" if p.duplicata else "não", "",
            ])
    return caminho, len(escolhidos)


# ── Etapa 3 (LLM) e comparação com os rótulos ─────────────────────────────────────────────

def _membros(pauta: ag.Pauta) -> tuple[ag.Candidato, ...]:
    """Os artigos que a pauta juntou: os que vão para a geração e os que passaram do limite."""
    return (*pauta.artigos, *pauta.excedentes)


def _pauta_de_cada(pautas: list[ag.Pauta]) -> dict[ag.Candidato, ag.Pauta]:
    return {c: p for p in pautas for c in _membros(p)}


def _todos_isolados(pauta: ag.Pauta) -> list[ag.Pauta]:
    """A pauta desfeita, cada artigo sozinho: o destino de uma chamada que falhou (na dúvida, não juntar)."""
    isolados = {"grupos": [], "isolados": list(range(1, len(pauta.artigos) + 1))}
    return ag.compor_pautas(pauta, isolados, settings.agrup_max_artigos)


def _consultar_llm(provider, pauta: ag.Pauta, repeticao: int) -> Chamada:
    """Pede ao LLM o veredito sobre uma pauta provisória e compõe as pautas finais."""
    provider.ultimo_uso = {}
    inicio = time.perf_counter()
    try:
        resposta = provider.chat_json(
            PROMPT_AGRUPADOR, ag.entrada_agrupador(pauta, settings.agrup_chars_etapa3), chaves=ag.CHAVES_AGRUPADOR,
            temperatura=TEMPERATURA_ETAPA3, max_saida=MAX_SAIDA_ETAPA3,
        )
    except Exception as e:  # resposta vazia, cortada, sem as chaves, servidor fora do ar...
        segundos = time.perf_counter() - inicio
        erro = f"a chamada falhou ({type(e).__name__}: {str(e)[:160]})"
        return Chamada(repeticao, pauta, segundos, dict(provider.ultimo_uso), "", erro, _todos_isolados(pauta))
    segundos = time.perf_counter() - inicio
    problemas = ag.problemas_do_veredito(resposta, len(pauta.artigos))
    motivo = resposta.get("motivo") if isinstance(resposta.get("motivo"), str) else ""
    erro = f"veredito descartado ({'; '.join(problemas)})" if problemas else ""
    finais = ag.compor_pautas(pauta, resposta, settings.agrup_max_artigos)
    return Chamada(repeticao, pauta, segundos, dict(provider.ultimo_uso), motivo, erro, finais)


def _resumo_do_veredito(chamada: Chamada, ids: dict[ag.Candidato, int]) -> str:
    grupos = []
    for final in chamada.finais:
        if len(_membros(final)) > 1:
            outros = [f"{ids[c]} ({final.relacoes.get(c, '?')}{', excedente' if c in final.excedentes else ''})"
                      for c in _membros(final)[1:]]
            grupos.append(f"{ids[final.principal]} + " + " + ".join(outros))
    sozinhos = [str(ids[final.principal]) for final in chamada.finais if len(_membros(final)) == 1]
    return f"juntos: {'; '.join(grupos) or '-'} · isolados: {', '.join(sozinhos) or '-'}"


def _rodar_etapa3(provisorias: list[ag.Pauta], ids: dict[ag.Candidato, int], repeticoes: int) -> list[Chamada]:
    """Uma chamada ao LLM por pauta provisória de 2 ou mais artigos, em cada repetição."""
    print(f"\n== Etapa 3: o LLM confirma {len(provisorias)} pauta(s) provisória(s), {repeticoes} vez(es) "
          f"(temperatura {TEMPERATURA_ETAPA3}, saída de até {MAX_SAIDA_ETAPA3} tokens, "
          f"{settings.agrup_chars_etapa3} caracteres de cada texto) ==", flush=True)
    if not provisorias:
        print("  nenhuma pauta provisória com 2 ou mais artigos: nada a confirmar")
        return []
    provider = get_provider(settings)
    modelo = settings.ollama_model if settings.llm_provider == "ollama" else settings.openai_model
    print(f"  modelo: {modelo} ({settings.llm_provider})", flush=True)
    chamadas = []
    for repeticao in range(1, repeticoes + 1):
        for n, pauta in enumerate(provisorias, 1):
            chamada = _consultar_llm(provider, pauta, repeticao)
            chamadas.append(chamada)
            tokens = (f"{chamada.tokens.get('prompt', 0)} + {chamada.tokens.get('saida', 0)} tokens"
                      if chamada.tokens else "sem contagem de tokens")
            print(f"  [repetição {repeticao}] pauta {n}/{len(provisorias)} · {len(pauta.artigos)} artigos "
                  f"(ids {', '.join(str(ids[c]) for c in pauta.artigos)}) · {chamada.segundos:.1f} s · {tokens}")
            print(f"      {chamada.erro or _resumo_do_veredito(chamada, ids)}")
            if chamada.motivo:
                print(f"      motivo: {chamada.motivo}", flush=True)

    tempos = [c.segundos for c in chamadas]
    com_tokens = [c.tokens for c in chamadas if c.tokens] or [{}]
    entrada, saida = (sum(t.get(chave, 0) for t in com_tokens) / len(com_tokens) for chave in ("prompt", "saida"))
    print(f"\n  {len(chamadas)} chamadas em {sum(tempos):.0f} s: média de {sum(tempos) / len(tempos):.1f} s por chamada "
          f"(de {min(tempos):.1f} a {max(tempos):.1f} s)")
    print(f"  tokens por chamada, em média: {entrada:.0f} de entrada e {saida:.0f} de saída")
    print(f"  chamadas que falharam: {sum(c.erro.startswith('a chamada falhou') for c in chamadas)} · "
          f"vereditos descartados: {sum(c.erro.startswith('veredito descartado') for c in chamadas)}")
    return chamadas


def _ler_rotulos(caminho: str, amostra: str) -> list[dict]:
    """Linhas do CSV de rótulos (id_a, id_b, relacao; os ids são os da amostra)."""
    try:
        with open(caminho, newline="", encoding="utf-8") as arquivo:
            linhas = list(csv.DictReader(arquivo))
        rotulos = [{"par": linha.get("par", ""), "id_a": int(linha["id_a"]), "id_b": int(linha["id_b"]),
                    "relacao": linha["relacao"].strip()} for linha in linhas]
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"CSV de rótulos ilegível ({type(e).__name__}: {e}): {caminho}")
    de_outra = {linha.get("amostra") for linha in linhas} - {None, "", Path(amostra).name}
    if de_outra:
        print(f"  ATENÇÃO: os rótulos dizem ser de outra amostra ({', '.join(sorted(de_outra))}); os ids podem não bater")
    return rotulos


def _situacao_do_par(a: ag.Candidato, b: ag.Candidato, provisoria_de: dict, final_de: dict, com_llm: bool) -> tuple[str, str]:
    """(veredito, relação) de um par: "juntos", "separados" ou "fora da etapa 3"."""
    if com_llm and (a not in provisoria_de or provisoria_de[a] is not provisoria_de.get(b)):
        return "fora da etapa 3", ""
    pauta = final_de.get(a)
    if pauta is None or pauta is not final_de.get(b):
        return "separados", ""
    if not pauta.relacoes:
        return "juntos", ""
    if pauta.principal in (a, b):
        return "juntos", pauta.relacoes.get(b if pauta.principal is a else a, "")
    ambos_iguais = pauta.relacoes.get(a) == pauta.relacoes.get(b) == "mesmo_acontecimento"
    return "juntos", "mesmo_acontecimento" if ambos_iguais else "desdobramento"


def _linhas_da_comparacao(
    rotulos: list[dict], provisorias: list[ag.Pauta], finais_por_repeticao: dict[int, list[ag.Pauta]],
    motivos: dict[tuple[int, ag.Pauta | None], str], por_id: dict[int, ag.Candidato], ids: dict[ag.Candidato, int],
    com_llm: bool,
) -> list[dict]:
    """Uma linha por repetição e por par: os pares rotulados e os que ficaram numa mesma pauta provisória."""
    provisoria_de = _pauta_de_cada(provisorias)
    rotulo_de = {frozenset((r["id_a"], r["id_b"])): r for r in rotulos}
    pares = dict.fromkeys(rotulo_de)
    for pauta in provisorias:
        pares.update(dict.fromkeys(frozenset((ids[a], ids[b])) for a, b in combinations(pauta.artigos, 2)))

    linhas = []
    for repeticao, finais in finais_por_repeticao.items():
        final_de = _pauta_de_cada(finais)
        for par in pares:
            rotulo = rotulo_de.get(par, {})
            id_a, id_b = (rotulo["id_a"], rotulo["id_b"]) if rotulo else sorted(par)
            a, b = por_id.get(id_a), por_id.get(id_b)
            if a is None or b is None:
                print(f"  ATENÇÃO: par rotulado com id fora da amostra: {id_a} × {id_b}")
                continue
            veredito, relacao = _situacao_do_par(a, b, provisoria_de, final_de, com_llm)
            relacao_rotulada = rotulo.get("relacao", "")
            esperado = ("juntos" if relacao_rotulada in ROTULOS_JUNTOS
                        else "separados" if relacao_rotulada in ROTULOS_SEPARADOS else "")
            acerto = "" if not esperado or veredito == "fora da etapa 3" else ("sim" if veredito == esperado else "não")
            linhas.append({
                "repeticao": repeticao, "par": rotulo.get("par", ""), "id_a": id_a, "id_b": id_b,
                "veiculo_a": a.veiculo, "titulo_a": a.titulo, "veiculo_b": b.veiculo, "titulo_b": b.titulo,
                "rotulo": relacao_rotulada, "esperado": esperado, "veredito": veredito, "relacao": relacao,
                "acerto": acerto, "motivo": motivos.get((repeticao, provisoria_de.get(a)), "") if veredito != "fora da etapa 3" else "",
            })
    return linhas


def _descrever(linha: dict) -> str:
    par = f"par {linha['par']} · " if linha["par"] else ""
    return (f"{par}id {linha['id_a']} × id {linha['id_b']} · {linha['veiculo_a']} × {linha['veiculo_b']} · "
            f"rótulo {linha['rotulo'] or '(sem rótulo)'}")


def _mostrar_comparacao(linhas: list[dict], caminho_rotulos: str, com_llm: bool) -> None:
    quem = "LLM" if com_llm else "limiar das etapas 1 e 2"
    print(f"\n== Comparação com os rótulos ({caminho_rotulos}) ==")
    print(f"  devem ficar juntos: {', '.join(ROTULOS_JUNTOS)} · separados: {', '.join(ROTULOS_SEPARADOS)}")
    repeticoes = sorted({linha["repeticao"] for linha in linhas})
    primeira = [linha for linha in linhas if linha["repeticao"] == repeticoes[0]]

    julgados = [linha for linha in primeira if linha["acerto"]]
    print(f"\n  Pares rotulados julgados pelo {quem}: {len(julgados)}")
    for repeticao in repeticoes:
        da_vez = [linha for linha in linhas if linha["repeticao"] == repeticao and linha["acerto"]]
        acertos = sum(linha["acerto"] == "sim" for linha in da_vez)
        rotulo_da_vez = f"repetição {repeticao}: " if len(repeticoes) > 1 else ""
        print(f"    {rotulo_da_vez}{acertos} acertos e {len(da_vez) - acertos} erros")
        for linha in da_vez:
            if linha["acerto"] == "não":
                print(f"      ERRO · {_descrever(linha)} · ficou {linha['veredito']}"
                      + (f" ({linha['relacao']})" if linha["relacao"] else ""))
                if linha["motivo"]:
                    print(f"             motivo do LLM: {linha['motivo']}")

    if com_llm:
        fora = [linha for linha in primeira if linha["veredito"] == "fora da etapa 3" and linha["esperado"]]
        perdas = [linha for linha in fora if linha["esperado"] == "juntos"]
        print(f"\n  Pares rotulados que não chegaram à etapa 3: {len(fora)}")
        print(f"    perdas das etapas 1 e 2 (deviam estar juntos): {len(perdas)}")
        for linha in perdas:
            print(f"      {_descrever(linha)}")
        ja_separados = [linha["par"] or f"{linha['id_a']}×{linha['id_b']}" for linha in fora if linha["esperado"] == "separados"]
        print(f"    já separados pelas etapas 1 e 2, como deviam: {len(ja_separados)}"
              + (f" (pares {', '.join(map(str, ja_separados))})" if ja_separados else ""))

    fora_da_conta = [linha for linha in primeira if not linha["esperado"]]
    print(f"\n  Fora da conta (rótulo duvidoso ou desconhecido, ou par sem rótulo): {len(fora_da_conta)}")
    for linha in fora_da_conta:
        print(f"    {_descrever(linha)} · ficou {linha['veredito']}" + (f" ({linha['relacao']})" if linha["relacao"] else ""))

    if len(repeticoes) > 1:
        historico: dict[tuple, list] = {}
        for linha in linhas:
            if linha["veredito"] != "fora da etapa 3":
                historico.setdefault((linha["id_a"], linha["id_b"]), []).append(linha)
        mudaram = [vezes for vezes in historico.values() if len({(l["veredito"], l["relacao"]) for l in vezes}) > 1]
        print(f"\n  Pares cujo veredito mudou entre as {len(repeticoes)} repetições: {len(mudaram)} de {len(historico)}")
        for vezes in mudaram:
            sequencia = " → ".join(l["veredito"] + (f" ({l['relacao']})" if l["relacao"] else "") for l in vezes)
            print(f"    {_descrever(vezes[0])}: {sequencia}")


def _mostrar_pautas_finais(finais: list[ag.Pauta], ids: dict[ag.Candidato, int], repeticoes: int) -> None:
    juntas = [p for p in finais if len(_membros(p)) > 1]
    print(f"\n== Pautas finais com 2 ou mais artigos: {len(juntas)}"
          + (" (repetição 1)" if repeticoes > 1 else "") + " ==")
    for n, pauta in enumerate(juntas, 1):
        print(f"\nPauta final {n} · {len(pauta.artigos)} texto(s) para a geração · {len(pauta.veiculos)} veículo(s) distinto(s)")
        print(f"  principal:    [id {ids[pauta.principal]}] {_rotulo(pauta.principal)}")
        for c in pauta.relacionados:
            print(f"  relacionado:  [id {ids[c]}] {_rotulo(c)}  ({pauta.relacoes.get(c, '?')})")
        for c in pauta.excedentes:
            print(f"  excedente:    [id {ids[c]}] {_rotulo(c)}  ({pauta.relacoes.get(c, '?')})")
        for c in pauta.duplicatas:
            print(f"  republicação: {_rotulo(c)}")
        if pauta.motivo:
            print(f"  motivo: {pauta.motivo}")


def _gravar_etapa3(linhas: list[dict], carimbo: str) -> Path:
    caminho = _pasta() / f"etapa3_{carimbo}.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        saida = csv.DictWriter(arquivo, fieldnames=COLUNAS_ETAPA3)
        saida.writeheader()
        saida.writerows(linhas)
    return caminho


def _etapa3_e_rotulos(args: argparse.Namespace, pautas: list[ag.Pauta], ids: dict[ag.Candidato, int], carimbo: str) -> None:
    """Confirma as pautas provisórias com o LLM (--etapa3) e confere o resultado com os rótulos (--rotulos)."""
    provisorias = [p for p in pautas if p.relacionados]
    sozinhas = [p for p in pautas if not p.relacionados]
    motivos: dict[tuple[int, ag.Pauta | None], str] = {}
    if args.etapa3:
        chamadas = _rodar_etapa3(provisorias, ids, args.repeticoes)
        finais_por_repeticao = {r: list(sozinhas) for r in range(1, args.repeticoes + 1)}
        for chamada in chamadas:
            finais_por_repeticao[chamada.repeticao] += chamada.finais
            motivos[chamada.repeticao, chamada.provisoria] = chamada.erro or chamada.motivo
    else:
        finais_por_repeticao = {1: pautas}

    rotulos = _ler_rotulos(args.rotulos, args.amostra) if args.rotulos else []
    por_id = {n: c for c, n in ids.items()}
    linhas = _linhas_da_comparacao(rotulos, provisorias, finais_por_repeticao, motivos, por_id, ids, com_llm=args.etapa3)
    if args.rotulos:
        _mostrar_comparacao(linhas, args.rotulos, com_llm=args.etapa3)
    if args.etapa3:
        _mostrar_pautas_finais(finais_por_repeticao[1], ids, args.repeticoes)
        print(f"\nEtapa 3: {_gravar_etapa3(linhas, carimbo)} ({len(linhas)} linhas: um par por repetição)")


def main() -> None:
    args = _argumentos()
    _log_no_console()
    carimbo = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"

    print("== Etapas ==", flush=True)
    feeds = amostra_gravada = None
    if args.amostra:
        candidatos, ids = _carregar_amostra(args.amostra)
    else:
        candidatos, feeds = _coletar_candidatos(args)
        ids = {c: n for n, c in enumerate(candidatos, 1)}
        if args.salvar_amostra:
            amostra_gravada = _gravar_amostra(candidatos, args.incluir_vistos, carimbo)
            sem_data = sum(1 for c in candidatos if c.data is None)
            print(f"  amostra gravada: {amostra_gravada}" + (f" ({sem_data} sem data)" if sem_data else ""), flush=True)
    _linha("candidatos", len(candidatos))
    if len(candidatos) < 2:
        print("\nMenos de dois candidatos: não há pares para comparar.")
        return

    titulos, segundos = _cronometrar(ag.comparar_titulos, candidatos, settings.agrup_chars_texto)
    _linha("etapa 1 (título)", len(titulos), "pares", segundos)
    textos, segundos = _cronometrar(ag.comparar_textos, candidatos, settings.agrup_chars_texto)
    _linha("etapa 2 (texto)", len(textos), "pares", segundos)

    pares = ag.pontuar_pares(candidatos, titulos, textos, args.peso_titulo, settings.agrup_limiar_duplicata)
    pautas, barrados = ag.formar_pautas(candidatos, pares, args.limiar, settings.agrup_max_artigos)
    duplicatas = [p for p in pares if p.duplicata]
    perto = [p for p in pares if CSV_SCORE_MIN <= p.score < args.limiar and not p.duplicata]
    _linha("pares no limiar", sum(p.score >= args.limiar for p in pares), f"score ≥ {args.limiar:.2f}")
    _linha("pares perto do limiar", len(perto), f"score entre {CSV_SCORE_MIN:.2f} e {args.limiar:.2f}")
    _linha("pautas provisórias", len(pautas), f"{sum(1 for p in pautas if p.relacionados)} com 2 ou mais artigos")

    _mostrar_pautas(pautas, args)
    _mostrar_pares(f"Pares no limiar barrados pelo teto de {settings.agrup_max_artigos} artigos: {len(barrados)}", barrados)
    _mostrar_pares(f"Republicações (similaridade de texto ≥ {settings.agrup_limiar_duplicata:.2f}): {len(duplicatas)}",
                   duplicatas)
    _mostrar_pares(f"Pares de maior score abaixo do limiar (até {QUASE_PAUTAS}, a partir de {CSV_SCORE_MIN:.2f})",
                   perto[:QUASE_PAUTAS])
    _descricoes_do_google(feeds)

    caminho, gravados = _gravar_csv(pares, carimbo)
    print(f"\nCSV: {caminho} ({gravados} pares com score ≥ {CSV_SCORE_MIN:.2f}; marque a coluna mesmo_fato)")
    if amostra_gravada:
        print(f"Amostra: {amostra_gravada} ({len(candidatos)} candidatos; reuse com --amostra)")
    if args.etapa3 or args.rotulos:
        _etapa3_e_rotulos(args, pautas, ids, carimbo)


if __name__ == "__main__":
    main()

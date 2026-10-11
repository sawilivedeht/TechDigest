"""Diagnóstico do agrupamento de notícias (Fase 1).

Coleta os feeds, extrai os textos em lote, pontua todos os pares (título e texto) e mostra as
pautas que seriam formadas. Não chama o LLM, não envia nada ao Telegram, não chama mark_seen e
não escreve no digest.db: o banco é aberto em modo somente leitura.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/testar_agrupamento.py                    # só os itens ainda não entregues
    python scripts/testar_agrupamento.py --incluir-vistos   # inclui os já entregues (mais amostras)
    python scripts/testar_agrupamento.py --limiar 0.25 --peso-titulo 0.5 --max-candidatos 60
    python scripts/testar_agrupamento.py --incluir-vistos --salvar-amostra   # guarda os candidatos extraídos
    python scripts/testar_agrupamento.py --amostra data/agrupamento/amostra_<data-hora>.json   # sem rede

Grava data/agrupamento/pares_<data-hora>.csv com os pares de maior score. A coluna mesmo_fato
fica vazia, para marcar à mão e calibrar os limiares. Cada coleta traz notícias diferentes: para
repetir a mesma comparação com outros limiares, grave uma amostra e rode de novo com --amostra.
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
from pathlib import Path

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


class VistosSomenteLeitura(SeenStore):
    """SeenStore sobre uma conexão somente leitura.

    O construtor original executa CREATE TABLE e cria o arquivo se ele não existir. Aqui a
    conexão é aberta com mode=ro: qualquer escrita, inclusive um mark_seen, falha no SQLite.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)


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
    args = p.parse_args()
    if args.amostra and (args.incluir_vistos or args.max_candidatos):
        p.error("--amostra já traz os candidatos: não combina com --incluir-vistos nem com --max-candidatos")
    return args


def _log_no_console() -> None:
    """Mostra o log do coletor e os avisos do extrator junto com o relatório.

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


def _coletar_candidatos(args: argparse.Namespace) -> tuple[list[ag.Candidato], list, dict[str, list]]:
    """Coleta, filtra e extrai. Devolve (candidatos, a data de publicação de cada um, entradas dos feeds)."""
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
    candidatos, datas = [], []
    for artigo, extracao in com_texto:
        titulo, veiculo = ag.separar_veiculo(artigo.title, artigo.source)
        candidatos.append(ag.Candidato(
            titulo=titulo, veiculo=veiculo, url=artigo.url,
            url_veiculo=extracao.url_resolvida or artigo.url, texto=extracao.texto,
        ))
        datas.append(publicacao.get(artigo.url))
    return candidatos, datas, feeds


def _gravar_amostra(candidatos: list[ag.Candidato], datas: list, incluir_vistos: bool, carimbo: str) -> Path:
    """Guarda os candidatos já extraídos, para repetir a comparação sem coletar de novo.

    O id é a posição do candidato na execução, a partir de 1; `url` é o link do feed.
    """
    conteudo = {
        "criada_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "incluir_vistos": incluir_vistos,
        "candidatos": [
            {"id": n, "veiculo": c.veiculo, "titulo": c.titulo, "url": c.url, "url_resolvida": c.url_veiculo,
             "data": data.isoformat() if data else None, "texto": c.texto}
            for n, (c, data) in enumerate(zip(candidatos, datas), 1)
        ],
    }
    caminho = _pasta() / f"amostra_{carimbo}.json"
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8")
    return caminho


def _carregar_amostra(caminho: str) -> list[ag.Candidato]:
    """Candidatos de uma amostra gravada com --salvar-amostra, na mesma ordem. Não acessa a rede."""
    try:
        conteudo = json.loads(Path(caminho).read_text(encoding="utf-8"))
        candidatos = [
            ag.Candidato(titulo=c["titulo"], veiculo=c["veiculo"], url=c["url"],
                         url_veiculo=c["url_resolvida"], texto=c["texto"])
            for c in conteudo["candidatos"]
        ]
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"Amostra ilegível ({type(e).__name__}: {e}): {caminho}")
    _linha("amostra", len(candidatos), f"{caminho} (criada em {conteudo.get('criada_em', '?')})")
    return candidatos


def _mostrar_pautas(pautas: list[ag.Pauta], args: argparse.Namespace) -> None:
    com_varios = [p for p in pautas if p.relacionados]
    print(f"\n== Pautas com 2 ou mais artigos: {len(com_varios)} "
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


def main() -> None:
    args = _argumentos()
    _log_no_console()
    carimbo = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"

    print("== Etapas ==", flush=True)
    feeds = amostra_gravada = None
    if args.amostra:
        candidatos = _carregar_amostra(args.amostra)
    else:
        candidatos, datas, feeds = _coletar_candidatos(args)
        if args.salvar_amostra:
            amostra_gravada = _gravar_amostra(candidatos, datas, args.incluir_vistos, carimbo)
            sem_data = sum(1 for data in datas if data is None)
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
    _linha("pautas", len(pautas), f"{sum(1 for p in pautas if p.relacionados)} com 2 ou mais artigos")

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


if __name__ == "__main__":
    main()

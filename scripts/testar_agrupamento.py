"""Diagnóstico do agrupamento de notícias (Fase 1).

Coleta os feeds, extrai os textos em lote, pontua todos os pares (título e texto) e mostra as
pautas que seriam formadas. Não chama o LLM, não envia nada ao Telegram, não chama mark_seen e
não escreve no digest.db: o banco é aberto em modo somente leitura.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/testar_agrupamento.py                    # só os itens ainda não entregues
    python scripts/testar_agrupamento.py --incluir-vistos   # inclui os já entregues (mais amostras)
    python scripts/testar_agrupamento.py --limiar 0.25 --peso-titulo 0.5 --max-candidatos 60

Grava data/agrupamento/pares_<data-hora>.csv com os pares de maior score. A coluna mesmo_fato
fica vazia, para marcar à mão e calibrar os limiares.
"""
import argparse
import csv
import datetime
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path

from techdigest.collectors.rss import _baixar_feed, collect_rss
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
    return p.parse_args()


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


def _descricoes_do_google() -> None:
    """Relata se as descrições do Google Notícias listam outras coberturas do mesmo fato.

    O collect_rss guarda a descrição já sem as tags, então os feeds do Google são baixados de
    novo aqui só para olhar o HTML. Nada disso entra no agrupamento ainda.
    """
    print("\n== Descrições dos itens do Google Notícias ==")
    feeds = [f for f in settings.feeds if _eh_google(f)]
    itens = com_lista = com_varios_links = 0
    for feed in feeds:
        try:
            entradas = _baixar_feed(feed).entries
        except Exception as e:
            print(f"  um feed não pôde ser baixado de novo ({type(e).__name__})")
            continue
        for entrada in entradas:
            descricao = entrada.get("summary", "")
            itens += 1
            com_lista += bool(re.search(r"<li\b", descricao))
            com_varios_links += len(re.findall(r"<a\b", descricao)) > 1
    if not itens:
        print("  nenhum item do Google Notícias para examinar")
        return
    print(f"  {len(feeds)} feed(s), {itens} itens: {com_lista} com lista (<li>), "
          f"{com_varios_links} com mais de um link")
    if com_lista or com_varios_links:
        print("  Há descrições que listam outras coberturas do mesmo fato (ainda não usadas no agrupamento).")
    else:
        print("  Nenhuma descrição lista outras coberturas: cada uma traz só o link e o veículo do próprio item.")


def _gravar_csv(pares: list[ag.ParPontuado]) -> tuple[Path, int]:
    escolhidos = [p for p in pares if p.score >= CSV_SCORE_MIN][:CSV_MAX_PARES]
    pasta = Path(settings.db_path).parent / "agrupamento"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"pares_{datetime.datetime.now():%Y%m%d-%H%M%S}.csv"
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

    print("== Etapas ==", flush=True)
    artigos, segundos = _cronometrar(collect_rss)
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

    candidatos = []
    for artigo, extracao in com_texto:
        titulo, veiculo = ag.separar_veiculo(artigo.title, artigo.source)
        candidatos.append(ag.Candidato(
            titulo=titulo, veiculo=veiculo, url=artigo.url,
            url_veiculo=extracao.url_resolvida or artigo.url, texto=extracao.texto,
        ))
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
    _descricoes_do_google()

    caminho, gravados = _gravar_csv(pares)
    print(f"\nCSV: {caminho} ({gravados} pares com score ≥ {CSV_SCORE_MIN:.2f}; marque a coluna mesmo_fato)")


if __name__ == "__main__":
    main()

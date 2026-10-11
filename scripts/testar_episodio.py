"""Diagnóstico da geração de episódios com várias fontes (Fase 3 do agrupamento).

Com uma amostra fixa, refaz as etapas 1 a 3 do agrupamento e gera, com Summarizer.process, os
episódios de algumas pautas: até 4 com várias fontes e 1 de fonte única, como controle. Não gera
áudio, não envia nada ao Telegram, não chama mark_seen e não abre o digest.db.

Uso (da raiz do projeto, com o venv ativo, o LLM no ar e nenhum pipeline rodando):
    python scripts/testar_episodio.py --amostra data/agrupamento/amostra_<data-hora>.json

Antes de cada chamada ao LLM mostra memória disponível, swap e temperaturas, e para se a memória
disponível estiver abaixo de --min-memoria (GiB). Grava em data/agrupamento/episodios/ o JSON de
cada episódio e um relatorio_<data-hora>.json com tudo o que foi medido.
"""
import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path

import testar_agrupamento as diag
from techdigest.ai import qa
from techdigest.ai.llm import _amostra_sistema, get_provider
from techdigest.ai.prompt import PROMPT_REVISOR, PROMPT_SISTEMA
from techdigest.ai.summarizer import TETO_PRINCIPAL, TETO_RELACIONADO, QAReprovado, Summarizer
from techdigest.config import Settings
from techdigest.processing import agrupamento as ag

settings = Settings()

ALERTA_DA_JANELA = 0.9   # avisa quando entrada + saída passam desta fração de num_ctx
FALAS_NO_RELATORIO = 3


class MemoriaInsuficiente(SystemExit):
    """Memória disponível abaixo do mínimo: interrompe o diagnóstico (não é pega por `except Exception`)."""


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera episódios de pautas com várias fontes, sem entregar nada.")
    p.add_argument("--amostra", metavar="ARQUIVO", required=True,
                   help="amostra gravada por testar_agrupamento.py --salvar-amostra")
    p.add_argument("--limiar", type=float, default=settings.agrup_limiar,
                   help="score mínimo da pauta provisória (padrão: AGRUP_LIMIAR = %(default)s)")
    p.add_argument("--max-pautas", type=int, default=4, metavar="N",
                   help="quantas pautas com várias fontes gerar (padrão: %(default)s)")
    p.add_argument("--min-memoria", type=float, default=4.0, metavar="GIB",
                   help="para se a memória disponível cair abaixo disto, em GiB (padrão: %(default)s)")
    return p.parse_args()


def _estado_da_maquina() -> tuple[float, str]:
    """Memória disponível em GiB e um resumo com swap e temperaturas, lidos agora."""
    with open("/proc/meminfo") as arquivo:
        mem = {linha.split(":")[0]: int(linha.split()[1]) for linha in arquivo}
    return mem["MemAvailable"] / 1048576, _amostra_sistema()


class ProviderMonitorado:
    """Envolve o provider: confere a memória antes de cada chamada e guarda tempo, tokens e resposta."""

    def __init__(self, provider, min_memoria: float):
        self.provider = provider
        self.min_memoria = min_memoria
        self.chamadas: list[dict] = []

    @property
    def ultimo_uso(self) -> dict:
        return self.provider.ultimo_uso

    def chat_json(self, system: str, user: str, **opcoes) -> dict:
        disponivel, resumo = _estado_da_maquina()
        chamada = {
            "prompt": {PROMPT_SISTEMA: "geração", PROMPT_REVISOR: "revisão"}.get(system, "outro"),
            "chars_sistema": len(system), "chars_entrada": len(user), "maquina_antes": resumo,
        }
        print(f"      {chamada['prompt']}: {len(system) + len(user)} caracteres · antes: {resumo}", flush=True)
        if disponivel < self.min_memoria:
            raise MemoriaInsuficiente(
                f"\nPAREI: memória disponível em {disponivel:.1f} GiB, abaixo do mínimo de {self.min_memoria:.1f} GiB."
            )
        self.chamadas.append(chamada)
        inicio = time.perf_counter()
        try:
            resposta = self.provider.chat_json(system, user, **opcoes)
        except Exception as e:
            chamada.update(segundos=time.perf_counter() - inicio, erro=f"{type(e).__name__}: {str(e)[:300]}")
            raise
        tokens = dict(self.provider.ultimo_uso)
        chamada.update(segundos=time.perf_counter() - inicio, tokens_entrada=tokens.get("prompt", 0),
                       tokens_saida=tokens.get("saida", 0), resposta=resposta)
        return resposta


def _pautas_finais(args: argparse.Namespace, provider) -> tuple[list[ag.Pauta], dict[ag.Candidato, int]]:
    """Etapas 1 a 3 sobre a amostra: as pautas finais e o id de cada candidato."""
    candidatos, ids = diag._carregar_amostra(args.amostra)
    titulos = ag.comparar_titulos(candidatos, settings.agrup_chars_texto)
    textos = ag.comparar_textos(candidatos, settings.agrup_chars_texto)
    pares = ag.pontuar_pares(candidatos, titulos, textos, settings.agrup_peso_titulo, settings.agrup_limiar_duplicata)
    provisorias, _ = ag.formar_pautas(candidatos, pares, args.limiar, settings.agrup_max_artigos)
    com_varios = [p for p in provisorias if p.relacionados]
    finais = [p for p in provisorias if not p.relacionados]
    print(f"\n== Etapa 3: o LLM confirma {len(com_varios)} pauta(s) provisória(s) (limiar {args.limiar:.2f}) ==", flush=True)
    for n, pauta in enumerate(com_varios, 1):
        chamada = diag._consultar_llm(provider, pauta, 1)
        finais += chamada.finais
        print(f"  pauta {n}/{len(com_varios)} (ids {', '.join(str(ids[c]) for c in pauta.artigos)}) · "
              f"{chamada.segundos:.1f} s · {chamada.erro or diag._resumo_do_veredito(chamada, ids)}", flush=True)
    return finais, ids


def _escolher(finais: list[ag.Pauta], ids: dict[ag.Candidato, int], quantas: int) -> list[tuple[str, ag.Pauta]]:
    """Até `quantas` pautas com várias fontes e uma de fonte única, cada uma com o nome do caso.

    A preferência cobre os casos diferentes: mesmo acontecimento entre veículos diferentes,
    desdobramento entre veículos diferentes e textos do mesmo veículo; depois, as pautas com mais
    textos. O controle é a primeira pauta de um artigo só, na ordem da amostra.
    """
    varias = [p for p in finais if p.relacionados]

    def caso(p: ag.Pauta) -> str:
        if len(p.veiculos) == 1:
            return "mesmo_veiculo"
        return "desdobramento" if "desdobramento" in p.relacoes.values() else "mesmo_acontecimento"

    escolhidas: list[tuple[str, ag.Pauta]] = []
    for nome in ("mesmo_acontecimento", "desdobramento", "mesmo_veiculo"):
        primeira = next((p for p in varias if caso(p) == nome), None)
        if primeira:
            escolhidas.append((nome, primeira))
    for p in sorted(varias, key=lambda p: -len(p.artigos)):
        if all(p is not escolhida for _, escolhida in escolhidas):
            escolhidas.append((caso(p), p))
    escolhidas = escolhidas[:quantas]
    sozinhas = sorted((p for p in finais if not p.relacionados), key=lambda p: ids[p.principal])
    return ([("controle_fonte_unica", sozinhas[0])] if sozinhas else []) + escolhidas


def _como_fonte(c: ag.Candidato, relacao: str | None = None) -> dict:
    fonte = {"source": c.veiculo, "title": c.titulo, "text": c.texto, "data": c.data}
    return {**fonte, "relacao": relacao} if relacao else fonte


def _gerar(n: int, caso: str, pauta: ag.Pauta, ids: dict, summarizer: Summarizer, monitor: ProviderMonitorado,
           pasta: Path, carimbo: str) -> dict:
    """Gera o episódio de uma pauta e devolve o relatório dela."""
    print(f"\n== Episódio {n}: {caso} · {len(pauta.artigos)} texto(s) de {len(pauta.veiculos)} veículo(s) ==")
    print(f"  principal:   [id {ids[pauta.principal]}] {diag._rotulo(pauta.principal)} ({len(pauta.principal.texto)} caracteres)")
    for c in pauta.relacionados:
        print(f"  relacionado: [id {ids[c]}] {diag._rotulo(c)} ({len(c.texto)} caracteres, {pauta.relacoes.get(c, '?')})")

    proporcao = summarizer.chars_por_token
    primeira = len(monitor.chamadas)
    inicio = time.perf_counter()
    try:
        episodio = summarizer.process(
            _como_fonte(pauta.principal), [_como_fonte(c, pauta.relacoes.get(c)) for c in pauta.relacionados],
        )
        situacao = "aprovado"
    except QAReprovado as e:
        situacao = f"reprovado pelo QA ({e})"
        episodio = next((ch["resposta"] for ch in reversed(monitor.chamadas[primeira:]) if "resposta" in ch), None)
    except Exception as e:
        situacao = f"falhou ({type(e).__name__}: {str(e)[:300]})"
        episodio = None
    segundos = time.perf_counter() - inicio
    chamadas = [{k: v for k, v in ch.items() if k != "resposta"} for ch in monitor.chamadas[primeira:]]
    diagnostico = summarizer.ultimo_diagnostico

    relatorio = {
        "episodio": n, "caso": caso, "situacao": situacao, "segundos": round(segundos, 1),
        "artigos": [{"id": ids[c], "veiculo": c.veiculo, "titulo": c.titulo, "caracteres": len(c.texto),
                     "relacao": pauta.relacoes.get(c, "principal")} for c in pauta.artigos],
        "veiculos_da_pauta": list(pauta.veiculos), "chars_por_token_no_inicio": round(proporcao, 2),
        "chamadas": chamadas,
        "problemas_antes_da_revisao": diagnostico.get("problemas"),
        "problemas_depois_da_revisao": diagnostico.get("problemas_da_revisao"),
    }
    for nome, entrada in (("cortes_na_geracao", diagnostico.get("entrada")), ("cortes_na_revisao", diagnostico.get("revisao"))):
        if entrada is not None:
            relatorio[nome] = [
                {**corte, "teto": TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO,
                 "cortado_pelo_orcamento": max(min(corte["texto"], TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) - corte["incluido"], 0)}
                for i, corte in enumerate(entrada.cortes)
            ]

    for ch in chamadas:
        if "erro" in ch:
            print(f"  {ch['prompt']}: FALHOU em {ch['segundos']:.0f} s — {ch['erro']}")
            continue
        total = ch["tokens_entrada"] + ch["tokens_saida"]
        ch["fracao_da_janela"] = round(total / settings.ollama_num_ctx, 2)
        alerta = "  ALERTA: perto do limite de num_ctx" if total >= ALERTA_DA_JANELA * settings.ollama_num_ctx else ""
        print(f"  {ch['prompt']}: {ch['tokens_entrada']} + {ch['tokens_saida']} tokens = {total} de {settings.ollama_num_ctx} "
              f"({total / settings.ollama_num_ctx:.0%}) · {ch['segundos']:.0f} s{alerta}")
    for nome, rotulo in (("cortes_na_geracao", "geração"), ("cortes_na_revisao", "revisão")):
        for corte in relatorio.get(nome, []):
            print(f"  texto na {rotulo}: {corte['fonte']} · {corte['incluido']} de {corte['texto']} caracteres "
                  f"(teto {corte['teto']}; o orçamento tirou {corte['cortado_pelo_orcamento']})")
    print(f"  QA antes da revisão: {relatorio['problemas_antes_da_revisao'] or 'sem problemas'}")
    if relatorio["problemas_depois_da_revisao"] is not None:
        print(f"  QA depois da revisão: {relatorio['problemas_depois_da_revisao'] or 'sem problemas'}")
    print(f"  situação: {situacao} · {segundos:.0f} s no total")

    if episodio is not None:
        citadas = episodio.get("fontes_citadas") if isinstance(episodio.get("fontes_citadas"), list) else []
        relatorio.update(
            houve_divergencia=episodio.get("houve_divergencia"), fontes_citadas=citadas,
            veiculos_sem_citacao=[v for v in pauta.veiculos if not any(qa.mesmo_veiculo(v, f) for f in citadas)],
            fontes_fora_da_pauta=[f for f in citadas if not any(qa.mesmo_veiculo(v, f) for v in pauta.veiculos)],
            resumo_didatico=episodio.get("resumo_didatico"),
            primeiras_falas=(episodio.get("roteiro_podcast") or [])[:FALAS_NO_RELATORIO],
        )
        print(f"  houve_divergencia: {relatorio['houve_divergencia']} · fontes_citadas: {citadas} · "
              f"veículos da pauta: {list(pauta.veiculos)}")
        print(f"  veículos sem citação: {relatorio['veiculos_sem_citacao'] or 'nenhum'} · "
              f"fontes fora da pauta: {relatorio['fontes_fora_da_pauta'] or 'nenhuma'}")
        print(f"  resumo_didatico: {relatorio['resumo_didatico']}")
        for fala in relatorio["primeiras_falas"]:
            print(f"  [{fala.get('personagem')}] {fala.get('fala')}")
        slug = re.sub(r"\W+", "-", str(episodio.get("titulo_reescrito", "")).lower())[:40].strip("-")
        arquivo = pasta / f"{carimbo}_{n}_{caso}{'' if situacao == 'aprovado' else '_reprovado'}_{slug}.json"
        arquivo.write_text(json.dumps(episodio, ensure_ascii=False, indent=1), encoding="utf-8")
        relatorio["arquivo"] = str(arquivo)
        print(f"  episódio gravado em {arquivo}")
    return relatorio


def main() -> None:
    args = _argumentos()
    diag._log_no_console()
    carimbo = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    pasta = diag._pasta() / "episodios"
    pasta.mkdir(parents=True, exist_ok=True)

    disponivel, resumo = _estado_da_maquina()
    print(f"== Máquina: {resumo} · num_ctx {settings.ollama_num_ctx} (reserva de saída "
          f"{min(settings.ollama_num_predict, settings.llm_reserva_saida)} tokens) ==")
    if disponivel < args.min_memoria:
        sys.exit(f"PAREI antes de começar: memória disponível em {disponivel:.1f} GiB, abaixo de {args.min_memoria:.1f} GiB.")

    provider = get_provider(settings)
    monitor = ProviderMonitorado(provider, args.min_memoria)
    summarizer = Summarizer(provider=monitor)
    finais, ids = _pautas_finais(args, provider)
    escolhidas = _escolher(finais, ids, args.max_pautas)
    print(f"\n{sum(1 for p in finais if p.relacionados)} pauta(s) final(is) com várias fontes; "
          f"{len(escolhidas)} episódio(s) a gerar: {', '.join(caso for caso, _ in escolhidas)}")

    relatorios = []
    caminho = pasta / f"relatorio_{carimbo}.json"

    def gravar() -> None:
        caminho.write_text(json.dumps(
            {"amostra": args.amostra, "limiar": args.limiar, "num_ctx": settings.ollama_num_ctx, "episodios": relatorios},
            ensure_ascii=False, indent=1, default=str,
        ), encoding="utf-8")

    try:
        for n, (caso, pauta) in enumerate(escolhidas, 1):
            relatorios.append(_gerar(n, caso, pauta, ids, summarizer, monitor, pasta, carimbo))
            gravar()  # a cada episódio: se a máquina cair no meio, fica o que já foi medido
    finally:
        gravar()
        print(f"\nRelatório: {caminho} ({len(relatorios)} de {len(escolhidas)} episódio(s))")


if __name__ == "__main__":
    main()

"""Diagnóstico da geração de episódios a partir de pautas (Fase 3 do agrupamento).

Com uma amostra fixa, gera com Summarizer.process os episódios de algumas pautas. Não gera áudio,
não envia nada ao Telegram, não chama mark_seen e não abre o digest.db.

Uso (da raiz do projeto, com o venv ativo, o LLM no ar e nenhum pipeline rodando):
    python scripts/testar_episodio.py --amostra data/agrupamento/amostra_<data-hora>.json
    python scripts/testar_episodio.py --repetir data/agrupamento/episodios/relatorio_<data-hora>.json --pasta episodios_v2
    python scripts/testar_episodio.py --repetir <relatório> --pautas "86+71" --so-lados

Sem --repetir nem --pautas, refaz as etapas 1 a 3 do agrupamento e escolhe até 4 pautas com várias
fontes e 1 de fonte única, como controle. --repetir usa as pautas de um relatório anterior, na
mesma ordem, e --pautas acrescenta pautas montadas pelos ids da amostra; nos dois casos a etapa 3
não roda. --so-lados faz só a análise de lados de cada pauta, sem gerar episódio.

Antes de cada chamada ao LLM mostra memória disponível, swap e temperaturas. Para se a memória
disponível estiver abaixo de --min-memoria (GiB) ou se o Ollama sair do ar ou descarregar o modelo
no meio da rodada. Grava em data/agrupamento/<pasta>/ o JSON de cada episódio e um
relatorio_<data-hora>.json (ou lados_<data-hora>.json) com tudo o que foi medido.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

import testar_agrupamento as diag
from techdigest.ai import qa
from techdigest.ai.llm import _amostra_sistema, get_provider
from techdigest.ai.lados import lados_finos
from techdigest.ai.prompt import PROMPT_LADOS, PROMPT_RESUMO, PROMPT_REVISOR, PROMPT_ROTEIRO, PROMPT_SISTEMA, PROMPT_TITULO
from techdigest.ai.summarizer import CORRECOES, TETO_PRINCIPAL, TETO_RELACIONADO, QAReprovado, Summarizer
from techdigest.config import Settings
from techdigest.processing import agrupamento as ag

settings = Settings()

ALERTA_DA_JANELA = 0.9   # avisa quando entrada + saída passam desta fração de num_ctx
FALAS_NO_RELATORIO = 3


class RodadaInterrompida(SystemExit):
    """Memória abaixo do mínimo ou Ollama fora do ar: interrompe o diagnóstico (não é pega por `except Exception`)."""


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera episódios de pautas com várias fontes, sem entregar nada.")
    p.add_argument("--amostra", metavar="ARQUIVO",
                   help="amostra gravada por testar_agrupamento.py --salvar-amostra (padrão: a do relatório de --repetir)")
    p.add_argument("--repetir", metavar="RELATORIO",
                   help="usa as pautas de um relatório anterior deste script, na mesma ordem, sem refazer a etapa 3")
    p.add_argument("--pautas", metavar="IDS", default="",
                   help='pautas a mais, pelos ids da amostra: "86+71;12" (o texto mais longo é o principal)')
    p.add_argument("--so-lados", action="store_true", help="faz só a análise de lados de cada pauta, sem gerar episódio")
    p.add_argument("--pasta", default="episodios", metavar="NOME",
                   help="subpasta de data/agrupamento/ para os arquivos (padrão: %(default)s)")
    p.add_argument("--limiar", type=float, default=settings.agrup_limiar,
                   help="score mínimo da pauta provisória (padrão: AGRUP_LIMIAR = %(default)s)")
    p.add_argument("--max-pautas", type=int, default=4, metavar="N",
                   help="quantas pautas com várias fontes gerar (padrão: %(default)s)")
    p.add_argument("--min-memoria", type=float, default=4.0, metavar="GIB",
                   help="para se a memória disponível cair abaixo disto, em GiB (padrão: %(default)s)")
    args = p.parse_args()
    if not args.amostra and not args.repetir:
        p.error("informe --amostra ou --repetir")
    return args


def _memoria_do_processo(pid) -> dict[str, float] | None:
    """Memória de um processo, em GiB: residente (rss), a parte anônima dela e o que está na swap."""
    try:
        with open(f"/proc/{pid}/status") as arquivo:
            campos = {linha.split(":")[0]: linha.split()[1] for linha in arquivo if linha.startswith(("VmRSS", "RssAnon", "VmSwap"))}
    except (OSError, IndexError):
        return None   # o processo acabou, ou é uma thread do kernel
    if "VmRSS" not in campos:
        return None
    return {"rss": int(campos["VmRSS"]) / 1048576, "anonima": int(campos.get("RssAnon", 0)) / 1048576,
            "swap": int(campos.get("VmSwap", 0)) / 1048576}


def _processos_do_ollama() -> dict[str, str]:
    """PID e nome do servidor do Ollama e de tudo o que ele abriu (o llama-server, que executa o modelo)."""
    nomes, pais = {}, {}
    for entrada in os.listdir("/proc"):
        if not entrada.isdigit():
            continue
        try:
            with open(f"/proc/{entrada}/stat") as arquivo:
                conteudo = arquivo.read()
            nomes[entrada] = conteudo[conteudo.index("(") + 1:conteudo.rindex(")")]
            pais[entrada] = conteudo[conteudo.rindex(")") + 2:].split()[1]
        except (OSError, ValueError, IndexError):
            continue
    do_ollama = {pid for pid, nome in nomes.items() if nome.startswith("ollama")}
    while novos := {pid for pid, pai in pais.items() if pai in do_ollama} - do_ollama:
        do_ollama |= novos
    return {pid: nomes[pid] for pid in sorted(do_ollama, key=int)}


def _memoria_por_processo() -> dict[str, dict[str, float]]:
    """Memória do processo deste script e dos processos do Ollama, somados e por nome.

    O Ollama são dois processos: o servidor ("ollama") e o executor do modelo ("llama-server"),
    que o servidor abre. A parte do modelo que fica na GPU não aparece aqui. Traz também, quando
    existe, a RAM ocupada pela swap comprimida (zram): com ela, o que vai para a swap continua
    ocupando memória.
    """
    soma = {"rss": 0.0, "anonima": 0.0, "swap": 0.0, "processos": 0}
    medidas = {"script": _memoria_do_processo(os.getpid()) or {}, "ollama": soma}
    for pid, nome in _processos_do_ollama().items():
        if memoria := _memoria_do_processo(pid):
            por_nome = medidas.setdefault(f"ollama:{nome}", {"rss": 0.0, "anonima": 0.0, "swap": 0.0})
            for chave, valor in memoria.items():
                soma[chave] += valor
                por_nome[chave] += valor
            soma["processos"] += 1
    try:
        with open("/sys/block/zram0/mm_stat") as arquivo:
            medidas["zram"] = {"ram": int(arquivo.read().split()[2]) / 1073741824}   # mem_used_total, em bytes
    except (OSError, IndexError, ValueError):
        pass
    return {nome: {chave: round(valor, 2) for chave, valor in medida.items()} for nome, medida in medidas.items()}


def _resumo_da_memoria(medidas: dict) -> str:
    script, ollama = medidas.get("script", {}), medidas.get("ollama", {})
    partes = [
        f"script {script.get('rss', 0):.2f} GB (swap {script.get('swap', 0):.2f})",
        f"ollama {ollama.get('rss', 0):.2f} GB (anônima {ollama.get('anonima', 0):.2f}, swap {ollama.get('swap', 0):.2f}, "
        f"{ollama.get('processos', 0):.0f} processo(s))",
    ]
    if "zram" in medidas:
        partes.append(f"zram ocupa {medidas['zram']['ram']:.2f} GB de RAM")
    return " · ".join(partes)


# Como cada chamada aparece no relatório, pelo prompt de sistema.
ROTULOS = {PROMPT_SISTEMA: "geração", PROMPT_LADOS: "lados", PROMPT_REVISOR: CORRECOES["completa"],
           PROMPT_RESUMO: CORRECOES["resumo"], PROMPT_ROTEIRO: CORRECOES["roteiro"], PROMPT_TITULO: CORRECOES["titulo"]}
# Primeira pessoa do plural na fala de um analista: pronomes e verbos em -amos, -emos e -imos. É só diagnóstico.
_NOS = re.compile(r"\b(?:nós|conosco|noss[oa]s?|[^\W\d_]{2,}(?:[aeií]mos))\b", re.IGNORECASE)
_NAO_E_NOS = {"mesmos", "termos", "extremos", "supremos", "ramos", "remos", "próximos", "últimos", "mínimos", "máximos",
              "ótimos", "íntimos", "legítimos", "empréstimos", "primos", "péssimos", "altíssimos", "muitíssimos"}


def _estado_da_maquina() -> tuple[float, str]:
    """Memória disponível em GiB e um resumo com swap e temperaturas, lidos agora."""
    with open("/proc/meminfo") as arquivo:
        mem = {linha.split(":")[0]: int(linha.split()[1]) for linha in arquivo}
    return mem["MemAvailable"] / 1048576, _amostra_sistema()


class ProviderMonitorado:
    """Envolve o provider: confere a memória e o Ollama antes de cada chamada e guarda tempo, tokens e resposta."""

    def __init__(self, provider, min_memoria: float):
        self.provider = provider
        self.min_memoria = min_memoria
        self.chamadas: list[dict] = []
        self.modelo_ja_carregou = False

    @property
    def ultimo_uso(self) -> dict:
        return self.provider.ultimo_uso

    def _conferir_ollama(self) -> None:
        """Para a rodada se o Ollama não responde ou se o modelo, que já tinha sido carregado, saiu da memória."""
        cliente = getattr(self.provider, "client", None)
        if settings.llm_provider != "ollama" or cliente is None:
            return
        try:
            carregados = [m.model for m in cliente.ps().models]
        except Exception as e:
            raise RodadaInterrompida(f"\nPAREI: o Ollama não responde ({type(e).__name__}: {str(e)[:120]}).") from None
        if self.modelo_ja_carregou and self.provider.model not in carregados:
            raise RodadaInterrompida(
                f"\nPAREI: o Ollama descarregou o modelo {self.provider.model} no meio da rodada "
                f"(carregados agora: {', '.join(carregados) or 'nenhum'})."
            )

    def chat_json(self, system: str, user: str, **opcoes) -> dict:
        disponivel, resumo = _estado_da_maquina()
        chamada = {
            "prompt": ROTULOS.get(system, "outro"),
            "chars_sistema": len(system), "chars_entrada": len(user), "maquina_antes": resumo,
            "memoria_disponivel": round(disponivel, 2), "memoria_por_processo": (memoria := _memoria_por_processo()),
        }
        print(f"      {chamada['prompt']}: {len(system) + len(user)} caracteres · antes: {resumo}", flush=True)
        print(f"        memória por processo: {_resumo_da_memoria(memoria)}", flush=True)
        if disponivel < self.min_memoria:
            raise RodadaInterrompida(
                f"\nPAREI: memória disponível em {disponivel:.1f} GiB, abaixo do mínimo de {self.min_memoria:.1f} GiB."
            )
        self._conferir_ollama()
        self.chamadas.append(chamada)
        inicio = time.perf_counter()
        try:
            resposta = self.provider.chat_json(system, user, **opcoes)
        except Exception as e:
            chamada.update(segundos=time.perf_counter() - inicio, erro=f"{type(e).__name__}: {str(e)[:300]}")
            self._conferir_ollama()   # se foi o servidor que caiu, a rodada para aqui em vez de seguir falhando
            raise
        self.modelo_ja_carregou = True
        tokens = dict(self.provider.ultimo_uso)
        chamada.update(segundos=time.perf_counter() - inicio, tokens_entrada=tokens.get("prompt", 0),
                       tokens_saida=tokens.get("saida", 0), resposta=resposta)
        return resposta


def _pautas_dadas(args: argparse.Namespace, ids: dict[ag.Candidato, int]) -> list[tuple[str, ag.Pauta]]:
    """As pautas de --repetir (como estavam no relatório) e as de --pautas (montadas pelos ids), com o nome do caso."""
    por_id = {n: c for c, n in ids.items()}
    escolhidas: list[tuple[str, ag.Pauta]] = []
    try:
        if args.repetir:
            for item in json.loads(Path(args.repetir).read_text(encoding="utf-8"))["episodios"]:
                principal, *demais = [(por_id[a["id"]], a.get("relacao")) for a in item["artigos"]]
                escolhidas.append((item["caso"], ag.Pauta(
                    principal=principal[0], relacionados=tuple(c for c, _ in demais),
                    relacoes={c: relacao for c, relacao in demais if relacao in ag.RELACOES},
                )))
        for grupo in filter(None, (g.strip() for g in args.pautas.split(";"))):
            artigos = [por_id[int(n)] for n in grupo.split("+")]
            principal = max(artigos, key=lambda c: len(c.texto))        # a regra do projeto: o texto extraído mais longo
            escolhidas.append((f"ids_{grupo}", ag.Pauta(principal=principal, relacionados=tuple(c for c in artigos if c is not principal))))
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"Pautas ilegíveis ({type(e).__name__}: {e}): confira --repetir e --pautas.")
    return escolhidas


def _pautas_finais(args: argparse.Namespace, provider, candidatos: list[ag.Candidato],
                   ids: dict[ag.Candidato, int]) -> list[ag.Pauta]:
    """Etapas 1 a 3 sobre a amostra: as pautas finais."""
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
    return finais


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


def _apresentar(rotulo: str, n: int, caso: str, pauta: ag.Pauta, ids: dict) -> dict:
    """Mostra a pauta e devolve o começo do relatório dela."""
    print(f"\n== {rotulo} {n}: {caso} · {len(pauta.artigos)} texto(s) de {len(pauta.veiculos)} veículo(s) ==")
    print(f"  principal:   [id {ids[pauta.principal]}] {diag._rotulo(pauta.principal)} ({len(pauta.principal.texto)} caracteres)")
    for c in pauta.relacionados:
        print(f"  relacionado: [id {ids[c]}] {diag._rotulo(c)} ({len(c.texto)} caracteres, {pauta.relacoes.get(c, '?')})")
    return {
        "episodio": n, "caso": caso,
        "artigos": [{"id": ids[c], "veiculo": c.veiculo, "titulo": c.titulo, "caracteres": len(c.texto),
                     "relacao": pauta.relacoes.get(c, "principal")} for c in pauta.artigos],
        "veiculos_da_pauta": list(pauta.veiculos),
    }


def _fontes(pauta: ag.Pauta) -> tuple[dict, list[dict]]:
    return _como_fonte(pauta.principal), [_como_fonte(c, pauta.relacoes.get(c)) for c in pauta.relacionados]


def _lados(analise, chamadas: list[dict]) -> dict:
    """Mostra o resultado da análise de lados e devolve o que vai para o relatório."""
    feitas = [ch for ch in chamadas if ch["prompt"] == "lados"]
    registro = {
        "quantos": len(analise.lados), "questao": analise.questao, "motivo": analise.motivo,
        "tentativas": len(feitas), "lado_de_emergencia": bool(analise.problemas), "invalida_porque": analise.problemas,
        "ajustes": analise.ajustes,
        "ressalvas": [{"grupos": list(r.grupos), "posicao": r.posicao, "veiculos": list(r.veiculos)} for r in analise.ressalvas],
        "ressalvas_descartadas": [{"grupos": list(r.grupos), "posicao": r.posicao, "veiculos": list(r.veiculos)}
                                  for r in analise.descartadas],
        "lados": [{"resposta": lado.resposta, "posicao": lado.posicao, "atores": list(lado.atores), "veiculos": list(lado.veiculos),
                   "trechos": list(lado.trechos), "fino": fino}
                  for lado, fino in zip(analise.lados, lados_finos(analise.lados))],
        "respostas_por_ator": [{"ator": e.ator, "resposta": e.resposta, "trecho": e.trecho, "veiculo": e.veiculo,
                                "comprovada": e.comprovada} for e in analise.respostas],
        "resposta_do_llm": analise.resposta,
        "primeira_tentativa": None if analise.primeira is None else {
            "invalida_porque": analise.primeira.problemas, "resposta_do_llm": analise.primeira.resposta,
        },
        "segundos": round(sum(ch.get("segundos", 0.0) for ch in feitas), 1),
        "segundos_por_tentativa": [round(ch.get("segundos", 0.0), 1) for ch in feitas],
        "tokens_entrada": [ch.get("tokens_entrada") for ch in feitas], "tokens_saida": [ch.get("tokens_saida") for ch in feitas],
    }
    print(f"  lados: {registro['quantos']} · {registro['tentativas']} tentativa(s) · {registro['segundos']:.1f} s · "
          f"tokens {registro['tokens_entrada']} + {registro['tokens_saida']}")
    print(f"    questão: {registro['questao'] or '(sem disputa)'}")
    for e in registro["respostas_por_ator"]:
        print(f"    resposta de {e['ator']}: {e['resposta'] or '-'} · {'comprovada' if e['comprovada'] else 'TRECHO NÃO ENCONTRADO'} "
              f"em {e['veiculo'] or '-'}: \"{e['trecho']}\"")
    for i, lado in enumerate(registro["lados"], 1):
        resposta = f"[{lado['resposta']}] " if lado["resposta"] else ""
        print(f"    lado {i}{' (FINO)' if lado['fino'] else ''}: {resposta}{lado['posicao']}")
        print(f"            atores: {', '.join(lado['atores']) or '-'} · veículos: {', '.join(lado['veiculos'])} · "
              f"trechos de evidência: {len(set(lado['trechos']))}")
    for i, ressalva in enumerate(registro["ressalvas"], 1):
        print(f"    ressalva {i}: {ressalva['posicao']}")
        print(f"            grupos: {', '.join(ressalva['grupos']) or '-'} · veículos: {', '.join(ressalva['veiculos'])}")
    print(f"    motivo: {registro['motivo'] or '-'}")
    for ajuste in analise.ajustes:
        print(f"    ajuste: {ajuste}")
    if analise.primeira is not None:
        print(f"    PRIMEIRA TENTATIVA RECUSADA: {'; '.join(analise.primeira.problemas)}")
        print(f"    resposta recusada: {json.dumps(analise.primeira.resposta, ensure_ascii=False)}")
    if analise.problemas:
        print(f"    AS DUAS TENTATIVAS FALHARAM, a pauta ficou com o lado de emergência: {'; '.join(analise.problemas)}")
        print(f"    resposta do LLM: {json.dumps(analise.resposta, ensure_ascii=False)}")
    return registro


def _primeira_pessoa(episodio: dict) -> list[dict]:
    """As frases dos analistas com primeira pessoa do plural ("nós", "precisamos"). Só diagnóstico: pega também
    o "vamos" de quem conduz a conversa."""
    achadas = []
    for turno in episodio.get("roteiro_podcast") or []:
        if not isinstance(turno, dict) or qa._palavras_do_nome(turno.get("personagem")) == [qa.HELENA]:
            continue
        for frase in qa.frases(turno.get("fala", "")):
            marcas = [m.group() for m in _NOS.finditer(frase) if m.group().lower() not in _NAO_E_NOS]
            if marcas:
                achadas.append({"personagem": turno.get("personagem"), "marcas": marcas, "frase": frase})
    return achadas


def _cortes(entrada) -> list[dict]:
    return [
        {**corte, "teto": TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO,
         "cortado_pelo_orcamento": max(min(corte["texto"], TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) - corte["incluido"], 0)}
        for i, corte in enumerate(entrada.cortes)
    ]


def _analisar(n: int, caso: str, pauta: ag.Pauta, ids: dict, summarizer: Summarizer, monitor: ProviderMonitorado) -> dict:
    """Só a análise de lados de uma pauta, sobre os trechos que a geração receberia."""
    relatorio = _apresentar("Pauta", n, caso, pauta, ids)
    primeira = len(monitor.chamadas)
    entrada, analise = summarizer.preparar(*_fontes(pauta))
    relatorio["lados"] = _lados(analise, monitor.chamadas[primeira:])
    relatorio["cortes_na_geracao"] = _cortes(entrada)
    relatorio["chars_da_entrada_do_episodio"] = len(entrada.texto)
    for corte in relatorio["cortes_na_geracao"]:
        print(f"  texto lido: {corte['fonte']} · {corte['incluido']} de {corte['texto']} caracteres "
              f"(teto {corte['teto']}; o orçamento tirou {corte['cortado_pelo_orcamento']})")
    return relatorio


def _gerar(n: int, caso: str, pauta: ag.Pauta, ids: dict, summarizer: Summarizer, monitor: ProviderMonitorado,
           pasta: Path, carimbo: str) -> dict:
    """Gera o episódio de uma pauta e devolve o relatório dela."""
    relatorio = _apresentar("Episódio", n, caso, pauta, ids)
    proporcao = summarizer.chars_por_token
    primeira = len(monitor.chamadas)
    inicio = time.perf_counter()
    try:
        episodio = summarizer.process(*_fontes(pauta))
        situacao = "aprovado"
    except QAReprovado as e:
        situacao = f"reprovado pelo QA ({e})"
        episodio = summarizer.ultimo_diagnostico.get("episodio")   # a última versão inteira, com a correção já aplicada
    except Exception as e:
        situacao = f"falhou ({type(e).__name__}: {str(e)[:300]})"
        episodio = None
    segundos = time.perf_counter() - inicio
    chamadas = [{k: v for k, v in ch.items() if k != "resposta"} for ch in monitor.chamadas[primeira:]]
    diagnostico = summarizer.ultimo_diagnostico

    relatorio.update({
        "situacao": situacao, "segundos": round(segundos, 1), "chars_por_token_no_inicio": round(proporcao, 2),
        "chamadas": chamadas,
        "problemas_antes_da_revisao": diagnostico.get("problemas"),
        "tipo_de_correcao": diagnostico.get("correcao"),
        "problemas_depois_da_revisao": diagnostico.get("problemas_da_revisao"),
    })
    primeira_versao = diagnostico.get("primeira_versao")
    if isinstance(primeira_versao, dict) and diagnostico.get("correcao"):
        relatorio["primeira_versao"] = {
            "titulo": primeira_versao.get("titulo_reescrito"), "resumo_didatico": primeira_versao.get("resumo_didatico"),
        }
    if diagnostico.get("lados") is not None:
        relatorio["lados"] = _lados(diagnostico["lados"], chamadas)
    for nome, entrada in (("cortes_na_geracao", diagnostico.get("entrada")), ("cortes_na_revisao", diagnostico.get("revisao"))):
        if entrada is not None:
            relatorio[nome] = _cortes(entrada)

    for ch in chamadas:
        if "erro" in ch:
            print(f"  {ch['prompt']}: FALHOU em {ch['segundos']:.0f} s — {ch['erro']}")
            continue
        total = ch["tokens_entrada"] + ch["tokens_saida"]
        ch["fracao_da_janela"] = round(total / settings.ollama_num_ctx, 2)
        alerta = "  ALERTA: perto do limite de num_ctx" if total >= ALERTA_DA_JANELA * settings.ollama_num_ctx else ""
        print(f"  {ch['prompt']}: {ch['tokens_entrada']} + {ch['tokens_saida']} tokens = {total} de {settings.ollama_num_ctx} "
              f"({total / settings.ollama_num_ctx:.0%}) · {ch['segundos']:.0f} s{alerta}")
    for nome, rotulo in (("cortes_na_geracao", "geração"), ("cortes_na_revisao", CORRECOES.get(relatorio["tipo_de_correcao"], "revisão"))):
        for corte in relatorio.get(nome, []):
            print(f"  texto na {rotulo}: {corte['fonte']} · {corte['incluido']} de {corte['texto']} caracteres "
                  f"(teto {corte['teto']}; o orçamento tirou {corte['cortado_pelo_orcamento']})")
    print(f"  QA antes da correção: {relatorio['problemas_antes_da_revisao'] or 'sem problemas'}")
    if relatorio["tipo_de_correcao"]:
        print(f"  correção usada: {CORRECOES[relatorio['tipo_de_correcao']]}")
    if relatorio["problemas_depois_da_revisao"] is not None:
        print(f"  QA depois da correção: {relatorio['problemas_depois_da_revisao'] or 'sem problemas'}")
    print(f"  situação: {situacao} · {segundos:.0f} s no total")

    if episodio is not None:
        citadas = episodio.get("fontes_citadas") if isinstance(episodio.get("fontes_citadas"), list) else []
        relatorio.update(
            houve_divergencia=episodio.get("houve_divergencia"), fontes_citadas=citadas,
            titulo=episodio.get("titulo_reescrito"),
            analistas=list(dict.fromkeys(
                str(t.get("personagem")) for t in episodio.get("roteiro_podcast") or []
                if isinstance(t, dict) and qa._palavras_do_nome(t.get("personagem")) != [qa.HELENA]
            )),
            veiculos_sem_citacao=[v for v in pauta.veiculos if not any(qa.mesmo_veiculo(v, f) for f in citadas)],
            fontes_fora_da_pauta=[f for f in citadas if not any(qa.mesmo_veiculo(v, f) for v in pauta.veiculos)],
            resumo_didatico=episodio.get("resumo_didatico"),
            primeiras_falas=(episodio.get("roteiro_podcast") or [])[:FALAS_NO_RELATORIO],
            personagens=episodio.get("personagens"),
            turnos=len(episodio.get("roteiro_podcast") or []),
            frases_na_primeira_pessoa=_primeira_pessoa(episodio),
        )
        analise = diagnostico.get("lados")
        try:
            relatorio["palavras_por_personagem"] = qa.palavras_por_personagem(episodio["roteiro_podcast"])
            relatorio["minimo_por_personagem"] = qa.minimo_de_cada_personagem(episodio, analise.lados) if analise else None
            relatorio["lado_de_cada_analista"] = qa.lado_de_cada_analista(episodio, analise.lados) if analise else None
        except (KeyError, TypeError, AttributeError):   # episódio fora do formato
            pass
        print(f"  turnos: {relatorio['turnos']} · palavras: {relatorio.get('palavras_por_personagem')} · "
              f"mínimos: {relatorio.get('minimo_por_personagem')}")
        print(f"  papéis: {[(p.get('nome'), p.get('papel')) for p in relatorio['personagens'] or [] if isinstance(p, dict)]}")
        for item in relatorio["frases_na_primeira_pessoa"]:
            print(f"  primeira pessoa ({item['personagem']}; {', '.join(item['marcas'])}): {item['frase']}")
        print(f"  título: {relatorio['titulo']}")
        print(f"  analistas: {', '.join(relatorio['analistas']) or 'nenhum'} · houve_divergencia: {relatorio['houve_divergencia']} · "
              f"fontes_citadas: {citadas} · veículos da pauta: {list(pauta.veiculos)}")
        print(f"  veículos sem citação: {relatorio['veiculos_sem_citacao'] or 'nenhum'} · "
              f"fontes fora da pauta: {relatorio['fontes_fora_da_pauta'] or 'nenhuma'}")
        print(f"  resumo_didatico: {relatorio['resumo_didatico']}")
        for fala in relatorio["primeiras_falas"]:
            print(f"  [{fala.get('personagem')}] {fala.get('fala')}")
        analise = diagnostico.get("lados")
        if analise is not None and analise.ressalvas:
            try:
                achadas = qa.perguntas_das_ressalvas(episodio, analise.ressalvas)
            except (KeyError, TypeError, AttributeError):   # episódio fora do formato: não há falas para conferir
                achadas = [[] for _ in analise.ressalvas]
            relatorio["perguntas_das_ressalvas"] = [
                [{"frase": frase, "fala_com_pergunta": com_pergunta} for frase, com_pergunta in da_ressalva] for da_ressalva in achadas
            ]
            for i, da_ressalva in enumerate(achadas, 1):
                if not da_ressalva:
                    print(f"  ressalva {i}: NENHUMA frase da Helena com veículo, grupo e verbo de posição")
                for frase, com_pergunta in da_ressalva:
                    print(f"  ressalva {i}, na fala da Helena ({'com' if com_pergunta else 'SEM'} pergunta): {frase}")
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
    pasta = diag._pasta() / args.pasta
    pasta.mkdir(parents=True, exist_ok=True)
    if not args.amostra:
        args.amostra = json.loads(Path(args.repetir).read_text(encoding="utf-8"))["amostra"]

    disponivel, resumo = _estado_da_maquina()
    print(f"== Máquina: {resumo} · num_ctx {settings.ollama_num_ctx} (reserva de saída "
          f"{min(settings.ollama_num_predict, settings.llm_reserva_saida)} tokens) ==")
    if disponivel < args.min_memoria:
        sys.exit(f"PAREI antes de começar: memória disponível em {disponivel:.1f} GiB, abaixo de {args.min_memoria:.1f} GiB.")

    provider = get_provider(settings)
    monitor = ProviderMonitorado(provider, args.min_memoria)
    summarizer = Summarizer(provider=monitor)
    candidatos, ids = diag._carregar_amostra(args.amostra)
    if args.repetir or args.pautas:
        escolhidas = _pautas_dadas(args, ids)
    else:
        finais = _pautas_finais(args, provider, candidatos, ids)
        escolhidas = _escolher(finais, ids, args.max_pautas)
        print(f"\n{sum(1 for p in finais if p.relacionados)} pauta(s) final(is) com várias fontes")
    print(f"\n{len(escolhidas)} pauta(s) para {'analisar os lados' if args.so_lados else 'gerar'}: "
          f"{', '.join(caso for caso, _ in escolhidas)}")

    relatorios = []
    caminho = pasta / f"{'lados' if args.so_lados else 'relatorio'}_{carimbo}.json"

    def gravar() -> None:
        caminho.write_text(json.dumps(
            {"amostra": args.amostra, "limiar": None if args.repetir or args.pautas else args.limiar,   # sem etapa 3, não há limiar
             "num_ctx": settings.ollama_num_ctx, "episodios": relatorios},
            ensure_ascii=False, indent=1, default=str,
        ), encoding="utf-8")

    try:
        for n, (caso, pauta) in enumerate(escolhidas, 1):
            if args.so_lados:
                relatorios.append(_analisar(n, caso, pauta, ids, summarizer, monitor))
            else:
                relatorios.append(_gerar(n, caso, pauta, ids, summarizer, monitor, pasta, carimbo))
            gravar()  # a cada pauta: se a máquina cair no meio, fica o que já foi medido
    finally:
        gravar()
        print(f"\nRelatório: {caminho} ({len(relatorios)} de {len(escolhidas)} pauta(s))")


if __name__ == "__main__":
    main()
